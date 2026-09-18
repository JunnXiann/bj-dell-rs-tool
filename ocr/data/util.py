import os
import sys
import csv
import json
import math
import random
import os.path as osp
from datetime import datetime
from functools import cmp_to_key

sys.path.append(osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__)))))

import helper as hp
import config

db_lab = hp.get_db('tw-lab')
db_work = hp.get_db('tw-work')


def load_json(fn):
    if not osp.exists(fn):
        return {}
    with open(fn, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(obj, fn):
    root = osp.dirname(fn)
    osp.exists(root) or os.makedirs(root)
    with open(fn, 'w', encoding='utf-8') as f:
        json.dump(obj, f)


def load_csv(fn):
    if not osp.exists(fn):
        return []
    with open(fn, 'r', encoding='utf-8') as f:
        return list(csv.reader(f))


def save_csv(rows, fn):
    root = osp.dirname(fn)
    osp.exists(root) or os.makedirs(root)
    with open(fn, 'w', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def get_expected_merged_cnt(n_src):
    """ 获取预期标注数据合并后的字频 """
    expected_cnt = sum(get_expected_cnt(n_src))
    return min([n_src, 2 * expected_cnt])


def get_expected_cnt(n_src):
    """ 获取预期的标注数据字频 """
    if n_src > 2000:
        n_train = n_test = 200
    elif n_src > 1500:
        n_train = n_test = 180
    elif n_src > 1000:
        n_train = n_test = 160
    elif n_src > 500:
        n_train = n_test = 140
    elif n_src > 240:
        n_train = n_test = 120
    elif n_src > 200:
        n_train = (n_src // 2) + (n_src % 2)
        n_test = n_src // 2
    elif n_src > 120:
        n_train = 100
        n_test = n_src - 100
    elif n_src > 100:
        n_test = 20
        n_train = n_src - 20
    else:
        n_train = (n_src // 5) * 4
        n_test = n_src - n_train
    return n_train, n_test


def cmp_sources(sources1, sources2):
    """ 比较数据源字频"""
    colls1 = set(sources1.keys())
    colls2 = set(sources2.keys())
    if len(colls1) != len(colls2) or colls1 - colls2:
        return False
    for coll in colls1:
        if sources1[coll] != sources2[coll]:
            return False
    return True


def get_valid_names(tk, colls, char_names):
    """ 检查字图是否有效 """
    if not char_names:
        return []
    valid_names = []
    conds = config.get_select_conds()
    for coll in colls:
        cond = conds.get(coll)
        # cond = {'uncertain': {'$ne': True}, 'remark': {'$not': {'$regex': 'E|e|Ｅ|ｅ|T$'}}}
        chars = list(db_work[coll].find({**cond, 'txt': tk, 'name': {'$in': list(char_names)}}, {'name': 1, '_id': 0}))
        valid_names.extend([c['name'] for c in chars])
    return valid_names


def cmp_dict_data(data1, data2):
    """ 比较两份标注数据"""
    added, deleted = {}, {}
    for k in ['km_train_data', 'km_test_data', 'cc_train_data', 'cc_test_data']:
        _data1, _data2 = set(hp.prop(data1, k, [])), set(hp.prop(data2, k, []))
        added[k] = list(_data1 - _data2)
        deleted[k] = list(_data2 - _data1)
    return {'added': added, 'deleted': deleted}


def merge_dict_data(data_dict):
    """ 获取最新的数据 """
    merged_data = set()
    for k in ['km_train_data', 'km_test_data', 'cc_train_data', 'cc_test_data']:
        merged_data.update(hp.prop(data_dict, k, []))
    return merged_data


def cmp_list_data(data1, data2):
    """ 比较两份标注数据 """
    data1 = merge_list_data(data1)
    data2 = merge_list_data(data2)
    added = list(set(data1) - set(data2))
    deleted = list(set(data2) - set(data1))
    return {'added': added, 'deleted': deleted}


def merge_list_data(data_list):
    """ 合并数据 """
    merged_data = []
    for data in data_list:
        merged_data.extend(data)
    return merged_data


def cmp_data(data1, data2):
    """ 比较两份标注数据 """
    added = list(set(data1) - set(data2))
    deleted = list(set(data2) - set(data1))
    return {'added': added, 'deleted': deleted}


def random_select(data, n):
    """ 随机选择数据 """
    data = list(data)
    if len(data) <= n:
        return data
    return random.sample(data, n)


def divide_cc_data(cc_data, ratio):
    """ 按比例划分数据"""
    total = sum([len(cd['selected_data']) for cd in cc_data])
    n1 = int(total * ratio + 0.5)

    data1, data2 = set(), set()
    for i, cd in enumerate(cc_data):
        _data1 = []
        if len(data1) < n1:
            _n1 = int(len(cd['selected_data']) * ratio + 0.5)
            if n1 - len(data1) < _n1:  # 检查是否超过
                _n1 = n1 - len(data1)
            if i == len(cc_data) - 1:  # 最后一个
                _n1 = n1 - len(data1)
            if _n1:
                _data1 = random.sample(cd['selected_data'], _n1)
        data1.update(_data1)
        data2.update([d for d in cd['selected_data'] if d not in _data1])

    return list(data1), list(data2)


def select_cc_data(txt, colls, n_expected, prior_data1=None, prior_data2=None, exclude_data=None):
    """ 选择置信度标注数据
        注：排除数据的优先级大于优先数据
    """
    exclude_data = set(exclude_data or [])
    prior_data1 = set(prior_data1 or []) - exclude_data
    prior_data2 = set(prior_data2 or []) - exclude_data
    prior_data2 = prior_data2 - prior_data1  # 需要进行去重
    # 1. 根据置信度区间，按比例选择数据
    select_conds = config.get_select_conds()
    cc_ratios = config.get_cc_ratio()
    for cc_ratio in cc_ratios:
        # 准备参数
        _n_expected = round(n_expected * cc_ratio['ratio'])
        cc_ratio['n_expected'] = _n_expected
        source_data = set()
        for coll in colls:  # 从多个表中查找、合并字图
            cond = select_conds.get(coll)
            if cond:
                chars = list(db_work[coll].find({**cond, 'txt': txt, 'cc': cc_ratio['cc']}, {'name': 1, '_id': 0}))
                source_data.update([c['name'] for c in chars])
        cc_ratio['source_data'] = source_data
        cc_ratio['prior1'] = list(prior_data1 & source_data)
        cc_ratio['prior2'] = list(prior_data2 & source_data)

        # 从prior中选择
        selected_data = set()
        if _n_expected > 0 and cc_ratio['prior1']:
            cc_ratio['selected1'] = random_select(cc_ratio['prior1'], _n_expected)
            selected_data.update(cc_ratio['selected1'])
            _n_expected -= len(selected_data)

        # 从prior2中选择
        if _n_expected > 0 and cc_ratio['prior2']:
            cc_ratio['selected2'] = random_select(cc_ratio['prior2'], _n_expected)
            selected_data.update(cc_ratio['selected2'])
            _n_expected -= len(selected_data)

        # 从数据源中选择
        source_data = source_data - exclude_data - selected_data
        if _n_expected > 0 and source_data:
            cc_ratio['selected3'] = random_select(source_data, _n_expected)
            selected_data.update(cc_ratio['selected3'])

        cc_ratio['selected_data'] = list(selected_data)

    # 2. 不足时，从整体中随机选择
    _n_expected = n_expected - sum([len(d['selected_data']) for d in cc_ratios])
    if _n_expected > 0:
        # 准备参数
        cc_ratio = {'cc': 'all', 'n_expected': _n_expected}

        source_data0, selected_data0 = set(), set()
        for cr in cc_ratios:
            selected_data0.update(cr['selected_data'])
            source_data0.update(cr['source_data'])
        cc_ratio['prior1'] = list(prior_data1 & source_data0 - selected_data0)
        cc_ratio['prior2'] = list(prior_data2 & source_data0 - selected_data0)

        # 从prior中选择
        selected_data = set()
        if _n_expected > 0 and cc_ratio['prior1']:
            cc_ratio['selected1'] = random_select(cc_ratio['prior1'], _n_expected)
            selected_data.update(cc_ratio['selected1'])
            _n_expected -= len(cc_ratio['selected1'])

        # 从prior2中选择
        if _n_expected > 0 and cc_ratio['prior2']:
            cc_ratio['selected2'] = random_select(cc_ratio['prior2'], _n_expected)
            selected_data.update(cc_ratio['selected2'])
            _n_expected -= len(cc_ratio['selected2'])

        # 从数据源中选择
        source_data = source_data0 - selected_data0 - exclude_data - selected_data
        if _n_expected > 0 and source_data:
            cc_ratio['selected3'] = random_select(source_data, _n_expected)
            selected_data.update(cc_ratio['selected3'])
            _n_expected -= len(cc_ratio['selected3'])

        cc_ratio['selected_data'] = list(selected_data)
        cc_ratios.append(cc_ratio)

    # 整理数据格式
    for cc_ratio in cc_ratios:
        cc_ratio.pop('source_data', 0)
        cc_ratio['src'] = str(cc_ratio.pop('cc', 0))
    return cc_ratios


def stat_meta_csv(which='build'):
    """" 统计基础数据"""
    cond = {'active': True}
    tk_datas = list(db_lab.tk_data.aggregate([
        {'$match': cond},
        {'$project': {
            'tk': 1,
            'freq': 1,
            'km_train_cnt': {'$size': {'$ifNull': [f'${which}.km_train_data', []]}},
            'km_test_cnt': {'$size': {'$ifNull': [f'${which}.km_test_data', []]}},
            'cc_train_cnt': {'$size': {'$ifNull': [f'${which}.cc_train_data', []]}},
            'cc_test_cnt': {'$size': {'$ifNull': [f'${which}.cc_test_data', []]}},
        }}
    ]))
    rows = []
    for tk in tk_datas:
        n_train, n_test = get_expected_cnt(tk['freq'])
        equal = True
        if tk['km_train_cnt'] != n_train or tk['km_test_cnt'] != n_test \
                or tk['cc_train_cnt'] != n_train or tk['cc_test_cnt'] != n_test:
            equal = False
        rows.append([
            tk['tk'], tk['freq'], n_train, n_test, equal,
            tk['km_train_cnt'], tk['km_test_cnt'], tk['cc_train_cnt'], tk['cc_test_cnt']
        ])
    rows.sort(key=lambda x: x[1], reverse=True)
    head = ['字种', '源字频', '预期训练集字频', '预期测试集字频', '是否满足', 'km训练集字频', 'km测试集字频', 'cc训练集字频', 'cc测试集字频']
    save_csv([head] + rows, './meta/标注数据字种统计-%s.csv' % datetime.now().strftime('%Y%m%d%H%M%S'))


def get_unicode(char):
    """ 字符转unicode """
    code = char.encode('unicode_escape').decode('utf-8')
    code = 'U+%s' % (code.upper().replace(r'\U', '').lstrip('0'))
    return code


def update_work_chars(coll, char_names, field, value):
    """ 设置work平台char表的字段值 """
    cnt = 0
    size = 20000
    char_names = list(char_names)
    group_cnt = math.ceil(len(char_names) / size)
    for i in range(group_cnt):
        _names = char_names[i * size:(i + 1) * size]
        r = db_work[coll].update_many({'name': {'$in': _names}}, {'$set': {field: value}})
        cnt += r.matched_count
    return cnt


def insert_work_chars(coll, chars):
    """ work平台插入字数据 """
    cnt = 0
    size = 50000
    group_cnt = math.ceil(len(chars) / size)
    for i in range(group_cnt):
        _chars = chars[i * size:(i + 1) * size]
        r = db_work[coll].insert_many(_chars)
        cnt += len(r.inserted_ids)
    return cnt


def get_work_chars(colls, char_names, projection=None):
    """ 从work平台多表中获取字数据 """
    if not char_names:
        return []
    if isinstance(colls, str):
        colls = colls.split(',')
    all_chars = []
    for coll in colls:
        size = 50000  # 分批次查找
        group_cnt = math.ceil(len(char_names) / size)
        for i in range(group_cnt):
            _names = char_names[i * size:(i + 1) * size]
            chars = list(db_work[coll].find({'name': {'$in': _names}}, projection))
            for ch in chars:
                ch['src_coll'] = coll
            all_chars.extend(chars)

    return all_chars


def get_lab_tk2freq(char_coll, source):
    """获取字种字频统计数据"""
    tk2freq = {}
    group_items = db_lab[char_coll].aggregate([
        {'$match': {'source': source}},
        {'$group': {'_id': '$txt', 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}}
    ])
    for item in group_items:
        tk2freq[item['_id']] = item['count']
    return tk2freq


def split_list(lst, n):
    """列表拆分成多个子列表，每个子列表的长度是n"""
    return [lst[i:i + n] for i in range(0, len(lst), n)]


def get_log_time(log):
    df_time = datetime.strptime('1970-01-01', '%Y-%m-%d')  # 缺省时间
    return log.get('updated_time') or log.get('create_time') or df_time


def merge_txt_logs(logs1, logs2):
    """按时间序合并文字校对日志并去重"""

    def cmp_log(a, b):
        t1, t2 = get_log_time(a), get_log_time(b)
        return 1 if t1 > t2 else -1 if t1 < t2 else 0

    # logs = logs1 or []
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


def get_last_log_time(logs, field):
    """ 根据logs，获取field最后的修改时间"""
    logs = [log for log in logs if field in log]
    last_log = logs and logs[-1] or {}
    if last_log:
        return last_log.get('updated_time') or last_log.get('create_time')
