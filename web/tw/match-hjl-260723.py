import csv
import os
import re
import sys
import random
import logging
import os.path as path
from datetime import datetime
from functools import cmp_to_key

sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

import helper as hlp
from util.diff import diff
from util.uni2std import normalize
from web.tw.page import get_base_txt, apply_txt2char, apply_txt2missingchars, apply_PH_txt2char
from web.tw.esearch import find_match, check_segments_v3, find_reel_txt
from util.punc import trim_punc, transfer_cmp_punc_to_base, trim_cbeta_whitespace, PUNC_STR
from util.find_match import find_best_match
from web.tw.reel import get_page_select_cond, col_sort_key

def get_code2txt(txt_type='base_txt', v_codes=None):
    """ 初始化code2txt"""

    def unicode2char(unicode):
        unicode = unicode.replace('U+', '').lower()
        unicode = f'\\u{unicode}' if len(unicode) <= 4 else f'\\U000{unicode}'
        return unicode.encode('utf-8').decode('unicode_escape')

    def get_txt(vt):
        if txt_type == 'ori_txt' and vt.get('unicode'):
            return unicode2char(vt.get('unicode'))
        else:
            return vt.get(txt_type) or vt.get('nor_txt') or ''

    cond = {'v_code': {'$exists': True}}
    if v_codes:
        cond = {'v_code': {'$in': v_codes}}
    db = hlp.get_db('tw-prod-readonly')
    vts = list(db.variant.find(cond, {'v_code': 1, 'base_txt': 1, 'nor_txt': 1, 'unicode': 1, '_id': 0}))
    return {vt.get('v_code'): get_txt(vt) for vt in vts}


def batch_set_base_txt():
    """ 批量设置base_txt """
    hlp.set_logging('batch_set_base_txt')

    # 需根据实际情况修改
    # cond = {
    #     'source': {'$in': 'JS1&2-XC/JS3-XC'.split('/')},
    #     'txt_match.selected': None, 'txt_match2.selected': None,
    #     '$or': [{'txt_match.status': {'$in': [3, 4]}}, {'txt_match2.status': {'$in': [3, 4]}}]
    # }
    # cond = {'page_code': {'$gte': hlp.align_code('JS_177_1'), '$lte': hlp.align_code('JS_226_9999')}}
    # cond = {'name': 'PH_10_1'}
    #cond = {'name': {'$regex': '^PH_'}}
    # cond = {'name': 'PH_1_45'}
   # cond = {'source':  {'$in':['RD-4','RD-5']}}
    
    cond = {'flag1':153621,'flag3':1242}
    print(cond)
    db = hlp.get_db('tw-prod-readonly')
    pages = list(db.page.find(cond, {'name': 1}))
    for i, page in enumerate(pages):
        logging.info('[%s/%s]%s' % (i, len(pages), page['name']))
        page = db.page.find_one({'name': page['name']}, {'name': 1, 'chars': 1, 'columns': 1})
        base_txt = get_base_txt(db, page)
        #print(base_txt)
        db.page.update_one({'_id': page['_id']}, {'$set': {'base_txt': base_txt}})


def has_special(txt):
    if '音釋' in txt or '音𥼶' in txt:
        return True
    return False


def get_status(r_match2base, r_similar2hit, r_hit2base, base_txt=''):
    status = 2  # 不匹配
    special = has_special(base_txt)
    ratio_hit_ok = r_hit2base > 0.4 or (special and r_hit2base > 0.3)
    if r_match2base < 2 and r_similar2hit > 0.7 and ratio_hit_ok:
        status = 3  # 中度匹配
        if r_hit2base > 0.9 and r_similar2hit > 0.9:
            status = 4  # 高度匹配
            if r_hit2base == 1.0 and r_similar2hit == 1.0 and r_match2base == 1.0:
                status = 5  # 完全匹配
    return status


def get_match_info(base_txt, match_txt, checked_segments=None, cencol_char_cnt=0):
    if not checked_segments:
        segments = diff(base_txt, match_txt, lambda x: x != '\n', lambda x: x not in f'{PUNC_STR}\n', True, True)
        _, _, match_txt, checked_segments = check_segments_v3(segments)
    len_base_txt0 = len(base_txt.replace('\n', ''))
    len_base_txt = len_base_txt0 - cencol_char_cnt  # 去掉版心列
    len_match_txt = len(trim_punc(match_txt, True))
    r_match2base = round(len_match_txt / len_base_txt, 3) if len_base_txt else 0
    len_hit = len(''.join([s['base'] for s in checked_segments])) - cencol_char_cnt  # 去掉版心列
    r_hit2base = round(len_hit / len_base_txt, 3) if len_base_txt else 0
    len_similar = len(''.join([s['base'] for s in checked_segments if s['is_same'] or len(s['base']) == len(s['cmp'])]))
    r_similar2hit = round(len_similar / len_hit, 3) if len_hit else 0
    r_similar2base = round(len_similar / len_base_txt, 3) if len_base_txt else 0
    special = has_special(base_txt)
    status = get_status(r_match2base, r_similar2hit, r_hit2base, base_txt)
    match = dict(
        status=status, has_special=special, len_base_txt0=len_base_txt0, len_base_txt=len_base_txt,
        match_txt=match_txt, len_match_txt=len_match_txt, r_match2base=r_match2base,
        len_hit=len_hit, r_hit2base=r_hit2base,
        len_similar=len_similar, r_similar2hit=r_similar2hit, r_similar2base=r_similar2base,
    )
    return match


def find_match_txt(base_txt, sutra_id='', index='jsz-ik', revserse=True):
    """ 页数据查找cbeta比对文本"""
    len_base_txt = len(base_txt.replace('\n', ''))
    if len(base_txt) < 10:
        return {'status': 0, 'len_base_txt': len_base_txt}  # 不予查找
    m = find_match(base_txt, sutra_id, revserse, index)
    if not m:
        return {'status': 1, 'len_base_txt': len_base_txt}  # 未找到
    match = get_match_info(base_txt, m['match_txt'], m['segments'])
    match.update(dict(
        page_ids=[pid for p in m['pages'] for pid in p.get('page_ids', [])],
        volume_ids=[p.get('volume_id', '') for p in m['pages']],
        sutra_ids=[p.get('sutra_id', '') for p in m['pages']],
        reel_ids=[p.get('reel_id', '') for p in m['pages']],
        sn=[p.get('sn', '') for p in m['pages']],
        sutra_id=sutra_id
    ))
    return match


def cmp_match(m1, m2):
    """ 比较match信息"""
    if not m1.get('status') or not m2.get('status'):
        return 0
    if m1['status'] != m2['status']:
        return 1 if m1['status'] > m2['status'] else -1
    if not m1.get('r_similar2base') or not m2.get('r_similar2base'):
        return 0
    if abs(m1['r_similar2base'] - m2['r_similar2base']) > 0.1:
        return 1 if m1['r_similar2base'] > m2['r_similar2base'] else -1
    return 1 if m1['r_similar2hit'] > m2['r_similar2hit'] else -1


def get_best_match(matches):
    """ 获取最佳匹配"""
    matches = [m for m in matches if m.get('status') is not None]
    matches.sort(key=cmp_to_key(cmp_match), reverse=True)
    return matches and matches[0]


