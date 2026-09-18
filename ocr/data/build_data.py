import os
import sys
import random
import shutil
import logging
import os.path as osp
from datetime import datetime

sys.path.append(osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__)))))

import build_cluster as bc
from ocr.data import config
from ocr.data import util
import helper as hp

db_lab = hp.get_db('tw-lab')
db_work = hp.get_db('tw-work')


def check_data_duplicated():
    """ 检查数据是否有重复"""
    tks, duplicated = [], []
    tk_datas = list(db_lab.tk_data.find({}, {'tk': 1, '_id': 0}))
    for td in tk_datas:
        if td['tk'] in tks:
            duplicated.append(td['tk'])
        tks.append(td['tk'])

    print('%s 个重复字种: %s。' % (len(duplicated), duplicated))
    return False if duplicated else True


# --------------更新数据源字种及字频--------------

def update_one_sources(tk_data):
    """ 设置单个字种的最新数据源字频"""
    sources = {}
    tk = tk_data['tk']
    conds = config.get_select_conds()
    for coll, cond in conds.items():
        cond['txt'] = tk
        sources[coll] = db_work[coll].count_documents(cond)
    freq = sum(sources.values())
    db_lab.tk_data.update_one({'tk': tk}, {'$set': {'sources': sources, 'freq': freq}})
    tk_data.update({'sources': sources, 'freq': freq})
    return sources


def get_all_sources():
    """ 获取单个字种的最新数据源字频"""
    tk2sources = {}
    conds = config.get_select_conds()
    for coll, cond in conds.items():
        items = list(db_work[coll].aggregate([
            {'$match': cond},
            {'$group': {'_id': '$txt', 'count': {'$sum': 1}}}
        ]))
        for it in items:
            tk, freq = it['_id'], it['count']
            tk2sources[tk] = tk2sources.get(tk) or {}
            tk2sources[tk][coll] = freq

    tk_sources = [[tk, sources, sum(sources.values())] for tk, sources in tk2sources.items()]  # 合并字频
    exclude_tks = config.get_exclude_tks()
    tk_sources = [s for s in tk_sources if s[0] not in exclude_tks]  # 过滤掉禁用的字频
    tk_sources = [s for s in tk_sources if s[2] >= 10]  # 过滤掉数据量小于10的字种
    tk_sources.sort(key=lambda x: x[2])  # 升序排列

    return [[ts[0], ts[1]] for ts in tk_sources]


def update_all_sources():
    """ 更新最新的数据源字频"""
    # 删除无效构建
    r = db_lab.tk_data.delete_many({'version': 'new'})
    print('[%s]删除%s个未确认的临时字种' % (hp.get_date_time(), r.deleted_count))

    # 获取最新的数据源
    tk_sources = get_all_sources()
    print('[%s]根据数据源配置进行统计，得到%s个字种' % (hp.get_date_time(), len(tk_sources)))

    # 设置无效字种
    tks = [ts[0] for ts in tk_sources]
    db_lab.tk_data.update_many({'tk': {'$nin': tks}, 'active': {'$ne': False}}, {'$set': {'active': False}})

    # 设置sources
    new_tks = []
    for i, (tk, sources) in enumerate(tk_sources):
        meta = {'active': True, 'sources': sources, 'freq': sum(sources.values())}
        r = db_lab.tk_data.update_one({'tk': tk}, {'$set': meta})
        if r.matched_count == 0:
            new_tks.append({'tk': tk, 'version': 'new', **meta})
    if new_tks:
        db_lab.tk_data.insert_many(new_tks)

    print('[%s]更新%s个字种，新增%s个字种。' % (hp.get_date_time(), len(tks) - len(new_tks), len(new_tks)))


# --------------更新标注数据状态--------------

