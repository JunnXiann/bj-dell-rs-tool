# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import logging
import pandas as pd
from os import path as osp

BASE_DIR = osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__))))
sys.path.append(BASE_DIR)
import helper as hp
from functools import cmp_to_key
from datetime import datetime

db_work = hp.get_db('tw-work')


def get_log_time(log):
    df_time = datetime.strptime('1970-01-01', '%Y-%m-%d')  # 缺省时间
    return log.get('updated_time') or log.get('create_time') or df_time


def sort_txt_logs(logs):
    """对日志进行按时间排序"""
    if not logs:
        return logs

    def cmp_log(a, b):
        t1, t2 = get_log_time(a), get_log_time(b)
        return 1 if t1 > t2 else -1 if t1 < t2 else 0

    logs.sort(key=cmp_to_key(cmp_log))
    return logs


def merge_txt_logs(logs1, logs2):
    """按时间序合并文字校对日志并去重"""

    def cmp_log(a, b):
        t1, t2 = get_log_time(a), get_log_time(b)
        return 1 if t1 > t2 else -1 if t1 < t2 else 0

    logs = []
    logs.extend(logs1 or [])
    logs.extend(logs2 or [])
    if not logs:
        return logs
    logs.sort(key=cmp_to_key(cmp_log))
    ret = [logs[0]]
    for lg in logs[1:]:
        if get_log_time(lg) != get_log_time(ret[-1]) or lg.get('user_id') != ret[-1].get('user_id'):
            ret.append(lg)
    return ret


def batch_update_txt(excel_file):
    """批量替换径山藏txt"""
    hp.set_logging('batch_update_txt', excel_file)
    data = pd.read_excel(osp.join(osp.dirname(osp.abspath(__file__)), f'data/batch_update_flag/{excel_file}'))

    for index, row in data.iterrows():
        flag_value = row['flag值']
        flag = row['flag類別']
        option = row['方案代碼']

        engine_version_1208 = '1208'
        engine_version_0923 = '0923'
        if flag == 'flag3':
            engine_version = engine_version_1208
        elif flag == 'flag5':
            engine_version = engine_version_0923
        else:
            return

        cond = {flag: flag_value}
        for coll in ['char1', 'char2', 'char3', 'char4', 'char5', 'char6']:
            chars = list(db_work[coll].find(cond))
            for ch in chars:
                ocr_res = ch['ocr_res']
                if option == 'km_txt':
                    ocr_engine = ocr_res['JSYZ_KM_%s' % engine_version]
                    # 加上6表示使用km值替换，加上7表示cc值替换
                    f_update_value = int('%s%s' % (flag_value, 6))
                elif option == 'max_cc':
                    km_engine = ocr_res['JSYZ_KM_%s' % engine_version]
                    cc_engine = ocr_res['JSYZ_CC_%s' % engine_version]
                    if km_engine['cc'] >= cc_engine['cc']:
                        ocr_engine = km_engine
                        f_update_value = int('%s%s' % (flag_value, 6))
                    else:
                        ocr_engine = cc_engine
                        f_update_value = int('%s%s' % (flag_value, 7))
                elif option == 'max_txt':
                    km_engine = ocr_res['JSYZ_KM_%s' % engine_version]
                    cc_engine = ocr_res['JSYZ_CC_%s' % engine_version]
                    km_txt = km_engine['ocr_txt']
                    cc_txt = cc_engine['ocr_txt']
                    txt = ch['txt']

                    if txt == km_txt:
                        ocr_engine = km_engine
                    elif txt == cc_txt:
                        ocr_engine = cc_engine
                    elif km_txt == cc_txt:
                        ocr_engine = km_engine
                    else:
                        logging.info('\t%s: max_txt错误' % ch['name'])
                        continue
                    f_update_value = int('%s%s' % (flag_value, 9))
                else:
                    logging.info('\t%s:option错误' % ch['name'])
                    return

                if not ocr_engine:
                    logging.info('\t%s:ocr_engine 为None' % ch['name'])
                    return
                ocr_txt = ocr_engine['ocr_txt']
                txt_updated_time = datetime.now()
                sys_log = [{'txt': ocr_txt, 'username': 'system', 'create_time': txt_updated_time}]
                txt_logs = sort_txt_logs(ch.get('txt_logs'))
                txt_logs2 = merge_txt_logs(txt_logs, sys_log)

                r = db_work[coll].update_one({'name': ch['name']}, {
                    '$set': {'txt': ocr_txt, flag: f_update_value, 'txt_logs': txt_logs2,
                             'txt_updated_time': txt_updated_time}})
                logging.info('\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s' % (
                    coll, ch['name'], flag, option, ch.get(flag), f_update_value, '更新txt&flag', r.matched_count,
                    ch['txt'], ocr_txt))


