import os
import sys
import csv
import logging
import os.path as path
from glob2 import glob
from datetime import datetime

sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

import helper as hlp
from util.diff import diff
from util.punc import trim_punc, trim_PH_punc
from util.uni2std import normalize
from web.tw.reel import get_page_select_cond


def get_char_txt(ch, field, trim_space=True, empty_mode=1, empty_default='■', long_default='※'):
    """ 获取字数据的文本 """
    t = ch.get(field)
    if t and trim_space:
        t = t.strip()
    if not t:
        if empty_mode == 0:
            t = ''
        elif empty_mode == 1:
            t = empty_default
        elif empty_mode == 2:
            t = ch.get('txt') or ch.get('ocr_txt') or ch.get('ocr_col') or empty_default
    if len(t) > 1 and long_default:  # 超长处理
        t = long_default
    return t


def get_code2txt(db, v_codes=None, trans_type='nor_txt', empty_mode=1):
    """ 获取自造字转换表"""
    cond = {}
    if v_codes:
        cond = {'v_code': {'$in': list(v_codes)}}
    if empty_mode == 0:  # 为空时不查找替代
        vts = list(db.variant.find(cond, {'v_code': 1, trans_type: 1, '_id': 0}))
        return {v['v_code']: v[trans_type] for v in vts if v.get('v_code')}
    elif empty_mode == 1:  # 为空时查找替代
        type2 = 'nor_txt' if trans_type == 'uni_txt' else 'uni_txt'
        vts = list(db.variant.find(cond, {'v_code': 1, 'nor_txt': 1, 'uni_txt': 1, '_id': 0}))
        return {v['v_code']: v.get(trans_type) or v.get(type2) for v in vts if v.get('v_code')}


def get_page_txt(page, field, newline='\n', trim_space=True, empty_mode=1, empty_default='■',
                 long_default='※', code2txt=None, exclude_center=True):
    """ 将原字文本转换为正字文本或通字文本
        trim_space: 是否清空两端的空字符
        empty_mode: 0-保持, 1-替换为empty_default, 2-查找其它字段
        long_default: 为空时不替换，否则替换为给定字符
        code2txt: 自造字转换表
    """

    def _get_char_txt(ch):
        t = get_char_txt(ch, field, trim_space, empty_mode, empty_default, '')
        if len(t) > 1 and t.startswith('v') and code2txt:  # 转换自造字
            t = code2txt.get(t) or t
        if len(t) > 1 and long_default:  # 超长处理
            t = long_default
        return t

    chars = page.get('chars')
    if not chars:
        return ''

    # Exclude chars from center columns if needed
    if exclude_center and page.get('columns'):
        # Build a set of center column_ids
        center_column_ids = {c['column_id'] for c in page['columns'] if not c.get('deleted') and c.get('is_center')}
        # Filter chars whose parent column is a center column
        chars = [c for c in chars if c.get('char_id', '').rsplit('c', 1)[0] not in center_column_ids]

    pre, txt = {}, ''
    for c in chars:
        if c.get('deleted'):
            continue
        # if c.get('added'):
        #     continue
        if pre.get('block_no') and c.get('block_no') and int(pre['block_no']) != int(c['block_no']):
            txt += newline
        elif pre.get('column_no') and c.get('column_no') and int(pre['column_no']) != int(c['column_no']):
            txt += newline
        txt += _get_char_txt(c)
        pre = c
    return txt.rstrip(newline)


def get_raw_txt(page, field):
    """ 获取原始文本，不进行任何处理 """
    return get_page_txt(page, field, '\n', False, 0, '', '')


def get_base_txt(db, page, field='txt', trans_type='nor_txt', newline='\n'):
    """ 获取基础文本，用来查找比对文本，或作为文本匹配的基准"""
    v_codes = {c[field] for c in page.get('chars', []) if (c.get(field) or '').startswith('v')}
    code2txt = get_code2txt(db, v_codes, trans_type, 1)
    return get_page_txt(page, field, newline, True, 2, '■', '※', code2txt)


def get_page_cids(page):
    """ 获取页数据的cid列表"""
    if not page.get('chars') or not page.get('columns'):
        return []
    columnid2cid = {c['column_id']: c['cid'] for c in page['columns'] if c.get('column_id')}
    page_cids, column_cid, char_cids = [], None, []
    pre = {}
    for c in page['chars']:
        if c.get('deleted'):
            continue
        column_cid = pre and columnid2cid.get('b%sc%s' % (pre['block_no'], pre['column_no']))
        if (pre.get('block_no') and c.get('block_no') and int(pre['block_no']) != int(c['block_no'])) or \
                (pre.get('column_no') and c.get('column_no') and int(pre['column_no']) != int(c['column_no'])):
            page_cids.append([column_cid, char_cids])
            char_cids = []
        char_cids.append(c.get('cid'))
        pre = c
    if char_cids:
        column_cid = pre and columnid2cid.get('b%sc%s' % (pre['block_no'], pre['column_no']))
        page_cids.append([column_cid, char_cids])
    return page_cids


