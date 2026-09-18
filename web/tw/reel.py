from email.mime import text
import re
import os
import sys
import json
import logging
import os.path as path
import pandas as pd

sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

import helper as hlp
from util.diff import diff, diff_v2, get_pos, repair_mid_repeats
from util.punc import PUNC_STR, not_newline_and_pagecode, not_punc_and_cbeta_whitespace
from util.uni2std import normalize


def replace(txt):
    """ 替换兼容字"""
    items = {'復': '復', '裏': '裏', '流': '流', '育': '育', '花': '花',
             '切': '切', '書': '書', '䂖': '䂖', '寳': '寳', '旣': '旣',
             '郞': '郞', '食': '食', '况': '况'}
    return ''.join([items.get(t, t) for t in txt])


def get_switch_pos(boxes):
    """ 查找小字折行位置"""
    for j, b in enumerate(boxes):
        if not j:
            continue
        prv = boxes[j - 1]
        if b['y'] < prv['y'] + prv['h'] / 2 and b['x'] + b['w'] / 2 < prv['x']:
            return j
    return 0

def get_page_select_cond(reel):
    """ 获取页数据查询条件"""
    start = hlp.align_code('%s_%s' % (reel['start_volume'], reel['start_page']))
    end = hlp.align_code('%s_%s' % (reel['end_volume'], reel['end_page']))
    cond = {'page_code': {'$gte': start, '$lte': end}}
    return cond


def get_range_fields():
    """ 计算卷相关的页数据"""
    # 'start_block', 'end_block'没有实际使用
    return ['start_column', 'start_volume', 'start_page', 'end_volume', 'end_page', 'end_column']


def get_reel_txt1(reel_code, db=None):
    """ 获取卷文本：按原书换行"""
    db = db or hlp.get_db('tw-work')
    fields = ['reel_code'] + get_range_fields()
    reel = db.reel.find_one({'reel_code': reel_code}, {f: 1 for f in fields})
    styles = hlp.prop(reel, 'labels.lines', {})  # 行格式
    cond = get_page_select_cond(reel)
    pages = list(db.page.find(cond, {'name': 1, 'uni_txt': 1, '_id': 0}))
    pages.sort(key=lambda x: hlp.align_code(x['name']))

    reel_lines = []
    for page in pages:
        page_txt = page.get('uni_txt') or ''
        if not page_txt:
            continue
        page_txt = normalize(page_txt)
        # reel_lines.append('[%s_1]' % page['name'])
        reel_lines.append('[%s]' % page['name'])
        page_lines = page_txt.split('\n')
        for i, line in enumerate(page_lines):
            line = replace(line)
            head = '%s@%02d' % (page['name'], i + 1)
            label = styles.get(head, '')
            if label in ['G'] or '<center>' in line:
                # reel_lines.append('[%s_2]' % page['name'])
                pass
            else:
                reel_lines.append(line)
    return '\n'.join(reel_lines)


def get_reel_txt2(reel_code, db=None):
    """ 获取卷文本：按格式简单设置换行"""
    db = db or hlp.get_db('tw-work')
    reel = db.reel.find_one({'reel_code': reel_code}, {'pages': 0, 'txt': 0})
    styles = hlp.prop(reel, 'labels.lines', {})  # 行格式
    cond = get_page_select_cond(reel)
    pages = list(db.page.find(cond, {'name': 1, 'uni_txt': 1}))
    pages.sort(key=lambda x: hlp.align_code(x['name']))

    fields = ['F', 'X', 'B', 'S', 'Z', 'P', 'K', '']
    f_status = {f: 0 for f in fields}
    reel_lines = []
    for page in pages:
        page_txt = page.get('uni_txt')
        page_txt = page_txt.replace('<center>', '')
        if not page_txt:
            continue
        page_lines = page_txt.split('\n')
        for i, line in enumerate(page_lines):
            line = replace(line)
            head = '%s@%02d' % (page['name'], i + 1)
            label = styles.get(head, '')
            if label in ['G']:  # 版心列
                continue
            elif label in ['J', 'R', 'D', 'H', 'A', 'Y', 'M']:  # 经名、卷名、品名、标题、作者、译者、目录
                reel_lines.append('\n%s\n' % line)
            elif label in fields:  # 附文、序、跋、偈颂、咒语、科判、刊记、正文
                if f_status[label] == 0:
                    reel_lines.append('\n%s' % line)
                    f_status = {f: 0 for f in fields}
                    f_status[label] = 1
                else:
                    reel_lines.append(line)
            else:
                reel_lines.append(line)
    reel_txt = re.sub(r'\n+', '\n', ''.join(reel_lines)).strip()
    return reel_txt


def export_reel_txt():
    """导出卷数据，存到文件系统"""
    db = hlp.get_db('tw-work')
    root = '/home/smjs/xiandu/jsz-reeltxt'
    cond = {'reel_code': {'$regex': 'JS_'}}
    # cond = {'reel_code': 'JS_1_2'}
    reels = list(db.reel.find(cond, {'reel_code': 1, 'pages': 1, '_id': 0}))
    for i, rl in enumerate(reels):
        reel_code = rl['reel_code']
        print('[%s/%s]%s' % (i, len(reels), reel_code))
        txt = get_reel_txt1(reel_code)
        dst_dir = path.join(root, reel_code.rsplit('_', 1)[0])
        os.makedirs(dst_dir, exist_ok=True)
        with open(path.join(dst_dir, f"{reel_code}.txt"), 'w') as f:
            f.write(txt)


def add_reel_marks(reel_code, reel_lines):
    """ 添加卷标记"""

    def is_js_txt(t):
        return t not in '%s<char .jpg">0123456789abcdefghijklmnopqrstuvwxyz\n' % PUNC_STR

    def reset_pos(_txt, n):
        # 以=代表一个字符
        return get_pos(_txt, is_js_txt, n, False)

    db = hlp.get_db('tw-work')
    reel = db.reel.find_one({'reel_code': reel_code}, {'labels': 1, '_id': 0})
    styles = hlp.prop(reel, 'labels.lines', {})  # 行格式
    notes = hlp.prop(reel, 'labels.notes', {})  # 字格式
    page_name, line_no = '', 0
    name2chars = {}
    res_lines = []
    for i, line in enumerate(reel_lines):
        line = line.strip()
        if not line:
            res_lines.append(line)
            continue
        m = re.match(r'^\[(JS[_\d]+)_1\]$', line)
        if m:
            page_name, line_no = m.group(1), 0
            res_lines.append(line)
            continue
        line_no += 1
        head = '%s@%02d' % (page_name, line_no)
        label = styles.get(head, '')
        # 0. 预处理
        line = re.sub(r'[\(\)]', '', line)  # 去掉英文括号
        if label in list('JRDHAYMZPK'):  # 经名/卷名/品名/标题/作者/译者/目录/咒语/科判/刊记
            line = line.replace('¶', '')
        if label in list('JRDHAYMZP'):  # 经名/卷名/品名/作者/译者/目录/咒语/科判
            line = re.sub(r'[%s]+' % PUNC_STR, '', line)
        # 1. 处理字格式
        _notes = notes.get(head, [])
        _notes = [nt for nt in _notes if nt[0] < nt[1]]  # 去掉空标记
        if _notes:
            if 'char' in line:
                logging.info('[%s]%s' % (reel_code, line.strip()))
            chars = name2chars.get(page_name)
            if not chars:
                page = db.page.find_one({'name': page_name}, {'chars': 1, '_id': 0})
                chars = [c for c in hlp.prop(page, 'chars', []) if not c.get('deleted')]
                name2chars[page_name] = chars
            ln_chars = [c for c in chars if c['column_no'] == line_no]
            start, slices = 0, []
            for nt in _notes:  # nt是封闭区间，它的序号是从1开始的
                s, e = reset_pos(line, nt[0]), reset_pos(line, nt[1])
                if s > start:
                    slices.append(line[start: s])  # big
                seg = line[s: e + 1]
                nt_chars = [c for c in ln_chars if nt[0] <= c['char_no'] <= nt[1]]
                pos = get_switch_pos(nt_chars)
                if pos:
                    seg = seg.replace('\u3000', '')
                    pos = reset_pos(seg, pos + 1)
                    slices.append('（%s/%s）' % (seg[0: pos], seg[pos: e + 1]))
                else:
                    slices.append('（%s）' % seg)
                start = e + 1
            line = ''.join(slices) + line[start:]
            line = line.replace('(（', '（').replace('）)', '）')
            line = line.replace('（(', '（').replace(')）', '）')
        # 2. 处理行格式
        if label in ['G']:  # 版心列
            res_lines.append('[%s_2]' % page_name)
        elif label in ['J', 'R']:  # 经名、卷名
            res_lines.append('<vol>%s</vol>' % line)
        elif label in ['D', 'H']:  # 品名、标题
            res_lines.append('<h1>%s</h1>' % line)
        elif label in ['A', 'Y']:  # 作译者
            res_lines.append('（%s|author）' % line)
        elif label in ['M', 'P']:  # 目录、科判
            res_lines.append('M#%s' % line)
        elif label in ['K']:  # 刊记作为小字处理
            res_lines.append('（%s）' % line)
        else:
            res_lines.append(line)

    txt = '\n'.join(res_lines)
    txt = txt.replace('（）', '').replace('。。', '。')
    return txt


def get_reel_column_list(reel, cut_txt=True):
    """ 获取卷相关的行数据
    注：reel需要包含需要pages和format字段
    返回值数据结构:
    [
        {
            'page_name': 'xxxx',
            'col_cid': 1,  # 行的唯一id
            'char_cids': [[1, 5], 7],  # 该行包含的字cid，连续cid可以合并，例如[1,5]表示从1到5
            'col_txt': "大般若波羅蜜多經卷第一",  # 校对文本的单行内容
            'col_format': "J",
            'char_format': [],  # 单行有多个字格式时：[["N", 1, 14], ] 含义: format, start_cid, end_cid
        },
        ...
    ]
    cut_txt：是否根据起止字段截取文本：start_volume、start_page、start_block、start_column、end_volume、end_page、end_block、end_column
    """
    col_list = []
    pages = reel.get('pages') or []
    name2format = {p['name']: p for p in reel.get('format') or []}
    start_page = '%s_%s' % (reel.get('start_volume'), reel.get('start_page'))
    end_page = '%s_%s' % (reel.get('end_volume'), reel.get('end_page'))

    for page in pages:
        page_name = page.get('name')
        if not page.get('cids'):
            continue

        page_format = name2format.get(page_name) or {}
        col_cid2col_format = {cid: fmt for fmt, cid in page_format.get('columns') or []}
        valid = page_name != start_page  # 当前行是否有效（起始页默认从无效开始）
        for idx, cid in enumerate(page['cids']):
            col_cid = cid[0]
            col_format = col_cid2col_format.get(col_cid) or 'T'  # 缺省为正文
            # 检查有效性
            add_current = False
            if page_name == start_page:  # 起始页去掉前面多余的文字
                # 默认从无效行开始，计算从哪里开始为有效
                if not reel.get('start_column') and (
                        not reel.get('start_block') or reel.get('start_block') == 1):
                    valid = True
                elif reel.get('start_column'):
                    if reel['start_column'] == col_cid:
                        valid = True
            elif page_name == end_page:  # 终止页去掉后面多余的文字
                # 默认从有效行开始，计算从哪里开始为无效
                if reel.get('end_column'):
                    if reel['end_column'] == col_cid:
                        valid = False
                        add_current = True

            if not cut_txt or valid or add_current:
                col = dict()
                col['page_name'] = page_name
                col['col_txt'] = page['txt'][idx]
                col['col_cid'] = col_cid
                col['col_format'] = col_format
                col['char_cids'] = hlp.merge_nums(cid[1])
                col['char_format'] = []
                for ch_fmt in page_format.get('chars') or []:  # 字格式
                    if ch_fmt[1] == col['col_cid']:
                        col['char_format'].append([ch_fmt[0], ch_fmt[2], ch_fmt[3]])
                col_list.append(col)

    return col_list


def merge_by_format(reel_column_list, include_center=False):
    """
    拼接col_format相同且连续的行，返回每组的page_name、col_format和拼接后的col_txts。
    返回相同format的连续行（所有格式）
    返回格式:
    [
        {'page_name': 'xxx', 'col_cid': 'E', 'col_format': 'E',  'col_txts': ['xxxxxx',]},
        ...
    ]
    include_center: 是否包含版心列
    """
    if not reel_column_list:
        return []
    result = []
    current_group = []
    for col in reel_column_list:
        if col.get('col_format') == 'G' and not include_center:
            continue
        if not current_group:
            current_group.append(col)
        else:
            # 判断col_format是否与上一行相同且连续
            if col['col_format'] == current_group[-1]['col_format']:
                current_group.append(col)
            else:
                # 拼接当前组
                col_txts = [item['col_txt'] for item in current_group]
                result.append({
                    'page_name': current_group[0]['page_name'],
                    'col_cid': current_group[0]['col_cid'],
                    'col_format': current_group[0]['col_format'],
                    'col_txts': col_txts
                })
                current_group = [col]
    # 最后一组
    if current_group:
        col_txts = [item['col_txt'] for item in current_group]
        result.append({
            'page_name': current_group[0]['page_name'],
            'col_cid': current_group[0]['col_cid'],
            'col_format': current_group[0]['col_format'],
            'col_txts': col_txts
        })
    return result


def merge_for_bd_transfer(reel_column_list, include_center=False):
    """ 按照标点类型合并，以便进行标点迁移。
    一、总体思路：
    正文中间的标题等格式会将正文分隔成多个片段，如果切割得很碎，会干扰标点迁移。为此，合并时采取以下逻辑：
    1. 将正文中间的标题等格式视为正文处理（需要在标题文字后加上逻辑换行符¶）
    2. 刊记、校讹、牌记等格式，不能视为正文
    """
    if not reel_column_list:
        return []

    # 检查最开始和最后的列是否为文本格式
    txt_fmts = ['T', 'F', 'X', 'B', 'S', 'Z']
    start = 0
    for i, col in enumerate(reel_column_list):
        if col.get('col_format') in txt_fmts:
            start = i
            break
    end = len(reel_column_list) - 1
    for i, col in enumerate(reel_column_list[::-1]):
        if col.get('col_format') in txt_fmts:
            end = len(reel_column_list) - i
            break

    # 将正文中间的标题等格式视为正文处理，音释、校讹、牌记等格式不视为正文
    for col in reel_column_list[start:end]:
        if col.get('col_format') == 'G' and not include_center:
            continue
        # 将标题等格式加上逻辑换行符
        newline_fmts = ['J', 'L', 'A', 'Y', 'H1', 'H2', 'H3', 'H4', 'H5']
        if col.get('col_format') in newline_fmts:
            col['col_txt'] += '¶'
        if col.get('col_format') not in ['E', 'C', 'K']:
            col['col_format'] = 'T'

    merged_column_list = merge_by_format(reel_column_list, False)

    return merged_column_list