def set_2221212_flag(flag, set_falg):
    # flag5是根据0923进行分类的，進一步分類使用flag6；
    # flag3是根据1208进行分类的，進一步分類使用flag7。
    hp.set_logging('set_2221212_flag')
    logging.info('set_2221212_flag')
    txt_path = 'data/batch_update_flag/flag5之2221212排除清單(86).txt'
    with open(osp.join(osp.dirname(osp.abspath(__file__)), txt_path), 'r', encoding='utf-8') as f:
        out_tks = [line.strip() for line in f.readlines()]

    tasks = list(db_work.task.find({}, {'_id': 1, 'finished_time': 1}))
    task2finished_time = {t['_id']: t.get('finished_time') for t in tasks if t.get('finished_time')}

    tk2create_time = {}
    df_time = datetime.strptime('1970-01-01', '%Y-%m-%d')  # 缺省时间
    create_time = '2021-01-01'
    create_time = datetime.strptime(create_time, "%Y-%m-%d")
    variants = list(db_work.variant.find({}))
    for v in variants:
        tk2create_time[v.get('v_code') or v.get('txt')] = v.get('create_time') or create_time
    # flag = 'flag5'
    # set_falg = 'flag6'
    if flag == 'flag5':
        ocr_version = '0923'  # flag3的ocr_version 是1208 flag5的ocr_version 是0923
    elif flag == 'flag3':
        ocr_version = '1208'
    flag_value = 2221212
    cond = {flag: flag_value}
    for coll in ['char1', 'char2', 'char3', 'char4', 'char5', 'char6']:
        # 默认值为0
        r = db_work[coll].update_many(cond, {'$set': {set_falg: 0}})
        logging.info('初始化%s\t%s\t%s' % (set_falg, coll, r.matched_count))

        chars = list(db_work[coll].find(cond, {'txt': 1, 'name': 1, 'tasks': 1, 'ocr_res': 1, 'txt_updated_time': 1}))
        for ch in chars:
            txt = ch['txt']
            ocr_txt = ch['ocr_res']['JSYZ_KM_%s' % ocr_version]['ocr_txt']
            if ocr_txt in out_tks:
                # B是86個標注數據品質不佳的字種之一(flag6=3)
                db_work[coll].update_one({'name': ch['name']}, {'$set': {set_falg: 3}})
                continue
            time_b = tk2create_time.get(ocr_txt) or create_time
            time_a = ch.get('txt_updated_time') or df_time
            # 人工檢查時間：
            # 最後一次參與任務的時間、最後一次修改的時間，以時間較晚的為準
            if ch.get('tasks'):
                time_lst = []
                for task_type, ids in ch['tasks'].items():
                    for task_id in ids:
                        finished_time = task2finished_time.get(task_id)
                        if finished_time:
                            time_lst.append(finished_time)
                if time_lst:
                    # 找到最大的时间
                    max_time = max(time_lst)
                    if time_a < max_time:
                        time_a = max_time
            if time_a > time_b:
                # 1: A的人工檢查時間>B字種的創建時間(flag6=111)
                end_value = 1
            else:
                # 2: A的人工檢查時間<=B字種的創建時間(flag6=112)
                end_value = 2

            if 'v' in txt and len(txt) > 1:
                # 1: A是自造字
                if 'v' in ocr_txt and len(ocr_txt) > 1:
                    # 1: B是自造字
                    set_falg_value = '11%s' % end_value
                else:
                    # 2: B是通字
                    set_falg_value = '12%s' % end_value
            else:
                # 2: A是通字
                if 'v' in ocr_txt and len(ocr_txt) > 1:
                    # 1: B是自造字
                    set_falg_value = '21%s' % end_value
                else:
                    # 2: B是通字
                    set_falg_value = '22%s' % end_value
            set_falg_value = int(set_falg_value)
            db_work[coll].update_one({'name': ch['name']}, {'$set': {set_falg: set_falg_value}})