def cmp_data_status(old, latest):
    """ 比较标注数据的状态（注：new是old的子集）"""
    status = {'km_data': 0, 'cc_data': 0}
    # 设置old的状态
    source_cnt = sum(hp.prop(old, 'sources', {}).values())
    expected_cnt = list(util.get_expected_cnt(source_cnt))
    km_cnt = len(old.get('km_train_data', [])) + len(old.get('km_test_data', []))
    cc_cnt = len(old.get('cc_train_data', [])) + len(old.get('cc_test_data', []))
    status['old'] = {'source_cnt': source_cnt, 'expected_cnt': expected_cnt, 'km_cnt': km_cnt,
                     'cc_cnt': cc_cnt, 'merged_cnt': len(util.merge_dict_data(old))}

    # 设置new的状态
    source_cnt = sum(hp.prop(latest, 'sources', {}).values())
    expected_cnt = list(util.get_expected_cnt(source_cnt))
    km_cnt = len(latest.get('km_train_data', [])) + len(latest.get('km_test_data', []))
    cc_cnt = len(latest.get('cc_train_data', [])) + len(latest.get('cc_test_data', []))
    status['latest'] = {'source_cnt': source_cnt, 'expected_cnt': expected_cnt, 'km_cnt': km_cnt,
                        'cc_cnt': cc_cnt, 'merged_cnt': len(util.merge_dict_data(latest))}

    # 检查km状态
    n_train, n_test = util.get_expected_cnt(source_cnt)
    if n_train != len(latest.get('km_train_data', [])) or n_test != len(latest.get('km_test_data', [])):  # 不满足预期
        status['km_data'] = 1

    # 检查cc状态
    if n_train != len(latest.get('cc_train_data', [])) or n_test != len(latest.get('cc_test_data', [])):  # 不满足预期
        status['cc_data'] = 1
    elif status['latest']['source_cnt'] > status['old']['source_cnt']:  # 虽满足预期，但字频有新增
        status['cc_data'] = 1

    # 检查合并字频状态
    expected_merged_cnt = util.get_expected_merged_cnt(status['latest']['source_cnt'])
    if expected_merged_cnt != status['latest']['merged_cnt']:  # 二者不一致
        status['cc_data'] = 1

    return status


def check_data_status(tk_data, which='dataset', refresh_sources=False):
    """ 检查数据状态"""
    # 获取最新的有效数据
    if refresh_sources:
        sources = update_one_sources(tk_data)
    else:
        sources = tk_data.get('sources')
    valid_data_dict = {'sources': sources}
    data_dict = tk_data.get(which) or {}
    for field in ['km_train_data', 'km_test_data', 'cc_train_data', 'cc_test_data']:
        valid_data_dict[field] = util.get_valid_names(tk_data['tk'], list(sources.keys()), data_dict.get(field))
    # 比较新旧数据的状态
    status = cmp_data_status(data_dict, valid_data_dict)
    # 计算有效、无效数据
    for select_type in ['km', 'cc']:
        data = util.merge_dict_data({k: v for k, v in data_dict.items() if select_type in k})
        valid_data = util.merge_dict_data({k: v for k, v in valid_data_dict.items() if select_type in k})
        invalid_data = list(set(data) - set(valid_data))
        status.update({f'{select_type}_valid_data': list(valid_data), f'{select_type}_invalid_data': invalid_data})
    db_lab.tk_data.update_one({'tk': tk_data['tk']}, {'$set': {f'{which}.data_status': status}})

    return status, valid_data_dict


def batch_check_data_status(which='dataset'):
    """ 批量检查数据状态"""
    tk_datas = list(db_lab.tk_data.find({'active': True}, {'tk': 1, 'sources': 1, which: 1}))
    for i, tk_data in enumerate(tk_datas):
        print('[%s][%s/%s]%s' % (hp.get_date_time(), i + 1, len(tk_datas), tk_data['tk']))
        check_data_status(tk_data, which)


# --------------构建标注数据--------------

