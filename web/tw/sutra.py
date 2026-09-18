import re
import os
import csv
import sys
import math
import logging
import os.path as path
from datetime import datetime

sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

import helper as hlp
# from wbst.tw import page as pg
# from wbst.tw.match import find_match_txt


def get_select_cond(sutra):
    """ 获取页数据查询条件"""
    start = hp.align_code('%s_%s' % (sutra['start_volume'], sutra['start_page']))
    end = hp.align_code('%s_%s' % (sutra['end_volume'], sutra['end_page']))
    cond = {'page_code': {'$gte': start, '$lte': end}}
    return cond


def get_cbeta_id(sutra_code):
    db = hp.get_db('')
    sutraid_cnt = dict()
    sutra = db.sutra.find_one({'sutra_code': sutra_code})
    pages = list(db.page.find(get_select_cond(sutra), {'name': 1, 'uni_txt': 1}).limit(10))
    for page in pages:
        match = find_match_txt(page['uni_txt'])
        if not match:
            continue
        for sid in match['sutra_id']:
            sutraid_cnt[sid] = sutraid_cnt.get(sid, 0) + 1
    return sutraid_cnt


def find_set_cbeta_id():
    """ 设置cbeta_id"""
    db = hp.get_db('')
    cond = {'source': 'JS6-1'}
    sutras = list(db.sutra.find(cond))
    for i, sutra in enumerate(sutras):
        cond = get_select_cond(sutra)
        pages = list(db.page.find(cond, {'_id': 0, 'txt_match0.sutra_id': 1}))
        sutraid2cnt = dict()
        for page in pages:
            for sid in hp.prop(page, 'txt_match0.sutra_id', []):
                sutraid2cnt[sid] = sutraid2cnt.get(sid, 0) + 1
        sutraid_cnt = sorted(sutraid2cnt.items(), key=lambda x: x[1], reverse=True)
        cbeta_id = sutraid_cnt[0][0] if sutraid_cnt else ''
        # db.sutra.update_one({'_id': sutra['_id']}, {'$set': {'cbeta_id': cbeta_id}})
        msg = ','.join(['%s#%s' % (sid, cnt) for sid, cnt in sutraid_cnt])
        print('%s\t%s\t%s' % (sutra['sutra_code'], cbeta_id, msg))


def set_page_cbeta_id():
    """ 设置cbeta_id"""
    db = hp.get_db('')
    cond = {'sutra_code': {'$regex': 'JS_'}, 'flag': 3}
    sutras = list(db.sutra.find(cond))
    cnt = 0
    for i, sutra in enumerate(sutras):
        cond = get_select_cond(sutra)
        cbeta_id = sutra.get('cbeta_id')
        r = db.page.update_many(cond, {'$set': {'cbeta_id': cbeta_id, 'flag': 18}})
        print('[%s/%s]%s, %s' % (i, len(sutras), sutra['sutra_code'], r.matched_count))
        cnt += r.matched_count
    print('total', cnt)


def sutra_find_match_txt():
    """ 查找cbeta文本"""
    hp.set_logging('sutra_find_match_txt')

    db = hp.get_db('')
    # cond = {'source': 'JS1'}
    cond = {'sutra_code': 'JS_1801'}
    start_time = hp.str2time('2023-08-23')
    sutras = list(db.sutra.find(cond))
    for i, sutra in enumerate(sutras):
        logging.info('[%s/%s]%s' % (i, len(sutras), sutra['sutra_code']))
        cbeta_id = sutra.get('cbeta_id')
        if cbeta_id in ['无', None]:
            cbeta_id = ''
        cond2 = get_select_cond(sutra)
        pages = list(db.page.find(cond2, {'name': 1, 'uni_txt': 1, 'txt_match': 1}))
        for j, page in enumerate(pages):
            logging.info('[%s/%s]%s, %s' % (j, len(pages), sutra['sutra_code'], page['name']))
            uni_txt = re.sub(r'<center>.*?\n', '', page.get('uni_txt', ''))
            if not uni_txt:
                continue
            page_cbeta_ids = list(set(hp.prop(page, 'txt_match.sutra_id', [])))
            if len(page_cbeta_ids) == 1 and page_cbeta_ids[0] == cbeta_id:
                continue
            create_time = hp.prop(page, 'txt_match.create_time')
            if create_time and create_time > start_time:
                continue
            match = find_match_txt(uni_txt, cbeta_id)
            if match:
                db.page.update_one({'name': page['name']}, {'$set': {'txt_match': match}})