def get_merged_column_list(reel, cut_txt=True, include_center=False):
    column_list = get_reel_column_list(reel, cut_txt)
    merged_column_list = merge_for_bd_transfer(column_list, include_center)
    return merged_column_list

def get_sx_reel_txt(reel_code, db=None, vdict=None):
    """
    获取思溪藏卷文本（每页带页编码，拼接chars，过滤deleted和is_center，按列断行）
    """
    import helper as hlp
    if db is None:
        db = hlp.get_db('tw-work')
    if vdict is None:
        vdict = load_js_variant_dict()
    reel = db.reel.find_one({'reel_code': reel_code})
    if not reel:
        print(f"Reel not found: {reel_code}")
        return ''

    cond = get_page_select_cond(reel)
    pages = list(db.page.find(cond, {'name': 1, 'chars': 1, 'columns': 1}))
    pages.sort(key=lambda x: hlp.align_code(x['name']))
    page_txts = []
    for page in pages:
        page_name = page['name']
        columns = page.get('columns', [])
                
        center_col_ids = set(
            col.get('column_id') for col in columns
            if col.get('is_center') and col.get('column_id') is not None
        )

        # 按列分组
        col_dict = {}
        for char in page.get('chars', []):
            if char.get('deleted'):
                continue
            char_id = char.get('char_id')
            if not char_id:
                continue
            c_column_id = char_id.rsplit('c', 1)[0]
            if c_column_id in center_col_ids:
                continue
            txt = char.get('txt', '■')
            if txt in vdict:
                # print(txt, '->', vdict[txt])
                txt = vdict[txt]
            col_dict.setdefault(c_column_id, []).append(txt)
            # col_dict.setdefault(c_column_id, []).append(char.get('txt', '■'))
        if col_dict:
            page_txts.append(f"[{page['name']}]")
            # 按列顺序输出，每列一行
            for col_id in sorted(col_dict.keys(), key=col_sort_key):
                line = ''.join(col_dict[col_id])
                page_txts.append(line)

    return '\n'.join(page_txts)

def col_sort_key(x):
    # Extract number after the last 'c'
    m = re.search(r'c(\d+)$', x)
    return int(m.group(1)) if m else x

def export_reel_diff(out_dir='./'):
    db = hlp.get_db('tw-work')
    cond = {'reel_code': {'$regex': '^SX_'}}
    reels = list(db.reel.find(cond, {'reel_code': 1, '_id': 1}))
    reels.sort(key=lambda x: hlp.align_reel_code(x['reel_code']))
    print(f"Found {len(reels)} SX reels.")
    summary_rows = []
    
    for i, rl in enumerate(reels):
        reel_code = rl['reel_code']
        print(f"[{i+1}/{len(reels)}] Processing {reel_code} ...")
        
        reel = db.reel.find_one(
            {'reel_code': reel_code},
            {'bd_match_data': 1, 'reel_no': 1, 'sutra_code': 1}
        )
        if not reel:
            print(f"  [skip] {reel_code} 不存在")
            summary_rows.append({
                '卷号': reel_code,
                '经名': '',
                '作译者': '',
                '差异大于50的页码': ''
            })
            continue

        sutra = db.sutra.find_one(
            {'sutra_code': reel.get('sutra_code')},
            {'sutra_name': 1, 'author': 1}
        )
        
        sx_txt = get_sx_reel_txt(reel_code, db)
        cbeta_txt = reel.get('bd_match_data', {}).get('CBETA', {}).get('match_txt', '')

        sutra_name = sutra.get('sutra_name', '')
        author = sutra.get('author', '')

        if not sx_txt or not cbeta_txt:
            print(f"  [skip] {reel_code} 缺少SX或CBETA文本")
            summary_rows.append({
                '卷号': reel_code,
                '经名': sutra_name,
                '作译者': author,
                '差异大于50的页码': ''
            })
            continue

        segments = diff(
            sx_txt,
            cbeta_txt,
            is_base=not_newline_and_pagecode,
            is_cmp=not_punc_and_cbeta_whitespace,
        )

        rows = []
        for seg in segments:
            rows.append({
                '序号': seg.get('no', ''),
                '是否相同': '是' if seg.get('is_same') else '否',
                '思溪藏 base0': seg.get('base0', ''),
                'CBETA cmp0': seg.get('cmp0', ''),
                '思溪藏 base': seg.get('base', ''),
                'CBETA cmp': seg.get('cmp', ''),
                '文本长度差异': seg.get('len_diff', 0)
            })

        df = pd.DataFrame(rows)
        out_path = path.join(out_dir, f"{reel_code}.xlsx")
        df.to_excel(out_path, index=False)

        large_diff_pages, _ = find_pages_with_large_diff(segments, threshold=50)
        total_len_diff = sum(abs(seg.get('len_diff', 0)) for seg in segments)
        summary_rows.append({
            '卷号': reel_code,
            '经名': sutra_name,
            '作译者': author,
            '差异大于50的页码': ', '.join(page.strip('[]') for page in large_diff_pages),
            '总文本长度差异': total_len_diff,
        })
    
    summary_df = pd.DataFrame(summary_rows)
    summary_out_path = path.join(out_dir, "reel_diff_统计报告.xlsx")
    # summary_df.to_excel(summary_out_path, index=False)

def find_pages_with_large_diff(segments, threshold=50):
    """
    Scan diff `segments` for bracketed markers produced by get_jiazhu_txt and
    return (reels, pages, cols, mapping).
    - reels: sorted list of reel headers found that have diffs
    - pages: sorted list of page markers (e.g. JS_79_493) that have diffs
    - cols: sorted list of page+col labels (e.g. JS_79_493_b1c11) that have diffs
    - mapping: {reel: {page: {'base': set(cols), 'cmp': set(cols)}}}
    Use `threshold=1` to report any diff (even 1 char); default 50 preserves previous behavior.
    """
    page_pat = re.compile(r'^(YB|JS|SX)_[0-9]+_[0-9]+$')
    reel_pat = re.compile(r'^(YB|JS|SX)\d+_\d+$')
    page_col_pat = re.compile(r'((?:YB|JS|SX)_[0-9]+_[0-9]+)_(.+)')

    def extract_side_tokens(txt):
        reels = []
        pages = []
        cols = []
        toks = re.findall(r'\[([^\]]+)\]', txt or '')
        for t in toks:
            if reel_pat.match(t):
                reels.append(t)
            elif page_pat.match(t):
                pages.append(t)
            elif page_col_pat.match(t):
                cols.append(t)
        return reels, pages, cols

    diff_map = {}
    seen_reels = set()
    seen_pages = set()
    seen_cols = set()

    for seg in segments:
        seg_has_diff = (not seg.get('is_same')) or abs(seg.get('len_diff', 0)) > 0

        base_reels, base_pages, base_cols = extract_side_tokens(seg.get('base0') or '')
        cmp_reels, cmp_pages, cmp_cols = extract_side_tokens(seg.get('cmp0') or '')

        # record seen tokens for outputs
        for r in base_reels + cmp_reels:
            seen_reels.add(r)
        for p in base_pages + cmp_pages:
            seen_pages.add(p)
        for c in base_cols + cmp_cols:
            seen_cols.add(c)

        if seg_has_diff:
            # attach base-side cols/pages
            current_reel = (base_reels or cmp_reels) and (base_reels[0] if base_reels else cmp_reels[0]) or 'UNKNOWN'
            # base cols
            for c in base_cols:
                r = current_reel
                diff_map.setdefault(r, {}).setdefault(p, {'base': set(), 'cmp': set()})['base'].add(c)
            # cmp cols
            for c in cmp_cols:
                r = current_reel
                diff_map.setdefault(r, {}).setdefault(p, {'base': set(), 'cmp': set()})['cmp'].add(c)
            # page-level (no cols) present in base/cmp
            # if pages appear but no cols, ensure page keys exist
            for p in base_pages + cmp_pages:
                r = current_reel
                diff_map.setdefault(r, {}).setdefault(p, {'base': set(), 'cmp': set()})

            # fallback: if no explicit tokens but there is a current page context from either side
            if not (base_cols or cmp_cols or base_pages or cmp_pages):
                # try to infer a page from either side's first page token
                inferred_page = (base_pages + cmp_pages) and (base_pages + cmp_pages)[0] or None
                if inferred_page:
                    r = current_reel
                    diff_map.setdefault(r, {}).setdefault(inferred_page, {'base': set(), 'cmp': set()})

    # If threshold > 1, compute per-page totals and prune pages below threshold (legacy behavior)
    if threshold and threshold > 1:
        page_totals = {}
        for seg in segments:
            seg_diff = abs(seg.get('len_diff', 0))
            if seg_diff == 0 and seg.get('is_same'):
                continue
            text = (seg.get('base0') or '') + '\n' + (seg.get('cmp0') or '')
            toks = re.findall(r'\[([^\]]+)\]', text)
            page = None
            for t in toks:
                if page_pat.match(t):
                    page = t
                    break
                if page_col_pat.match(t):
                    m = page_pat.match(t)
                    if m:
                        page = m.group(0)
                        break
            if page:
                page_totals[page] = page_totals.get(page, 0) + seg_diff
        for r in list(diff_map.keys()):
            for p in list(diff_map[r].keys()):
                if page_totals.get(p, 0) <= threshold:
                    del diff_map[r][p]
            if not diff_map[r]:
                del diff_map[r]

    reels = sorted(seen_reels)
    pages = sorted(seen_pages)
    cols = sorted(seen_cols)
    return reels, pages, cols, diff_map

def export_all_reel_txt(out_dir='./JS_reel_txt'):
    """
    导出所有JS藏卷文本，每卷一个txt文件，文件名为reel_code.txt
    """
    db = hlp.get_db('tw-work')
    cond = {'reel_code': {'$regex': '^JS'}}
    # cond = {'reel_code': {'$regex': 'SX0106_032'}}
    reels = list(db.reel.find(cond, {'reel_code': 1, 'reel_type': 1, '_id': 0}))
    reels = [r for r in reels if r.get('reel_type') != '空卷']
    reels.sort(key=lambda x: hlp.align_reel_code(x['reel_code']))
    print(f'Found {len(reels)} reels.')

    os.makedirs(out_dir, exist_ok=True)

    for i, rl in enumerate(reels):
        reel_code = rl['reel_code']
        print(f'[{i+1}/{len(reels)}] Exporting {reel_code} ...')
        reel_txt = get_js_reel_txt(reel_code, db)
        if not reel_txt:
            print(f'  [skip] {reel_code} 无文本')
            continue
        out_path = path.join(out_dir, f"{reel_code}.txt")
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(reel_txt)

def read_txt_files(cbeta_path, sx_path):
    """读取两个txt文件内容到cbeta和sx变量"""
    with open(cbeta_path, 'r', encoding='utf-8') as f:
        cbeta = f.read()
    with open(sx_path, 'r', encoding='utf-8') as f:
        sx = f.read()
    return cbeta, sx

def export_reel_diff_cbetatxt(out_dir='./'):
    folder = '../../../data/cbeta-text-20250515/T0220'
    db = hlp.get_db('tw-prod-readonly')
    cond = {'reel_code': {'$regex': '^JS0001_'}}
    reels = list(db.reel.find(cond, {'reel_code': 1, 'reel_type': 1, '_id': 0}))
    reels = [r for r in reels if r.get('reel_type') != '空卷']
    reels.sort(key=lambda x: hlp.align_reel_code(x['reel_code']))
    print(f"Found {len(reels)} reels.")
    summary_rows = []

    for i, rl in enumerate(reels):
        reel_code = rl['reel_code']
        if reel_code not in ['JS0001_178']:
            continue
        print(f"[{i+1}/{len(reels)}] Processing {reel_code} ...")

        js_txt = get_js_reel_txt(reel_code, db)
        cbeta_path = path.join(folder, f"T0220_{reel_code.split('_')[1]}.txt")
        if not path.exists(cbeta_path):
            print(f"  [skip] {reel_code} CBETA文件不存在")
            summary_rows.append({
                '卷号': reel_code,
                '经名': '大般若波羅蜜多經',
                '作译者': '[唐]玄奘·譯',
                '差异大于50的页码': '',
                '总文本长度差异': ''
            })
            continue
        with open(cbeta_path, 'r', encoding='utf-8') as f:
            cbeta_txt = ''.join([line for line in f if not line.startswith('#')])

        if not js_txt or not cbeta_txt:
            print(f"  [skip] {reel_code} 缺少JS或CBETA文本")
            summary_rows.append({
                '卷号': reel_code,
                '经名': '大般若波羅蜜多經',
                '作译者': '[唐]玄奘·譯',
                '差异大于50的页码': '',
                '总文本长度差异': ''
            })
            continue

        segments = diff_v2(
            js_txt,
            cbeta_txt,
            is_base=not_newline_and_pagecode,
            is_cmp=not_punc_and_cbeta_whitespace,
        )

        js_txt_path = path.join(out_dir, f"{reel_code}_js.txt")
        cbeta_txt_path = path.join(out_dir, f"{reel_code}_cbeta.txt")
        with open(js_txt_path, 'w', encoding='utf-8') as f:
            f.write(js_txt)
        with open(cbeta_txt_path, 'w', encoding='utf-8') as f:
            f.write(cbeta_txt)

        # os.makedirs(out_dir, exist_ok=True)
        # out_file = path.join(out_dir, f"{reel_code}_segments_before_repair.txt")
        # with open(out_file, 'w', encoding='utf-8') as f:
        #     for seg in segments:
        #         f.write(json.dumps(seg, ensure_ascii=False) + '\n')
        # print(f"Wrote {len(segments)} segments to {out_file}")

        rows = []
        for seg in segments:
            rows.append({
                '序号': seg.get('no', ''),
                '是否相同': '是' if seg.get('is_same') else '否',
                '思溪藏 base0': seg.get('base0', ''),
                'CBETA cmp0': seg.get('cmp0', ''),
                '思溪藏 base': seg.get('base', ''),
                'CBETA cmp': seg.get('cmp', ''),
                '文本长度差异': seg.get('len_diff', 0)
            })

        # df = pd.DataFrame(rows)
        # out_path = path.join(out_dir, f"{reel_code}_fix_22.xlsx")
        # df.to_excel(out_path, index=False)

        large_diff_pages, _ = find_pages_with_large_diff(segments, threshold=50)
        total_len_diff = sum(abs(seg.get('len_diff', 0)) for seg in segments)
        total_pos_len_diff = sum(seg.get('len_diff', 0) for seg in segments if seg.get('len_diff', 0) > 0)
        total_neg_len_diff = sum(seg.get('len_diff', 0) for seg in segments if seg.get('len_diff', 0) < 0)
        summary_rows.append({
            '卷号': reel_code,
            '经名': '大般若波羅蜜多經',
            '作译者': '[唐]玄奘·譯',
            '差异大于50的页码': ', '.join(page.strip('[]') for page in large_diff_pages),
            '总文本长度差异': total_len_diff,
            '正差异': total_pos_len_diff,
            '负差异': total_neg_len_diff,
        })
    
    # summary_df = pd.DataFrame(summary_rows)
    # summary_out_path = path.join(out_dir, "JS0001_diff_统计报告.xlsx")
    # summary_df.to_excel(summary_out_path, index=False)