def select_km_data(tk_data, prior_km_data, prior_cc_data, model=None):
    """ 选择kmeans标注数据 """
    # 检查聚类状态
    sources = hp.prop(tk_data, 'sources')
    cluster = bc.get_cluster(tk_data['tk'], sources, model)
    if not cluster:
        return False, [], [], False

    freq = sum(sources.values())
    n_train, n_test = util.get_expected_cnt(freq)
    prior_cc_data = set(prior_cc_data) - set(prior_km_data)  # 去重

    # 从聚类中挑选标注数据
    used_cc = False  # 是否选用了cc的数据
    train_data, test_data = [], []
    while len(train_data) < n_train or len(test_data) < n_test:
        for item in cluster:
            com_km_data = list(set(item) & set(prior_km_data))
            com_cc_data = list(set(item) & set(prior_cc_data))
            if item and len(train_data) < n_train:
                if com_km_data:
                    train_data.append(random.sample(com_km_data, 1)[0])
                    com_km_data.remove(train_data[-1])
                    item.remove(train_data[-1])
                elif com_cc_data:
                    train_data.append(random.sample(com_cc_data, 1)[0])
                    com_cc_data.remove(train_data[-1])
                    item.remove(train_data[-1])
                    used_cc = True
                else:
                    train_data.append(random.sample(item, 1)[0])
                    item.remove(train_data[-1])
            if item and len(test_data) < n_test:
                if com_km_data:
                    test_data.append(random.sample(com_km_data, 1)[0])
                    com_km_data.remove(test_data[-1])
                    item.remove(test_data[-1])
                elif com_cc_data:
                    test_data.append(random.sample(com_cc_data, 1)[0])
                    com_cc_data.remove(test_data[-1])
                    item.remove(test_data[-1])
                    used_cc = True
                else:
                    test_data.append(random.sample(item, 1)[0])
                    item.remove(test_data[-1])

    return True, train_data, test_data, used_cc


def sort_cluster(cluster, prior_km_data, reverse=False):
    """对cluster进行排序"""
    cluster_list = []
    for cl in cluster:
        com_data = set(cl) & set(prior_km_data)
        cluster_list.append((len(com_data), cl))
    sorted_data = sorted(cluster_list, key=lambda x: x[0], reverse=reverse)
    cluster = [x[1] for x in sorted_data]
    return cluster


def select_km_data_v2(tk_data, prior_km_data, prior_cc_data, model=None):
    """ 选择kmeans标注数据 """
    # 检查聚类状态
    sources = hp.prop(tk_data, 'sources')
    cluster = bc.get_cluster(tk_data['tk'], sources, model)
    if not cluster:
        return False, [], [], False

    freq = sum(sources.values())
    n_train, n_test = util.get_expected_cnt(freq)
    prior_cc_data = set(prior_cc_data) - set(prior_km_data)  # 去重

    # 从聚类中挑选标注数据
    used_cc = False  # 是否选用了cc的数据
    train_data, test_data = [], []
    cluster_names = [name for item in cluster if item for name in item]
    com_km_data_list = list(set(cluster_names) & set(prior_km_data))
    cluster = sort_cluster(cluster, prior_km_data, False)
    while len(train_data) < n_train or len(test_data) < n_test:
        for item in cluster:
            com_km_data = list(set(item) & set(com_km_data_list))
            if item and len(train_data) < n_train:
                if com_km_data and com_km_data_list:
                    train_data.append(random.sample(com_km_data, 1)[0])
                    com_km_data.remove(train_data[-1])
                    item.remove(train_data[-1])
                    com_km_data_list.remove(train_data[-1])

            if item and len(test_data) < n_test:
                if com_km_data:
                    test_data.append(random.sample(com_km_data, 1)[0])
                    com_km_data.remove(test_data[-1])
                    item.remove(test_data[-1])
                    com_km_data_list.remove(test_data[-1])
        if len(com_km_data_list) == 0:
            break
    km_data = set(test_data) | set(train_data)
    prior_km_data = list(set(prior_km_data) - km_data)
    while len(train_data) < n_train or len(test_data) < n_test:
        for item in cluster:
            com_km_data = list(set(item) & set(prior_km_data))
            com_cc_data = list(set(item) & set(prior_cc_data))
            if item and len(train_data) < n_train:
                if com_km_data:
                    train_data.append(random.sample(com_km_data, 1)[0])
                    com_km_data.remove(train_data[-1])
                    item.remove(train_data[-1])
                elif com_cc_data:
                    train_data.append(random.sample(com_cc_data, 1)[0])
                    com_cc_data.remove(train_data[-1])
                    item.remove(train_data[-1])
                    used_cc = True
                else:
                    train_data.append(random.sample(item, 1)[0])
                    item.remove(train_data[-1])
            if item and len(test_data) < n_test:
                if com_km_data:
                    test_data.append(random.sample(com_km_data, 1)[0])
                    com_km_data.remove(test_data[-1])
                    item.remove(test_data[-1])
                elif com_cc_data:
                    test_data.append(random.sample(com_cc_data, 1)[0])
                    com_cc_data.remove(test_data[-1])
                    item.remove(test_data[-1])
                    used_cc = True
                else:
                    test_data.append(random.sample(item, 1)[0])
                    item.remove(test_data[-1])

    return True, train_data, test_data, used_cc