def batch_update_txt_0110():
    """批量替换径山藏第二批数据"""
    hp.set_logging('batch_update_txt_0112')
    logging.info('batch_update_txt_0112')
    data = pd.read_excel(
        osp.join(osp.dirname(osp.abspath(__file__)), 'data/batch_update_flag/flag5自動替換txt字組-250111_21_18.xlsx'))

    for index, row in data.iterrows():
        txt = row['A#B']
        flag = row['flag']
        f_value = row['flag值-前']
        f_update_value = row['flag值-後']
        ocr_engine = row['引擎']
        cc = row['置信度>=']
        remark = row['備註']
        txt_a = txt.split('#')[0]
        txt_b = txt.split('#')[1]
        cond = {'txt': txt_a, 'ocr_res.JSYZ_KM_0923.ocr_txt': txt_b, flag: f_value}
        if cc > 0:
            cond['ocr_res.JSYZ_KM_0923.cc'] = {'$gte': cc}
        for coll in ['char1', 'char2', 'char3', 'char4', 'char5', 'char6']:
            chars = list(db_work[coll].find(cond))
            for ch in chars:
                if remark == '只改flag5的值':
                    r = db_work[coll].update_one({'name': ch['name']}, {'$set': {flag: f_update_value}})
                    logging.info('%s\t%s\t%s\t%s\t%s\t%s\t%s' % (
                        txt, coll, ch['name'], ch.get(flag), f_update_value, '更新flag', r.matched_count))
                else:
                    txt_updated_time = datetime.now()
                    ocr_txt = ch['ocr_res'][ocr_engine]['ocr_txt']
                    sys_log = [{"txt": ocr_txt, "username": "system", "create_time": txt_updated_time}]
                    txt_logs = sort_txt_logs(ch.get('txt_logs'))
                    txt_logs2 = merge_txt_logs(txt_logs, sys_log)

                    r = db_work[coll].update_one({'name': ch['name']}, {
                        '$set': {'txt': ocr_txt, flag: f_update_value, 'txt_logs': txt_logs2,
                                 'txt_updated_time': txt_updated_time}})
                    logging.info('%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s' % (
                        txt, coll, ch['name'], ch.get(flag), f_update_value, '更新txt&flag', r.matched_count, ch['txt'],
                        ocr_txt))


def batch_update_txt_4(flag='', sub_flag='', coll=''):
    """第四批批量替换"""
    """分类2221212，使用km_txt替换"""
    hp.set_logging(f'第4批更新{flag}_{coll}')
    logging.info(f'第4批更新{flag}_{coll}')
    txt_path = 'data/batch_update_flag/统计2221212分类中属于1208标注数据的字图编码.txt'
    with open(osp.join(osp.dirname(osp.abspath(__file__)), txt_path), 'r', encoding='utf-8') as f:
        names_1208 = [line.strip() for line in f.readlines()]
    if flag == 'flag5':
        ocr_version = '0923'  # flag3的ocr_version 是1208 flag5的ocr_version 是0923
    elif flag == 'flag3':
        ocr_version = '1208'
    cond = {flag: 2221212}
    f_update_value = 22212126

    chars = list(db_work[coll].find(cond))
    for ch in chars:
        if ch.get(sub_flag) == 3:
            logging.info(' %s\t %s\t%s\t%s\t%s\t%s\t%s\t%s\t%s' % (
                coll, ch['name'], flag, ch.get(flag), f_update_value, '不更新(排除86个字种)', 0, ch['txt'], ''))
            continue
        if ch.get('name') in names_1208:
            logging.info(' %s\t %s\t%s\t%s\t%s\t%s\t%s\t%s\t%s' % (
                coll, ch['name'], flag, ch.get(flag), f_update_value, '不更新(排除1208标注数据)', 0, ch['txt'], ''))
            continue
        txt_updated_time = datetime.now()
        ocr_txt = ch['ocr_res']['JSYZ_KM_%s' % ocr_version]['ocr_txt']
        sys_log = [{"txt": ocr_txt, "username": "system", "create_time": txt_updated_time}]
        txt_logs = sort_txt_logs(ch.get('txt_logs'))
        txt_logs2 = merge_txt_logs(txt_logs, sys_log)

        r = db_work[coll].update_one({'name': ch['name']}, {
            '$set': {'txt': ocr_txt, flag: f_update_value, 'txt_logs': txt_logs2,
                     'txt_updated_time': txt_updated_time}})
        logging.info(' %s\t %s\t%s\t%s\t%s\t%s\t%s\t%s\t%s' % (
            coll, ch['name'], flag, ch.get(flag), f_update_value, '更新txt&flag', r.matched_count, ch['txt'], ocr_txt))


def process():
    # batch_update_txt('全藏檢校批量替換250108.xlsx')  # 1月9日对径山藏488766条数据批量替换
    # set_2221212_flag(flag='flag5', set_falg='flag6')  # 1月22日对flag为2221212进行设置flag6
    # set_2221212_flag(flag='flag3', set_falg='flag7')
    # batch_update_txt_0110()  # 对径山藏第二批数据批量替换
    # batch_update_txt('全藏檢校批量替換250110.xlsx')  # 对径山藏第三批数据批量替换
    # 1月26日对径山藏第四批数据批量替换
    # python update_chars.py --func=batch_update_txt_4 --flag=flag5 --sub_flag=flag6 --coll=char1
    # python update_chars.py --func=batch_update_txt_4 --flag=flag3 --sub_flag=flag7 --coll=char1
    pass


def main(func='process', **kwargs):
    eval(func)(**kwargs)
    print('finished.')


if __name__ == '__main__':
    import fire

    fire.Fire(main)
