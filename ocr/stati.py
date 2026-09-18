import os
import csv
import sys
import os.path as osp
from datetime import datetime

sys.path.append(osp.dirname(osp.dirname(osp.abspath(__file__))))

import helper as hp


def stat_ocr_res(
        ocr_engine='JSYZ_v2.0',  # ocr引擎代码
        dict_file='meta/JSYZ_v2.0_freq.txt',  # ocr引擎代码字频文件
        char_coll='char4',  # 测试数据的char表名
        char_source='JSYZ_v2',  # 测试数据的char数据分类
        equal='equal',  # 选用比对的值来统计，equal的值为：equal、equal_uni、equal_vrt
        save_path='log/',  # 统计结果存放目录
        n_group=None,  # 0是不加入训练的字图，1是加入训练的字图
):
    """ 统计OCR引擎的结果"""
    # 1.读取字种的字频
    txt2cnt = {}
    with open(dict_file, mode='r', encoding='utf-8') as rf:
        for line in rf.readlines():
            txt, cnt = line.strip().split('\t')
            txt2cnt[txt] = cnt
    # 3.统计每个字种的数据
    cond = {'source': char_source}
    if n_group >= 0:
        cond.update({'n_group': n_group})
    db_lab = hp.connect_db('tw', 'lab')
    group_items = db_lab[char_coll].aggregate([
        {'$match': cond}, {'$group': {'_id': '$txt', 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}}])
    # 4.准备字频统计数据
    rows = [['字种', '字频', '错误率', '测试字图总数', '错误字图总数', '错误字图链接']]
    for item in group_items:
        print(item['_id'])
        cond.update({'txt': item['_id']})
        field = 'ocr_res.%s' % ocr_engine.replace('.', '_')
        chars = list(db_lab[char_coll].find(cond, {field: 1, '_id': 0}))
        error_cnt = len([c for c in chars if not hp.prop(c, '%s.%s' % (field, equal))])
        train_cnt = txt2cnt.get(item['_id'])
        test_cnt = item['count']
        error_ratio = round(error_cnt / test_cnt, 4)
        error_url = 'https://lab.tripitakas.net:800/%s/list?source==%s&txt==%s&eq2cb=False' % (
            char_coll, char_source, item['_id'])
        rows.append([item['_id'], train_cnt, error_ratio, test_cnt, error_cnt, error_url])
    # 5.导出统计报告
    # 5.1 导出字种统计报告，如 [GJTZ_v1.0]字种统计_yyyymmdd_hash.csv
    not osp.exists(save_path) and os.makedirs(save_path)
    now = datetime.now()
    rule = '_通字' if '_uni' in equal else '_正字' if '_nor' in equal else '_原字'
    fn = '[%s]字种统计%s_%s_%d.csv' % (ocr_engine, rule, now.strftime('%Y%m%d'), int(now.timestamp()))
    if n_group >= 0:
        fn = fn.replace('.csv', '_%d.csv' % n_group)
    with open(osp.join(save_path, fn), 'w', encoding='utf-8') as wf:
        writer = csv.writer(wf)
        writer.writerows(rows)
    # 5.2 导出总体统计报告，如 [GJTZ_v1.0]总体统计_yyyymmdd_hash.csv
    rows.pop(0)
    txt_cnt = len(rows)
    error_txt_cnt = len([r for r in rows if float(r[2]) > 0.0001])
    error_txt_ratio = round(error_txt_cnt / txt_cnt, 4)
    char_cnt = sum([r[3] for r in rows])
    error_char_cnt = sum([r[4] for r in rows])
    error_char_ratio = round(error_char_cnt / char_cnt, 4)
    with open(osp.join(save_path, fn.replace('字种', '总体')), 'w', encoding='utf-8') as wf:
        writer = csv.writer(wf)
        writer.writerows([
            ['字种总数', '错误字种总数', '字种错误率', '字图总数', '错误字图总数', '字图错误率'],
            [txt_cnt, error_txt_cnt, error_txt_ratio, char_cnt, error_char_cnt, error_char_ratio]])


def main(func='', **kwargs):
    eval(func)(**kwargs)
    print('finished.')


if __name__ == '__main__':
    import fire

    fire.Fire(main)