def select_cc_data(
        tk_data,  # 待构建的字种
        valid_cc_data,  # dataset中有效的cc数据
        valid_km_data,  # dataset中有效的km数据
        km_data  # 已构建的km数据，需尽量排除，避免重复
):
    """ 选择置信度标注数据 """
    sources = hp.prop(tk_data, 'sources')
    n_train, n_test = util.get_expected_cnt(sum(sources.values()))
    n_expected = n_test + n_train
    # 先从优先数据以及数据源数据中挑选，避免重复
    cc_data = util.select_cc_data(tk_data['tk'], list(sources.keys()), n_expected,
                                  valid_cc_data, valid_km_data, km_data)
    # 不足时，从km_data中补充，只好重复
    _n_expected = n_expected - sum([len(d['selected_data']) for d in cc_data])
    if _n_expected > 0:
        selected_data = util.random_select(km_data, _n_expected)
        cc_data.append({'src': 'km', 'n_expected': _n_expected, 'selected_data': selected_data})
    # 按比例划分
    train_data, test_data = util.divide_cc_data(cc_data, n_train / n_expected)

    return train_data, test_data, cc_data


def build_data(tk_data, model=None):
    """ 针对单个字种，构建标注数据"""
    # 获取dataset的最新状态
    data_status, valid_dataset = check_data_status(tk_data, 'dataset', False)

    # 初始化build，开始构建
    build = {'task_status': 2, 'build_status': {}, 'sources': tk_data['sources'],
             'freq': tk_data['freq'], 'created_at': datetime.now()}
    build.update({f: valid_dataset.get(f) for f in [
        'km_train_data', 'km_test_data', 'cc_train_data', 'cc_test_data']})

    # km和cc均无需重新挑选
    if data_status.get('km_data') == 0 and data_status.get('cc_data') == 0:
        db_lab.tk_data.update_one({'tk': tk_data['tk']}, {'$set': {'build': build}})
        return True

    # 重新挑选km标注数据
    valid_km_train_data = hp.prop(valid_dataset, 'km_train_data', [])
    valid_km_test_data = hp.prop(valid_dataset, 'km_test_data', [])
    used_cc = False
    if data_status.get('km_data') == 1:
        success, km_train_data, km_test_data, used_cc = select_km_data_v2(
            tk_data, data_status['km_valid_data'], data_status['cc_valid_data'], model)
        if not success:  # km构建失败，直接返回（须人工检查）
            build.update({'task_status': 3})
            db_lab.tk_data.update_one({'_id': tk_data['_id']}, {'$set': {'build': build}})
            logging.info('tk %s: select_km_data failed.' % tk_data['tk'])
            return False
        km_status = util.cmp_data(km_train_data + km_test_data, valid_km_train_data + valid_km_test_data)
    else:
        km_train_data, km_test_data = valid_km_train_data, valid_km_test_data
        km_status = {'added': [], 'deleted': []}

    # 重新挑选cc标注数据
    valid_cc_train_data = hp.prop(valid_dataset, 'cc_train_data', [])
    valid_cc_test_data = hp.prop(valid_dataset, 'cc_test_data', [])
    if data_status.get('cc_data') == 1 or used_cc:
        km_data = km_train_data + km_test_data
        cc_train_data, cc_test_data, cc_data = select_cc_data(
            tk_data, data_status['cc_valid_data'], data_status['km_valid_data'], km_data)
        cc_status = util.cmp_data(cc_train_data + cc_test_data, valid_cc_train_data + valid_cc_test_data)
    else:
        cc_train_data, cc_test_data, cc_data = valid_cc_train_data, valid_cc_test_data, []
        cc_status = {'added': [], 'deleted': []}

    # 设置build
    build.update({
        'km_train_data': km_train_data, 'km_test_data': km_test_data,
        'cc_train_data': cc_train_data, 'cc_test_data': cc_test_data,
    })
    total_status = util.cmp_data(util.merge_dict_data(build), util.merge_dict_data(valid_dataset))
    build.update({'build_status': {'km': km_status, 'cc': cc_status, 'cc_segs': cc_data, 'total': total_status}})

    db_lab.tk_data.update_one({'_id': tk_data['_id']}, {'$set': {'build': build}})
    return True