def pad_sutra_code(code):
    """
    Convert SX_1 → SX0001, SX_123 → SX0123, etc.
    """
    m = re.match(r'^(SX)_?(\d+)$', code)
    if m:
        return f"{m.group(1)}{int(m.group(2)):04d}"
    return code


def export_reel_diff_cbetatxt_sutra(out_dir='./data'):
    folder = '../../../data/cbeta-text-20250515'
    db = hlp.get_db('tw-prod-readonly')
    cond = {'source_type': 'SXZ'}
    sutras = list(db.sutra_source.find(cond, {'sutra_uid': 1, 'rushi_sutra_uid': 1, 'assist_sutra_uid': 1, '_id': 0}))
    print(f"Found {len(sutras)} SX sutras.")
    summary_rows = []

    # sx2js = {
    #     'SX0004': 'JS0004',
    #     'SX0056': 'JS0061',
    #     'SX0057': 'JS0062',
    #     'SX0058': 'JS0063',
    #     'SX0061': 'JS0066',
    #     'SX0072': 'JS0077',
    # }

    sx2js = {
        'SX0056': 'JS0061',
        'SX0057': 'JS0062',
        'SX0058': 'JS0063',
        'SX0061': 'JS0066',
        'SX0072': 'JS0077',
        'SX0434': 'JS0535',
        'SX0565': 'JS1203',
        'SX0664': 'JS0546',
        # 'SX0841': 'JS0779',
        'SX0903': 'JS1118',
        'SX0904': 'JS1145',
        'SX0997': 'JS1320',
        'SX1015': 'JS1327',
        'SX1031': 'JS1456',
        'SX1061': 'JS1466',
        'SX1089': 'JS1492',
        'SX0068': 'JS0073',
    }

    for i, s in enumerate(sutras):
        sutra_code = pad_sutra_code(s.get('sutra_uid'))
        # if sutra_code == 'SX0001':
        if sutra_code != 'SX0664':
        # if sutra_code not in sx2js:
            continue

        print(f"[{i+1}/{len(sutras)}] Processing {sutra_code} ...")

        # 查找经名和作译者
        sutra = db.sutra.find_one(
            {'sutra_code': sutra_code},
            {'sutra_name': 1, 'author': 1}
        )
        sutra_name = sutra.get('sutra_name', '')
        author = sutra.get('author', '')

        # 汇总该经所有卷的文本进行对比
        sutra_txt = ''

        reels = list(db.reel.find({'sutra_code': sutra_code}, {'reel_code': 1, '_id': 0}))
        reels.sort(key=lambda x: hlp.align_reel_code(x['reel_code']))

        for j, rl in enumerate(reels):
            reel_code = rl['reel_code']
            print(f"  [{j+1}/{len(reels)}] Processing {reel_code} ...")

            sx_txt = get_sx_reel_txt(reel_code, db)
            sutra_txt += sx_txt + '\n'

        # If this is a JS comparison sutra, use JS as the comparison base
        is_js_cmp = False
        if sutra_code in sx2js:
            js_code = sx2js[sutra_code]
            js_txt = ''
            js_reels = list(db.reel.find({'sutra_code': js_code}, {'reel_code': 1, '_id': 0}))
            js_reels.sort(key=lambda x: hlp.align_reel_code(x['reel_code']))
            for jr in js_reels:
                js_txt += get_sx_reel_txt(jr['reel_code'], db) + '\n'
            cmp_txt = js_txt
            is_js_cmp = True
        # Default: use CBETA
        else:
            # 查找对应的CBETA经号
            cbeta = db.sutra_source.find_one(
                {'rushi_sutra_uid': s.get('rushi_sutra_uid'), 'source_type': 'CBETA'},
                {'sutra_uid': 1, 'assist_sutra_uid': 1, '_id': 0}
            )
            if not cbeta:
                print(f"  [skip] {sutra_code} 缺少CBETA sutra_source")
                summary_rows.append({
                    '经号': sutra_code,
                    '经名': sutra_name,
                    '作译者': author,
                    '差异大于50的页码': '',
                    '总文本长度差异': ''
                })
                continue
            # 读取CBETA文本
            cbeta_txt = ''
            # cbeta_folder = path.join(folder, f"{cbeta.get('sutra_uid')}")
            cbeta_folder = path.join(folder, "T1694")
            cbeta_files = [f for f in os.listdir(cbeta_folder) if re.search(r'_(\d+)\.txt$', f)]
            cbeta_files_sorted = sorted(cbeta_files, key=lambda x: int(re.search(r'_(\d+)\.txt$', x).group(1)))
            for fname in cbeta_files_sorted:
                with open(os.path.join(cbeta_folder, fname), 'r', encoding='utf-8') as ftxt:
                    cbeta_txt += ''.join([
                        line for line in ftxt
                        if not line.startswith('#')
                        and not re.match(r'^[0-9A-Za-z]', line.strip())
                    ])
            cmp_txt = cbeta_txt
            is_js_cmp = False

        if not sutra_txt or not cmp_txt:
            print(f"  [skip] {sutra_code} 缺少SX或CBETA文本")
            summary_rows.append({
                '经号': sutra_code,
                '经名': sutra_name,
                '作译者': author,
                '差异大于50的页码': '',
                '总文本长度差异': ''
            })
            continue

        cmp_func = not_newline_and_pagecode if is_js_cmp else not_punc_and_cbeta_whitespace
        segments = diff_v2(
            sutra_txt,
            cmp_txt,
            is_base=not_newline_and_pagecode,
            is_cmp=cmp_func,
        )

        rows = []
        cmp_prefix = 'JS' if is_js_cmp else 'CBETA'
        for seg in segments:
            rows.append({
                '序号': seg.get('no', ''),
                '是否相同': '是' if seg.get('is_same') else '否',
                '思溪藏 base0': seg.get('base0', ''),
                f'{cmp_prefix} cmp0': seg.get('cmp0', ''),
                '思溪藏 base': seg.get('base', ''),
                f'{cmp_prefix} cmp': seg.get('cmp', ''),
                '文本长度差异': seg.get('len_diff', 0)
            })

        df = pd.DataFrame(rows)
        out_path = path.join(out_dir, f"{sutra_code}.xlsx")
        df.to_excel(out_path, index=False)

        large_diff_pages, _ = find_pages_with_large_diff(segments, threshold=50)
        total_len_diff = sum(abs(seg.get('len_diff', 0)) for seg in segments)
        total_pos_len_diff = sum(seg.get('len_diff', 0) for seg in segments if seg.get('len_diff', 0) > 0)
        total_neg_len_diff = sum(seg.get('len_diff', 0) for seg in segments if seg.get('len_diff', 0) < 0)
        summary_rows.append({
            '经号': sutra_code,
            '经名': sutra_name,
            '作译者': author,
            '差异大于50的页码': ', '.join(page.strip('[]') for page in large_diff_pages),
            '总文本长度差异': total_len_diff,
            '正差异': total_pos_len_diff,
            '负差异': total_neg_len_diff,
        })

    # summary_df = pd.DataFrame(summary_rows)
    # summary_out_path = path.join(out_dir, "sutra_diff_统计报告.xlsx")
    # summary_df.to_excel(summary_out_path, index=False)  

def export_variants_to_txt(out_path='./variants.txt'):
    db = hlp.get_db('tw-work')
    variants = db.variant.find({}, {'v_code': 1, 'nor_txt': 1, '_id': 0})
    vdict = {v['v_code']: v['nor_txt'] for v in variants if v.get('v_code') and v.get('nor_txt')}
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(vdict, ensure_ascii=False, indent=2))

def load_js_variant_dict(path='./variants.txt'):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_js_reel_txt(reel_code, db=None, vdict=None):
    """
    获取JS藏卷文本，自动替换所有v_code为nor_txt
    """
    if db is None:
        db = hlp.get_db('tw-work')
    if vdict is None:
        vdict = load_js_variant_dict()
    txt = get_reel_txt_v2(reel_code, db)
    # 替换所有v_code为nor_txt
    def repl(m):
        code = m.group(0)
        return vdict.get(code, code)
    # 假设v_code格式为v\d+n?
    txt = re.sub(r'v\d+n?', repl, txt)
    return txt

def test():
    cbeta_txt, sx_txt = read_txt_files('SX0001_002_cbeta.txt', 'SX0001_002_sx.txt')
    # run diff with CBETA as base so 'base' fields correspond to the CBETA file
    segments = diff_v2(sx_txt, cbeta_txt, is_base=not_newline_and_pagecode, is_cmp=not_punc_and_cbeta_whitespace)
    # segments = diff_v2(sx_txt, cbeta_txt, is_base=not_newline_and_pagecode, is_cmp=not_punc_and_cbeta_whitespace)
    print(segments)
    
    # merged base reconstructed from diff segments
    merged_base = ''.join(seg.get('base0', '') for seg in segments)
    print("len(SX_1_2_cbeta_cmp.txt):", len(sx_txt))
    print("len(merged base from diff):", len(merged_base))
    print("len(SX_1_2_sx_base.txt):", len(cbeta_txt))
    print("segments count:", len(segments))
    # show discrepancy if any
    print("merged_base - file length:", len(merged_base) - len(cbeta_txt))


def export_reel_diff_cbetatxt_0422(out_dir='./data/161225_SX0422_sutra_diff'):
    folder = '../../../data/cbeta-text-20250515/T0397'
    db = hlp.get_db('tw-work')
    cond = {'reel_code': {'$regex': '^SX0422_'}}
    # cond = {'reel_code': 'SX0001_002'}
    reels = list(db.reel.find(cond, {'reel_code': 1, '_id': 0}))
    reels.sort(key=lambda x: hlp.align_reel_code(x['reel_code']))
    print(f"Found {len(reels)} SX reels.")
    summary_rows = []

    sutra_txt = ''

    for i, rl in enumerate(reels):
        reel_code = rl['reel_code']
        print(f"[{i+1}/{len(reels)}] Processing {reel_code} ...")

        sx_txt = get_sx_reel_txt(reel_code, db)
        sutra_txt += sx_txt + '\n'

    cbeta_txt = ''
    cbeta_files = [path.join(folder, f"T0397_059.txt"), path.join(folder, f"T0397_060.txt")]
    for cbeta_path in cbeta_files:
        with open(cbeta_path, 'r', encoding='utf-8') as f:
            cbeta_txt += ''.join([
                line for line in f
                if not line.startswith('#')
                and not re.match(r'^[0-9A-Za-z]', line.strip())
            ])

    segments = diff(
        sutra_txt,
        cbeta_txt,
        is_base=not_newline_and_pagecode,
        is_cmp=not_punc_and_cbeta_whitespace,
    )

    rows = []
    for seg in segments:
        rows.append({
            '序号': seg.get('no', ''),
            '是否相同': '是' if seg.get('is_same') else '否',
            '思溪藏 base0': seg.get('base0', ''),
            'CBETA cmp0': seg.get('cmp0', ''),
            '思溪藏 base': seg.get('base', ''),
            'CBETA cmp': seg.get('cmp', ''),
            '文本长度差异': seg.get('len_diff', 0)
        })

    df = pd.DataFrame(rows)
    out_path = path.join(out_dir, f"SX0422.xlsx")
    df.to_excel(out_path, index=False)

    large_diff_pages, _ = find_pages_with_large_diff(segments, threshold=50)
    total_len_diff = sum(abs(seg.get('len_diff', 0)) for seg in segments)
    total_pos_len_diff = sum(seg.get('len_diff', 0) for seg in segments if seg.get('len_diff', 0) > 0)
    total_neg_len_diff = sum(seg.get('len_diff', 0) for seg in segments if seg.get('len_diff', 0) < 0)
    summary_rows.append({
        '经号': 'SX0422',
        '经名': '佛說明度五十校計經',
        '作译者': '[後漢]安世高·譯',
        '差异大于50的页码': ', '.join(page.strip('[]') for page in large_diff_pages),
        '总文本长度差异': total_len_diff,
        '正差异': total_pos_len_diff,
        '负差异': total_neg_len_diff,
    })

    summary_df = pd.DataFrame(summary_rows)
    summary_out_path = path.join(out_dir, "sutra_diff_SX0422_统计报告.xlsx")
    summary_df.to_excel(summary_out_path, index=False)  
    

# region updated reel_diff scripts