def batch_find_match_txt(flag3):
    """ 页数据查找cbeta比对文本"""
    hlp.set_logging('batch_find_match_txt')

    # 设置参数
    force = True  # 已存在时，是否强制查找 
    #index_id = 'jsz-ik-std-reel'  # 查询哪个索引库 5 ik cbeta-ik jsz-ik jsz-ik-std jsz-ik-reel jsz-ik-std-reel
    #index_id = 'cbeta-ik' 
    #index_id = 'jsz-ik' 
    #index_id = 'jsz-ik-std' 
    index_id = 'jsz-ik-reel' 

    #index_id = 'jsz-ik-std-reel'
   # cond = {'name': {'$regex': '^RD_'}}
    #cond = {'source': 'RD-AK'}
    #cond = {'source':{'$in':['RD-3','RD-4']},'flag': 260723}
    db = hlp.get_db('tw-prod-readonly')
    #cond = {'source':  'RD-3'}
    #cond = {'source':  {'$in':['RD-4','RD-5']}}
    
    cond = {'flag1':153621,'flag3':flag3}
    print(cond)
    # page_names = db.page.distinct('name', cond)
    page_names = db.page.distinct('name', cond) #flag1 flag3 
    print('Total pages to process:', len(page_names))
    for i, page_name in enumerate(page_names):
        print('[%s/%s]%s' % (i, len(page_names), page_name))
        page = db.page.find_one({'name': page_name}, {'name': 1, 'sutra_id': 1, 'base_txt': 1, 'match': 1, 'match_logs': 1})
        if not page.get('base_txt'):  # 需先设置基准文本
            continue
        if hlp.prop(page, 'match.status') == 5:  # 已找到
            continue

        now = datetime.now()
        logs = page.get('match_logs') or []
        logs0 = [[i, log] for i, log in enumerate(logs) if log.get('index_id') == index_id]
        # 初次查找，不指定经号
        logs1 = [log for log in logs0 if not log[1].get('sutra_id')]  # 无经号
        if not logs1 or force:
            match1 = find_match_txt(page['base_txt'], index=index_id)
            if not logs1:  # 新增
                match1.update({'index_id': index_id, 'create_by': 'operator', 'create_time': now})
                logs.append(match1)
            else:  # 更新
                match1.update({'updated_time': now})
                logs[logs1[0][0]].update(match1)
        # 二次查找，指定经号
        sutra_id = page.get('sutra_id')
        logs2 = [log for log in logs0 if log[1].get('sutra_id') == sutra_id]  # 有经号
        if sutra_id and (not logs2 or force):
            match2 = find_match_txt(page['base_txt'], sutra_id, index=index_id)
            if not logs2:  # 新增
                match2.update({'index_id': index_id, 'create_by': 'operator', 'create_time': now})
                logs.append(match2)
            else:  # 更新
                match2.update({'updated_time': now})
                logs[logs2[0][0]].update(match2)

        match = get_best_match(logs)
        db.page.update_one({'name': page['name']}, {'$set': {'match': match, 'match_logs': logs}})


def batch_find_match_txt_912():
    """ 页数据查找cbeta比对文本"""
    hlp.set_logging('batch_find_match_txt')

    # 设置参数
    force = False  # 已存在时，是否强制查找
    index_id = 'jsz-ik-reel'  # 查询哪个索引库 5 ik

    db = hlp.get_db('tw-work')
    cond = {'flag': 717, 'flag2': 1217 } #flag1: 91220251 ~ 91220256
    # cond = {'name': 'FZ_83_3_19'}

    page_names = db.page.distinct('name', cond) #flag1 flag3 
    # print('Total pages to process:', len(page_names))
    # return
    for i, page_name in enumerate(page_names):
        print('[%s/%s]%s' % (i, len(page_names), page_name))
        page = db.page.find_one({'name': page_name}, {'name': 1, 'sutra_id': 1, 'base_txt': 1, 'match': 1, 'match_logs': 1})
        if not page.get('base_txt'):  # 需先设置基准文本
            continue
        if hlp.prop(page, 'match.status') == 5 and not force:  # 已找到
            continue

        now = datetime.now()
        logs = page.get('match_logs') or []
        logs0 = [[i, log] for i, log in enumerate(logs) if log.get('index_id') == index_id]
        # 初次查找，不指定经号
        logs1 = [log for log in logs0 if not log[1].get('sutra_id')]  # 无经号
        if not logs1 or force:
            match1 = find_match_txt(page['base_txt'], index=index_id)
            if not logs1:  # 新增
                match1.update({'index_id': index_id, 'create_by': 'operator', 'create_time': now})
                logs.append(match1)
            else:  # 更新
                match1.update({'updated_time': now})
                logs[logs1[0][0]].update(match1)
        # 二次查找，指定经号
        sutra_id = page.get('sutra_id')
        logs2 = [log for log in logs0 if log[1].get('sutra_id') == sutra_id]  # 有经号
        if sutra_id and (not logs2 or force):
            match2 = find_match_txt(page['base_txt'], sutra_id, index=index_id)
            if not logs2:  # 新增
                match2.update({'index_id': index_id, 'create_by': 'operator', 'create_time': now})
                logs.append(match2)
            else:  # 更新
                match2.update({'updated_time': now})
                logs[logs2[0][0]].update(match2)

        match = get_best_match(logs)
        # db.page.update_one({'name': page['name']}, {'$set': {'match': match, 'match_logs': logs}})
        result = db.page.update_one({'name': page['name']}, {'$set': {'match': match, 'match_logs': logs}})
        # print(f"Update result for {page['name']}: matched={result.matched_count}, modified={result.modified_count}")

# def clear_match_logs():
#     """ 清除match_logs """
#     hlp.set_logging('clear_match_logs')

#     db = hlp.get_db('tw-prod-readonly')
#     cond = {'name': {'$regex': '^PH_'}}

#     db.page.update_many(cond, {'$unset': {'match_logs': 1, 'match': 1}})

def count_match_status(cond={'source': 'RD-AK'}, db_name='tw-prod-readonly'):
    """
    Count occurrences of different match.status values for pages matching cond.
    """
    db = hlp.get_db(db_name)
    cursor = db.page.find(cond, {'match.status': 1, 'name': 1})
    status_count = {}
    total = 0
    pages_with_none = []

    for page in cursor:
        status = hlp.prop(page, 'match.status')
        if status is None:
            pages_with_none.append(page.get('name'))
        status_count[status] = status_count.get(status, 0) + 1
        total += 1

    print(f'Total pages: {total}')
    print('match.status counts:')
    # Sort keys: None last, numbers first
    for k in sorted(status_count.keys(), key=lambda x: (x is None, x)):
        print(f'  status={k}: {status_count[k]}')

    if pages_with_none:
        print('Pages with None match.status:')
        for name in pages_with_none:
            print(f'  {name}')

    return status_count

def set_flag1_in_batches(flag_base=91220251, batch_size=10000, batches=6,
                         cond=None, db_name='tw-work', dry_run=True, chunk_size=1000):

    cond = {'flag': 717, 'flag2': 1208}
    db = hlp.get_db(db_name)

    # get distinct page names
    names = db.page.distinct('name', cond)
    total = len(names)
    if total == 0:
        print('No names found for condition:', cond)
        return

    print(f'Found {total} distinct names. Preparing {batches} batches.')
    batches_list = []
    start = 0
    # create first (batches-1) blocks of batch_size
    for i in range(batches - 1):
        end = min(start + batch_size, total)
        batches_list.append(names[start:end])
        start = end
    # last batch = remainder
    batches_list.append(names[start:total])

    # perform updates per batch (chunked updates to avoid very large $in lists)
    for i, batch_names in enumerate(batches_list):
        flag_value = flag_base + i
        count_batch = len(batch_names)
        if count_batch == 0:
            print(f'Batch {i+1} (flag1={flag_value}) is empty, skipping.')
            continue

        print(f'Batch {i+1}/{batches}: flag1={flag_value}, names={count_batch}')
        if dry_run:
            # print a small sample
            sample = batch_names[:5]
            print('  sample names:', sample)
            continue

        modified_total = 0
        # chunked update_many calls
        for j in range(0, count_batch, chunk_size):
            chunk = batch_names[j:j + chunk_size]
            r = db.page.update_many({'name': {'$in': chunk}}, {'$set': {'flag1': flag_value}})
            modified_total += getattr(r, 'modified_count', 0)
            print(f'  updated chunk {j//chunk_size + 1}: {len(chunk)} names, modified={getattr(r, "modified_count", 0)}')

        print(f'Batch {i+1} done: total updated documents = {modified_total}')

    print('All batches processed.')