def init_build_data():
    """ 初始化批量构建标注数据 """
    db_lab.tk_data.update_many({'active': True}, {'$set': {'dataset.data_status': {}, 'build.task_status': 0}})


def batch_build_data(n=None):
    """ 批量构建标注数据 """
    hp.set_logging('./log/batch_build_data_%s.log' % (datetime.now().strftime('%Y%m%d%H%M%S')))
    model = bc.get_model()
    cond = {'build.task_status': 0, 'active': True}
    tk_data = db_lab.tk_data.find_one_and_update(cond, {'$set': {'build.task_status': 1}})
    while tk_data:
        logging.info('[%s]tk %s started.' % (n, tk_data['tk']))
        r = build_data(tk_data, model)
        logging.info('[%s]tk %s %s.' % (n, tk_data['tk'], 'finished' if r else 'failed'))
        tk_data = db_lab.tk_data.find_one_and_update(cond, {'$set': {'build.task_status': 1}})


def multi_batch_build_data(n=3):
    """ 多进程构建标注数据"""
    cmd = 'nohup python3 %s/data/build_data.py --func=batch_build_data --n=%s &'
    for i in range(n):
        cmd_i = cmd % (hp.BASE_DIR, i + 1)
        # print(cmd_i)
        os.system(cmd_i)


# --------------标注数据迭代--------------

def update_dataset_by_build():
    """ 批量更新标注数据集 """
    # 更新版本号
    version = 'JS%s' % datetime.now().strftime('%m%d')
    db_lab.tk_data.update_many({'active': True, 'version': 'new'}, {'$set': {'version': version}})
    db_lab.tk_data.delete_many({'active': False, 'version': 'new'})

    # 更新dataset
    cond = {'active': True}
    tk_datas = list(db_lab.tk_data.find(cond, {'tk': 1}))
    for i, tk_data in enumerate(tk_datas):
        print('[%s][%s/%s]%s' % (hp.get_date_time(), i + 1, len(tk_datas), tk_data['tk']))
        tk_data = db_lab.tk_data.find_one({'tk': tk_data['tk']})
        fields = ['sources', 'created_at', 'km_train_data', 'km_test_data',
                  'cc_train_data', 'cc_test_data', 'ocr_ratio']
        # 更新日志
        logs = tk_data.get('logs') or []
        last = logs[-1] if logs else {}
        dataset = tk_data.get('dataset') or {}
        dataset = {f: dataset.get(f) for f in fields if dataset.get(f)}
        if dataset and dataset.get('created_at') != last.get('created_at'):
            logs.append(dataset)
        # 用build更新dataset
        build = tk_data.get('build') or {}
        dataset = {f: build.get(f) for f in fields + ['data_status'] if build.get(f)}
        db_lab.tk_data.update_one({'_id': tk_data['_id']}, {'$set': {'dataset': dataset, 'logs': logs}})


