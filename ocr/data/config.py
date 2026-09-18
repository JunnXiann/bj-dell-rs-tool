import sys
import os.path as osp

sys.path.append(osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__)))))

import helper as hp

db_lab = hp.get_db('tw-lab')
db_work = hp.get_db('tw-work')


def get_exclude_tks():
    """ 获取排除的字种 """
    # 异体字管理中被禁用的字种
    vts = list(db_work.variant.find({'activated': '否'}, {'v_code': 1, 'txt': 1}))
    tks1 = [vt.get('txt') or vt.get('v_code') for vt in vts]

    # 不纳入训练的字种（如特殊符号和兼容字）
    with open('./meta/ocr排除的符号和兼容字-231005.txt', mode='r', encoding='utf-8') as rf:
        tks2 = [ln.strip() for ln in rf.readlines()]

    return tks1 + tks2


def get_select_conds():
    """ 获取各表的查询条件 """
    cond = {'uncertain': {'$ne': True}, 'remark': {'$not': {'$regex': 'E|e|Ｅ|ｅ|T$'}}}
    # char2_sources = [f'JS2{i}' for i in 'ABCDEFGHIJ'] + ['JS1-V2']
    # char3_sources = ['JS3-1A', 'JS3-1B', 'JS3-1C', 'JS3-2', 'JS3A', 'JS3B', 'JS3C']
    # char6_sources = ['JS6-1A', 'JS6-1B', 'JS6-2A', 'JS6-2B', 'JS6-2C', 'JS50A', 'JS50B', 'JS50C']
    #
    # return {
    #     'char2': {**cond, 'tasks.cluster_review': {'$ne': None}, 'source': {'$in': char2_sources}},
    #     'char6': {**cond, 'tasks.cluster_review': {'$ne': None}, 'source': {'$in': char6_sources}},
    #     'char3': {**cond, 'tasks.cluster_proof': {'$ne': None}, 'source': {'$in': char3_sources}}
    # }

    char2_sources = [f'JS2{i}' for i in 'ABCDEFGHIJK'] + ['JS2-V']
    char3_sources = ['JS3-1A', 'JS3-1B', 'JS3-1C', 'JS3-2', 'JS3-3C', 'JS3-4A1', 'JS3-4A2', 'JS3-4B1', 'JS3-4B2']
    char4_sources = ['JS4A1-1', 'JS4A2-1', 'JS4B1', 'JS4B2', 'JS4C']
    char5_sources = ['JS5A1', 'JS5A2', 'JS5B1', 'JS5B2', 'JS5C']
    char6_sources = ['JS50A', 'JS50B', 'JS50C', 'JS6-1A', 'JS6-1B', 'JS6-2A', 'JS6-2B', 'JS6-2C', 'JS6-3', 'JS6-4',
                     'JS6-5']

    return {
        'char1': {**cond, 'source': 'JS1-V'},
        'char2': {**cond, 'source': {'$in': char2_sources}},
        'char3': {**cond, 'source': {'$in': char3_sources}},
        'char4': {**cond, 'source': {'$in': char4_sources}},
        'char5': {**cond, 'tasks.cluster_proof': {'$ne': None}, 'source': {'$in': char5_sources}},
        'char6': {**cond, 'tasks.cluster_review': {'$ne': None}, 'source': {'$in': char6_sources}}
    }


def get_select_colls():
    """ 获取启用的数据源表名称 """
    return ['char1', 'char2', 'char3', 'char4', 'char5', 'char6']


def get_cc_ratio():
    """ 不同的置信度区间，设置不同的比例"""
    return [
        {'cc': {'$gte': 751, '$lte': 1000}, 'ratio': 0.35},
        {'cc': {'$gte': 501, '$lte': 750}, 'ratio': 0.30},
        {'cc': {'$gte': 251, '$lte': 500}, 'ratio': 0.20},
        {'cc': {'$gte': 0, '$lte': 250}, 'ratio': 0.15},
    ]