def batch_find_match_txt_jx():
    """ 东大嘉兴藏页数据查找径山藏比对文本"""
    hlp.set_logging('batch_find_match_txt_jx')

    # 设置参数
    force = True  # 已存在时，是否强制查找
    index_id = 'jsz_std_txt_by_block'  # 查询哪个索引库

    db = hlp.get_db('tw-work')
    # cond = {'page_code': {'$gte': hp.align_code('JS_156_422'), '$lte': hp.align_code('JS_156_584')}}
    cond = {'name': {'$regex': '^JX_4_4_17'}}

    page_names = db.page.distinct('name', cond)
    for i, page_name in enumerate(page_names):
        print('[%s/%s]%s' % (i, len(page_names), page_name))
        page = db.page.find_one(cond, {'name': 1, 'sutra_id': 1, 'base_txt_a': 1, 'base_txt_b': 1, 'match_logs': 1})
        match_logs = page.get('match_logs') or []

        for j, key in enumerate(['a', 'b']):
            base_txt = page.get(f'base_txt_{key}')
            if not base_txt:  # 需先设置基准文本
                continue
            now = datetime.now()
            block_no = f'{page_name}_{key}'
            # 如果status=5或者0，跳过
            logs_matched = [log for log in match_logs if log.get('index_id') == index_id and
                            log.get('block_no') == block_no and log.get('status') in [5, 0]]
            if logs_matched:
                continue
            # 检查日志是否已存在
            logs0 = [[i, log] for i, log in enumerate(match_logs) if
                     log.get('index_id') == index_id and log.get('block_no') == block_no]
            # 检查初次查找（不指定经号）的日志是否已存在
            logs1 = [log for log in logs0 if not log[1].get('sutra_id')]
            if not logs1 or force:
                match1 = find_match_txt(base_txt, index=index_id, revserse=False)  # 不进行前后页查找
                if not logs1:  # 新增
                    match1.update({'index_id': index_id, 'create_by': 'operator', 'create_time': now,
                                   'block_no': block_no})
                    match_logs.append(match1)
                else:  # 更新
                    match1.update({'updated_time': now})
                    match_logs[logs1[0][0]].update(match1)

        db.page.update_one({'name': page['name']}, {'$set': {'match_logs': match_logs}})


# def batch_apply_match_txt():
#     """ 批量适配cbeta比对文本"""
#     hlp.set_logging('batch_apply_match_txt')

#     db = hlp.get_db('tw-work')
#     cond = {'name': 'YB_18_217'}
#     # cond = {'name': {'$regex': 'YB_'}}

#     pages = list(db.page.find(cond, {'name': 1, '_id': 0}))
#     for i, page in enumerate(pages):
#         logging.info('[%s/%s]%s' % (i, len(pages), page['name']))
#         fields = ['name', 'match', 'chars', 'columns']
#         page = db.page.find_one({'name': page['name']}, {f: 1 for f in fields})
#         base_txt = get_base_txt(db, page).replace('\n', '')
#         match_txt = hlp.prop(page, 'match.match_txt')
#         if not base_txt or not match_txt:
#             continue
#         r = apply_txt2char(page, base_txt, match_txt, 'cmp_txt', False)
#         if r:
#             db.page.update_one({'name': page['name']}, {'$set': {'chars': page['chars']}})
#         else:
#             logging.info('[e1]%s failed' % page['name'])


def batch_apply_match_txt():
    """ 批量适配cbeta比对文本"""
    hlp.set_logging('batch_apply_match_txt')
    print('batch_apply_match_txt')

    db_work = hlp.get_db('tw-prod-readonly')
    #names = db_work.page.distinct('name', {'source': 'RD-AC'})
    names = db_work.page.distinct('name', {'source': 'RD-3','flag2':788})
    # names = ['RD_332_1']
    # name = ['PH_1_45', 'PH_1_46', 'PH_1_47', 'PH_1_48', 'PH_1_49', 'PH_1_50', 'PH_1_60']
    # names = db_work.page.distinct('name', {'name': {'$in': name}})
    sorted_lst = sorted(names, key=lambda x: [int(y) for y in x.split('_') if y.isdigit()])
    split_lst = [sorted_lst[i:i + 10] for i in range(0, len(sorted_lst), 10)]
    for i, lst in enumerate(split_lst):
        print(i, len(split_lst))
        pages = list(db_work.page.find({'name': {'$in': lst}}))
        for i, page in enumerate(pages):
            # if 'PH' not in page['name']:
            #     continue
            logging.info('[%s/%s]%s' % (i, len(pages), page['name']))
            base_txt = get_base_txt(db_work, page).replace('\n', '')
            match_txt = hlp.prop(page, 'match.match_txt')
            if not base_txt or not match_txt:
                continue
            try:
                for ch in page.get('chars', []):
                    ch.pop('cmp_txt', 0)
                r = apply_txt2char(page, base_txt, match_txt, 'cmp_txt', False)
                # r = apply_PH_txt2char(page, base_txt, match_txt, 'cmp_txt', False)
                if r:
                    db_work.page.update_one({'name': page['name']}, {'$set': {'chars': page['chars'], 'flag3': 2606260924}})
                else:
                    logging.info('[e1]%s failed' % page['name'])
            except Exception as e:
                print(f"Error reading font file: {e}")