def get_reel_txt_v2(reel_code, db=None, vdict=None):
    """
    获取思溪藏卷文本（每页带页编码，拼接chars，过滤deleted和is_center，按列断行）
    """
    import helper as hlp
    if db is None:
        db = hlp.get_db('tw-work')
    if vdict is None:
        vdict = load_js_variant_dict()
    reel = db.reel.find_one({'reel_code': reel_code})
    if not reel:
        print(f"Reel not found: {reel_code}")
        return ''

    # get E 音释 and K 刊记 formats
    page_col_formats = {}
    page_char_formats = {}
    for fmt in hlp.prop(reel, 'format', []):
        page_name = fmt.get('name')
        columns = fmt.get('columns', [])
        chars = fmt.get('chars', [])

        col_filtered = [
            {'format': col[0], 'col_id': col[1]}
            for col in columns if col[0] in ('E', 'K')
        ]

        char_filtered = [
            {
                'format': ch[0],
                'col_id': ch[1],
                'start_char_id': ch[2],
                'end_char_id': ch[3]
            }
            for ch in chars if ch[0] in ('E', 'K')
        ]

        if col_filtered:
            page_col_formats[page_name] = col_filtered

        if char_filtered:
            page_char_formats[page_name] = char_filtered

    cond = get_page_select_cond(reel)
    pages = list(db.page.find(cond, {'name': 1, 'chars': 1, 'columns': 1}))
    pages.sort(key=lambda x: hlp.align_code(x['name']))
    page_txts = []
    for page in pages:
        page_name = page['name']
        columns = page.get('columns', [])

        EK_col_ids = []
        if page_name in page_col_formats:
            relevant_cols = page_col_formats[page_name]
            for col in columns: 
                col_cid = col.get('cid')
                for fmt_col in relevant_cols:
                    if fmt_col['col_id'] == col_cid:
                        EK_col_ids.append(col.get('column_id'))

        EK_char_ids = []
        if page_name in page_char_formats:
            relevant_chars = page_char_formats[page_name]
            for char in page.get('chars', []):
                char_id = char.get('cid')
                for fmt_char in relevant_chars:
                    if fmt_char['start_char_id'] <= char_id <= fmt_char['end_char_id']:
                        EK_char_ids.append(char.get('char_id'))
                
        center_col_ids = set(
            col.get('column_id') for col in columns
            if col.get('is_center') and col.get('column_id') is not None
        )

        # 按列分组
        col_dict = {}
        for char in page.get('chars', []):
            if char.get('deleted'):
                continue
            char_id = char.get('char_id')
            if not char_id or char_id in EK_char_ids:
                continue
            c_column_id = char_id.rsplit('c', 1)[0]
            if c_column_id in center_col_ids or c_column_id in EK_col_ids:
                continue
            txt = char.get('txt', '■')
            if txt in vdict:
                # print(txt, '->', vdict[txt])
                txt = vdict[txt]
            col_dict.setdefault(c_column_id, []).append(txt)
            # col_dict.setdefault(c_column_id, []).append(char.get('txt', '■'))
        if col_dict:
            page_txts.append(f"[{page['name']}]")
            # 按列顺序输出，每列一行
            for col_id in sorted(col_dict.keys(), key=col_sort_key):
                line = ''.join(col_dict[col_id])
                page_txts.append(line)

    return '\n'.join(page_txts)

def get_cbeta_text_by_ref(refs, root_folder):
    """
    Given a CBETA reference string, fetch and concatenate all relevant texts.
    Handles:
      - Single reel codes: GA0019_001
      - Reel ranges: X0679_001-005
      - Sutra codes: T0366
    """
    import re, os
    texts = []
    for ref in refs:
        # Reel range: CODE_NUM1-NUM2
        m = re.match(r'^([A-Z0-9]+)_(\d+)-(\d+)$', ref)
        if m:
            code, start, end = m.group(1), int(m.group(2)), int(m.group(3))
            folder = os.path.join(root_folder, code)
            for num in range(start, end + 1):
                reel_code = f"{code}_{num:03d}"
                txt = get_cbeta_reel_txt(reel_code, folder)
                if txt:
                    texts.append(txt)
            continue
        # Single reel: CODE_NUM
        m = re.match(r'^([A-Z0-9]+)_(\d+)$', ref)
        if m:
            code = m.group(1)
            folder = os.path.join(root_folder, code)
            reel_code = f"{code}_{int(m.group(2)):03d}"
            txt = get_cbeta_reel_txt(reel_code, folder)
            if txt:
                texts.append(txt)
            continue
        # Sutra code: CODE
        m = re.match(r'^([A-Z0-9]+)$', ref)
        if m:
            code = m.group(1)
            folder = os.path.join(root_folder, code)
            for fname in sorted(os.listdir(folder)):
                if fname.startswith(code + '_') and fname.endswith('.txt'):
                    with open(os.path.join(folder, fname), 'r', encoding='utf-8') as ftxt:
                        txt = ''.join([
                            line for line in ftxt
                            if not line.startswith('#')
                            and not re.match(r'^[0-9A-Za-z]', line.strip())
                        ])
                        texts.append(txt)
            continue
    return '\n'.join(texts)

def get_cbeta_reel_txt(reel_code, folder):
    # Try to find the file for this reel_code in the folder
    for fname in os.listdir(folder):
        if fname.startswith(reel_code) and fname.endswith('.txt'):
            with open(os.path.join(folder, fname), 'r', encoding='utf-8') as ftxt:
                return ''.join([
                    line for line in ftxt
                    if not line.startswith('#')
                    and not re.match(r'^[0-9A-Za-z]', line.strip())
                ])
    return ''


def get_jiazhu_txt(reel_code, db=None, vdict=None):
    import helper as hlp
    if db is None:
        db = hlp.get_db('tw-prod-readonly')
    if vdict is None:
        vdict = load_js_variant_dict()
    reel = db.reel.find_one({'reel_code': reel_code})
    if not reel:
        print(f"Reel not found: {reel_code}")
        return ''
    
    page_char_formats = {}
    for fmt in hlp.prop(reel, 'format', []):
        page_name = fmt.get('name')
        chars = fmt.get('chars', [])

        char_selected = [
            {
                'format': ch[0],
                'col_id': ch[1],
                'start_char_id': ch[2],
                'end_char_id': ch[3]
            }
            for ch in chars if ch[0] == 'N'
        ]

        if char_selected:
            page_char_formats[page_name] = char_selected

    cond = get_page_select_cond(reel)
    pages = list(db.page.find(cond, {'name': 1, 'chars': 1, 'columns': 1}))
    pages.sort(key=lambda x: hlp.align_code(x['name']))
    page_txts = []

    # include reel_code header
    page_txts.append(f"[{reel_code}]")

    for page in pages:
        page_name = page['name']

        N_char_ids = []
        if page_name in page_char_formats:
            relevant_chars = page_char_formats[page_name]
            for char in page.get('chars', []):
                char_id = char.get('cid')
                for fmt_char in relevant_chars:
                    start_id = fmt_char.get('start_char_id')
                    end_id = fmt_char.get('end_char_id')
                    if start_id is not None and end_id is not None and start_id <= char_id <= end_id:
                        N_char_ids.append(char.get('char_id'))

        # 按列分组
        col_dict = {}
        for char in page.get('chars', []):
            if char.get('deleted'):
                continue
            char_id = char.get('char_id')
            if not char_id or char_id not in N_char_ids:
                continue
            c_column_id = char_id.rsplit('c', 1)[0]
            txt = char.get('txt', '■')
            if txt in vdict:
                txt = vdict[txt]
            col_dict.setdefault(c_column_id, []).append(txt)
        if col_dict:
            page_txts.append(f"[{page_name}]")
            # 按列顺序输出，每列以 [page_colId] 开头
            for col_id in sorted(col_dict.keys(), key=col_sort_key):
                line = ''.join(col_dict[col_id])
                label = f"{page_name}_{col_id}"
                page_txts.append(f"[{label}] {line}")

    return '\n'.join(page_txts)


def export_diff_cbetatxt_sutra_v2(out_dir='./repair'):
    def append_summary_and_continue(summary_rows, sutra_code, sutra_name, author, extra=None):
        row = {
            '经号': sutra_code,
            '经名': sutra_name,
            '作译者': author,
            '差异大于50的页码': '',
            '总文本长度差异': ''
        }
        if extra:
            row.update(extra)
        summary_rows.append(row)
        return

    exception = ['JS1400']

    folder = '../../../data/cbeta-text-20250515'
    db = hlp.get_db('tw-prod-readonly')
    cond = {'source_type': 'JSZ'} # change for different sutra
    sutras = list(db.sutra_source.find(cond, {'sutra_uid': 1, 'rushi_sutra_uid': 1, 'assist_sutra_uid': 1, '_id': 0}))
    print(f"Found {len(sutras)} sutras.")
    summary_rows = []

    # Open log file for assist_sutra_uid usage
    assist_log_path = path.join(out_dir, "assist_uid_log.txt")
    os.makedirs(out_dir, exist_ok=True)
    assist_log = open(assist_log_path, "w", encoding="utf-8")

    for i, s in enumerate(sutras):
        uid_list = s.get('sutra_uid')
        uid_list = uid_list if isinstance(uid_list, list) else [uid_list] if uid_list is not None else []

        for sutra_uid in uid_list:
            sutra_code = pad_sutra_code(sutra_uid)
            # if sutra_code not in ['JS1796','JS1798','JS1787','JS1789','JS1807','JS1816','JS1818','JS1846','JS1852','JS1854','JS1869','JS1905','JS1921']: # change for different sutra
            #     continue
            if sutra_code != 'JS1400': # change for different sutra
                continue

            print(f"[{i+1}/{len(sutras)}] Processing {sutra_code} ...")

            # 查找经名和作译者
            sutra = db.sutra.find_one(
                {'sutra_code': sutra_code},
                {'sutra_name': 1, 'author': 1}
            )
            sutra_name = sutra.get('sutra_name', '')
            author = sutra.get('author', '')

            # 汇总该经所有卷的文本进行对比
            assist_uid = s.get('assist_sutra_uid')
            sutra_txt = ''

            if assist_uid and sutra_code not in exception:
                for j, reel_code in enumerate(assist_uid):
                    if '_' not in reel_code:
                        # Fetch all reels for this sutra
                        reels = list(db.reel.find({'sutra_code': reel_code}, {'reel_code': 1, 'reel_type': 1, '_id': 0}))
                        reels = [r for r in reels if r.get('reel_type') != '空卷']
                        reels.sort(key=lambda x: hlp.align_reel_code(x['reel_code']))
                        for k, rl in enumerate(reels):
                            rc = rl['reel_code']
                            print(f"  [assist {j+1}.{k+1}/{len(assist_uid)}.{len(reels)}] Processing {rc} ...")
                            sx_txt = get_reel_txt_v2(rc, db)
                            sutra_txt += sx_txt + '\n'
                            assist_log.write(f"SX assist_sutra_uid: {sutra_code} - {rc}\n")
                            assist_log.write(sx_txt + "\n\n")
                    else:
                        print(f"  [assist {j+1}/{len(assist_uid)}] Processing {reel_code} ...")
                        sx_txt = get_reel_txt_v2(reel_code, db)
                        sutra_txt += sx_txt + '\n'
                        # Log SX assist_sutra_uid usage
                        assist_log.write(f"SX assist_sutra_uid: {sutra_code} - {reel_code}\n")
                        assist_log.write(sx_txt + "\n\n")

            else:
                reels = list(db.reel.find({'sutra_code': sutra_code}, {'reel_code': 1, 'reel_type': 1, '_id': 0}))
                reels = [r for r in reels if r.get('reel_type') != '空卷']
                reels.sort(key=lambda x: hlp.align_reel_code(x['reel_code']))

                for j, rl in enumerate(reels):
                    reel_code = rl['reel_code']
                    print(f"  [{j+1}/{len(reels)}] Processing {reel_code} ...")

                    sx_txt = get_reel_txt_v2(reel_code, db)
                    sutra_txt += sx_txt + '\n'

            # 查找对应的CBETA经号
            cbeta = db.sutra_source.find_one(
                {'rushi_sutra_uid': s.get('rushi_sutra_uid'), 'source_type': 'CBETA'},
                {'sutra_uid': 1, 'assist_sutra_uid': 1, '_id': 0}
            )
            if not cbeta:
                print(f"  [skip] {sutra_code} 缺少CBETA sutra_source")
                append_summary_and_continue(summary_rows, sutra_code, sutra_name, author)
                continue

            # 读取CBETA文本
            cbeta = db.sutra_source.find_one(
                {'rushi_sutra_uid': s.get('rushi_sutra_uid'), 'source_type': 'CBETA'},
                {'sutra_uid': 1, 'assist_sutra_uid': 1, '_id': 0}
            )
            cbeta_ref = cbeta.get('assist_sutra_uid') or cbeta.get('sutra_uid')
            if not isinstance(cbeta_ref, list):
                cbeta_ref = [cbeta_ref]
            cmp_txt = get_cbeta_text_by_ref(cbeta_ref, folder)

            # Log CBETA assist_sutra_uid usage if used
            if cbeta.get('assist_sutra_uid'):
                assist_log.write(f"CBETA assist_sutra_uid: {sutra_code} - {cbeta_ref}\n")
                assist_log.write(cmp_txt + "\n\n")

            if not sutra_txt or not cmp_txt:
                print(f"  [skip] {sutra_code} 缺少SX或CBETA文本")
                append_summary_and_continue(summary_rows, sutra_code, sutra_name, author)
                continue

            segments = diff_v2(
                sutra_txt,
                cmp_txt,
                is_base=not_newline_and_pagecode,
                is_cmp=not_punc_and_cbeta_whitespace,
            )

            rows = []
            for seg in segments:
                print(seg)
                rows.append({
                    '序号': seg.get('no', ''),
                    '是否相同': '是' if seg.get('is_same') else '否',
                    '思溪藏 base0': seg.get('base0', ''),
                    'CBETA cmp0': seg.get('cmp0', ''),
                    '思溪藏 base': seg.get('base', ''),
                    'CBETA cmp': seg.get('cmp', ''),
                    '文本长度差异': seg.get('len_diff', 0)
                })

            df = pd.DataFrame(rows)
            out_path = path.join(out_dir, f"{sutra_code}.xlsx")
            # df.to_excel(out_path, index=False)

            large_diff_pages, _ = find_pages_with_large_diff(segments, threshold=1)
            total_len_diff = sum(abs(seg.get('len_diff', 0)) for seg in segments)
            total_pos_len_diff = sum(seg.get('len_diff', 0) for seg in segments if seg.get('len_diff', 0) > 0)
            total_neg_len_diff = sum(seg.get('len_diff', 0) for seg in segments if seg.get('len_diff', 0) < 0)
            summary_rows.append({
                '经号': sutra_code,
                '经名': sutra_name,
                '作译者': author,
                '差异大于50的页码': ', '.join(page.strip('[]') for page in large_diff_pages),
                '总文本长度差异': total_len_diff,
                '正差异': total_pos_len_diff,
                '负差异': total_neg_len_diff,
            })

    assist_log.close()
    summary_df = pd.DataFrame(summary_rows)
    summary_out_path = path.join(out_dir, "sutra_diff_统计报告.xlsx")
    # summary_df.to_excel(summary_out_path, index=False)  

# endregion