def count_cbeta_txt():
    cond = {'source': 'JS1'}
    db = hp.get_db('')
    sutras = list(db.sutra.find(cond))
    for i, sutra in enumerate(sutras):
        cond2 = get_select_cond(sutra)
        cnt = db.page.count_documents({**cond2, 'source': 'JS1'})
        cnt2 = db.page.count_documents({**cond2, 'source': 'JS1', 'txt_match.found': None})
        ratio = cnt2 / cnt if cnt else 1
        print('%s\t%s\t%s\t%s\t%s' % (sutra['sutra_code'], sutra['cbeta_id'], cnt, cnt2, round(ratio, 3)))


def export_sutra_meta():
    """ 导出经元数据"""
    rows = []
    cond = {'source': 'JS3'}
    db = hp.get_db('')
    sutras = list(db.sutra.find(cond))
    for s in sutras:
        rows.append([s['sutra_code'], s['sutra_name'], s['author'], s['start_volume'],
                     s['start_page'], s['end_volume'], s['end_page'], s['existed_reel_count'],
                     s['remark'], s.get('cbeta_id', '')])
    rows.insert(0, ['经号', '经名', '作者', '起始册', '起始页', '终止册', '终止页', '实存卷数', '备注',
                    'CBETA经号'])
    with open(path.join(hp.BASE_DIR, 'txt/log', 'sutra_meta.csv'), 'w') as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def export_sutra_match_info():
    """ 导出经数据"""
    rows = []
    db = hp.get_db('')
    cond = {'sutra_code': {'$regex': 'JS_'}}
    sutras = list(db.sutra.find(cond))
    sutras.sort(key=lambda x: hp.align_code(x['sutra_code']))
    for i, s in enumerate(sutras):
        print('[%s/%s]%s' % (i, len(sutras), s['sutra_code']))
        cond = get_select_cond(s)
        total = db.page.count_documents(cond)
        cond2 = {**cond, '$or': [{'txt_match.selected': True}, {'txt_match2.selected': True}]}
        matched = db.page.count_documents(cond2)
        ratio = round(matched / total, 3)
        cond3 = {**cond, 'txt_match.selected': None, 'txt_match2.selected': None}
        pages = list(db.page.find(cond3, {'name': 1, '_id': 0}))
        missed = len(pages)
        missed_names = ','.join([page['name'] for page in pages])
        rows.append([
            s['sutra_code'], s['sutra_name'], s['author'], s['start_volume'],
            s['start_page'], s['end_volume'], s['end_page'], s['existed_reel_count'],
            s.get('cbeta_id', ''), total, matched, ratio, missed, missed_names
        ])
    rows.insert(0, ['经号', '经名', '作者', '起始册', '起始页', '终止册', '终止页', '卷数',
                    'CBETA经号', '总页数', '匹配页数', '匹配率', '失配页数', '失配页码'])
    with open(path.join(hp.BASE_DIR, 'txt/log', 'sutra_match_info.csv'), 'w') as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def set_char_n_group():
    """ 设置char表的n_group值"""
    size = 10000
    coll = 'char1'
    source = 'JS1-L'
    n_start = 4090  # n_group起始值
    db = hp.get_db('')
    sutra_no = range(1668, 1937)
    for sn in sutra_no:
        sutra_code = 'JS_%s' % sn
        sutra = db.sutra.find_one({'sutra_code': sutra_code})
        start = hp.align_code('%s_%s_1_1_1' % (sutra['start_volume'], sutra['start_page']))
        end = hp.align_code('%s_%s_9_1_1' % (sutra['end_volume'], sutra['end_page']))
        cond = {'uid': {'$gte': start, '$lte': end}, 'source': source}
        cnt = db[coll].count_documents(cond)
        if cnt < size:
            print(sutra_code, cnt, sn)
            # db[coll].update_many(cond, {'$set': {'n_group': sn}})
            continue
        chars = list(db[coll].find(cond, {'name': 1, '_id': 0}))
        names = [c['name'] for c in chars]
        names.sort(key=lambda x: hp.align_code(x))
        item_count = len(names)
        group_count = math.ceil(item_count / size)
        for i in range(group_count):
            _names = names[i * size:(i + 1) * size]
            r = db[coll].update_many({'name': {'$in': _names}}, {'$set': {'n_group': n_start}})
            print(sutra_code, cnt, i, n_start, r.matched_count)
            n_start += 1