def batch_check_PH_match_txt(source='PH', out_path=None):
    """ 检查PH页字框中疑似错位的cmp_txt，并写入csv日志"""

    def clean_txt(ch, field):
        return (ch.get(field) or '').strip()

    def get_active_chars(page):
        center_column_ids = {
            c.get('column_id') for c in page.get('columns', [])
            if c.get('is_center') and not c.get('deleted')
        }
        return [
            ch for ch in page.get('chars', [])
            if not ch.get('deleted')
            and not ch.get('added')
            and ch.get('char_id', '').rsplit('c', 1)[0] not in center_column_ids
        ]
    def get_match2base(page):
        match = page.get('match', {})
        return match.get('r_match2base', 0)

    hlp.set_logging('batch_check_PH_match_txt')
    db_work = hlp.get_db('tw-prod-readonly')
    cond = {'name': {'$regex': f'^{source}_'}}
    names = db_work.page.distinct('name', cond)
    sorted_lst = sorted(names, key=lambda x: [int(y) for y in x.split('_') if y.isdigit()])
    split_lst = [sorted_lst[i:i + 10] for i in range(0, len(sorted_lst), 10)]

    out_path = out_path or path.join(hlp.BASE_DIR, 'log', f'{source.lower()}_match_char_errors_4.0.csv')
    os.makedirs(path.dirname(out_path), exist_ok=True)

    total_hits = 0
    with open(out_path, 'w', encoding='utf-8', newline='') as fw:
        writer = csv.writer(fw)
        writer.writerow(['page_name', 'cid', 'next_cid', 'ocr_txt', 'cmp_txt', 'next_ocr_txt', 'next_cmp_txt', 'link'])

        for batch_idx, lst in enumerate(split_lst):
            print(batch_idx, len(split_lst))
            pages = list(db_work.page.find({'name': {'$in': lst}}, {'name': 1, 'chars': 1, 'columns': 1, 'match': 1, '_id': 0}))
            pages.sort(key=lambda x: [int(y) for y in x['name'].split('_') if y.isdigit()])
            for page_idx, page in enumerate(pages):
                logging.info('[%s/%s]%s' % (page_idx, len(pages), page['name']))
                chars = get_active_chars(page)
                if len(chars) < 2:
                    continue

                for idx in range(len(chars) - 1):
                    curr_char = chars[idx]
                    next_char = chars[idx + 1]
                    curr_ocr_txt = clean_txt(curr_char, 'ocr_txt')
                    curr_cmp_txt = clean_txt(curr_char, 'cmp_txt')
                    next_ocr_txt = clean_txt(next_char, 'ocr_txt')
                    next_cmp_txt = clean_txt(next_char, 'cmp_txt')

                    if curr_ocr_txt == '一' and curr_cmp_txt == '一' and ((next_ocr_txt == '一' and next_cmp_txt != '一') or next_cmp_txt == '■'):
                    # if curr_ocr_txt == '一' and curr_cmp_txt == '一' and get_match2base(page) > 1.0:
                        writer.writerow(
                            [
                                page['name'],
                                curr_char.get('cid', ''),
                                next_char.get('cid', ''),
                                curr_ocr_txt,
                                curr_cmp_txt,
                                next_ocr_txt,
                                next_cmp_txt,
                                f'https://work.tripitakas.net/page/{page["name"]}?cid={curr_char.get("cid", "")}',
                            ]
                        )
                        total_hits += 1

    print('done, %s hits written to %s' % (total_hits, out_path))
    return out_path


def batch_transfer_bd_from_match_txt():
    """ 按页进行标点迁移"""

    def is_js_txt(t):
        return t not in '\n'

    def is_match_txt(t):
        return t not in PUNC_STR

    hlp.set_logging('batch_transfer_bd_from_match_txt')

    db = hlp.get_db('tw-work')
    # cond = {
    #     'source': 'JS3', 'flag': {'$ne': 9},
    #     '$or': [{'txt_match.status': {'$in': [3, 4]}}, {'txt_match2.status': {'$in': [3, 4]}}]
    # }
    cond = {'name': 'JS_14_1077'}
    pages = list(db.page.find(cond, {'name': 1, '_id': 0}))
    for i, page in enumerate(pages):
        fields = ['name', 'txt_match', 'txt_match2', 'base_txt']
        page = db.page.find_one({'name': page['name']}, {f: 1 for f in fields})
        # base_txt
        base_txt = page.get('base_txt', '').strip()
        if not base_txt:
            logging.info('[%s/%s]%s, base_txt is empty.' % (i, len(pages), page['name']))
            continue
        # match_txt
        m1, m2 = hlp.prop(page, 'txt_match'), hlp.prop(page, 'txt_match2')
        if not m1 and not m2:
            logging.info('[%s/%s]%s, txt_match dict is empty.' % (i, len(pages), page['name']))
            continue

        if m1 and m2:
            selected = 1 if cmp_match(m1, m2) else 2
        else:
            selected = 1 if m1 else 2
        match = m1 if selected == 1 else m2
        match_txt = match.get('match_txt')
        if not match_txt:
            logging.info('[%s/%s]%s, match_txt is empty.' % (i, len(pages), page['name']))
            continue
        match_txt = match_txt.replace('\n', '¶')
        match_txt = re.sub('[（）()]+', '', match_txt)
        # transfer bd
        cencol_lines = [(i, ln) for i, ln in enumerate(base_txt.split('\n')) if 'center' in ln]
        if cencol_lines:
            n, cencol_txt = cencol_lines[0]
            base_txt = re.sub(r'<center>.*?(\n|$)', '', base_txt)  # 去掉版心列
            segments = diff(base_txt, match_txt, is_js_txt, is_match_txt)
            transfer_cmp_punc_to_base(segments, is_js_txt, is_match_txt)
            bd_txt = ''.join([seg['base1'] for seg in segments])
            bd_txt = re.sub(r'\n([%s]+)' % PUNC_STR, r'\1\n', bd_txt)
            bd_txt_lines = bd_txt.split('\n')
            bd_txt_lines.insert(n, cencol_txt)
            bd_txt = '\n'.join(bd_txt_lines)
        else:
            segments = diff(base_txt, match_txt, is_js_txt, is_match_txt)
            transfer_cmp_punc_to_base(segments, is_js_txt, is_match_txt)
            bd_txt = ''.join([seg['base1'] for seg in segments])
            bd_txt = re.sub(r'\n([%s]+)' % PUNC_STR, r'\1\n', bd_txt)
        db.page.update_one({'name': page['name']}, {'$set': {'bd_txt': bd_txt}})
        logging.info('[%s/%s]%s, success.' % (i, len(pages), page['name']))


def batch_transfer_bd_from_cmp_txt():
    """ 按页进行标点迁移"""

    def is_js_txt(t):
        return t not in '<char id=".jpg">abcdefghijklmnopqrstuvwxyz\n'

    def is_match_txt(t):
        return t not in PUNC_STR

    hlp.set_logging('batch_transfer_bd_from_cmp_txt')

    db = hlp.get_db('tw-work')
    # cond = {'page_code': {'$gte': hp.align_code('JS_177_1'), '$lte': hp.align_code('JS_226_9999')}}
    cond = {'name': 'JS_192_830'}

    pages = list(db.page.find(cond, {'name': 1, '_id': 0}))
    for i, page in enumerate(pages):
        fields = ['name', 'base_txt', 'cmp_txt']
        page = db.page.find_one({'name': page['name']}, {f: 1 for f in fields})
        # base_txt
        base_txt = page.get('base_txt', '').strip()
        if not base_txt:
            logging.info('[%s/%s]%s, base_txt is empty.' % (i, len(pages), page['name']))
            continue
        # match_txt
        cmp_txt = page.get('cmp_txt')
        if not cmp_txt:
            logging.info('[%s/%s]%s, cmp_txt is empty.' % (i, len(pages), page['name']))
            continue
        cmp_txt = cmp_txt.replace('\n', '').replace('/', '')
        cmp_txt = re.sub('[（）()]+', '', cmp_txt)
        # cmp_txt = cmp_txt.replace('\n', '¶')
        # transfer bd
        cencol_lines = [(i, ln) for i, ln in enumerate(base_txt.split('\n')) if 'center' in ln]
        if cencol_lines:
            n, cencol_txt = cencol_lines[0]
            base_txt = re.sub(r'<center>.*?(\n|$)', '', base_txt)  # 去掉版心列
            segments = diff(base_txt, cmp_txt, is_js_txt, is_match_txt)
            transfer_cmp_punc_to_base(segments, is_js_txt, is_match_txt)
            bd_txt = ''.join([seg['base1'] for seg in segments])
            bd_txt = re.sub(r'\n([%s]+)' % PUNC_STR, r'\1\n', bd_txt)
            bd_txt_lines = bd_txt.split('\n')
            bd_txt_lines.insert(n, cencol_txt)
            bd_txt = '\n'.join(bd_txt_lines)
        else:
            segments = diff(base_txt, cmp_txt, is_js_txt, is_match_txt)
            transfer_cmp_punc_to_base(segments, is_js_txt, is_match_txt)
            bd_txt = ''.join([seg['base1'] for seg in segments])
            bd_txt = re.sub(r'\n([%s]+)' % PUNC_STR, r'\1\n', bd_txt)
        db.page.update_one({'name': page['name']}, {'$set': {'bd_txt': bd_txt}})
        logging.info('[%s/%s]%s, success.' % (i, len(pages), page['name']))