def get_js_reel_txt(reel_code, db=None, vdict=None):
    """
    获取JS藏卷文本，自动替换所有v_code为nor_txt
    """
    if db is None:
        db = hlp.get_db('tw-work')
    if vdict is None:
        vdict = load_js_variant_dict()
    txt = get_sx_reel_txt(reel_code, db)
    # 替换所有v_code为nor_txt
    def repl(m):
        code = m.group(0)
        return vdict.get(code, code)
    # 假设v_code格式为v\d+n?
    txt = re.sub(r'v\d+n?', repl, txt)
    return txt

# create an excel file that show the JS sutra code and the corresponding CBETA sutra code, and if there's any assist_sutra_uid used
def export_js_cbeta_sutra_mapping(out_path='./js_cbeta_sutra_mapping.xlsx'):
    db = hlp.get_db('tw-work')
    sutra_sources = list(db.sutra_source.find({'source_type': 'JSZ'}, {'sutra_uid': 1, 'rushi_sutra_uid': 1, 'assist_sutra_uid': 1, '_id': 0}))
    rows = []
    for s in sutra_sources:
        js_uid = s.get('sutra_uid')
        if isinstance(js_uid, list):
            js_uids = js_uid
        else:
            js_uids = [js_uid] if js_uid is not None else []
        js_assist = s.get('assist_sutra_uid')
        cbeta = db.sutra_source.find_one(
            {'rushi_sutra_uid': s.get('rushi_sutra_uid'), 'source_type': 'CBETA'},
            {'sutra_uid': 1, 'assist_sutra_uid': 1, '_id': 0}
        )
        cbeta_uid = cbeta.get('sutra_uid') if cbeta else None
        assist_uid = cbeta.get('assist_sutra_uid') if cbeta else None
        for js in js_uids:
            rows.append({
                'JS sutra_uid': js,
                'JS assist_sutra_uid used': js_assist if js_assist else '-',
                'CBETA sutra_uid': cbeta_uid,
                'CBETA assist_sutra_uid used': assist_uid if assist_uid else '-'
            })
    df = pd.DataFrame(rows)
    df.to_excel(out_path, index=False)


def export_js_cbeta_sutra_mapping(out_path='./js_cbeta_sutra_mapping.xlsx'):
    db = hlp.get_db('tw-work')
    sutra_sources = list(db.sutra_source.find({'source_type': 'JSZ'}, {'sutra_uid': 1, 'rushi_sutra_uid': 1, 'assist_sutra_uid': 1, '_id': 0}))
    rows = []
    for s in sutra_sources:
        js_uid = s.get('sutra_uid')
        if isinstance(js_uid, list):
            js_uids = js_uid
        else:
            js_uids = [js_uid] if js_uid is not None else []
        js_assist = s.get('assist_sutra_uid')
        cbeta = db.sutra_source.find_one(
            {'rushi_sutra_uid': s.get('rushi_sutra_uid'), 'source_type': 'CBETA'},
            {'sutra_uid': 1, 'assist_sutra_uid': 1, '_id': 0}
        )
        cbeta_uid = cbeta.get('sutra_uid') if cbeta else None
        assist_uid = cbeta.get('assist_sutra_uid') if cbeta else None
        for js in js_uids:
            rows.append({
                'JS sutra_uid': js,
                'JS assist_sutra_uid used': js_assist if js_assist else '-',
                'CBETA sutra_uid': cbeta_uid,
                'CBETA assist_sutra_uid used': assist_uid if assist_uid else '-'
            })
    df = pd.DataFrame(rows)
    df.to_excel(out_path, index=False)


def export_js_cbeta_sutra_mapping(out_path='./js_cbeta_sutra_mapping.xlsx'):
    db = hlp.get_db('tw-work')
    sutra_sources = list(db.sutra_source.find({'source_type': 'JSZ'}, {'sutra_uid': 1, 'rushi_sutra_uid': 1, 'assist_sutra_uid': 1, '_id': 0}))
    rows = []
    for s in sutra_sources:
        js_uid = s.get('sutra_uid')
        if isinstance(js_uid, list):
            js_uids = js_uid
        else:
            js_uids = [js_uid] if js_uid is not None else []
        js_assist = s.get('assist_sutra_uid')
        cbeta = db.sutra_source.find_one(
            {'rushi_sutra_uid': s.get('rushi_sutra_uid'), 'source_type': 'CBETA'},
            {'sutra_uid': 1, 'assist_sutra_uid': 1, '_id': 0}
        )
        cbeta_uid = cbeta.get('sutra_uid') if cbeta else None
        assist_uid = cbeta.get('assist_sutra_uid') if cbeta else None
        for js in js_uids:
            rows.append({
                'JS sutra_uid': js,
                'JS assist_sutra_uid used': js_assist if js_assist else '-',
                'CBETA sutra_uid': cbeta_uid,
                'CBETA assist_sutra_uid used': assist_uid if assist_uid else '-'
            })
    df = pd.DataFrame(rows)
    df.to_excel(out_path, index=False)


def export_common_rushi_sutra_uid_pairs(out_path='./data/JSZxYLBZ.json'):
    db = hlp.get_db('tw-prod-readonly')
    """
    Export JSON: [{rushi_sutra_uid, jsz_uid, yl_uid}] for uids present in both JSZ and YLBZ.
    """
    # Get all JSZ and YLBZ entries with their uids
    jsz = list(db.sutra_source.find({'source_type': 'JSZ'}, {'_id': 0, 'rushi_sutra_uid': 1, 'sutra_uid': 1}))
    yl = list(db.sutra_source.find({'source_type': 'YLBZ'}, {'_id': 0, 'rushi_sutra_uid': 1, 'sutra_uid': 1}))

    jsz_map = {d['rushi_sutra_uid']: d.get('sutra_uid') for d in jsz if d.get('rushi_sutra_uid')}
    yl_map = {d['rushi_sutra_uid']: d.get('sutra_uid') for d in yl if d.get('rushi_sutra_uid')}
    # Find common rushi_sutra_uid
    common_uids = set(jsz_map) & set(yl_map)

    result = [
        {
            'rushi_sutra_uid': uid,
            'jsz_uid': jsz_map[uid],
            'yl_uid': yl_map[uid]
        }
        for uid in common_uids
    ]

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'Exported {len(result)} records to {out_path}')


def scan_duplicate_format_cid_in_reels(log_path='./duplicate_format_cid_log.txt'):
    """
    Scan the reel collection for any format.columns with more than one format pointing to the same cid.
    Log the reel_code, page_name, and cid to a text file.
    """
    db = hlp.get_db('tw-work')
    reels = db.reel.find({}, {'reel_code': 1, 'format': 1, '_id': 0})
    out_lines = []
    for reel in reels:
        reel_code = reel.get('reel_code')
        for fmt in reel.get('format', []):
            page_name = fmt.get('name')
            columns = fmt.get('columns', [])
            cid_count = {}
            for col in columns:
                # col is usually [format, cid]
                if len(col) < 2:
                    continue
                cid = col[1]
                cid_count.setdefault(cid, []).append(col[0])
            for cid, fmts in cid_count.items():
                if len(fmts) > 1:
                    out_lines.append(f"{reel_code}\t{page_name}\t{cid}\t{','.join(fmts)}")
    with open(log_path, 'w', encoding='utf-8') as f:
        for line in out_lines:
            f.write(line + '\n')
    print(f"Scan complete. {len(out_lines)} issues found. See {log_path}")

# Usage:
# scan_duplicate_format_cid_in_reels()

def diff_test(out_xlsx='difftest_ori.xlsx'):
    from util.diff import diff_v2, diff
    from util.punc import not_newline_and_pagecode, not_punc_and_cbeta_whitespace

    # Read files
    with open('./data/JS0001_178.txt', 'r', encoding='utf-8') as f:
        txt1 = f.read()
    with open('./JS0001_178_js.txt', 'r', encoding='utf-8') as f:
        txt2 = f.read()

    # Run diff
    segments = diff(
        txt1,
        txt2,
        is_base=not_punc_and_cbeta_whitespace,
        is_cmp=not_newline_and_pagecode,
    )

    # Prepare rows for DataFrame
    rows = []
    for seg in segments:
        rows.append({
            '序号': seg.get('no', ''),
            '是否相同': '是' if seg.get('is_same') else '否',
            'base0': seg.get('base0', ''),
            'cmp0': seg.get('cmp0', ''),
            'base': seg.get('base', ''),
            'cmp': seg.get('cmp', ''),
            '文本长度差异': seg.get('len_diff', 0)
        })

    # Save to Excel
    df = pd.DataFrame(rows)
    df.to_excel(out_xlsx, index=False)
    print(f"Diff result saved to {out_xlsx}")


def export_diff_jiazhu_txt(out_dir='./data/jiazhu_diff_0205'):
    jiazhu_map = './data/JSZxYLBZ.json'
    db = hlp.get_db('tw-prod-readonly')
    os.makedirs(out_dir, exist_ok=True)

    with open(jiazhu_map, 'r', encoding='utf-8') as f:
        records = json.load(f)
    
    summary_rows = []
    for rec in records:
        jsz_sutracode = rec.get('jsz_uid')
        yl_sutracode = rec.get('yl_uid')
        # if not jsz_sutracode == 'JS1302':
        #     continue
        if not jsz_sutracode or not yl_sutracode:
            continue

        jsz_list = jsz_sutracode if isinstance(jsz_sutracode, list) else [jsz_sutracode]
        yl_list = yl_sutracode if isinstance(yl_sutracode, list) else [yl_sutracode]

        for jsz_code in jsz_list:
            for yl_code in yl_list:
                print(f"Processing JSZ: {jsz_code} and YLBZ: {yl_code} ...")

                js_sutra = db.sutra.find_one(
                    {'sutra_code': jsz_code},
                    {'sutra_name': 1, 'author': 1}
                )
                if js_sutra:
                    js_sutra_name = js_sutra.get('sutra_name', '')
                    js_author = js_sutra.get('author', '')
                else:
                    js_sutra_name = ''
                    js_author = ''

                jsz_reels = list(db.reel.find({'sutra_code': jsz_code}, {'reel_code': 1, 'reel_type': 1, '_id': 0}))
                jsz_reels = [r for r in jsz_reels if r.get('reel_type') != '空卷']
                jsz_reels.sort(key=lambda x: hlp.align_reel_code(x['reel_code']))

                yl_reels = list(db.reel.find({'sutra_code': yl_code}, {'reel_code': 1, 'reel_type': 1, '_id': 0}))
                yl_reels = [r for r in yl_reels if r.get('reel_type') != '空卷']
                yl_reels.sort(key=lambda x: hlp.align_reel_code(x['reel_code']))

                jsz_jiazhu_txt = ''
                for rl in jsz_reels:
                    reel_code = rl['reel_code']
                    txt = get_jiazhu_txt(reel_code, db)
                    if txt:
                        jsz_jiazhu_txt += txt + '\n'

                yl_jiazhu_txt = ''
                for rl in yl_reels:
                    reel_code = rl['reel_code']
                    txt = get_jiazhu_txt(reel_code, db)
                    if txt:
                        yl_jiazhu_txt += txt + '\n'

                if not jsz_jiazhu_txt or not yl_jiazhu_txt:
                    remark = []
                    if not jsz_jiazhu_txt:
                        remark.append('JSZ缺少jiazhu_txt')
                    if not yl_jiazhu_txt:
                        remark.append('YLBZ缺少jiazhu_txt')
                    summary_rows.append({
                        'JSZ经号': jsz_code,
                        'YLBZ经号': yl_code,
                        '经名': js_sutra_name,
                        '作译者': js_author,
                        '差异大于50的页码': '',
                        '总文本长度差异': '',
                        '正差异': '',
                        '负差异': '',
                        '备注': '; '.join(remark),
                    })
                    continue

                segments = diff_v2(
                    jsz_jiazhu_txt,
                    yl_jiazhu_txt,
                    is_base=not_newline_and_pagecode,
                    is_cmp=not_newline_and_pagecode
                )

                rows = []
                for seg in segments:
                    rows.append({
                        '序号': seg.get('no', ''),
                        '是否相同': '是' if seg.get('is_same') else '否',
                        'JSZ jiazhu': seg.get('base0', ''),
                        'YLBZ jiazhu': seg.get('cmp0', ''),
                        '文本长度差异': seg.get('len_diff', 0)
                    })
                
                df = pd.DataFrame(rows)
                out_path = path.join(out_dir, f"{jsz_code}_{yl_code}.xlsx")
                df.to_excel(out_path, index=False)

                reels, pages, cols, mapping = find_pages_with_large_diff(segments, threshold=1)
                total_len_diff = sum(abs(seg.get('len_diff', 0)) for seg in segments)
                total_pos_len_diff = sum(seg.get('len_diff', 0) for seg in segments if seg.get('len_diff', 0) > 0)
                total_neg_len_diff = sum(seg.get('len_diff', 0) for seg in segments if seg.get('len_diff', 0) < 0)
                summary_rows.append({
                    'JSZ经号': jsz_code,
                    'YLBZ经号': yl_code,
                    '经名': js_sutra_name,
                    '作译者': js_author,
                    '差异卷码': '\n'.join(reel.strip() for reel in reels),
                    '差异页码': '\n'.join(page.strip('[]') for page in pages),
                    '差异列码': '\n'.join(col.strip('[]') for col in cols),
                    '总文本长度差异': total_len_diff,
                    '正差异': total_pos_len_diff,
                    '负差异': total_neg_len_diff,
                    '备注': '',
                })

    summary_df = pd.DataFrame(summary_rows)
    summary_out_path = path.join(out_dir, "jiazhu_diff_统计报告.xlsx")
    summary_df.to_excel(summary_out_path, index=False)

