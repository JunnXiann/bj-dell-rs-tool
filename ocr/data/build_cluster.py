import sys
import cv2
import torch
import pynvml
import logging
import os.path as osp
from datetime import datetime

sys.path.append(osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__)))))

import helper as hp
from ocr.data import util
from tool import kmeans as km
from tool.char_recog import CharRecog

db_lab = hp.get_db('tw-lab')


def check_cluster_duplicated():
    """ 检查是否有重复"""
    km_clusters = list(db_lab.km_cluster.find({}, {'tk': 1, '_id': 0}))
    tks = []
    duplicated = []
    for kc in km_clusters:
        if kc['tk'] in tks:
            duplicated.append(kc['tk'])
        tks.append(kc['tk'])

    print('%s 个重复字种: %s。' % (len(duplicated), duplicated))
    return False if duplicated else True


def get_cut_cnt(freq):
    """ 获取压缩源字频"""
    return freq if freq < 2000 else 2000


def get_gpu_used_rate():
    """ 检查GPU0的显存使用率"""
    pynvml.nvmlInit()
    gpu0 = pynvml.nvmlDeviceGetHandleByIndex(0)  # 第一块GPU
    meminfo = pynvml.nvmlDeviceGetMemoryInfo(gpu0)
    pynvml.nvmlShutdown()
    return round(meminfo.used / meminfo.total, 2)


def kmeans_cluster(model, char_names, k):
    """ 进行kmeans聚类"""
    # 获取字图块
    imgs_crop = []
    for char_name in char_names:
        img_path = hp.get_char_img_path(char_name)
        crop = cv2.imread(img_path, 0)
        crop = cv2.resize(crop, (96, 96), interpolation=cv2.INTER_CUBIC)
        imgs_crop.append(crop)
    # 利用识别模型，获取字图特征数据
    data = model.batch_char_recog2(imgs_crop)
    # 把字图数据进行kmeans分类，采用特征层面策略聚类
    cluster = km.kmeans(data, k)
    # 聚类结果，相同的类存储在同个list中
    cluster = [[char_names[j] for j in i] for i in cluster if i]
    cluster.sort(key=lambda x: len(x), reverse=True)
    return cluster


def get_model():
    """ 获取识别模型"""
    thresh = 0.5
    num_classes = 19189  # 模型的字种数量
    model_path = './meta/JSYZ_v2.pth'
    if torch.cuda.is_available() and get_gpu_used_rate() > 0.9:
        return
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = CharRecog(model_path, device, thresh, num_classes)
    return model


def get_cut_data(tk, sources, prior_data=None):
    """ 获取一个字种的压缩源数据，依赖tk_data的latest字段 """
    # 计算有效标注数据
    prior_data = set(prior_data or [])
    tk_data = db_lab.tk_data.find_one({'tk': tk}, {'dataset': 1})
    if tk_data:
        dataset = util.merge_dict_data(tk_data.get('dataset'))
        dataset = util.get_valid_names(tk, list(sources.keys()), dataset)
        prior_data.update(dataset)

    # 获取压缩源数据
    cut_data = []
    cut_freq = get_cut_cnt(sum(sources.values()))
    cc_data = util.select_cc_data(tk, list(sources.keys()), cut_freq, list(prior_data))
    for cd in cc_data:
        cut_data.extend(cd['selected_data'])
    return cut_data


def get_cluster(tk, sources, model=None):
    """ 获取聚类状态"""
    hp.set_logging('./log/get_cluster_%s.log' % datetime.now().strftime('%Y%m%d'))
    km_cluster = db_lab.km_cluster.find_one({'tk': tk}) or {}

    # 获取有效压缩源
    status = 0
    cut_data0 = km_cluster.get('cut_data') or []
    cut_data = util.get_valid_names(tk, list(sources.keys()), cut_data0)
    if len(cut_data) < len(cut_data0):  # 有效数据减少
        status = 1
    n_train, n_test = util.get_expected_cnt(sum(sources.values()))
    n_needed = n_train + n_test
    if len(cut_data) < n_needed:  # 压缩源不足时，重新获取
        cut_data = get_cut_data(tk, sources, cut_data)
        status = 2
    if len(cut_data) < n_needed:  # 重新获取后仍不足
        status = 3

    # 获取有效聚类
    status2 = 0
    cluster = []
    if status != 3:
        cluster0 = km_cluster.get('cluster') or []
        for i, item in enumerate(cluster0):
            cluster0[i] = list(set(item) & set(cut_data))
        cluster = [c for c in cluster0 if c]
        if len(cluster) < len(cluster0):  # 有效聚类减少
            status2 = 1
        total = sum([len(c) for c in cluster])
        if n_needed > total or n_train - len(cluster) > 10:  # 有效聚类数不足，重新聚类
            logging.info('[1]tk %s, kmeans_cluster k=%s.' % (tk, n_train))
            model = model or get_model()
            cluster = kmeans_cluster(model, cut_data, n_train)
            status2 = 2
        if n_needed > total or n_train - len(cluster) > 10:  # 再次重新聚类
            logging.info('[2]tk %s, kmeans_cluster k=%s.' % (tk, n_train))
            cluster = kmeans_cluster(model, cut_data, n_train)
        if n_needed > total or n_train - len(cluster) > 10:  # 重新聚类后仍不足
            status2 = 3

        cluster.sort(key=lambda x: len(x), reverse=True)

    data_status = {'cut_data': status, 'cluster': status2}
    meta = {'created_at': datetime.now(), 'sources': sources, 'cut_data': cut_data,
            'cluster': cluster, 'data_status': data_status}
    if km_cluster:
        if status == 0 and status2 == 0:  # 未改变
            db_lab.km_cluster.update_one({'tk': tk}, {'$set': {'data_status': data_status}})
        else:
            logs = km_cluster.get('logs') or []
            logs.append({f: km_cluster.get(f) for f in ['created_at', 'sources', 'cut_data', 'cluster']})
            db_lab.km_cluster.update_one({'tk': tk}, {'$set': {**meta, 'logs': logs}})

    else:
        db_lab.km_cluster.insert_one({'tk': tk, **meta})
    return cluster


def process():
    pass


def main(func='process', **kwargs):
    eval(func)(**kwargs)
    print('finished.')


if __name__ == '__main__':
    import fire

    fire.Fire(main)