def set_uni_txt():
    """导出页数据通字文本"""
    db = hlp.get_db('tw-work')
    cond = {'name': {'$regex': '^JS_'}}
    # cond = {'name': 'JS_100_10'}
    pages = list(db.page.find(cond, {'_id': 0, 'name': 1}))
    code2txt = get_code2txt(db, trans_type='uni_txt', empty_mode=1)
    for i, p in enumerate(pages):
        print('[%s/%s]%s' % (i, len(pages), p['name']))
        page = db.page.find_one({'name': p['name']})
        uni_txt = get_page_txt(page, 'txt', '\n', True, 2, '■', '※', code2txt)
        db.page.update_one({'name': p['name']}, {'$set': {'uni_txt': uni_txt}})


def export_uni_txt():
    """导出页数据通字文本"""
    db = hlp.get_db('tw-work')
    cond = {'name': {'$regex': '^JS_'}}
    # cond = {'name': 'JS_203_866'}
    pages = list(db.page.find(cond, {'_id': 0, 'name': 1}))
    code2txt = get_code2txt(db, trans_type='uni_txt', empty_mode=1)
    for i, p in enumerate(pages):
        print('[%s/%s]%s' % (i, len(pages), p['name']))
        page = db.page.find_one({'name': p['name']})
        uni_txt = get_page_txt(page, 'txt', '\n', True, 2, '■', '※', code2txt)
        root = '/home/smjs/xiandu/jsz-unitxt-250827'
        # root = '/Volumes/v2/00Inbox/jsz-unitxt'
        dst_dir = path.join(root, *p['name'].split('_')[:-1])
        os.makedirs(dst_dir, exist_ok=True)
        with open(path.join(dst_dir, f'{p["name"]}.txt'), 'w') as f:
            f.write(uni_txt)


def export_nor_txt():
    """导出页数据正字文本"""
    db = hlp.get_db('tw-work')
    # cond = {'name': {'$regex': '^JS_'}}
    cond = {'name': 'JS_100_10'}
    pages = list(db.page.find(cond, {'_id': 0, 'name': 1}))
    code2txt = get_code2txt(db, trans_type='nor_txt', empty_mode=1)
    for i, p in enumerate(pages):
        print('[%s/%s]%s' % (i, len(pages), p['name']))
        page = db.page.find_one({'name': p['name']})
        nor_txt = get_page_txt(page, 'txt', '\n', True, 2, '■', '※', code2txt)
        nor_txt = normalize(nor_txt)
        # root = '/home/smjs/xiandu/jsz-nortxt'
        root = '/Volumes/v2/00Inbox/JSZ/jsz-nortxt'
        dst_dir = path.join(root, *p['name'].split('_')[:-1])
        os.makedirs(dst_dir, exist_ok=True)
        with open(path.join(dst_dir, f'{p["name"]}.txt'), 'w') as f:
            f.write(nor_txt)


# def apply_txt2char(page, base_txt, cmp_txt, field='cmp_txt', cut_long=False):
#     """ 将cmp_txt文本的每个字适配至chars的每个字框"""
#     # 清理标点换行等符号
#     base_txt = trim_punc(base_txt, True)
#     cmp_txt = trim_punc(cmp_txt, True)
#     # 检查基础文本，必须一个字框对应一个文字
#     chars = [c for c in page.get('chars') or [] if not c.get('deleted')]
#     if len(base_txt) != len(chars):
#         return False
#     # 文本比对
#     segments = diff(base_txt, cmp_txt, lambda x: True, lambda x: True, normalize=True)
#     for i, seg in enumerate(segments):
#         if i and not seg.get('base'):  # 如果base为空，则将cmp合并至前一个seg
#             segments[i - 1]['cmp'] += seg['cmp']
#     # 进行适配
#     start = 0
#     for seg in segments:
#         if not seg.get('base'):
#             continue
#         len_b, len_c = len(seg['base']), len(seg['cmp'])
#         for i in range(len_b):
#             if i < len_c:
#                 chars[start + i][field] = seg['cmp'][i]
#             else:
#                 chars[start + i][field] = '■'  # 缺省值
#         if len_c > len_b and not cut_long:
#             chars[start + len_b - 1][field] += seg['cmp'][len_b:]
#         start += len_b
#     return True