def set_page_txt():
    db = hp.get_db('')
    sutra_codes = ['WZ_1764']
    for sc in sutra_codes:
        sutra = db.sutra.find_one({'sutra_code': sc})
        cond = get_select_cond(sutra)
        pages = list(db.page.find(cond, {'name': 1}))
        for i, page in enumerate(pages):
            print(page['name'])
            page = db.page.find_one({'name': page['name']}, {'name': 1, 'chars': 1, 'columns': 1})
            txt = pg.get_page_txt(page, txt_type='uni_txt', code2txt={'n': 'n'})
            db.page.update_one({'_id': page['_id']}, {'$set': {'uni_txt': txt}})


def export_match_txt():
    source = 'JS1'
    db = hp.get_db('')
    sutras = list(db.sutra.find({'source': source}))
    rows = [['序号', '经号', '页码', '页文本长度', '命中文本长度', '匹配文本长度', '命中-匹配长度', '命中文本相似率',
             '页文本', '匹配文本']]
    for i, sutra in enumerate(sutras):
        print(i, sutra['sutra_code'])
        cond = get_select_cond(sutra)
        cond.update({'source': source, 'txt_match.found': None})
        pages = list(db.page.find(cond, {'name': 1, 'uni_txt': 1, 'txt_match': 1}))
        for j, p in enumerate(pages):
            m = p.get('txt_match') or {}
            if not m.get('match_txt'):
                continue
            bd_str = '。？！，、；：“”‘’「」『』﹃﹄﹁﹂（）()《》〈〉［］〔〕【】——……－～P\u3000'
            match_txt = re.sub(r'[%s]+' % bd_str, '', m.get('match_txt', ''))  # 去掉标点
            match_txt = match_txt.replace('\n', '')
            uni_txt = re.sub(r'<center>.*?(\n|$)', '', p.get('uni_txt', ''))  # 去掉版心列
            uni_txt = uni_txt.replace('\n', '')
            row = [j + 1, sutra['sutra_code'], p['name'], m['len_uni_txt'], m['len_base'], m['len_match_txt'],
                   m['len_base_diff'], m['similar_base_ratio'], uni_txt, match_txt]
            rows.append(row)
    with open('/Users/xiandu/Document/00Inbox/%s-missed.csv' % source, 'w') as f:
        writer = csv.writer(f)
        writer.writerows(rows)

def get_sx_to_cbeta_mapping():
    """
    Returns a dict mapping SX sutra_uid to CBETA sutra_uid using rushi_sutra_uid as the bridge.
    """
    db = hp.get_db('tw-work')
    coll = db['sutra_source']

    # 1. Get all SX sutras
    sx_docs = list(coll.find({'source_type': 'SXZ'}, {'sutra_uid': 1, 'rushi_sutra_uid': 1}))
    sx_map = {doc['sutra_uid']: doc['rushi_sutra_uid'] for doc in sx_docs if 'sutra_uid' in doc and 'rushi_sutra_uid' in doc}

    # 2. For each rushi_sutra_uid, find the CBETA sutra_uid
    mapping = {}
    for sx_uid, rushi_uid in sx_map.items():
        cbeta_doc = coll.find_one({'rushi_sutra_uid': rushi_uid, 'source_type': 'CBETA'}, {'sutra_uid': 1})
        if cbeta_doc and 'sutra_uid' in cbeta_doc:
            mapping[sx_uid] = cbeta_doc['sutra_uid']
        else:
            mapping[sx_uid] = None  # or skip if you prefer

    return mapping

def get_text_w_catalog(sutra_uid="JS1523"):
    db = hlp.get_db('tr-prod-readonly')
    from web.tw.reel import get_reels_for_sutra_uid
    
    def get_catalog(sutra_uid):
        sutra = db['sutra']
        catalog = sutra.find({'uid': sutra_uid}, {'catalog': 1})
        return catalog

    def get_pages(reel_uid):
        page = db['page']
        pages = page.find({'uid': reel_uid}, {'pages': 1})
        return pages

    catalog = get_catalog(sutra_uid)
    reels = get_reels_for_sutra_uid(sutra_uid)
    print(reels)

    

def main(func='', **kwargs):
    eval(func)(**kwargs)

if __name__ == '__main__':
    import fire

    fire.Fire(main)