def get_yinshi_txt(reel_code, db=None, vdict=None):
    """
    Get phonetic/explanatory text for a reel.
    - If reel_type is '音释': Returns all text (excluding 'is_center' columns).
    - Otherwise: Returns only format 'E'.
    """
    import helper as hlp
    if db is None:
        db = hlp.get_db('tw-prod-readonly')
    if vdict is None:
        vdict = load_js_variant_dict()

    reel = db.reel.find_one({'reel_code': reel_code})
    if not reel:
        print(f"Reel not found: {reel_code}")
        return ''
    
    reel_type = reel.get('reel_type')
    if reel_type in ['空卷', '音释（缺）']:
        print(f"Reel is empty or missing: {reel_code}")
        return ''

    is_pure_yinshi = (reel_type == '音释')
    
    page_col_formats = {}
    page_char_formats = {}

    # Only look up format markers if it's NOT a 'pure' yinshi reel
    if not is_pure_yinshi:
        for fmt in hlp.prop(reel, 'format', []):
            page_name = fmt.get('name')
            columns = fmt.get('columns', [])
            chars = fmt.get('chars', [])

            # For non-pure reels, we only want format 'E'
            col_filtered = [col[1] for col in columns if col[0] == 'E']
            char_filtered = [(ch[2], ch[3]) for ch in chars if ch[0] == 'E']

            if col_filtered:
                page_col_formats[page_name] = set(col_filtered)
            if char_filtered:
                page_char_formats[page_name] = char_filtered

    cond = get_page_select_cond(reel)
    pages = list(db.page.find(cond, {'name': 1, 'chars': 1, 'columns': 1}))
    pages.sort(key=lambda x: hlp.align_code(x['name']))

    page_txts = []
    for page in pages:
        page_name = page['name']
        page_cols = page.get('columns', [])
        
        # 1. Determine which column IDs to include
        if is_pure_yinshi:
            # For pure yinshi, include every column that isn't central (is_center)
            target_col_ids = {c['column_id'] for c in page_cols if not c.get('is_center') and not c.get('deleted')}
            target_char_ranges = []
        else:
            # Otherwise, use the mapped 'E' format column/char IDs
            target_col_ids = set()
            if page_name in page_col_formats:
                fmt_col_cids = page_col_formats[page_name]
                for col in page_cols:
                    if col.get('cid') in fmt_col_cids:
                        target_col_ids.add(col.get('column_id'))
            target_char_ranges = page_char_formats.get(page_name, [])

        # 2. Extract characters for those columns
        col_dict = {}
        for char in page.get('chars', []):
            if char.get('deleted'):
                continue
            
            char_id = char.get('char_id')
            if not char_id:
                continue
                
            c_column_id = char_id.rsplit('c', 1)[0]
            
            # Inclusion check
            in_fmt = (c_column_id in target_col_ids)
            if not in_fmt and target_char_ranges:
                char_cid = char.get('cid')
                for start_cid, end_cid in target_char_ranges:
                    if start_cid <= char_cid <= end_cid:
                        in_fmt = True
                        break
            
            if in_fmt:
                txt = char.get('txt', '■')
                if txt in vdict:
                    txt = vdict[txt]
                col_dict.setdefault(c_column_id, []).append(txt)

        if col_dict:
            for col_id in sorted(col_dict.keys(), key=col_sort_key):
                line = ''.join(col_dict[col_id])
                page_txts.append(line)
    
    return '\n'.join(page_txts)

def get_std_reel_txt(reel_uid, db=None, vdict=None):
    """
    获取JS藏卷文本，自动替换所有v_code为nor_txt
    """
    if db is None:
        db = hlp.get_db('tr-prod-readonly')
    if vdict is None:
        vdict = load_js_variant_dict()
    txt = get_std_reel_txt_0506(reel_uid, db)
    # 替换所有v_code为nor_txt
    def repl(m):
        code = m.group(0)
        return vdict.get(code, code)
    # 假设v_code格式为v\d+n?
    txt = re.sub(r'v\d+n?', repl, txt)
    return txt

def load_tw_format_map(path='./data/js_tw_format_map_0502.json'):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f).get('reels', {})

def get_std_reel_txt_v2(uid, db=None, vdict=None, tw_format_map=None):
    """
    获取思溪藏卷文本（每页带页编码，拼接chars，过滤deleted和is_center，按列断行）
    """
    import helper as hlp
    if db is None:
        db = hlp.get_db('tr-prod-readonly')
    if vdict is None:
        vdict = load_js_variant_dict()
    if tw_format_map is None:
        tw_format_map = load_tw_format_map()

    reel = db.reel.find_one({'uid': uid})
    if not reel:
        print(f"Reel not found: {uid}")
        return ''

    reel_format_override = tw_format_map.get(uid, {})
    all_txt = []
    pending_state = None
    pending_parts = []

    def flush_pending_segment():
        nonlocal pending_state, pending_parts
        if not pending_parts:
            return
        seg = ''.join(pending_parts)
        if seg:
            all_txt.append(f'【{seg}】' if pending_state else seg)
        pending_state = None
        pending_parts = []

    def append_segment(text, is_d):
        nonlocal pending_state, pending_parts
        if not text:
            return

        if pending_state is None:
            pending_state = is_d
            pending_parts = [text]
            return

        if pending_state == is_d:
            pending_parts.append(text)
        else:
            flush_pending_segment()
            pending_state = is_d
            pending_parts = [text]

    pages = hlp.prop(reel, 'pages', [])
    for page in pages:
        page_name = hlp.prop(page, 'ouid')
        page_override = hlp.prop(reel_format_override, f'pages.{page_name}', {})

        blocks = hlp.prop(page, 'blocks', '')
        for blk in blocks:
            columns = hlp.prop(blk, 'columns', [])
            for col in columns:
                std_txt = hlp.prop(col, 'std_txt', '').replace('\n', '').replace('\r', '')
                char_cids = hlp.expand_nums(hlp.prop(col, 'char_cids', []))
                col_cid = hlp.prop(col, 'col_cid')
                col_format = hlp.prop(col, 'col_format', '')
                char_format = hlp.prop(col, 'char_format', [])
                kan_chars = hlp.prop(col, 'kan_chars', [])
                
                if col_cid is not None:
                    col_format = hlp.prop(page_override, f'columns.{col_cid}', col_format)
                    char_format = hlp.prop(page_override, f'chars_by_col.{col_cid}', char_format)

                PUNC_TO_FILTER = '。？！，、；：“”‘’「」『』﹃﹄﹁﹂《》〈〉［］〔〕【】——……－～．'
                FORMAT_FILTER = ['J','L','H1','H2','H3','H4','H5','E', 'C', 'G', 'K', 'SZ', 'PZ', 'I', 'W','P']
                CHAR_FORMAT_FILTER = ['J','L','H1','H2','H3','H4','H5','T', 'E', 'C', 'K', 'PZ', 'P']

                if col_format in FORMAT_FILTER:
                    continue

                cids_to_filter = set()
                d_cids = set()
                for fmt, start, end in char_format:
                    if fmt in CHAR_FORMAT_FILTER:
                        # Add all CIDs in this range to our skip set
                        cids_to_filter.update(range(start, end + 1))
                    if fmt == 'D':
                        d_cids.update(range(start, end + 1))

                txt_list = list(std_txt)
                indices_to_delete = set()
                d_indices = set()

                char_ptr = 0
                for i, char in enumerate(txt_list):
                    if char in PUNC_STR:
                        continue
                    
                    if char_ptr < len(char_cids):
                        current_cid = char_cids[char_ptr]
                        
                        # A. Check if this character should be replaced by a kan_char
                        for kan in kan_chars:
                            if kan.get('cid') == current_cid:
                                txt_list[i] = kan.get('kstd_txt') or '■'
                        
                        # B. Check if this character should be filtered out
                        if current_cid in cids_to_filter:
                            indices_to_delete.add(i)

                        if current_cid in d_cids:
                            d_indices.add(i)
                    
                    char_ptr += 1

                filtered_items = [
                    (i, char) for i, char in enumerate(txt_list)
                    if i not in indices_to_delete and char not in PUNC_TO_FILTER
                ]

                if col_format == 'D':
                    final_col_txt = ''.join(char for _, char in filtered_items)
                    append_segment(final_col_txt, True)
                    continue

                chunk = []
                in_d = None

                for i, char in filtered_items:
                    char_is_d = i in d_indices
                    if chunk and char_is_d != in_d:
                        append_segment(''.join(chunk), in_d)
                        chunk = []
                    chunk.append(char)
                    in_d = char_is_d

                if chunk:
                    append_segment(''.join(chunk), in_d)

    flush_pending_segment()
    return ''.join(all_txt).replace('\n', '').replace('\r', '')

js_list = ["JS1481",
"JS1482",
"JS1485",
"JS1486",
"JS1487",
"JS1503",
"JS1610",
"JS1611",
"JS1612",
"JS1613",
"JS1614",
"JS2330",
"JS2331",
"JS2332"
]

def export_tw_format_map_for_js_list(out_path='./data/js_tw_format_map_0502.json'):
    tw_db = hlp.get_db('tw-prod-readonly')
    tr_db = hlp.get_db('tr-prod-readonly')

    format_map = {}
    missing = []

    for sutra_uid in js_list:
        tr_reels = list(tr_db.reel.find(
            {'sutra_uid': sutra_uid},
            {'uid': 1, 'sn': 1, 'name': 1, '_id': 0}
        ))
        tr_by_reel_no = {
            str(r.get('sn')): r.get('uid')
            for r in tr_reels
            if r.get('uid') is not None and r.get('sn') is not None
        }

        tw_reels = list(tw_db.reel.find(
            {'sutra_code': sutra_uid},
            {'reel_code': 1, 'reel_no': 1, 'format': 1, '_id': 0}
        ))

        for tw_reel in tw_reels:
            reel_no = str(tw_reel.get('reel_no'))
            tr_uid = tr_by_reel_no.get(reel_no)

            if not tr_uid:
                missing.append({
                    'sutra_uid': sutra_uid,
                    'reel_no': reel_no,
                    'tw_reel_code': tw_reel.get('reel_code'),
                })
                continue

            page_map = {}
            for page_fmt in tw_reel.get('format') or []:
                page_name = page_fmt.get('name')
                if not page_name:
                    continue

                col_map = {}
                for fmt, cid in page_fmt.get('columns') or []:
                    col_map[str(cid)] = fmt

                char_map = {}
                for fmt, col_cid, start_cid, end_cid in page_fmt.get('chars') or []:
                    key = str(col_cid)
                    char_map.setdefault(key, []).append([fmt, start_cid, end_cid])

                page_map[page_name] = {
                    'columns': col_map,
                    'chars_by_col': char_map,
                }

            format_map[tr_uid] = {
                'sutra_uid': sutra_uid,
                'reel_no': reel_no,
                'tw_reel_code': tw_reel.get('reel_code'),
                'pages': page_map,
            }

    payload = {
        'reels': format_map,
        'missing': missing,
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f'exported {len(format_map)} reels to {out_path}')
    if missing:
        print(f'missing matches: {len(missing)}')



def get_std_reel_txt_v3(uid, db=None, vdict=None): # 禅宗文本
    """
    获取思溪藏卷文本（每页带页编码，拼接chars，过滤deleted和is_center，按列断行）
    """
    import helper as hlp
    if db is None:
        db = hlp.get_db('tr-prod-readonly')
    if vdict is None:
        vdict = load_js_variant_dict()
    reel = db.reel.find_one({'uid': uid})
    if not reel:
        print(f"Reel not found: {uid}")
        return ''

    all_txt = []
    pages = hlp.prop(reel, 'pages', [])
    for page in pages:
        blocks = hlp.prop(page, 'blocks', '')
        for blk in blocks:
            columns = hlp.prop(blk, 'columns', [])
            for col in columns:
                std_txt = hlp.prop(col, 'std_txt', '')
                char_cids = hlp.expand_nums(hlp.prop(col, 'char_cids', []))
                col_format = hlp.prop(col, 'col_format', '')
                char_format = hlp.prop(col, 'char_format', [])
                kan_chars = hlp.prop(col, 'kan_chars', [])

                PUNC_TO_FILTER = '。？！，、；：“”‘’「」『』﹃﹄﹁﹂《》〈〉［］〔〕【】——……－～．'
                FORMAT_FILTER = ['E', 'C', 'G', 'M', 'P', 'K', 'SZ', 'PZ', 'I', "W"]
                CHAR_FORMAT_FILTER = ['T', 'E', 'C', 'P', 'K', 'PZ', 'M']

                if col_format in FORMAT_FILTER:
                    continue

                cids_to_filter = set()
                for fmt, start, end in char_format:
                    if fmt in CHAR_FORMAT_FILTER:
                        # Add all CIDs in this range to our skip set
                        cids_to_filter.update(range(start, end + 1))

                txt_list = list(std_txt)
                indices_to_delete = set()

                char_ptr = 0
                for i, char in enumerate(txt_list):
                    if char in PUNC_STR:
                        continue
                    
                    if char_ptr < len(char_cids):
                        current_cid = char_cids[char_ptr]
                        
                        # A. Check if this character should be replaced by a kan_char
                        for kan in kan_chars:
                            if kan.get('cid') == current_cid:
                                txt_list[i] = kan.get('kstd_txt') or '■'
                        
                        # B. Check if this character should be filtered out
                        if current_cid in cids_to_filter:
                            indices_to_delete.add(i)
                    
                    char_ptr += 1

                final_col_txt = ''.join([
                    char for i, char in enumerate(txt_list) 
                    if i not in indices_to_delete and char not in PUNC_TO_FILTER
                ])
                all_txt.append(final_col_txt)

    return ''.join(all_txt) 