# ----------------导出图片----------------

def init_export_imgs():
    """ 初始化批量构建标注数据 """
    db_lab.tk_data.update_many({'active': True}, {'$set': {'export.task_status': 0}})


def export_imgs(tk_data, refresh=False):
    """ 导出图片"""
    tk = tk_data['tk']
    if len(tk) == 1 and 'v' not in tk:
        tk = util.get_unicode(tk)
    dataset = tk_data.get('dataset') or {}
    dataset = {f: dataset.get(f) or [] for f in [
        'km_train_data', 'km_test_data', 'cc_train_data', 'cc_test_data']}
    for data_type, names in dataset.items():
        root = osp.join('/data/ocr/label_data', data_type, tk)
        osp.exists(root) or os.makedirs(root)
        for name in names:
            dst_fn = osp.join(root, name + '.jpg')
            if osp.exists(dst_fn) and not refresh:
                continue
            img = hp.get_char_img_path(name)
            shutil.copy2(img, dst_fn)
    db_lab.tk_data.update_one({'_id': tk_data['_id']}, {'$set': {'export.task_status': 2}})


def batch_export_imgs(n=None, refresh=False):
    """ 批量导出图片"""
    hp.set_logging('./log/batch_export_imgs_%s.log' % (datetime.now().strftime('%Y%m%d%H%M%S')))
    cond = {'export.task_status': 0, 'active': True}
    tk_data = db_lab.tk_data.find_one_and_update(cond, {'$set': {'export.task_status': 1}})
    while tk_data:
        logging.info('[%s]tk %s started.' % (n, tk_data['tk']))
        export_imgs(tk_data, refresh)
        logging.info('[%s]tk %s finished.' % (n, tk_data['tk']))
        tk_data = db_lab.tk_data.find_one_and_update(cond, {'$set': {'export.task_status': 1}})


def multi_batch_export_imgs(n=3):
    """ 多进程构建标注数据"""
    cmd = 'nohup python3 %s/data/build_data.py --func=batch_export_imgs --n=%s &'
    for i in range(n):
        cmd_i = cmd % (hp.BASE_DIR, i + 1)
        # print(cmd_i)
        os.system(cmd_i)


def example():
    """ 示例"""
    # 检查字种是否重复
    if not check_data_duplicated():
        return False
    if bc.check_cluster_duplicated():
        return False

    # --------处理数据源的所有字种--------
    # 更新数据源
    update_all_sources()
    # 批量构建标注数据
    init_build_data()
    # batch_build_data()
    multi_batch_build_data(3)
    # 检查build的数据状态
    batch_check_data_status('build')

    # --------处理指定的字种集合--------
    cond = {}
    tk_datas = list(db_lab.tk_data.find(cond))
    for tk_data in tk_datas:
        # 更新数据源
        update_one_sources(tk_data)
        # 构建标注数据
        build_data(tk_data)
        # 检查build的数据状态
        check_data_status(tk_data, 'build')


def process():
    # # 检查build的数据状态
    # # batch_check_data_status('build')
    # 更新数据源
    cond = {'tk': '識'}  # 識 vtk6
    tk_datas = list(db_lab.tk_data.find(cond))
    for tk_data in tk_datas:
        # 更新数据源
        # update_one_sources(tk_data)
        # # 构建标注数据
        build_data(tk_data)
        # check_data_status(tk_data, 'build')
    # pass


def main(func='process', **kwargs):
    eval(func)(**kwargs)
    print('finished.')


if __name__ == '__main__':
    import fire

    fire.Fire(main)