def custom_sort_key(s):
    parts = re.findall(r'[A-Z](\d+)[a-z]*_(\d+)', s)
    if parts:
        main_part1, main_part2 = parts[0]
        main_key = (int(main_part1), int(main_part2))
    else:
        main_key = (0, 0)
    if re.search(r'x\d+$', s):
        suffix_match = re.search(r'x(\d+)$', s)
        suffix_num = int(suffix_match.group(1)) if suffix_match else 0
        priority = 1
        suffix_type = 'x'
    elif re.search(r'z\d+$', s):
        suffix_match = re.search(r'z(\d+)$', s)
        suffix_num = int(suffix_match.group(1)) if suffix_match else 0
        priority = 3
        suffix_type = 'z'
    elif re.search(r'[a-z]$', s) and not re.search(r'[a-z]\d', s):
        suffix_type = re.search(r'([a-z])$', s).group(1)
        suffix_num = ord(suffix_type) - ord('a') + 1
        priority = 2
    else:
        priority = 2
        suffix_type = ''
        suffix_num = 0
    return (main_key[0], main_key[1], priority, suffix_type, suffix_num)


def excel_fz_js_mapping_with_pages(excel_path="./data/福州藏对应径山藏.xlsx", json_path="./data/fz_js.json"):
    import pandas as pd
    import json
    import re

    def is_match(page_name, start_code, end_code):
        def parse(code):
            m = re.match(r'(FZ_\d+)_(\d+)_(\d+)', str(code))
            if not m:
                return None
            return m.group(1), int(m.group(2)), int(m.group(3))
        record = parse(page_name)
        range_start = parse(start_code)
        range_end = parse(end_code)
        if not record or not range_start or not range_end:
            return False
        if record[0] != range_start[0]:
            return False
        if record[1] < range_start[1] or record[1] > range_end[1]:
            return False
        if record[1] == range_start[1] and record[2] < range_start[2]:
            return False
        if record[1] == range_end[1] and record[2] > range_end[2]:
            return False
        return True

    df = pd.read_excel(excel_path)
    result = {}
    db = hlp.get_db('tw-work')
    for _, row in df.iterrows():
        fz_id = row['FZ经编码']
        js_id = row['JS经编码']
        start_page = row['FZ起始页']
        end_page = row['FZ终止页']
        # Get all pages for this sutra
        db_pages = list(db.page.find({'name': {'$regex': f'^{fz_id}_'}}, {'name': 1}))
        page_names = [p['name'] for p in db_pages if is_match(p['name'], start_page, end_page)]
        result[fz_id] = {
            'js_id': js_id,
            'pages': page_names
        }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Saved mapping with pages to {json_path}")


def normalize_js_code(s):
    """
    Normalize JS page codes to the form `JS_<n1><mid>_<n2><tail>`.
    Examples:
      - "JS0001_001"      -> "JS_1_1"
      - "js0001a_001"     -> "JS_1a_1"
      - "JS_0001_005X2"   -> "JS_1_5X2"
      - "JS0001a-001z3"   -> "JS_1a_1z3"
    Rules:
      - Strips leading zeros from numeric groups.
      - Preserves an optional letter immediately after the first number (normalized to lowercase).
      - Preserves any trailing alphanumeric suffix after the second number (kept as-is).
      - If the string doesn't match expected JS pattern, returns the original string.
    """
    if not s:
        return s
    s = s.strip()
    # Match:
    # 1: 'JS' (case-insensitive), optional underscore
    # 2: first number (with possible leading zeros)
    # 3: optional letters immediately after first number (e.g. 'a')
    # separator: underscore or hyphen or nothing
    # 4: second number (with possible leading zeros)
    # 5: optional trailing suffix (letters/digits, e.g. 'x2' or 'z3' or 'a')
    m = re.match(r'^(JS)_?0*(\d+)([A-Za-z]*)[_-]?0*(\d+)([A-Za-z0-9]*)$', s, re.IGNORECASE)
    if not m:
        return s
    prefix = m.group(1).upper()
    main1 = str(int(m.group(2)))
    mid = (m.group(3) or '').lower()
    main2 = str(int(m.group(4)))
    tail = m.group(5) or ''
    # If tail contains letters, keep their case from original substring:
    # we reconstructed tail from the regex match (same case as input).
    return f"{prefix}_{main1}{mid}_{main2}{tail}"


def batch_fzpage_match_jssutra(jsonpath="fz_js"):
    db = hlp.get_db('tw-work')

    import json

    with open(f'./data/{jsonpath}.json', 'r', encoding='utf-8') as f:
        fz_js = json.load(f)

    for fz_code, info in fz_js.items():
        js_id = info.get('js_id')
        pages = info.get('pages', [])

        if not js_id: # or js_id == 'JS_1':
            continue  # Skip if js_id is null 

        if not pages:
            continue  # No pages to process

        fz_pages = list(db.page.find(
            {
                'name': {'$in': pages},
                'match.status': {'$ne': 5},
                'flag': 717,
                'flag2': 1217
            },
            {'name': 1, 'base_txt': 1, 'match': 1, 'match_logs': 1}
        ))

        if not fz_pages:
            print(f"No FZ pages found for {fz_code} needing update, skipping.")
            continue

        # 3. Get all FZ pages
        print(f"Processing all FZ pages for {fz_code}... ({len(fz_pages)} pages)")

        # 1. Get all unique reel_codes for that js_id
        reel_codes = db.page.distinct('reel_code', {'sutra_uids': js_id})
        reel_codes_sorted = sorted(reel_codes, key=custom_sort_key)

        # 2. Concatenate all reel texts
        big_txt = ''
        for reel_code in reel_codes_sorted:
            reel_code = normalize_js_code(reel_code)
            hit = find_reel_txt(reel_code)
            if not hit:
                print(f"No JS reel found for {reel_code}, skipping.")
                continue
            reel_txt = hit['_source'].get('txt', '')
            big_txt += reel_txt

        for page in fz_pages:
            pn = page['name']
            status_db = None
            if page.get('match') and isinstance(page['match'], dict):
                status_db = page['match'].get('status')
            if status_db == 5:
                continue

            print(f"Processing {pn} ...")
            base_txt = page.get('base_txt', '')
            if not base_txt or len(base_txt) < 10:
                continue

            ret = find_best_match(base_txt, big_txt)
            match_txt = ret[0] if ret else ''
            status_now = get_match_info(base_txt, match_txt).get('status') if match_txt else 0

            if status_now == 5 and status_now > status_db:
                print(f"Improved: {pn} from {status_db} to {status_now}")
                now = datetime.now()
                logs = page.get('match_logs') or []
                match_info = get_match_info(base_txt, match_txt)
                match_info.update({
                    'index_id': 'jsz_ik_sutra_best_match',
                    'created_by': 'operator',
                    'create_time': now
                })
                logs.append(match_info)
                match = get_best_match(logs)
                db.page.update_one(
                    {'name': pn},
                    {'$set': {'match': match, 'match_logs': logs, 'flag3': 151225001}}
                )