def get_std_reel_txt_v4(uid, db=None, vdict=None): # 禅宗文本
    """
    获取思溪藏卷文本（每页带页编码，拼接chars，过滤deleted和is_center，按列断行）
    对 J/L/H1-H5/A/Y 格式加 {}，并按格式分别合并连续片段。
    """
    import helper as hlp
    if db is None:
        db = hlp.get_db('tr-prod-readonly')
    if vdict is None:
        vdict = load_js_variant_dict()
    reel = db.reel.find_one({'uid': uid})
    if not reel:
        print(f"Reel not found: {uid}")
        return ''

    all_txt = []
    pending_format = None
    pending_parts = []

    def flush_pending_segment():
        nonlocal pending_format, pending_parts
        if not pending_parts:
            return
        seg = ''.join(pending_parts)
        if seg:
            if pending_format == 'N':
                all_txt.append(f'({seg})')
            else:
                all_txt.append(f'{{{seg}}}' if pending_format else seg)
        pending_format = None
        pending_parts = []

    def append_segment(text, fmt):
        nonlocal pending_format, pending_parts
        if not text:
            return

        if pending_format is None and not pending_parts:
            pending_format = fmt
            pending_parts = [text]
            return

        if pending_format == fmt:
            pending_parts.append(text)
        else:
            flush_pending_segment()
            pending_format = fmt
            pending_parts = [text]

    pages = hlp.prop(reel, 'pages', [])
    for page in pages:
        blocks = hlp.prop(page, 'blocks', '')
        for blk in blocks:
            columns = hlp.prop(blk, 'columns', [])
            for col in columns:
                std_txt = hlp.prop(col, 'std_txt', '').replace('\n', '').replace('\r', '')
                char_cids = hlp.expand_nums(hlp.prop(col, 'char_cids', []))
                col_format = hlp.prop(col, 'col_format', '')
                char_format = hlp.prop(col, 'char_format', [])
                kan_chars = hlp.prop(col, 'kan_chars', [])

                PUNC_TO_FILTER = '。？！，、；：“”‘’「」『』﹃﹄﹁﹂《》〈〉［］〔〕（）()【】——……－～．'
                FORMAT_FILTER = ['E', 'C', 'K', 'G', 'M', 'SZ', 'PZ', 'I', 'W']
                CHAR_FORMAT_FILTER = ['T', 'E', 'C', 'K', 'PZ', 'M']
                WRAP_FORMATS = ['J', 'L', 'H1', 'H2', 'H3', 'H4', 'H5', 'A', 'Y', 'N']

                if col_format in FORMAT_FILTER:
                    continue

                cids_to_filter = set()
                wrap_cid_to_format = {}

                for fmt, start, end in char_format:
                    if fmt in CHAR_FORMAT_FILTER:
                        cids_to_filter.update(range(start, end + 1))
                    if fmt in WRAP_FORMATS:
                        for cid in range(start, end + 1):
                            wrap_cid_to_format[cid] = fmt

                txt_list = list(std_txt)
                indices_to_delete = set()
                index_to_wrap_format = {}

                char_ptr = 0
                for i, char in enumerate(txt_list):
                    if char in PUNC_STR:
                        continue

                    if char_ptr < len(char_cids):
                        current_cid = char_cids[char_ptr]

                        for kan in kan_chars:
                            if kan.get('cid') == current_cid:
                                txt_list[i] = kan.get('kstd_txt') or '■'

                        if current_cid in cids_to_filter:
                            indices_to_delete.add(i)

                        wrap_fmt = wrap_cid_to_format.get(current_cid)
                        if wrap_fmt:
                            index_to_wrap_format[i] = wrap_fmt

                    char_ptr += 1

                filtered_items = [
                    (i, char) for i, char in enumerate(txt_list)
                    if i not in indices_to_delete and char not in PUNC_TO_FILTER
                ]

                if not filtered_items:
                    continue

                if col_format in WRAP_FORMATS:
                    final_col_txt = ''.join(char for _, char in filtered_items)
                    append_segment(final_col_txt, col_format)
                    continue

                chunk = []
                current_fmt = None

                for i, char in filtered_items:
                    char_fmt = index_to_wrap_format.get(i)

                    if chunk and char_fmt != current_fmt:
                        append_segment(''.join(chunk), current_fmt)
                        chunk = []

                    chunk.append(char)
                    current_fmt = char_fmt

                if chunk:
                    append_segment(''.join(chunk), current_fmt)

    flush_pending_segment()
    return ''.join(all_txt).replace('\n', '').replace('\r', '')


def get_std_reel_txt_v5(uid, db=None, vdict=None): # 禅宗文本
    """
    获取思溪藏卷文本（每页带页编码，拼接chars，过滤deleted和is_center，按列断行）
    对 D 格式加 【】，并按格式分别合并连续片段。
    """
    import helper as hlp
    if db is None:
        db = hlp.get_db('tr-prod-readonly')
    if vdict is None:
        vdict = load_js_variant_dict()
    reel = db.reel.find_one({'uid': uid})
    if not reel:
        print(f"Reel not found: {uid}")
        return ''

    all_txt = []
    pending_format = None
    pending_parts = []

    def flush_pending_segment():
        nonlocal pending_format, pending_parts
        if not pending_parts:
            return
        seg = ''.join(pending_parts)
        if seg:
            all_txt.append(f'【{seg}】' if pending_format else seg)
        pending_format = None
        pending_parts = []

    def append_segment(text, fmt):
        nonlocal pending_format, pending_parts
        if not text:
            return

        if pending_format is None and not pending_parts:
            pending_format = fmt
            pending_parts = [text]
            return

        if pending_format == fmt:
            pending_parts.append(text)
        else:
            flush_pending_segment()
            pending_format = fmt
            pending_parts = [text]

    pages = hlp.prop(reel, 'pages', [])
    for page in pages:
        blocks = hlp.prop(page, 'blocks', '')
        for blk in blocks:
            columns = hlp.prop(blk, 'columns', [])
            for col in columns:
                std_txt = hlp.prop(col, 'std_txt', '').replace('\n', '').replace('\r', '')
                char_cids = hlp.expand_nums(hlp.prop(col, 'char_cids', []))
                col_format = hlp.prop(col, 'col_format', '')
                char_format = hlp.prop(col, 'char_format', [])
                kan_chars = hlp.prop(col, 'kan_chars', [])

                PUNC_TO_FILTER = '。？！，、；：“”‘’「」『』﹃﹄﹁﹂《》〈〉［］〔〕【】——……－～．'
                FORMAT_FILTER = ['E', 'C', 'K', 'G', 'M', 'SZ', 'PZ', 'I', 'W']
                CHAR_FORMAT_FILTER = ['T', 'E', 'C', 'K', 'PZ', 'M']
                WRAP_FORMATS = ['D']

                if col_format in FORMAT_FILTER:
                    continue

                cids_to_filter = set()
                wrap_cid_to_format = {}

                for fmt, start, end in char_format:
                    if fmt in CHAR_FORMAT_FILTER:
                        cids_to_filter.update(range(start, end + 1))
                    if fmt in WRAP_FORMATS:
                        for cid in range(start, end + 1):
                            wrap_cid_to_format[cid] = fmt

                txt_list = list(std_txt)
                indices_to_delete = set()
                index_to_wrap_format = {}

                char_ptr = 0
                for i, char in enumerate(txt_list):
                    if char in PUNC_STR:
                        continue

                    if char_ptr < len(char_cids):
                        current_cid = char_cids[char_ptr]

                        for kan in kan_chars:
                            if kan.get('cid') == current_cid:
                                txt_list[i] = kan.get('kstd_txt') or '■'

                        if current_cid in cids_to_filter:
                            indices_to_delete.add(i)

                        wrap_fmt = wrap_cid_to_format.get(current_cid)
                        if wrap_fmt:
                            index_to_wrap_format[i] = wrap_fmt

                    char_ptr += 1

                filtered_items = [
                    (i, char) for i, char in enumerate(txt_list)
                    if i not in indices_to_delete and char not in PUNC_TO_FILTER
                ]

                if not filtered_items:
                    continue

                if col_format in WRAP_FORMATS:
                    final_col_txt = ''.join(char for _, char in filtered_items)
                    append_segment(final_col_txt, col_format)
                    continue

                chunk = []
                current_fmt = None

                for i, char in filtered_items:
                    char_fmt = index_to_wrap_format.get(i)

                    if chunk and char_fmt != current_fmt:
                        append_segment(''.join(chunk), current_fmt)
                        chunk = []

                    chunk.append(char)
                    current_fmt = char_fmt

                if chunk:
                    append_segment(''.join(chunk), current_fmt)

    flush_pending_segment()
    return ''.join(all_txt).replace('\n', '').replace('\r', '')


def get_std_reel_txt_v6(uid, db=None, vdict=None, tw_format_map=None): # 禅宗文本
    import helper as hlp
    if db is None:
        db = hlp.get_db('tr-prod-readonly')
    if vdict is None:
        vdict = load_js_variant_dict()
    if tw_format_map is None:
        tw_format_map = load_tw_format_map()

    reel = db.reel.find_one({'uid': uid})
    if not reel:
        print(f"Reel not found: {uid}")
        return ''

    reel_format_override = tw_format_map.get(uid, {})
    all_txt = []
    pending_format = None
    pending_parts = []

    def flush_pending_segment():
        nonlocal pending_format, pending_parts
        if not pending_parts:
            return
        seg = ''.join(pending_parts)
        if seg:
            all_txt.append(f'【{seg}】' if pending_format else seg)
        pending_format = None
        pending_parts = []

    def append_segment(text, fmt):
        nonlocal pending_format, pending_parts
        if not text:
            return
        if pending_format is None and not pending_parts:
            pending_format = fmt
            pending_parts = [text]
            return
        if pending_format == fmt:
            pending_parts.append(text)
        else:
            flush_pending_segment()
            pending_format = fmt
            pending_parts = [text]

    pages = hlp.prop(reel, 'pages', [])
    for page in pages:
        page_name = hlp.prop(page, 'ouid')
        page_override = hlp.prop(reel_format_override, f'pages.{page_name}', {})

        blocks = hlp.prop(page, 'blocks', '')
        for blk in blocks:
            columns = hlp.prop(blk, 'columns', [])
            for col in columns:
                std_txt = hlp.prop(col, 'std_txt', '').replace('\n', '').replace('\r', '')
                char_cids = hlp.expand_nums(hlp.prop(col, 'char_cids', []))
                col_cid = hlp.prop(col, 'col_cid')
                col_format = hlp.prop(col, 'col_format', '')
                char_format = hlp.prop(col, 'char_format', [])
                kan_chars = hlp.prop(col, 'kan_chars', [])

                if col_cid is not None:
                    col_format = hlp.prop(page_override, f'columns.{col_cid}', col_format)
                    char_format = hlp.prop(page_override, f'chars_by_col.{col_cid}', char_format)

                PUNC_TO_FILTER = '。？！，、；：“”‘’「」『』﹃﹄﹁﹂《》〈〉［］〔〕【】——……－～．'
                FORMAT_FILTER = ['E', 'C', 'K', 'G', 'M', 'SZ', 'PZ', 'I', 'W']
                CHAR_FORMAT_FILTER = ['T', 'E', 'C', 'K', 'PZ', 'M']
                WRAP_FORMATS = ['D']

                if col_format in FORMAT_FILTER:
                    continue

                cids_to_filter = set()
                wrap_cid_to_format = {}

                for fmt, start, end in char_format:
                    if fmt in CHAR_FORMAT_FILTER:
                        cids_to_filter.update(range(start, end + 1))
                    if fmt in WRAP_FORMATS:
                        for cid in range(start, end + 1):
                            wrap_cid_to_format[cid] = fmt

                txt_list = list(std_txt)
                indices_to_delete = set()
                index_to_wrap_format = {}

                char_ptr = 0
                for i, char in enumerate(txt_list):
                    if char in PUNC_STR:
                        continue

                    if char_ptr < len(char_cids):
                        current_cid = char_cids[char_ptr]

                        for kan in kan_chars:
                            if kan.get('cid') == current_cid:
                                txt_list[i] = kan.get('kstd_txt') or '■'

                        if current_cid in cids_to_filter:
                            indices_to_delete.add(i)

                        wrap_fmt = wrap_cid_to_format.get(current_cid)
                        if wrap_fmt:
                            index_to_wrap_format[i] = wrap_fmt

                    char_ptr += 1

                filtered_items = [
                    (i, char) for i, char in enumerate(txt_list)
                    if i not in indices_to_delete and char not in PUNC_TO_FILTER
                ]

                if not filtered_items:
                    continue

                if col_format in WRAP_FORMATS:
                    final_col_txt = ''.join(char for _, char in filtered_items)
                    append_segment(final_col_txt, col_format)
                    continue

                chunk = []
                current_fmt = None

                for i, char in filtered_items:
                    char_fmt = index_to_wrap_format.get(i)
                    if chunk and char_fmt != current_fmt:
                        append_segment(''.join(chunk), current_fmt)
                        chunk = []
                    chunk.append(char)
                    current_fmt = char_fmt

                if chunk:
                    append_segment(''.join(chunk), current_fmt)

    flush_pending_segment()
    return ''.join(all_txt).replace('\n', '').replace('\r', '')
    

def get_std_reel_txt_0506(uid, db=None, vdict=None): # 0506目录文本处理
    """
    获取思溪藏卷文本（每页带页编码，拼接chars，过滤deleted和is_center，按列断行）
    对 J/L/H1-H5/A/Y 格式加 {}，并按格式分别合并连续片段。
    """
    import helper as hlp
    if db is None:
        db = hlp.get_db('tr-prod-readonly')
    if vdict is None:
        vdict = load_js_variant_dict()
    reel = db.reel.find_one({'uid': uid})
    if not reel:
        print(f"Reel not found: {uid}")
        return ''

    all_txt = []
    pending_format = None
    pending_parts = []

    def flush_pending_segment():
        nonlocal pending_format, pending_parts
        if not pending_parts:
            return
        seg = ''.join(pending_parts)
        if seg:
            if pending_format == 'N':
                all_txt.append(f'({seg})')
            else:
                all_txt.append(f'{{{seg}}}' if pending_format else seg)
        pending_format = None
        pending_parts = []

    def append_segment(text, fmt):
        nonlocal pending_format, pending_parts
        if not text:
            return

        if pending_format is None and not pending_parts:
            pending_format = fmt
            pending_parts = [text]
            return

        if pending_format == fmt:
            pending_parts.append(text)
        else:
            flush_pending_segment()
            pending_format = fmt
            pending_parts = [text]

    pages = hlp.prop(reel, 'pages', [])
    for page in pages:
        blocks = hlp.prop(page, 'blocks', '')
        for blk in blocks:
            columns = hlp.prop(blk, 'columns', [])
            for col in columns:
                std_txt = hlp.prop(col, 'std_txt', '').replace('\n', '').replace('\r', '')
                char_cids = hlp.expand_nums(hlp.prop(col, 'char_cids', []))
                col_format = hlp.prop(col, 'col_format', '')
                char_format = hlp.prop(col, 'char_format', [])
                kan_chars = hlp.prop(col, 'kan_chars', [])

                #
                PUNC_TO_FILTER = '。？！，、；：“”‘’「」『』﹃﹄﹁﹂《》〈〉［］〔〕（）()【】——……－～．'
                FORMAT_FILTER = [
                    'E', #音释
                    'C', #校讹
                    'K', #刊记
                    'G', #版心列
                    'SZ', #栏上注
                    'PZ', #旁注
                    'I', #图片名
                    'W', #图中文
                    'P', #科判
                    'J', #经卷名
                    'L', #尾题
                    'H1','H2','H3','H4','H5', #各级标题
                    ] 
                CHAR_FORMAT_FILTER = [
                    'T', #千字文
                    'E', #音释
                    'C', #校讹
                    'K', #刊记
                    'PZ', #旁注
                    'J', #经卷名
                    'L', #尾题
                    'H1','H2','H3','H4','H5', #各级标题
                    ]
                WRAP_FORMATS = ['N']

                if col_format in FORMAT_FILTER:
                    continue

                cids_to_filter = set()
                wrap_cid_to_format = {}

                for fmt, start, end in char_format:
                    if fmt in CHAR_FORMAT_FILTER:
                        cids_to_filter.update(range(start, end + 1))
                    if fmt in WRAP_FORMATS:
                        for cid in range(start, end + 1):
                            wrap_cid_to_format[cid] = fmt

                txt_list = list(std_txt)
                indices_to_delete = set()
                index_to_wrap_format = {}

                char_ptr = 0
                for i, char in enumerate(txt_list):
                    if char in PUNC_STR:
                        continue

                    if char_ptr < len(char_cids):
                        current_cid = char_cids[char_ptr]

                        for kan in kan_chars:
                            if kan.get('cid') == current_cid:
                                txt_list[i] = kan.get('kstd_txt') or '■'

                        if current_cid in cids_to_filter:
                            indices_to_delete.add(i)

                        wrap_fmt = wrap_cid_to_format.get(current_cid)
                        if wrap_fmt:
                            index_to_wrap_format[i] = wrap_fmt

                    char_ptr += 1

                filtered_items = [
                    (i, char) for i, char in enumerate(txt_list)
                    if i not in indices_to_delete and char not in PUNC_TO_FILTER
                ]

                if not filtered_items:
                    continue

                if col_format in WRAP_FORMATS:
                    final_col_txt = ''.join(char for _, char in filtered_items)
                    append_segment(final_col_txt, col_format)
                    continue

                chunk = []
                current_fmt = None

                for i, char in filtered_items:
                    char_fmt = index_to_wrap_format.get(i)

                    if chunk and char_fmt != current_fmt:
                        append_segment(''.join(chunk), current_fmt)
                        chunk = []

                    chunk.append(char)
                    current_fmt = char_fmt

                if chunk:
                    append_segment(''.join(chunk), current_fmt)

    flush_pending_segment()
    return ''.join(all_txt).replace('\n', '').replace('\r', '')