def apply_txt2char(page, base_txt, cmp_txt, field='cmp_txt', cut_long=False):
    """ 将cmp_txt文本的每个字适配至chars的每个字框"""
    # 清理标点换行等符号
    # base_txt = trim_punc(base_txt, True)
    base_txt = base_txt
    cmp_txt = trim_punc(cmp_txt, True)
    # 检查基础文本，必须一个字框对应一个文字
    cen_column_ids = [c.get('column_id') for c in
                      page.get('columns', []) if
                      c.get('is_center') and not c.get('deleted')]
    chars = [ch for ch in page.get('chars') if not ch.get('deleted') and ch['char_id'].rsplit('c', 1)[0]
             not in cen_column_ids]
    # chars = [c for c in page.get('chars') or [] if not c.get('deleted')]
    if len(base_txt) != len(chars):
        return False
    # 文本比对
    segments = diff(base_txt, cmp_txt, lambda x: True, lambda x: True, normalize=True)
    for seg in segments:
        seg['base'] = seg['base0']
        seg['cmp'] = seg['cmp0']

    for i, seg in enumerate(segments):
        if i and not seg.get('base'):  # 如果base为空，则将cmp合并至前一个seg
            segments[i - 1]['cmp'] += seg['cmp']
    # 进行适配
    start = 0
    for seg in segments:
        if not seg.get('base'):
            continue
        len_b, len_c = len(seg['base']), len(seg['cmp'])
        for i in range(len_b):
            if i < len_c:
                chars[start + i][field] = seg['cmp'][i]
            else:
                chars[start + i][field] = '■'  # 缺省值
        if len_c > len_b and not cut_long:
            chars[start + len_b - 1][field] += seg['cmp'][len_b:]
        start += len_b
    return True


def apply_PH_txt2char(page, base_txt, cmp_txt, field='cmp_txt', cut_long=False):
    """ 将cmp_txt文本的每个字适配至chars的每个字框"""
    # 清理标点换行等符号
    # base_txt = trim_punc(base_txt, True)
    base_txt = base_txt
    cmp_txt = trim_PH_punc(cmp_txt, True)
    # 检查基础文本，必须一个字框对应一个文字
    cen_column_ids = [c.get('column_id') for c in
                      page.get('columns', []) if
                      c.get('is_center') and not c.get('deleted')]
    chars = [ch for ch in page.get('chars') if not ch.get('deleted') and not ch.get('added') and ch['char_id'].rsplit('c', 1)[0]
             not in cen_column_ids]
    # chars = [c for c in page.get('chars') or [] if not c.get('deleted')]
    
    if len(base_txt) != len(chars):
        return False
    # 文本比对
    segments = diff(base_txt, cmp_txt, lambda x: True, lambda x: True, normalize=True)
    for seg in segments:
        seg['base'] = seg['base0']
        seg['cmp'] = seg['cmp0']

    for i, seg in enumerate(segments):
        if i and not seg.get('base'):  # 如果base为空，则将cmp合并至前一个seg
            segments[i - 1]['cmp'] += seg['cmp']
    # 进行适配
    start = 0
    for seg in segments:
        if not seg.get('base'):
            continue
        len_b, len_c = len(seg['base']), len(seg['cmp'])
        for i in range(len_b):
            # Check the current value safely
            current_char_data = chars[start + i]
            if current_char_data.get(field, '') in '（ ）〔〕「」『』':
                if i < len_c:
                    current_char_data[field] = seg['cmp'][i]
                else:
                    # Optional: handle cases where base has a bracket but match text is shorter
                    current_char_data[field] = '■' 
        start += len_b
    return True


def apply_txt2missingchars(db, page, index_id='fz_yinshi_match', field='cmp_txt'):
    """ 
    Finds a specific match_log and fills missing character fields 
    without overwriting existing valid text.
    """
    # 1. Find the target log
    target_log = next((log for log in page.get('match_logs', []) 
                      if log.get('index_id') == index_id), None)
    
    if not target_log or not target_log.get('match_txt'):
        return False

    base_txt = page.get('base_txt', '')
    match_txt = target_log['match_txt']
    
    # 2. Perform alignment (reusing util.diff)
    from util.diff import diff
    from util.punc import trim_punc
    
    match_txt_clean = trim_punc(match_txt, True)
    # Get active characters (excluding center columns like '張□' and '十五')
    cen_column_ids = [c.get('column_id') for c in page.get('columns', []) 
                      if c.get('is_center') and not c.get('deleted')]
    chars = [ch for ch in page.get('chars') if not ch.get('deleted') 
             and ch['char_id'].rsplit('c', 1)[0] not in cen_column_ids]

    if len(base_txt.replace('\n', '')) != len(chars):
        # Fallback: if base_txt has newlines, ensure we align against the clean string
        clean_base = base_txt.replace('\n', '')
    else:
        clean_base = base_txt

    segments = diff(clean_base, match_txt_clean, lambda x: True, lambda x: True, normalize=True)
    
    # 3. Selective Update
    start = 0
    for seg in segments:
        if not seg.get('base0'): continue
        
        len_b = len(seg['base0'])
        len_c = len(seg['cmp0'])
        
        for i in range(len_b):
            target_char = chars[start + i]
            current_val = target_char.get(field)
            
            # CONDITION: Only fill if missing or placeholder
            if not current_val or current_val == '■':
                if i < len_c:
                    target_char[field] = seg['cmp0'][i]
                else:
                    target_char[field] = '■'
            
        start += len_b
    return True