def update_fz_js_with_cbeta(excel_path="./data/经编码关系表.xlsx", fz_js_path="./data/fz_js.json", output_path="./data/fz_cbeta.json"):
    import pandas as pd
    import json
    # 1. Load Excel mapping
    df = pd.read_excel(excel_path)
    # Assume columns: 'FZ经编码', 'CBETA编码'
    fz_to_cbeta = dict(zip(df['FZ经编码'], df['CBETA经编码']))

    # 2. Load fz_js.json
    with open(fz_js_path, 'r', encoding='utf-8') as f:
        fz_js = json.load(f)

    # 3. Update js_id to cbeta_code
    for fz_code, info in fz_js.items():
        cbeta_code = fz_to_cbeta.get(fz_code)
        if cbeta_code:
            info['cbeta_id'] = cbeta_code
        # Optionally remove js_id if present
        if 'js_id' in info:
            del info['js_id']

    # 4. Save as fz_cbeta.json
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(fz_js, f, ensure_ascii=False, indent=2)
    print(f"Saved updated mapping to {output_path}")


def batch_fzpage_match_cbetasutra():
    import os
    import json

    # Load fz_cbeta.json
    with open('./data/fz_cbeta.json', 'r', encoding='utf-8') as f:
        fz_cbeta = json.load(f)

    cbeta_root = './data/cbeta-text-20250515'
    db = hlp.get_db('tw-work')

    for fz_id, info in fz_cbeta.items():
        cbeta_id = info.get('cbeta_id')
        pages = info.get('pages', [])
        fz_pages = list(db.page.find(
            {
                'name': {'$in': pages},
                'match.status': {'$ne': 5},
                'flag': 717,
                'flag2': 1217
            },
            {'name': 1, 'base_txt': 1, 'match': 1, 'match_logs': 1}
        ))
        if not cbeta_id or cbeta_id == 'null' or not pages or not fz_pages:
            continue  # Skip if cbeta_id is null or pages is empty

        cbeta_folder = os.path.join(cbeta_root, cbeta_id.strip())
        if not os.path.isdir(cbeta_folder):
            print(f"CBETA folder not found: {cbeta_folder}")
            continue

        # Merge all txt files in cbeta_folder
        cbeta_files = [f for f in os.listdir(cbeta_folder) if re.search(r'_(\d+)\.txt$', f)]
        cbeta_files_sorted = sorted(cbeta_files, key=lambda x: int(re.search(r'_(\d+)\.txt$', x).group(1)))
        big_txt = ''
        for fname in cbeta_files_sorted:
            with open(os.path.join(cbeta_folder, fname), 'r', encoding='utf-8') as ftxt:
                big_txt += ''.join([trim_cbeta_whitespace(line) for line in ftxt if not line.startswith('#')])

        print(f"Processing all FZ pages for {fz_id}... ({len(fz_pages)} pages)")

        for page in fz_pages:
            pn = page['name']
            status_db = None
            if page.get('match') and isinstance(page['match'], dict):
                status_db = page['match'].get('status')
            if status_db == 5:
                continue

            print(f"Processing {pn} ...")
            base_txt = page.get('base_txt', '')
            if not base_txt or len(base_txt) < 10:
                continue

            ret = find_best_match(base_txt, big_txt)
            match_txt = ret[0] if ret else ''
            status_now = get_match_info(base_txt, match_txt).get('status') if match_txt else 0

            if status_now == 5 and status_now > status_db:
                print(f"Improved: {pn} from {status_db} to {status_now}")
                now = datetime.now()
                logs = page.get('match_logs') or []
                match_info = get_match_info(base_txt, match_txt)
                match_info.update({
                    'index_id': 'cbeta_txt_best_match',
                    'created_by': 'operator',
                    'create_time': now
                })
                logs.append(match_info)
                match = get_best_match(logs)
                db.page.update_one(
                    {'name': pn},
                    {'$set': {'match': match, 'match_logs': logs, 'flag3': 151225002}}
                )


def count_match_backupdata():
    dir = '../../../../../nas/data/tmp/fz_ocr完成的备份json_bak_20251207/FZ'
    import os
    import json
    count_status = {}
    count = 0
    for sutra in os.listdir(dir):
        for dpath in os.listdir(os.path.join(dir, sutra)):
            for fpath in os.listdir(os.path.join(dir, sutra, dpath)):
                if not fpath.endswith('.json'):
                    continue
                with open(os.path.join(dir, sutra, dpath, fpath), 'r', encoding='utf-8') as f:
                    print(os.path.join(dir, sutra, dpath, fpath))
                    data = json.load(f)
                    name = data.get('name')
                    # print(dpath) # 12
                    # print(fpath) # FZ_1_12_15.json
                    # print(name) # FZ_1_12_12
                        # print(data)
                        # status = data.get('match').get('status')
                        # count_status[status] = count_status.get(status, 0) + 1
                    
    print('match.status counts:')
    for k in sorted(count_status.keys(), key=lambda x: (x is None, x)):
        print(f'  status={k}: {count_status[k]}')
    return count_status


def count_match_status_backup():
    import json
    db = hlp.get_db('tw-work')
    cond = {'flag': 717, 'flag2': 1208 }
    page_names = db.page.distinct('name', cond)

    status_count = {}
    total = 0

    for i, page_name in enumerate(page_names):
        parts = page_name.split('_')
        path = f'../../../../../nas/data/tmp/fz_ocr完成的备份json_bak_20251207/FZ/{parts[1]}/{parts[2]}/{page_name}.json'
        json_data = json.load(open(path, 'r', encoding='utf-8'))
        status = hlp.prop(json_data, 'match.status')
        status_count[status] = status_count.get(status, 0) + 1
        total += 1

    print(f'Total pages: {total}')
    print('match.status counts:')
    # Sort keys: None last, numbers first
    for k in sorted(status_count.keys(), key=lambda x: (x is None, x)):
        print(f'  status={k}: {status_count[k]}')