def export_js_std_txt_0506():
    db_work = hlp.get_db('tr-prod-readonly')
    output_root = './data/JS_std_reel_txt_0506_v2'
    for sutra_code in js_list:
        # if sutra_code != 'JS2008':
        #     continue
        reels = list(db_work.reel.find({'sutra_uid': sutra_code}, {'uid': 1, '_id': 0}))
        reels.sort(key=lambda x: hlp.align_reel_code(x['uid']))

        for rl in reels:
            reel_code = rl['uid']
            print(f"Processing {reel_code} ...")
            std_txt = get_std_reel_txt(reel_code, db_work)
            out_path = os.path.join(output_root, f"{reel_code}.txt")
            os.makedirs(output_root, exist_ok=True)
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(std_txt)
            print(f"Exported {reel_code} to {out_path}")


bd_ids = [
    "JS1840_003","JS2078_001","JS1831_001","JS2161_004","JS2161_029","JS1831_005","JS1831_004",
    "JS2168_002","JS1852_006","JS1851_009","JS2278_005","JS2183_001x1","JS1831_002","JS2162_003",
    "JS1840_002","JS2164_001x1","JS2290_001","JS2323_002","JS2290_004z1","JS1846_001","JS1844_003",
    "JS1834_001","JS1840_001","JS1839_005","JS1831_003","JS2183_001","JS2287_001","JS2278_003",
    "JS2323_003","JS2278_001","JS2183_002","JS1831_008","JS1840_006z1","JS2323_004","JS2278_006",
    "JS2171_001","JS2290_004","JS2290_002","JS2278_007","JS1825_002","JS2175_001","JS2174_001z1",
    "JS2291_001x1","JS2183_003z1","JS2197_004z1","JS2300_004","JS2311_010z1","JS2252_001x1",
    "JS2013_001","JS1840_006","JS1843_001x1","JS2163_006","JS1835_001x1","JS2183_003","JS2271_001x1",
    "JS2034_001x1","JS2269_001x1","JS2300_002","JS2218_001x1","JS2033_001","JS1828_001","JS1950_001x1",
    "JS2260_001x1","JS1839_008","JS2174_001x1","JS2169_003","JS1831_006","JS2171_001x1","JS2298_001x1",
    "JS1851_004","JS2164_002","JS2184_001x1","JS1852_001x1","JS2319_001x1","JS1828_001x1","JS2236_001x1",
    "JS2161_005","JS1839_001","JS1840_005","JS1840_004","JS1851_007","JS1834_001x1","JS2192_001x1",
    "JS2161_027","JS2270_001","JS2161_013","JS1831_001x1","JS1831_008z1","JS2323_001","JS2312_001x1",
    "JS2199_009","JS2164_020","JS2278_004","JS2254_001x1","JS2269_001","JS1832_001x1","JS2162_001x1",
    "JS2299_002","JS1843_003","JS2286_002","JS2296_001x1","JS2277_003","JS2279_001x1","JS1829_001x1",
    "JS2166_003","JS1844_001","JS2282_001x1","JS2222_042","JS2201_008","JS2293_001","JS2161_003",
    "JS2201_001x1","JS2222_006","JS1831_007","JS2222_008","JS2163_011","JS1854_003","JS2199_005",
    "JS1844_004","JS2301_001x1","JS2218_001","JS2301_001","JS1852_002","JS2194_001x1","JS1827_002",
    "JS2237_005","JS2185_001x1","JS2290_003","JS2289_001x1","JS2322_001x1","JS2281_001x1","JS2173_006",
    "JS2277_001","JS2163_009","JS2222_043","JS2222_016","JS2311_001x1","JS2222_001x1","JS2161_037",
    "JS2169_001","JS2203_003","JS2303_001x1","JS2161_008","JS2300_001","JS2199_002","JS2286_001x1",
    "JS2163_012","JS1839_004","JS1846_016","JS2199_003","JS2201_001","JS2278_002","JS1840_001x1",
    "JS2316_001x1","JS2222_028","JS2161_028","JS2271_001","JS2218_011","JS2278_001x1","JS2222_013",
    "JS2161_039","JS1851_011","JS2161_018","JS2161_031","JS2197_001x1"
]

def get_problematic_bd():
    import helper as hlp
    db = hlp.get_db('tw-prod-readonly')
        
    def get_bd_txt_list(reel_code, db=None):
        reel = db.reel.find_one({'reel_code': reel_code})
        bd_txt_list = reel.get('bd_txt_list', [])
        bd_txt = '\n'.join([i['txt'] for i in bd_txt_list])
        bd_txt = re.sub(r'\n+', '\n', bd_txt)
        return bd_txt

    def get_pic(reel_code, db=None):
        doc = db.task.find({'doc_id': reel_code}, {'picked_by': 1, '_id': 0}).sort('picked_time', -1).limit(1)
        doc = next(doc, None)
        latest_picked_by = doc.get('picked_by') if doc else None
        return latest_picked_by

    def extract_quote_errors(text, reel_code, pic):
        """
        Scans text for mismatched Chinese quotes. 
        Returns a list of error dictionaries suitable for an Excel export.
        """
        # If text is empty or not a string, return empty list
        if not isinstance(text, str) or not text:
            return []

        errors = []
        expect_open = True 
        
        for i, char in enumerate(text):
            if char == "“":
                if not expect_open:
                    # ERROR: Found an opening quote when expecting a closing quote
                    start = max(0, i - 10)
                    end = min(len(text), i + 11)
                    # Highlight the error quote with brackets
                    context = text[start:i] + f"【{char}】" + text[i+1:end]
                    
                    errors.append({
                        "reel_code": reel_code,
                        "pic": pic,
                        "error_context": context,
                        "error_msg": "连续前引号" # "Consecutive opening quotes"
                    })
                # Reset state: we are now inside a quote, expect a closing one
                expect_open = False 
                
            elif char == "”":
                if expect_open:
                    # ERROR: Found a closing quote when expecting an opening quote
                    start = max(0, i - 10)
                    end = min(len(text), i + 11)
                    context = text[start:i] + f"【{char}】" + text[i+1:end]
                    
                    errors.append({
                        "reel_code": reel_code,
                        "pic": pic,
                        "error_context": context,
                        "error_msg": "缺失前引号" # "Missing opening quote"
                    })
                # Reset state: we are now outside, expect an opening quote next
                expect_open = True 
                
        # ERROR: String ended but we were still expecting a closing quote
        if not expect_open:
            start = max(0, len(text) - 10)
            context = text[start:] + "【缺失”】"
            errors.append({
                "reel_code": reel_code,
                "pic": pic,
                "error_context": context,
                "error_msg": "末尾未闭合" # "Unclosed at the end"
            })
            
        return errors

    all_errors = []
    for bd_id in bd_ids:
        bd_txt = get_bd_txt_list(bd_id, db)
        latest_picked_by = get_pic(bd_id, db)
        errors = extract_quote_errors(bd_txt, bd_id, latest_picked_by)
        if errors:
            all_errors.extend(errors)

    if all_errors:
        df = pd.DataFrame(all_errors)
        df = df[["reel_code", "pic", "error_msg", "error_context"]]
        df.rename(columns={
            "reel_code": "卷编码",
            "pic": "任务领取人",
            "error_msg": "引号不对类型",
            "error_context": "错误上下文 (前后10字符)"
        }, inplace=True)
        
        output_filename = "0414—引号错误.xlsx"
        df.to_excel(output_filename, index=False)
        
        print(f"成功导出 {len(all_errors)} 个错误到 {output_filename}！")
    else:
        print("太棒了！没有发现任何引号报错，无需生成Excel。")
    

zstp_ids = ['JS1523','JS1664','JS1783','JS1818', 'JS1952']

def get_text_w_catalog(sutra_uid="JS1818"):
    db = hlp.get_db('tr-prod-readonly')
    
    # 1. Get the catalog and flatten it into a dictionary of lists:
    # { 'line_uid': ['level 1 txt', 'level 2 txt', 'level 3 txt'] }
    sutra = db['sutra'].find_one({'uid': sutra_uid}, {'catalog': 1})
    catalog_tree = sutra.get('catalog', []) if sutra else []
    catalog_map = {}
    
    def flatten_catalog(nodes):
        for node in nodes:
            line_uid = node.get('line_uid')
            txt = node.get('std_txt', '')
            if line_uid:
                if line_uid not in catalog_map:
                    catalog_map[line_uid] = []
                catalog_map[line_uid].append(txt)
                
            if 'children' in node:
                flatten_catalog(node['children'])
                
    flatten_catalog(catalog_tree)

    # 2. Get all reels and sort them
    reels = list(db['reel'].find({'sutra_uid': sutra_uid}, {'uid': 1, 'pages': 1}))
    reels.sort(key=lambda x: hlp.align_reel_code(x['uid']))
    
    # 3. Iterate through content and map to Excel rows
    output_rows = []
    current_catalog = ""  
    current_content = []
    
    for reel in reels:
        for page in reel.get('pages', []):
            ouid = page.get('uid')
            for block in page.get('blocks', []):
                for col in block.get('columns', []):
                    col_cid = col.get('col_cid')
                    current_line_uid = f"{ouid}@{col_cid}"
                    
                    std_txt = col.get('std_txt', '')
                    
                    # If we hit a new catalog anchor
                    if current_line_uid in catalog_map:
                        # 1. Save the PREVIOUS catalog and its accumulated content
                        if current_content or current_catalog:
                            output_rows.append({
                                '目录': current_catalog,
                                '内容': "".join(current_content)
                            })
                            
                        # 2. Process the NEW overlapping catalogs
                        matched_catalogs = catalog_map[current_line_uid]
                        
                        # For all upper levels (everything except the last one),
                        # create a row with empty content.
                        for cat in matched_catalogs[:-1]:
                            output_rows.append({
                                '目录': cat,
                                '内容': ""
                            })
                            
                        # The deepest level (the last one) becomes the active catalog
                        current_catalog = matched_catalogs[-1]
                        current_content = [std_txt] # Start absorbing text
                        
                    else:
                        # No catalog anchor here, just keep accumulating text
                        current_content.append(std_txt)
                        
    # 4. Save the very last chunk of text after the loop finishes
    if current_content or current_catalog:
        output_rows.append({
            '目录': current_catalog,
            '内容': "".join(current_content)
        })
        
    # 5. Export to Excel
    df = pd.DataFrame(output_rows)
    df.to_excel(f"{sutra_uid}_目录-内容.xlsx", index=False)
    print(f"Done! Exported to {sutra_uid}_目录-内容.xlsx")

def zstp_export():
    for sutra_uid in zstp_ids:
        print(f"Processing {sutra_uid} ...")
        get_text_w_catalog(sutra_uid)


import os
import helper as hlp

def scan_and_test_d_format():
    # 1. Connect to the DB
    db = hlp.get_db('tr-prod-readonly')
    
    print("Scanning sutras for 'D' format instances...")
    test_cases = []

    # 2. Scan through all sutras in your list
    for sutra_code in js_list:
        reels = list(db.reel.find({'sutra_uid': sutra_code}, {'uid': 1, 'pages': 1, '_id': 0}))
        
        for rl in reels:
            uid = rl['uid']
            pages = rl.get('pages', [])
            
            # Look inside pages -> blocks -> columns
            has_d_format = False
            for page in pages:
                for blk in page.get('blocks', []):
                    for col in blk.get('columns', []):
                        # Check column format
                        if col.get('col_format') == 'D':
                            has_d_format = True
                            break
                        # Check character formats inside the column
                        for fmt, start, end in col.get('char_format', []):
                            if fmt == 'D':
                                has_d_format = True
                                break
                    if has_d_format: break
                if has_d_format: break
            
            if has_d_format:
                test_cases.append(uid)

    # 3. Report findings and run your logic on the matches
    print(f"\nFound {len(test_cases)} reels containing 'D' format.")
    if not test_cases:
        print("No 'D' format found in any of the specified sutras.")
        return

    print("\n--- Running Test Extractions ---")
    for uid in test_cases[:5]:  # Let's peek at the first 5 matches to verify
        print(f"\n[Test Case] Reel UID: {uid}")
        
        # Call your specific v5 extraction function
        result_txt = get_std_reel_txt_v5(uid, db=db)
        
        # Extract snippets containing 【 】 to check the wrapping
        import re
        brackets_found = re.findall(r'【[^】]{1,30}】', result_txt)
        
        if brackets_found:
            print("  Success! Found wrapped segments:")
            for sample in brackets_found[:3]: # Show up to 3 samples
                print(f"    -> {sample}")
        else:
            print("  Warning: 'D' format metadata exists, but no text was wrapped in 【】.")
            print(f"  Raw sample (first 100 chars): {result_txt[:100]}...")

def main(func='', **kwargs):
    eval(func)(**kwargs)

if __name__ == '__main__':
    import fire

    fire.Fire(main)