def jxz_apply_txt2char(db, page_name, page=None, code2txt=None):
    """ 将径山藏的原字文本适配至嘉兴藏的每个字框 """

    def get_txt(code):
        if code.startswith('v') and len(code) > 1:
            code = code2txt.get(code) or code
            if len(code) > 1:
                code = code[0]  # 正字有可能是 fw 或 fh等
            return code
        else:
            return code

    # 获取嘉兴藏不含版心列的字框
    page = page or db.page.find_one({'name': page_name}, {'chars': 1, 'columns': 1, 'match_logs': 1})
    cencol_ids = [c['column_id'] for c in page.get('columns', []) if
                  not c.get('deleted') and c.get('is_center')]
    jxz_chars = [c for c in page.get('chars', []) if not c.get('deleted')
                 and c.get('char_id').rsplit('c', 1)[0] not in cencol_ids]
    # 获取径山藏的原字文本
    jsz_txts = []
    for log in page['match_logs']:
        jsz_name, block_key = log['page_ids'][0].rsplit('_', 1)
        jsz_page = db.page.find_one({'name': jsz_name}, {'chars': 1, 'columns': 1, 'width': 1})
        # cencols = [c for c in jsz_page.get('columns', []) if not c.get('deleted') and c.get('is_center')]
        # if len(cencols) > 1:  # 不止一个版心列时直接退出
        #     logging.error(f'{jsz_name} has more than one center column.')
        #     return
        # cencol = cencols[0]

        block_txts_a, block_txts_b = split_block_txt(jsz_page)
        if block_key == 'a':
            jsz_txts.extend(block_txts_a)
            # jsz_txts.extend([c['txt'] for c in jsz_page['chars'] if not c.get('deleted')
            #                  and c['block_no'] <= cencol['block_no'] and c['column_no'] < cencol['column_no']])
        elif block_key == 'b':
            jsz_txts.extend(block_txts_b)
            # jsz_txts.extend([c['txt'] for c in jsz_page['chars'] if not c.get('deleted')
            #                  and c['block_no'] >= cencol['block_no'] and c['column_no'] > cencol['column_no']])

    # 获取原字转正字表
    if not code2txt:
        v_codes = {c['txt'] for c in jxz_chars if (c.get('txt') or '').startswith('v')}
        v_codes.update({t for t in jsz_txts if t.startswith('v')})
        code2txt = get_code2txt(db, v_codes=v_codes, empty_mode=0)
    base_txt = ''.join([get_txt(c.get('txt')) for c in jxz_chars])
    cmp_txt = ''.join([get_txt(t) for t in jsz_txts])
    # 文本比对
    segments = diff(base_txt, cmp_txt, lambda x: True, lambda x: True, normalize=True)
    # 进行适配
    base_idx, cmp_idx = 0, 0
    for seg in segments:
        if not seg.get('base'):
            continue
        len_b, len_c = len(seg['base']), len(seg['cmp'])
        for i in range(len_b):
            if i < len_c:
                print(base_idx + i, jxz_chars[base_idx + i]['txt'], jsz_txts[cmp_idx + i])
                jxz_chars[base_idx + i]['txt2'] = jsz_txts[cmp_idx + i]
            else:
                print(base_idx + i, jxz_chars[base_idx + i]['txt'], '■')
                jxz_chars[base_idx + i]['txt2'] = '■'  # 缺省值
        base_idx += len_b
        cmp_idx += len_c
    return page


def batch_jxz_apply_txt2char():
    """ 批量将径山藏的原字文本适配至嘉兴藏的每个字框"""
    hlp.set_logging('batch_jxz_apply_txt2char')

    db = hlp.get_db('tw-work')
    # 获取异体字转换正字表
    code2txt = get_code2txt(db, trans_type='nor_txt', empty_mode=0)
    # 批量进行适配
    cond = {'name': 'JX_1_1_10'}
    page_names = db.page.distinct('name', cond)
    for i, name in enumerate(page_names):
        logging.info('[%s/%s]%s' % (i, len(page_names), name))
        page = jxz_apply_txt2char(db, name, code2txt=code2txt)
        db.page.update_one({'name': name}, {'$set': {'chars': page['chars']}})