def phz_centercol(logfile='phz_centercol_log.txt'):
    db = hlp.get_db('tw-work')
    cond = {'name': {'$regex': '^PH'}}
    pages = db.page.find(cond, {'name': 1, 'columns': 1, 'chars': 1})
    chinese_num_set = set('〇一二三四五六七八九十百千萬零壹貳參肆伍陸柒捌玖拾')

    def col_score(col, min_char_count, chars, gap_threshold):
        ocr_txt = col.get('ocr_txt', '')
        char_count = len(ocr_txt)
        last_char = ocr_txt[-1] if ocr_txt else ''
        fewer_chars = int((min_char_count is not None) and (char_count == min_char_count) and (char_count > 1))
        last_char_is_chinese_num = int(last_char in chinese_num_set)
        not_only_chinese_num = int(not (all(char in chinese_num_set for char in ocr_txt) and ocr_txt))
        has_juan_or_pin = int(('卷' in ocr_txt) or ('品' in ocr_txt) or ('篇' in ocr_txt))
        # Large gap flag
        col_chars = [c for c in chars if c.get('column_no') == col.get('column_no')]
        gaps = [abs(col_chars[i+1]['y'] - col_chars[i]['y']) for i in range(len(col_chars)-1)] if len(col_chars) > 1 else []
        avg_gap = sum(gaps)/len(gaps) if gaps else 0
        large_gap = int(avg_gap > gap_threshold and avg_gap > 0)
        return fewer_chars + last_char_is_chinese_num + not_only_chinese_num + has_juan_or_pin + large_gap * 4

    with open(logfile, 'a', encoding='utf-8') as logf:
        for page in pages:
            name = page['name']
            columns = page.get('columns', [])
            chars = page.get('chars', [])
            if not columns:
                continue

            char_counts = [len(c.get('ocr_txt', '')) for c in columns if c.get('ocr_txt')]
            min_char_count = None
            if char_counts:
                sorted_counts = sorted(set(char_counts))
                if sorted_counts[0] == 1 and len(sorted_counts) > 1:
                    min_char_count = sorted_counts[1]
                else:
                    min_char_count = sorted_counts[0]

            # Compute gap threshold (median of all column avg gaps)
            avg_gaps = []
            for col in columns:
                col_chars = [c for c in chars if c.get('column_no') == col.get('column_no')]
                gaps = [abs(col_chars[i+1]['y'] - col_chars[i]['y']) for i in range(len(col_chars)-1)] if len(col_chars) > 1 else []
                avg_gap = sum(gaps)/len(gaps) if gaps else 0
                if avg_gap > 0:
                    avg_gaps.append(avg_gap)
            gap_threshold = 0
            if avg_gaps:
                avg_gaps_sorted = sorted(avg_gaps)
                mid = len(avg_gaps_sorted)//2
                median_gap = avg_gaps_sorted[mid] if len(avg_gaps_sorted)%2==1 else (avg_gaps_sorted[mid-1]+avg_gaps_sorted[mid])/2
                gap_threshold = median_gap * 1.5

            # Left bun inward
            left_idx = 0
            while left_idx + 1 < len(columns):
                left_score = col_score(columns[left_idx], min_char_count, chars, gap_threshold)
                next_score = col_score(columns[left_idx + 1], min_char_count, chars, gap_threshold)
                if next_score > left_score:
                    left_idx += 1
                else:
                    break

            # Right bun inward
            right_idx = len(columns) - 1
            while right_idx - 1 >= 0:
                right_score = col_score(columns[right_idx], min_char_count, chars, gap_threshold)
                prev_score = col_score(columns[right_idx - 1], min_char_count, chars, gap_threshold)
                if prev_score > right_score:
                    right_idx -= 1
                else:
                    break

            left_score = col_score(columns[left_idx], min_char_count, chars, gap_threshold)
            right_score = col_score(columns[right_idx], min_char_count, chars, gap_threshold)
            if left_score >= right_score:
                best_idx = left_idx
            else:
                best_idx = right_idx

            col = columns[best_idx]
            col['is_center'] = True
            log_str = f"Page: {name}, Center column idx: {best_idx}, col_no: {col.get('column_no')}, chars: {col.get('ocr_txt', '')}"
            print(log_str)
            logf.write(log_str + '\n')

            # db.page.update_one({'name': name}, {'$set': {'columns': columns}})


def phz_centercol_update():
    import pandas as pd
    df = pd.read_excel('data/PH版心统计_602.xlsx')
    db_work = hlp.get_db('tw-prod-readonly')

    filtered = df[df.iloc[:, 6] == 'n']
    page_names = filtered.iloc[:, 0].tolist()
    count = 0
    for name in page_names:
        count += 1
        # cond = {'name': name}
        # page = db_work.page.find_one(cond, {'columns': 1})
        # cols = page['columns']
        # non_deleted_idxs = [i for i, c in enumerate(cols) if not c.get('deleted')]

        # # Determine last numeric group from page name, take its last digit
        # last_part = name.split('_')[-1]
        # nums = re.findall(r'(\d+)', last_part)
        # last_num = int(nums[-1]) if nums else 0
        # # choose leftmost if odd, rightmost if even
        # center_idx = (len(cols)-1) if (last_num % 2 == 1) else 0

        # if last_num % 2 == 1:
        #     target_idx = non_deleted_idxs[-1]
        # else:
        #     target_idx = non_deleted_idxs[0]

        # cols[target_idx]['is_center'] = True

        # result = db_work.page.update_one(cond, {'$set': {'columns': cols}})
        # print(result.modified_count)
    print(count)

        

def get_center_txt():
    from natsort import natsorted
    import pandas as pd

    """统计版心列数据"""
    db_work = hlp.get_db('tw-prod-readonly')
    # page_names = db_work.page.distinct('name', {'source': 'PH'})
    # page_names = natsorted(page_names)

    df = pd.read_excel('data/PH版心统计_602.xlsx')
    filtered = df[df.iloc[:, 6] == 'n']
    page_names = filtered.iloc[:, 0].tolist()
    page_names = natsorted(page_names)

    split_lst = [page_names[i:i + 10] for i in range(0, len(page_names), 10)]
    for i, lst in enumerate(split_lst):
        print(i, len(split_lst))
        pages = list(db_work.page.find({'name': {'$in': lst}}, {'columns': 1, 'chars': 1, 'name': 1}))
        pages = natsorted(pages, key=lambda x: x['name'])
        for page in pages:
            center_cols = [col['column_id'] for col in page.get('columns') if
                           not col.get('deleted') and col.get('is_center')]
            center_ids = [str(col['cid']) for col in page.get('columns') if
                          not col.get('deleted') and col.get('is_center')]
            txts = []
            for column_id in center_cols:
                center_col_txt = [
                    char.get('txt') or char.get('ocr_txt', '') for char in page.get('chars', [])
                    if not char.get('deleted') and char.get('char_id').rsplit('c', 1)[0] == column_id
                ]
                center_col_txt = ''.join(center_col_txt)
                txts.append(center_col_txt)
            with open('PH版心统计.txt', 'a', encoding='utf-8') as f:
                url = 'https://work.tripitakas.net/page/box/%s' % page['name']
                f.write('%s\t%s\t%s\t%s\t%s\t%s\n' % (
                    page['name'], ','.join(center_cols), ','.join(center_ids), ','.join(txts), len(center_cols), url))


def FZ_yinshi_export(out_path='./data/fz_yinshi.txt', db=None):
    from reel import get_yinshi_txt
    if db is None:
        db = hlp.get_db('tw-prod-readonly')

    cond = {'source_type': 'FZZ'}
    sutras = db.sutra_source.distinct('sutra_uid', cond)
    sutras = sorted(sutras)

    with open(out_path, 'w', encoding='utf-8') as outf:
        for s in sutras:
            reel_codes = db.reel.distinct('reel_code', {'sutra_code': s})
            reel_codes = sorted(reel_codes, key=custom_sort_key)
            for r in reel_codes:
                txt = get_yinshi_txt(r, db)
                if txt:
                    outf.write(f"[{r}]\n")
                    outf.write(txt)
                    outf.write("\n")
                outf.flush()
            

def batch_match_fzyinshi():
    db = hlp.get_db('tw-prod-readonly')
    cond = {'reel_code': 'FZ0328_001z1'}
    pages = db.page.distinct('name', cond)
    with open('./data/sx_yinshi0.txt', 'r', encoding='utf-8') as f:
        sx_yinshi_txt = f.read()
    for pn in pages:
        page = db.page.find_one({'name': pn})
        status_db = None
        if page.get('match') and isinstance(page['match'], dict):
            status_db = page['match'].get('status')
        if status_db == 5:
            continue

        print(f"Processing {pn} ...")
        base_txt = page.get('base_txt', '')
        if not base_txt or len(base_txt) < 10:
            continue

        ret = find_best_match(base_txt, sx_yinshi_txt)
        match_txt = ret[0] if ret else ''
        match_info = get_match_info(base_txt, match_txt)
        status = match_info.get('status')

        if status > status_db:
            now = datetime.now()
            logs = page.get('match_logs') or []
            match_info.update({
                'index_id': 'sx_yinshi_best_match',
                'created_by': 'operator',
                'create_time': now
            })
            logs.append(match_info)
            match = get_best_match(logs)
            db.page.update_one(
                {'name': pn},
                {'$set': {'match': match, 'match_logs': logs, 'flag3': 20260206002}}
            )