def batch_update_cencol_txt_fields():
    """ 更新页数据版心列文本字段的uni_txt"""
    hlp.set_logging('batch_update_cencol_txt_fields')

    db = hlp.get_db('')
    # 'JS2/JS3/JS50'
    cond = {'source': 'JS2'}
    cond = {'name': 'JS_202_154'}
    pages = list(db.page.find(cond, {'_id': 0, 'name': 1}))
    cnt = 0
    errors = []
    missed = []
    total = len(pages)
    code2txt = get_code2txt(db)
    for i, p in enumerate(pages):
        logging.info('[%s/%s]%s' % (i, total, p['name']))
        page = db.page.find_one({'name': p['name']}, {'_id': 0, 'name': 1, 'columns': 1, 'chars': 1})
        center_columns = [c for c in page['columns'] if not c.get('deleted') and c.get('is_center')]
        if not center_columns:
            continue
        if len(center_columns) > 1:
            errors.append(page['name'])
            logging.info('%s, %s center columns' % (page['name'], len(center_columns)))

        center_column_ids = [c['column_id'] for c in center_columns]
        _chars = [c for c in page.get('chars', []) if not c.get('deleted') and
                  c['char_id'].rsplit('c', 1)[0] in center_column_ids]
        if not _chars:
            continue

        changed = False
        for ch in _chars:
            fields = ['ocr_txt', 'ocr_col', 'cmp_txt', 'cmb_txt', 'txt']
            for f in fields:
                t = ch.get(f) or ''
                if t.startswith('v') and len(t) > 1:
                    t2 = code2txt.get(t)
                    if not t2:
                        missed.append(t)
                    else:
                        ch[f] = t2
                        changed = True

            alts = []
            alternatives = ch.get('alternatives') or ''
            for t in alternatives.split(','):
                if t.startswith('v') and len(t) > 1:
                    t2 = code2txt.get(t)
                    if not t2:
                        missed.append(t)
                        alts.append(t)
                    elif t2 not in alts:
                        alts.append(t2)
                else:
                    alts.append(t)
            if ','.join(alts) != alternatives:
                ch['alternatives'] = ','.join(alts)
                changed = True

        if changed:
            db.page.update_one({'name': page['name']}, {'$set': {'chars': page['chars']}})
            cnt += 1
    logging.info('%s updated' % cnt)
    logging.info('missed codes: %s' % list(set(missed)))
    logging.info('error names: %s' % list(set(errors)))


def batch_check_cencol_equal():
    hlp.set_logging('batch_check_cencol_equal')
    db = hlp.get_db('')

    items = [
        ['JS1', 'char1', 'JS1-L'],
        ['JS2', 'char2', 'JS2-L'],
        ['JS3', 'char3', 'JS3-L'],
        ['JS4', 'char4', 'JS4-L'],
        ['JS5', 'char5', 'JS5-L'],
        ['JS6', 'char6', 'JS6-L'],
        ['JS50', 'char6', 'JS60-L'],
    ]
    errors = []
    for it in items:
        page_source, char_coll, char_source = it
        cond = {'source': page_source}
        pages = list(db.page.find(cond, {'_id': 0, 'name': 1}))
        for i, p in enumerate(pages):
            logging.info('[%s/%s]%s' % (i, len(pages), p['name']))
            page = db.page.find_one({'name': p['name']}, {'_id': 0, 'name': 1, 'columns': 1, 'chars': 1})
            center_columns = [c for c in page['columns'] if not c.get('deleted') and c.get('is_center')]
            if not center_columns:
                continue
            center_column_ids = [c['column_id'] for c in center_columns]
            p_chars = [c for c in page.get('chars', []) if not c.get('deleted') and
                       c['char_id'].rsplit('c', 1)[0] in center_column_ids]
            if not p_chars:
                continue

            p_ch2alts = {str(c.get('cid') or ''): c.get('alternatives') for c in page['chars']}
            c_chars = list(db[char_coll].find({'source': char_source, 'page_name': p['name']},
                                              {'_id': 0, 'name': 1, 'alternatives': 1}))
            for ch in c_chars:
                cid = ch['name'].rsplit('_', 1)[1]
                p_alts = p_ch2alts.get(cid)
                if p_alts != ch.get('alternatives'):
                    logging.info('[%s]%s != %s' % (ch['name'], p_alts, ch['alternatives']))
                    errors.append([ch['name'], p_alts, ch['alternatives']])
    fn = path.join(hlp.BASE_DIR, 'txt/log', 'cencol_unequal.csv')
    with open(fn, 'w', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(errors)


def check_cencols():
    """ 计算版心列数量>1的情况"""
    names = []
    db = hlp.get_db('')
    cond = {'name': {'$regex': 'JS_'}}
    pages = list(db.page.find(cond, {'_id': 0, 'name': 1}))
    for i, p in enumerate(pages):
        print('[%s/%s]%s' % (i, len(pages), p['name']))
        page = db.page.find_one({'name': p['name']}, {'columns': 1})
        columns = page.get('columns') or []
        cencols = [c for c in columns if not c.get('deleted') and c.get('is_center')]
        if len(cencols) > 1:
            names.append(p['name'])
    print(names)


def set_reel_code():
    """ 设置页数据的卷编码"""
    db = hlp.get_db('')
    cond = {'reel_code': {'$regex': 'JS_'}}
    # cond = {'reel_code': 'YB_1_1'}
    reels = list(db.reel.find(cond, {'format': 0, 'format_logs': 0, 'labels': 0, 'pages': 0}))
    for i, rl in enumerate(reels):
        print('[%s/%s]%s' % (i + 1, len(reels), rl['reel_code']))
        cond2 = get_page_select_cond(rl)
        r = db.page.update_many(cond2, {'$set': {'reel_code': rl['reel_code']}})
        print('%s pages updated' % r.modified_count)


def export_xuba():
    """导出序跋文字"""
    db = hlp.get_db('tw-work')
    # 获取异体字转换表
    vts = list(db.variant.find({'v_code': {'$ne': None}}, {'_id': 0, 'v_code': 1, 'uni_txt': 1, 'nor_txt': 1}))
    vt2txt = {v['v_code']: v.get('nor_txt') or v.get('uni_txt') or '' for v in vts}
    # 获取序跋页数据
    # root = '/Volumes/v2/00Inbox/JSZ/序跋'
    root = '/home/smjs/xiandu/JSZ/序跋'
    with open(path.join(root, '径山藏序跋目錄-總表-1104.csv'), 'r', encoding='utf-8') as f:
        rows = list(csv.reader(f))[1:]
    for i, r in enumerate(rows):
        no, name, bz_type = r[0], r[3], r[11]
        fn = path.join(root, '径山藏序跋正字文本', '#%s-%s.txt' % (no, name.strip()))
        if path.exists(fn):
            continue
        reel_code, start_column, end_column = r[12], r[13], r[14]
        if '图' in bz_type:
            # print('[e0]%s,%s, %s' % (no, name, reel_code))
            continue
        if not start_column or not end_column:
            # print('[e1]%s,%s, %s' % (no, name, reel_code))
            continue
        start_page, start_line = start_column.split('#')[0].rsplit('@', 1)
        end_page, end_line = end_column.split('#')[0].rsplit('@', 1)
        start_volume, start_page_no = start_page.rsplit('_', 1)
        end_volume, end_page_no = end_page.rsplit('_', 1)
        if start_volume != end_volume:
            # print('[e2]%s,%s, %s' % (no, name, reel_code))
            continue
        print('[%s/%s]' % (i + 1, len(rows)), start_page, start_line, end_page, end_line)
        lines = []
        for j in range(int(start_page_no), int(end_page_no) + 1):
            page_name = '%s_%s' % (start_volume, j)
            lines.append(page_name)
            page = db.page.find_one({'name': page_name}, {'_id': 0, 'name': 1, 'chars': 1})
            page_lines = get_page_txt(page, 'txt', code2txt=vt2txt).split('\n')
            if page_name == start_page:
                page_lines = page_lines[int(start_line) - 1:]
            elif page_name == end_page:
                page_lines = page_lines[:int(end_line)]
            lines.extend(page_lines)
        fn = path.join(root, '径山藏序跋正字文本', '#%s-%s.txt' % (no, name.strip()))
        with open(fn, 'w', encoding='utf-8') as f:
            txt = '\n'.join(lines)
            txt = normalize(txt)
            f.write(txt)


def split_block_txt(page):
    """对径山藏page进行拆分成a栏和b栏的txt列表"""

    def in_center_region(x, image_width, region_ratio=1 / 3):
        """
        判断x坐标是否在图片的中间区域

        参数:
        x: 要判断的x坐标
        image_width: 图片宽度
        region_ratio: 中间区域比例，默认1/3表示中间三分之一

        返回:
        bool: 是否在中间区域
        """
        # 计算中间区域的左右边界
        region_width = image_width * region_ratio
        left_boundary = (image_width - region_width) / 2
        right_boundary = (image_width + region_width) / 2
        return left_boundary <= x <= right_boundary

    def split_columns_by_center_columns(page0):
        """
        使用center_columns中的第一个列进行拆分
        """
        # 获取所有未删除的columns
        columns = [c for c in page0.get('columns', []) if not c.get('deleted')]
        # 获取所有is_center为True的columns
        center_columns = [c for c in columns if c.get('is_center')]
        # 使用第一个center_column进行拆分
        first_center = center_columns[0]
        split_index = columns.index(first_center)  # 找到在原始列表中的索引
        # 拆分columns列表
        columns_a = columns[:split_index + 1]
        columns_b = columns[split_index + 1:]
        # 过滤版心列
        columns_a = [c for c in columns_a if not c.get('is_center')]
        columns_b = [c for c in columns_b if not c.get('is_center')]
        return columns_a, columns_b

    def split_columns_by_image_width(columns, image_width):
        """
        根据图片在中间线进行拆分columns列表
        """
        center_line = image_width / 2

        # 1. 从columns列表的后面往前计算（倒序），找到第一个完全在左侧的列
        split_index = -1
        for i in range(len(columns) - 1, -1, -1):
            col = columns[i]
            if col['x'] + col['w'] > center_line:
                split_index = i
                break

        # 2. 根据索引位置直接拆分columns列表
        if split_index != -1:
            # 拆分点包括拆分列本身，所以用split_index+1
            columns_a = columns[:split_index + 1]
            columns_b = columns[split_index + 1:]
        else:
            columns_a = []
            columns_b = columns
        return columns_a, columns_b

    # 如果有版心列，使用版心列进行栏的拆分
    center_cols = [c for c in page.get('columns', []) if not c.get('deleted') and c.get('is_center')]
    split_flag = False
    a_columns, b_columns = [], []
    if center_cols:
        # 判断版心列是否在页的中间区域
        in_center = in_center_region(center_cols[0]['x'], page['width'])
        if in_center:
            a_columns, b_columns = split_columns_by_center_columns(page)
            split_flag = True
        else:
            split_flag = False
    # 没有版心列，使用图片的中间线进行拆分
    if not split_flag:
        columns = [ch for ch in page.get('columns', []) if not ch.get('deleted') and not ch.get('is_center')]
        a_columns, b_columns = split_columns_by_image_width(columns, page['width'])

    a_columns_ids = [c['column_id'] for c in a_columns]
    b_columns_ids = [c['column_id'] for c in b_columns]

    block_txts_a = []
    block_txts_b = []

    for ch in page.get('chars'):
        if ch.get('deleted'):
            continue
        txt = ch.get('txt', '■')
        column_id = ch['char_id'].rsplit('c', 1)[0]

        if column_id in a_columns_ids:
            block_txts_a.append(txt)
        if column_id in b_columns_ids:
            block_txts_b.append(txt)

    return block_txts_a, block_txts_b

# 检查字框需有对应列框，列框需有对应栏框
def stream_pages_cursor(db=None, projection=None, batch_size=1000, filter_cond=None):
    """
    Stream all pages using a pymongo cursor with controlled batch_size.
    Yields one page document at a time.
    """
    db = db or hlp.get_db('tw-work')
    filter_cond = filter_cond or {}
    projection = projection or {'_id': 0, 'name': 1, 'blocks': 1, 'columns': 1, 'chars': 1}
    cursor = db.page.find(filter_cond, projection).batch_size(batch_size)
    try:
        for doc in cursor:
            yield doc
    finally:
        try:
            cursor.close()
        except Exception:
            pass

def process_pages_in_batches(process_fn, db=None, projection=None, batch_size=500, group_size=50, filter_cond=None):
    """
    process_fn(batch_list) is called for each group of pages (list length <= group_size).
    This accumulates small groups from the streaming source and calls your checker.
    """
    db = db or hlp.get_db('tw-work')
    projection = projection or {'_id': 0, 'name': 1, 'blocks': 1, 'columns': 1, 'chars': 1}
    buf = []
    for i, page in enumerate(stream_pages_cursor(db=db, projection=projection, batch_size=batch_size, filter_cond=filter_cond)):
        buf.append(page)
        if len(buf) >= group_size:
            process_fn(buf)
            buf = []
    if buf:
        process_fn(buf)

import csv

def check_and_export(out_path='./log/page_issues.csv', batch_size=500, group_size=50, filter_cond=None):
    """
    Scan pages and log problematic column/char relationships into CSV.
    - out_path: output CSV (default: <BASE_DIR>/txt/log/page_issues.csv)
    - batch_size: pymongo batch_size for cursor
    - group_size: how many pages to process per write
    - filter_cond: optional mongo filter for pages
    """
    # db = hlp.get_db('tw-work')
    out_path = out_path or path.join(hlp.BASE_DIR, 'txt/log', 'page_issues.csv')
    os.makedirs(path.dirname(out_path), exist_ok=True)
    total = 1439416

    processed = 0
    issues = 0
    start_ts = datetime.now()

    def proc(batch):
        nonlocal processed, issues
        rows = []
        for p in batch:
            name = p.get('name') or ''
            blocks = p.get('blocks') or []
            columns = p.get('columns') or []
            chars = p.get('chars') or []

            # collect non-deleted block ids and column ids for quick membership tests
            block_ids = [b.get('block_id') for b in blocks if not b.get('deleted') and b.get('block_id')]
            col_ids = [c.get('column_id') for c in columns if not c.get('deleted') and c.get('column_id')]

            # check columns -> blocks
            for col in columns:
                if col.get('deleted'):
                    continue
                col_id = col.get('column_id') or ''
                # column's block id is column_id.rsplit('c',1)[0] in your schema
                parent_block_id = col_id.rsplit('c', 1)[0] if col_id else ''
                if parent_block_id and parent_block_id not in block_ids:
                    rows.append([name, 'COLUMN_MISSING_BLOCK', col_id, f'expected block {parent_block_id}'])

            # check chars -> columns
            for ch in chars:
                if ch.get('deleted'):
                    continue
                char_id = ch.get('char_id') or ''
                parent_col_id = char_id.rsplit('c', 1)[0] if char_id else ''
                if parent_col_id and parent_col_id not in col_ids:
                    rows.append([name, 'CHAR_MISSING_COLUMN', char_id, f'expected column {parent_col_id}'])

        if rows:
            with open(out_path, 'a', encoding='utf-8', newline='') as fw:
                writer = csv.writer(fw)
                writer.writerows(rows)

        processed += len(batch)
        issues += len(rows)
        elapsed = datetime.now() - start_ts
        pct = (processed / total * 100) if total else 0.0
        print(f'[{datetime.now().isoformat()}] processed {processed}/{total} pages ({pct:.2f}%), '
              f'issues={issues}, elapsed={str(elapsed).split(".")[0]}', flush=True)

    # write header once
    if not path.exists(out_path):
        with open(out_path, 'w', encoding='utf-8', newline='') as fh:
            writer = csv.writer(fh)
            writer.writerow(['page', 'issue_type', 'obj_id', 'detail'])

    # stream pages and call proc in groups
    process_pages_in_batches(proc, db=None, projection={'_id': 0, 'name': 1, 'blocks': 1, 'columns': 1, 'chars': 1},
                             batch_size=batch_size, group_size=group_size, filter_cond=filter_cond)

    total_elapsed = datetime.now() - start_ts
    print(f'Finished. total pages={processed}, total issues={issues}, time={str(total_elapsed).split(".")[0]}')
    print(f'Issues logged to: {out_path}')


def apply_txt2missingchars(db, page, index_id='fz_yinshi_match', field='cmp_txt'):
    """
    Finds a specific match_log and fills missing character fields
    without overwriting existing valid text.
    """
    # 1. Find the target log
    target_log = next((log for log in page.get('match_logs', []) if log.get('index_id') == index_id), None)

    if not target_log or not target_log.get('match_txt'):
        return False

    base_txt = page.get('base_txt', '')
    match_txt = target_log['match_txt']

    # 2. Get active characters (excluding center columns)
    cen_column_ids = [
        c.get('column_id') for c in page.get('columns', []) if c.get('is_center') and not c.get('deleted')
    ]
    chars = [
        ch
        for ch in page.get('chars')
        if not ch.get('deleted') and ch['char_id'].rsplit('c', 1)[0] not in cen_column_ids
    ]

    # 3. Rebuild base_txt to match the chars array (exclude center columns)
    rebuilt_base_txt = ''
    for ch in chars:
        char_txt = ch.get('txt', '■')
        rebuilt_base_txt += char_txt

    # 4. Perform alignment (reusing util.diff)
    from util.diff import diff
    from util.punc import trim_punc

    match_txt_clean = trim_punc(match_txt, True)
    clean_base = trim_punc(rebuilt_base_txt, True)

    segments = diff(clean_base, match_txt_clean, lambda x: True, lambda x: True, normalize=True)

    # 5. Selective Update with bounds checking
    start = 0
    for seg in segments:
        if not seg.get('base0'):
            continue

        len_b = len(seg['base0'])
        len_c = len(seg['cmp0'])

        # Find which characters in the base segment ARE missing or placeholders
        updatable_indices = []
        for i in range(len_b):
            idx = start + i
            if idx < len(chars):
                current_val = chars[idx].get(field)
                if not current_val or current_val == '■':
                    updatable_indices.append(idx)

        # Redistribute cmp0 characters into the updatable base positions
        num_updatable = len(updatable_indices)
        if num_updatable > 0:
            if len_c > num_updatable:
                # Squeeze surplus into the first updatable position
                surplus = len_c - num_updatable
                first_idx = updatable_indices[0]
                # Combine the first char of what's left with all extra chars
                chars[first_idx][field] = seg['cmp0'][: surplus + 1]

                # Fill remaining positions 1:1
                for i in range(1, num_updatable):
                    chars[updatable_indices[i]][field] = seg['cmp0'][surplus + i]
            else:
                # 1:1 mapping (or fill with ■ if cmp is shorter)
                for i in range(num_updatable):
                    if i < len_c:
                        chars[updatable_indices[i]][field] = seg['cmp0'][i]
                    else:
                        chars[updatable_indices[i]][field] = '■'

        start += len_b
    return True


def process():
    batch_jxz_apply_txt2char()


def main(func='process', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