def batch_match_sxyinshi():
    db = hlp.get_db('tw-test-readonly')
    print(db)
    vdict = get_code2txt('nor_txt')

    with open('./data/fz_yinshi.txt', 'r', encoding='utf-8') as f:
        ref_txt = f.read()

    cond = {'source_type': 'SXZ'}
    sutra_uids = db.sutra_source.distinct('sutra_uid', cond)
    sutra_uids = sorted(sutra_uids)

    for s_uid in sutra_uids:
        print(f"Processing Sutra: {s_uid}")
        reels = list(db.reel.find({'sutra_code': s_uid}))
        for reel in reels:
            # Get 'E' format mappings from the reel
            page_col_formats = {}
            page_char_formats = {}
            for fmt in hlp.prop(reel, 'format', []):
                p_name = fmt.get('name')
                col_f = [c[1] for c in fmt.get('columns', []) if c[0] == 'E']
                char_f = [(ch[2], ch[3]) for ch in fmt.get('chars', []) if ch[0] == 'E']
                if col_f: page_col_formats[p_name] = set(col_f)
                if char_f: page_char_formats[p_name] = char_f

            # Find all pages in this reel
            p_cond = get_page_select_cond(reel)
            pages = list(db.page.find(p_cond).sort([('name', 1)]))
            
            for page in pages:
                pn = page['name']
                page_cols = page.get('columns', [])
                
                # 1. Identify which columns/chars to extract based on 'E' format
                target_col_ids = set()
                if pn in page_col_formats:
                    fmt_cids = page_col_formats[pn]
                    target_col_ids = {c['column_id'] for c in page_cols if c.get('cid') in fmt_cids and c.get('column_id')}
                
                target_char_ranges = page_char_formats.get(pn, [])

                # 2. Extract the text (Mirroring get_yinshi_txt logic)
                col_dict = {}
                for char in page.get('chars', []):
                    if char.get('deleted') or char.get('is_center'):
                        continue
                    
                    c_id = char.get('char_id')
                    if not c_id: continue
                    
                    cid = char.get('cid')
                    col_id = c_id.rsplit('c', 1)[0]
                    
                    # Check if character is part of an 'E' format group
                    in_fmt = (col_id in target_col_ids)
                    if not in_fmt:
                        for start, end in target_char_ranges:
                            if start <= cid <= end:
                                in_fmt = True
                                break
                    
                    if in_fmt:
                        txt = char.get('txt', '■')
                        txt = vdict.get(txt, txt) # Normalize
                        col_dict.setdefault(col_id, []).append(txt)

                # Combine extracted lines for the page
                yinshi_base_txt = '\n'.join([''.join(col_dict[cid]) for cid in sorted(col_dict.keys(), key=col_sort_key)])

                if not yinshi_base_txt.strip():
                    continue

                db.page.update_one({'name': pn}, {'$set': {'flag1': 1204261841}})

                base_txt = page.get('base_txt', '')
                ret = find_best_match(yinshi_base_txt, ref_txt)
                match_txt = ret[0] if ret else ''
                match_info = get_match_info(base_txt, match_txt)

                if match_info.get('status', 0) > 0:
                    now = datetime.now()
                    match_log = {
                        'status': match_info['status'],
                        'match_txt': match_txt,
                        'index_id': 'fz_yinshi_match',
                        'create_time': now,
                        'r_similar2base': match_info.get('r_similar2base', 0),
                        'r_hit2base': match_info.get('r_hit2base', 0),
                        'r_similar2hit': match_info.get('r_similar2hit', 0),
                    }
                    
                    logs = page.get('match_logs') or []
                    logs = [l for l in logs if l.get('index_id') != 'fz_yinshi_match']
                    logs.append(match_log)
                    match = get_best_match(logs)

                    db.page.update_one(
                        {'name': pn},
                        {'$set': {'match': match, 'match_logs': logs}}
                    )


def batch_apply_txt2missingchars(source='SX', index_id='fz_yinshi_match'):
    """
    Selective batch update for missing cmp_txt values
    using a specific match index (e.g. Yinshi).
    """
    hlp.set_logging('batch_apply_txt2missingchars')
    db = hlp.get_db('tw-test-readonly')  # Ensure we use a write-enabled DB handle

    # Filter for the source (e.g., 'SX') and ensure base_txt exists
    # cond = {'source': source, 'base_txt': {'$exists': True}}
    cond = {'flag1': 1204261841}
    pages = list(db.page.find(cond, {'name': 1, 'base_txt': 1, 'chars': 1, 'columns': 1, 'match_logs': 1}))

    total = len(pages)
    for i, page in enumerate(pages):
        logging.info(f'[{i + 1}/{total}] Processing {page["name"]}')

        # Apply the selective fill
        success = apply_txt2missingchars(db, page, index_id=index_id)

        if success:
            db.page.update_one(
                {'_id': page['_id']}, 
                {'$set': {
                    'chars': page['chars'],
                    'flag3': 130426001,
                }}
            )
            logging.info(f'Applied missing chars for {page["name"]}')
        else:
            logging.warning(f'Skipped {page["name"]}: No target log or alignment error')

    
def import_full_sutra_data(sutra_source_type='SXZ'):
    db_prod = hlp.get_db('tw-prod-readonly')
    db_test = hlp.get_db('tw-test-readonly')

    # 1. Get Sutras (excluding prod _id)
    sutras = list(db_prod.sutra_source.find({'source_type': sutra_source_type}, {'_id': 0}))

    for sutra in sutras:
        s_uid = sutra['sutra_uid']
        print(f"Syncing: {s_uid}")

        # Update or Insert Sutra (Matches by sutra_uid)
        # db_test.sutra_source.replace_one({'sutra_uid': s_uid}, sutra, upsert=True)

        # 2. Get Reels (excluding prod _id)
        reels = list(db_prod.reel.find({'sutra_code': s_uid}, {'_id': 0}))
        
        for reel in reels:
            # We match reels by sutra_code + reel_no (the 'business key')
            reel_filter = {
                'sutra_code': s_uid, 
                'reel_no': reel.get('reel_no')
            }
            # db_test.reel.replace_one(reel_filter, reel, upsert=True)

            # 3. Get Pages (excluding prod _id)
            p_cond = get_page_select_cond(reel)
            pages = list(db_prod.page.find(p_cond, {'_id': 0}))
            
            for page in pages:
                # We match pages by their unique name/ID within that reel
                # Adjust 'name' to whatever field makes a page unique in your schema
                page_filter = {'name': page.get('name')}
                # db_test.page.replace_one(page_filter, page, upsert=True)
                
            print(f"   Synced Reel {reel.get('reel_no')} ({len(pages)} pages)")

    print("Import Finished.")


import logging

def update_match_status_2_flag():
    """
    Sets flag1 to 1234 for all documents where flag1 is 1204261841 
    and match.status is 2.
    """
    hlp.set_logging('update_match_status_2_flag')
    db = hlp.get_db('tw-test-readonly') 

    filter_cond = {
        'flag1': 1204261841,
        'match.status': 2
    }
    
    # Update: set flag2 to 1204261841002
    update_ops = {'$set': {'flag2': 1204261841002}}

    logging.info("Starting bulk update for flag1 where match status is 2...")

    result = db.page.update_many(filter_cond, update_ops)

    logging.info(f"Update complete.")
    logging.info(f"Documents matched: {result.matched_count}")
    logging.info(f"Documents modified: {result.modified_count}")

def process():
    batch_find_match_txt_jx()


def main(func='', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
