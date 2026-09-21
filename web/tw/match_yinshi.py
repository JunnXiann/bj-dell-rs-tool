"""福州藏(FZ)与思溪藏(SX)音释比对文本(cmp_txt)的范围匹配

思路：用两张对照表把每个福州藏音释卷(z卷)限定到含有对应音释的思溪藏卷("窗口")，只在窗口内做匹配，
而不是在全部思溪藏音释文本里大海捞针。两个方向共用同一套窗口/取字/匹配逻辑：

    fz2sx(默认)  福州藏音释字获得cmp_txt，参考文本来自思溪藏窗口内各卷的音释(E格式)
    sx2fz        思溪藏音释字(E格式)获得cmp_txt，参考文本来自福州藏z卷的音释

用法（默认只预演，加 --commit 才写库；默认库 tw-test-readonly）：
    python match_yinshi.py preview --sutra=FZ0002 [--direction=fz2sx|sx2fz] [--db=...]   # 只读，输出逐页逐列对照
    python match_yinshi.py plan  [--with_counts]
    python match_yinshi.py match [--direction=fz2sx|sx2fz] [--only=FZ0001_010z1] [--commit] [--force] [--set_page_match]
    python match_yinshi.py apply [--direction=fz2sx|sx2fz] [--only=FZ0001_010z1] [--min_status=3] [--commit]

两个xlsx被.gitignore忽略，需手工拷到本目录：福州藏vs思溪藏卷编码.xlsx、福州藏音释卷编码.xlsx
"""
import re
import os
import sys
import csv
import json
import logging
import os.path as path
from datetime import datetime

sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

HERE = path.dirname(path.abspath(__file__))
MAPPING_XLSX = path.join(HERE, '福州藏vs思溪藏卷编码.xlsx')
YINSHI_XLSX = path.join(HERE, '福州藏音释卷编码.xlsx')
VARIANTS_TXT = path.join(HERE, 'variants.txt')
REPORT_DIR = path.join(HERE, 'data', 'yinshi_match')

DIRECTIONS = {
    'fz2sx': {'target': 'FZ', 'reference': 'SX', 'index_id': 'sx_yinshi_scoped'},
    'sx2fz': {'target': 'SX', 'reference': 'FZ', 'index_id': 'fz_yinshi_scoped'},
}
EMPTY_REEL_TYPES = ('空卷', '音释（缺）')
# find_best_match要求至少10字的连续同文才算匹配，更短的音释改用find_short_match
SHORT_TXT_LEN = 30  # 页音释字数不超过该值才启用
SHORT_MIN_SCORE = 80  # 最佳位置的相似度(0-100)至少达到该值
SHORT_MIN_GAP = 10  # 最佳位置比其它位置至少高出该值，重复出现的文本(如“第N卷不出字”)因此不匹配
Z_REEL_RE = re.compile(r'^([A-Z]+\d+)_(\d+)z(\d+)$')
TITLE_RE = re.compile(r'經卷第[一二三四五六七八九十百千〇零]+重?$')  # 如“放光般若波羅蜜經卷第十二重”


# region 窗口：把福州藏音释卷对应到思溪藏卷

def is_z_reel(code):
    return bool(Z_REEL_RE.match(code))


def build_yinshi_windows(mapping_rows, existing_z):
    """ 计算每个福州藏音释卷(z卷)覆盖的福州藏卷和对应的思溪藏卷
    mapping_rows: [(福州藏卷编码, 思溪藏卷编码或None)]，按对照表原有顺序（x卷、正卷、z卷）
    existing_z: {z卷编码: reel_type}，库里实际存在的福州藏z卷。表里有但库里没有的z卷直接忽略，
        既没有窗口，也不作为分界（如疑似错误的 FZ0001_120z1）
    规则：z卷覆盖同一经中上一个（存在的）z卷之后的所有卷。返回(windows, skipped_z)
        windows: {z卷: {'fz_reels': [...], 'sx_reels': [...], 'reel_type': ...}}
    """
    windows, skipped = {}, []
    pending = {}  # 经号 -> 上个z卷之后收集到的[(福州藏卷, 思溪藏卷)]
    last = {}  # 经号 -> (锚点卷序号, 上个窗口的行)，用于同一卷后的z1/z2共用窗口
    for fz, sx in mapping_rows:
        sutra = fz.split('_')[0]
        m = Z_REEL_RE.match(fz)
        if not m:
            pending.setdefault(sutra, []).append((fz, sx))
            continue
        if fz not in existing_z:
            skipped.append(fz)
            continue
        rows = pending.get(sutra, [])
        if not rows and sutra in last and last[sutra][0] == m.group(2):
            rows = last[sutra][1]
        last[sutra] = (m.group(2), rows)
        pending[sutra] = []
        sx_reels = [b for _, b in rows if b]
        if sx:  # 思溪藏自己也有音释卷(z1)
            sx_reels.append(sx)
        windows[fz] = {'fz_reels': [a for a, _ in rows], 'sx_reels': sx_reels, 'reel_type': existing_z[fz]}
    return windows, skipped


def build_jobs(windows, direction):
    """ 把窗口转成匹配任务：[{'id', 'z_reels', 'target_reels', 'reference_reels'}]
    fz2sx：目标是z卷本身，参考是窗口内思溪藏卷
    sx2fz：目标是窗口内思溪藏卷，参考是z卷（共用窗口的z1/z2合并为一个参考）
    没有音释文本(空卷/音释（缺）)或没有思溪藏卷的窗口不产生任务
    """
    if direction not in DIRECTIONS:
        raise ValueError('direction must be one of %s' % list(DIRECTIONS))
    usable = [(z, w) for z, w in windows.items() if w['sx_reels'] and w.get('reel_type') not in EMPTY_REEL_TYPES]
    if direction == 'fz2sx':
        return [{'id': z, 'z_reels': [z], 'target_reels': [z], 'reference_reels': w['sx_reels']}
                for z, w in usable]
    groups = {}
    for z, w in usable:
        groups.setdefault(tuple(w['sx_reels']), []).append(z)
    return [{'id': zs[0], 'z_reels': zs, 'target_reels': list(sx), 'reference_reels': zs}
            for sx, zs in groups.items()]


# endregion


# region 取音释字：从卷/页数据里挑出音释的字框

def _char_key(ch, idx):
    m = re.match(r'^b(\d+)c(\d+)c(\d+)$', ch.get('char_id') or '')
    return tuple(int(x) for x in m.groups()) if m else (0, 0, idx)


def _iter_live(page):
    """ 遍历未删除且有char_id的字：(下标, 字, 所在列id)"""
    for idx, ch in enumerate(page.get('chars') or []):
        char_id = ch.get('char_id')
        if not ch.get('deleted') and char_id:
            yield idx, ch, char_id.rsplit('c', 1)[0]


def norm_char(ch, vdict):
    """ 单字的比对文本：异体字编码换成正字，且只取一个字，保证文本与字框一一对应"""
    txt = ch.get('txt') or '■'
    if vdict.get(txt):
        txt = vdict[txt]
    elif re.match(r'^v\d+n?$', txt):  # 没有对应正字的异体字编码
        txt = '■'
    return txt[0]


def order_chars(page, idxs):
    chars = page['chars']
    return sorted(idxs, key=lambda i: _char_key(chars[i], i))


def group_columns(page, idxs):
    """ 按列分组：[(列id, [字下标])]，均按阅读顺序"""
    cols = {}
    for i in order_chars(page, idxs):
        cols.setdefault(page['chars'][i]['char_id'].rsplit('c', 1)[0], []).append(i)
    return list(cols.items())


def page_text(page, idxs, vdict):
    """ 一页音释文本，一列一行；返回(文本, 按阅读顺序的字下标)，去掉换行后文本长度等于字数"""
    lines = [''.join(norm_char(page['chars'][i], vdict) for i in ids) for _, ids in group_columns(page, idxs)]
    return '\n'.join(lines), order_chars(page, idxs)


def _usable_column_ids(page):
    return {c.get('column_id') for c in page.get('columns') or []
            if c.get('column_id') and not c.get('is_center') and not c.get('deleted')}


def _e_format(reel, page_name):
    """ 页中E(音释)格式的行cid集合和字cid区间"""
    for fmt in reel.get('format') or []:
        if fmt.get('name') != page_name:
            continue
        col_cids = {c[1] for c in fmt.get('columns') or [] if c[0] == 'E'}
        # 单个字的字格式，起始值为空
        ranges = [(ch[2] or ch[3], ch[3]) for ch in fmt.get('chars') or [] if ch[0] == 'E']
        return col_cids, ranges
    return set(), []


def _select_by_e(reel, page):
    col_cids, ranges = _e_format(reel, page['name'])
    if not col_cids and not ranges:
        return []
    usable = _usable_column_ids(page)
    e_col_ids = {c.get('column_id') for c in page.get('columns') or [] if c.get('cid') in col_cids}
    picked = []
    for idx, ch, col_id in _iter_live(page):
        if col_id not in usable:
            continue
        cid = ch.get('cid')
        if col_id in e_col_ids or (cid is not None and any(s <= cid <= e for s, e in ranges)):
            picked.append(idx)
    return picked


def _select_all(page):
    usable = _usable_column_ids(page)
    return [idx for idx, _, col_id in _iter_live(page) if col_id in usable]


def _find_title(full, vdict):
    """ 找到第一个“…經卷第N(重)”标题列，返回(页序号, 列序号)"""
    for n, (page, idxs) in enumerate(full):
        for k, (_, ids) in enumerate(group_columns(page, idxs)):
            if TITLE_RE.search(''.join(norm_char(page['chars'][i], vdict) for i in ids)):
                return n, k
    return None


def select_reel_yinshi(reel, pages, vdict=None):
    """ 从卷的各页中挑出音释字，返回[{'page', 'method', 'idx'}]（idx是page['chars']的下标）
    优先级：
    1. 卷的format里有E(音释)格式：只取E格式的行/字 (method='E')
    2. 没有E格式，且是音释卷(reel_type为音释或z卷)：
       福州藏z卷开头可能夹有正文，取第一个“…經卷第N(重)”标题之后的字 (method='title')；
       没有标题或不是福州藏，则取全部非版心字 (method='all')
    3. 普通卷没有E格式：没有音释
    """
    vdict = vdict or {}
    by_e = [(p, _select_by_e(reel, p)) for p in pages]
    if any(idxs for _, idxs in by_e):
        return [{'page': p, 'method': 'E', 'idx': idxs} for p, idxs in by_e if idxs]

    reel_code = reel.get('reel_code') or ''
    if reel.get('reel_type') != '音释' and not is_z_reel(reel_code):
        return []
    full = [(p, _select_all(p)) for p in pages]
    title = _find_title(full, vdict) if reel_code.startswith('FZ') else None
    picked = []
    for n, (page, idxs) in enumerate(full):
        if not idxs:
            continue
        if title is None:
            picked.append({'page': page, 'method': 'all', 'idx': idxs})
        elif n == title[0]:
            rest = [i for _, ids in group_columns(page, idxs)[title[1] + 1:] for i in ids]
            if rest:
                picked.append({'page': page, 'method': 'title', 'idx': rest})
        elif n > title[0]:
            picked.append({'page': page, 'method': 'title', 'idx': idxs})
    return picked


# endregion


# region 数据读取

def load_variants(variants_txt=VARIANTS_TXT):
    with open(variants_txt, 'r', encoding='utf-8') as f:
        return json.load(f)


def _clean(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    return str(v).strip() or None


def _read_sheet(xlsx_path):
    if not path.exists(xlsx_path):
        raise FileNotFoundError('%s not found: xlsx files are gitignored, copy it to web/tw/ by hand' % xlsx_path)
    import pandas as pd
    return pd.read_excel(xlsx_path, dtype=str)


def load_mapping(xlsx_path=MAPPING_XLSX):
    """ 福州藏vs思溪藏卷编码：[(福州藏卷编码, 思溪藏卷编码或None)]，保持表中顺序"""
    df = _read_sheet(xlsx_path)
    rows = [(_clean(a), _clean(b)) for a, b in zip(df.iloc[:, 0], df.iloc[:, 1])]
    return [(a, b) for a, b in rows if a]


def load_yinshi_list(xlsx_path=YINSHI_XLSX):
    """ 福州藏音释卷编码：音释卷编码列表（仅用于和库核对）"""
    df = _read_sheet(xlsx_path)
    return [c for c in (_clean(v) for v in df.iloc[:, 0]) if c]


def load_existing_z_reels(db):
    """ 库里实际存在的福州藏z卷：{reel_code: reel_type}"""
    cond = {'reel_code': {'$regex': r'^FZ\d+_\d+z\d+$'}}
    return {r['reel_code']: r.get('reel_type') for r in db.reel.find(cond, {'reel_code': 1, 'reel_type': 1})}


def load_reel(db, reel_code):
    fields = ['reel_code', 'reel_type', 'format', 'start_volume', 'start_page', 'end_volume', 'end_page']
    return db.reel.find_one({'reel_code': reel_code}, {f: 1 for f in fields})


def load_reel_pages(db, reel):
    import helper as hlp
    from web.tw.reel import get_page_select_cond
    pages = list(db.page.find(get_page_select_cond(reel), {'name': 1, 'chars': 1, 'columns': 1, 'match_logs': 1}))
    pages.sort(key=lambda p: hlp.align_code(p['name']))
    return pages


def collect_yinshi(db, reel_codes, vdict):
    """ 收集若干卷的音释字，按页合并（两卷共用的页只保留一份，字取并集）
    返回({页名: {'page', 'idx': set, 'methods': set}}, {卷编码: 音释字数})
    """
    targets, counts = {}, {}
    for code in reel_codes:
        counts[code] = 0
        reel = load_reel(db, code)
        if not reel or reel.get('reel_type') in EMPTY_REEL_TYPES:
            continue
        for sel in select_reel_yinshi(reel, load_reel_pages(db, reel), vdict):
            t = targets.setdefault(sel['page']['name'], {'page': sel['page'], 'idx': set(), 'methods': set()})
            t['idx'].update(sel['idx'])
            t['methods'].add(sel['method'])
            counts[code] += len(sel['idx'])
    return targets, counts


def sorted_page_names(targets):
    import helper as hlp
    return sorted(targets, key=hlp.align_code)


def build_reference_txt(db, reel_codes, vdict):
    """ 参考文本：各卷音释文本按阅读顺序拼接。返回(文本, {卷编码: 音释字数})"""
    targets, counts = collect_yinshi(db, reel_codes, vdict)
    texts = [page_text(targets[n]['page'], targets[n]['idx'], vdict)[0] for n in sorted_page_names(targets)]
    return '\n'.join(texts), counts


# endregion


# region 命令

def _parse_only(only):
    if not only:
        return set()
    return set(only.split(',')) if isinstance(only, str) else set(only)


def _prepare(db, direction, only, mapping):
    """ 读表、核对库里的z卷、计算窗口和任务"""
    existing_z = load_existing_z_reels(db)
    windows, skipped = build_yinshi_windows(load_mapping(mapping), existing_z)
    jobs = build_jobs(windows, direction)
    only = _parse_only(only)
    if only:
        jobs = [j for j in jobs if only & set(j['z_reels'])]
    return existing_z, windows, skipped, jobs


def write_csv(file_path, rows, fields):
    os.makedirs(path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    logging.info('wrote %s (%s rows)' % (file_path, len(rows)))


def _span(codes):
    if len(codes) > 3:
        return '%s..%s (%s)' % (codes[0], codes[-1], len(codes))
    return ', '.join(codes)


def run_plan(db='tw-test-readonly', direction='fz2sx', with_counts=False, mapping=MAPPING_XLSX,
             yinshi_list=YINSHI_XLSX, report_dir=REPORT_DIR):
    """ 核对库并输出窗口(windows)与对不上的情况(reconcile)两个csv；with_counts会统计思溪藏窗口内的音释字数(较慢)"""
    import helper as hlp
    hlp.set_logging('match_yinshi')
    dbh = hlp.get_db(db)
    mapping_rows = load_mapping(mapping)
    existing_z, windows, skipped, jobs = _prepare(dbh, direction, '', mapping)
    vdict = load_variants() if with_counts else {}
    now = datetime.now().strftime('%Y%m%d-%H%M%S')

    no_sx = {a for a, b in mapping_rows if not b}
    rows = []
    for z, w in windows.items():
        row = {'z_reel': z, 'reel_type': w['reel_type'] or '', 'fz_reels': _span(w['fz_reels']),
               'sx_reels': _span(w['sx_reels']),
               'fz_reels_without_sx': ','.join(a for a in w['fz_reels'] if a in no_sx)}
        if with_counts:
            row['sx_char_count'] = sum(collect_yinshi(dbh, w['sx_reels'], vdict)[1].values())
        rows.append(row)
    write_csv(path.join(report_dir, 'plan_windows-%s.csv' % now), rows,
              ['z_reel', 'reel_type', 'fz_reels', 'sx_reels', 'fz_reels_without_sx', 'sx_char_count'])

    sheet_z = {a for a, _ in mapping_rows if is_z_reel(a)}
    recon = [{'issue': 'sheet z row missing in DB (ignored, not a boundary)', 'reel': z} for z in skipped]
    if path.exists(yinshi_list):
        recon += [{'issue': 'yinshi list code missing in DB', 'reel': c}
                  for c in load_yinshi_list(yinshi_list) if c not in existing_z]
    recon += [{'issue': 'DB z reel missing from mapping sheet', 'reel': z} for z in sorted(set(existing_z) - sheet_z)]
    recon += [{'issue': 'z reel exists but has no yinshi text (%s)' % t, 'reel': z}
              for z, t in existing_z.items() if t in EMPTY_REEL_TYPES]
    recon += [{'issue': 'window has no SX reel', 'reel': z} for z, w in windows.items() if not w['sx_reels']]
    if with_counts:
        recon += [{'issue': 'window has no SX yinshi text', 'reel': r['z_reel']}
                  for r in rows if r.get('sx_char_count') == 0]
    write_csv(path.join(report_dir, 'plan_reconcile-%s.csv' % now), recon, ['issue', 'reel'])
    logging.info('windows=%s jobs(%s)=%s reconcile issues=%s' % (len(windows), direction, len(jobs), len(recon)))


def find_short_match(base_txt, ref_txt):
    """ 在参考文本里为很短的音释找匹配文本；找不到或有多处同样好的位置时返回''
    逐字滑动窗口(窗口长度=base字数)比较，最佳位置须足够像，且明显好于不重叠的其它位置
    """
    from rapidfuzz import fuzz
    base = base_txt.replace('\n', '')
    pos = [i for i, c in enumerate(ref_txt) if c != '\n']  # 去掉换行后各字在ref_txt里的位置
    ref = ''.join(ref_txt[i] for i in pos)
    n = len(base)
    if not n or len(ref) < n:
        return ''
    scores = [fuzz.ratio(base, ref[i:i + n]) for i in range(len(ref) - n + 1)]
    best = max(range(len(scores)), key=scores.__getitem__)
    rival = max([s for i, s in enumerate(scores) if abs(i - best) >= n] or [0])
    if scores[best] < SHORT_MIN_SCORE or scores[best] - rival < SHORT_MIN_GAP:
        return ''
    return ref_txt[pos[best]:pos[best + n - 1] + 1]


def _own_log(page, index_id):
    return next((l for l in page.get('match_logs') or [] if l.get('index_id') == index_id), None)


REPORT_FIELDS = ['job', 'page', 'method', 'n_chars', 'status', 'r_hit2base', 'r_similar2hit', 'r_similar2base',
                 'len_match_txt', 'action', 'note']


def _match_target(job_id, name, t, ref_txt, vdict, index_id, reference_reels, force=False):
    """ 为一页目标音释字在参考文本里查找匹配。返回(报告行, match_log或None)，不写库"""
    from util.find_match import find_best_match
    from web.tw.match import get_match_info
    page = t['page']
    base_txt, ordered = page_text(page, t['idx'], vdict)
    row = {'job': job_id, 'page': name, 'method': ','.join(sorted(t['methods'])), 'n_chars': len(ordered)}
    if not ordered:  # 短的音释也要匹配，只有完全没字时才无可查找
        return dict(row, action='skipped_empty'), None
    own = _own_log(page, index_id)
    if own and own.get('status') == 5 and not force:
        return dict(row, action='skipped_done', status=5), None
    try:
        match_txt, by = find_best_match(base_txt, ref_txt)[0], 'find_best_match'
        if not match_txt.strip() and len(ordered) <= SHORT_TXT_LEN:
            match_txt, by = find_short_match(base_txt, ref_txt), 'short'
        info = get_match_info(base_txt, match_txt)
    except Exception as e:  # 单页出错不影响整批
        logging.exception('%s failed' % name)
        return dict(row, action='error', note=str(e)), None
    log = dict(info, index_id=index_id, created_by='operator', create_time=datetime.now(),
               reference_reels=reference_reels, method=row['method'], found_by=by)
    row.update(status=info['status'], r_hit2base=info['r_hit2base'], r_similar2hit=info['r_similar2hit'],
               r_similar2base=info['r_similar2base'], len_match_txt=info['len_match_txt'])
    if by == 'short':
        row['note'] = 'short text search'
    return row, log


def _fill_cmp(page, t, index_id, vdict, log=None, min_status=3):
    """ 在内存里把匹配文本填入目标音释字的cmp_txt，不写库。log默认取页里index_id对应的日志
    返回(状态, 按阅读顺序的字下标, 替身字列表)；状态：ok/no_log/status_too_low/apply_failed
    用单字的比对文本做替身参与对齐，避免异体字编码(多个字符)破坏字数对应
    """
    from web.tw.page import apply_txt2missingchars
    log = log or _own_log(page, index_id)
    if not log:
        return 'no_log', [], []
    if (log.get('status') or 0) < min_status:
        return 'status_too_low', [], []
    ordered = order_chars(page, t['idx'])
    proxies = [{'txt': norm_char(page['chars'][i], vdict), 'cmp_txt': page['chars'][i].get('cmp_txt')}
               for i in ordered]
    view = dict(page, match_logs=[log])
    if not apply_txt2missingchars(None, view, index_id=index_id, field='cmp_txt', chars=proxies):
        return 'apply_failed', ordered, []
    return 'ok', ordered, proxies


def _cmp_changes(page, ordered, proxies):
    """ 填充后发生变化的字：{page['chars']下标: 新cmp_txt}"""
    return {i: p['cmp_txt'] for i, p in zip(ordered, proxies) if p.get('cmp_txt') != page['chars'][i].get('cmp_txt')}


def run_match(direction='fz2sx', db='tw-test-readonly', only='', commit=False, force=False, set_page_match=False,
              mapping=MAPPING_XLSX, report_dir=REPORT_DIR):
    """ 在窗口内为目标页查找参考文本，写入match_logs（index_id见DIRECTIONS）。
    默认预演不写库；已有完全匹配(status=5)的页跳过，force可重跑；
    默认不改page.match(音释文本占比会扭曲整页状态)，set_page_match可开启
    """
    import helper as hlp
    from web.tw.match import get_best_match
    hlp.set_logging('match_yinshi')
    index_id = DIRECTIONS[direction]['index_id']
    dbh = hlp.get_db(db)
    vdict = load_variants()
    _, _, _, jobs = _prepare(dbh, direction, only, mapping)
    logging.info('%s: %s jobs, commit=%s, db=%s' % (direction, len(jobs), commit, db))

    report, stats = [], {}
    for j, job in enumerate(jobs):
        logging.info('[%s/%s] %s <- %s' % (j + 1, len(jobs), _span(job['target_reels']), _span(job['reference_reels'])))
        ref_txt, ref_counts = build_reference_txt(dbh, job['reference_reels'], vdict)
        targets, _ = collect_yinshi(dbh, job['target_reels'], vdict)
        if not ref_txt:
            report.append({'job': job['id'], 'action': 'no_reference', 'note': 'no yinshi text in %s' % ref_counts})
            continue
        for name in sorted_page_names(targets):
            page = targets[name]['page']
            row, log = _match_target(job['id'], name, targets[name], ref_txt, vdict, index_id,
                                     job['reference_reels'], force)
            if log is not None:
                logs = [l for l in page.get('match_logs') or [] if l.get('index_id') != index_id] + [log]
                if commit:
                    update = {'match_logs': logs}
                    if set_page_match:
                        update['match'] = get_best_match(logs)
                    dbh.page.update_one({'_id': page['_id']}, {'$set': update})
                row['action'] = 'written' if commit else 'dry_run'
                stats[log['status']] = stats.get(log['status'], 0) + 1
            report.append(row)
    now = datetime.now().strftime('%Y%m%d-%H%M%S')
    write_csv(path.join(report_dir, 'match_%s-%s.csv' % (direction, now)), report, REPORT_FIELDS)
    logging.info('status distribution (2 no match .. 5 exact): %s' % dict(sorted(stats.items())))


def run_apply(direction='fz2sx', db='tw-test-readonly', only='', min_status=3, commit=False,
              mapping=MAPPING_XLSX, report_dir=REPORT_DIR):
    """ 把match_logs里状态>=min_status的匹配文本填入目标音释字的cmp_txt（只填空缺或■的字，不覆盖已有内容）"""
    import helper as hlp
    hlp.set_logging('match_yinshi')
    index_id = DIRECTIONS[direction]['index_id']
    dbh = hlp.get_db(db)
    vdict = load_variants()
    _, _, _, jobs = _prepare(dbh, direction, only, mapping)
    logging.info('%s: %s jobs, min_status=%s, commit=%s, db=%s' % (direction, len(jobs), min_status, commit, db))

    report = []
    for j, job in enumerate(jobs):
        logging.info('[%s/%s] %s' % (j + 1, len(jobs), _span(job['target_reels'])))
        targets, _ = collect_yinshi(dbh, job['target_reels'], vdict)
        for name in sorted_page_names(targets):
            t = targets[name]
            page = t['page']
            row = {'job': job['id'], 'page': name, 'method': ','.join(sorted(t['methods'])), 'n_chars': len(t['idx'])}
            status, ordered, proxies = _fill_cmp(page, t, index_id, vdict, min_status=min_status)
            log = _own_log(page, index_id)
            if status != 'ok':
                report.append(dict(row, action=status, status=log and log.get('status')))
                continue
            changes = _cmp_changes(page, ordered, proxies)
            if commit and changes:
                dbh.page.update_one({'_id': page['_id']},
                                    {'$set': {'chars.%s.cmp_txt' % i: v for i, v in changes.items()}})
            report.append(dict(row, action='written' if commit else 'dry_run', status=log.get('status'),
                               note='%s chars changed, %s placeholders' % (
                                   len(changes), sum(1 for v in changes.values() if v == '■'))))
    now = datetime.now().strftime('%Y%m%d-%H%M%S')
    write_csv(path.join(report_dir, 'apply_%s-%s.csv' % (direction, now)), report, REPORT_FIELDS)


PREVIEW_FIELDS = ['job', 'page', 'method', 'n_chars', 'status', 'r_hit2base', 'r_similar2hit', 'r_similar2base',
                  'applied', 'n_same', 'n_placeholder', 'n_diff', 'action', 'target_txt', 'match_txt']


def render_page_view(page, t, vdict, cmp_by_idx):
    """ 一页音释的列对照，每列三行：原字(txt)、比对字(cmp)、差异标记（＾表示与原字不同，含■占位）"""
    lines = []
    for col_id, ids in group_columns(page, t['idx']):
        own = ''.join(norm_char(page['chars'][i], vdict) for i in ids)
        cmp = ''.join((cmp_by_idx.get(i) or '＿')[0] for i in ids)
        marks = ''.join('　' if a == b else '＾' for a, b in zip(own, cmp))
        lines += ['%-5s txt: %s' % (col_id, own), '%-5s cmp: %s' % ('', cmp), '%-5s      %s' % ('', marks)]
    return lines


def run_preview(sutra, direction='fz2sx', db='tw-test-readonly', min_status=3, mapping=MAPPING_XLSX,
                report_dir=REPORT_DIR):
    """ 试跑一部(或几部)经并输出结果，全程只读库：在内存里完成match和apply，没有任何写库的代码路径。
    sutra: 福州藏经号，如 FZ0002 或 FZ0002,FZ0003（两个方向都用福州藏经号）
    输出到report_dir：preview_*.txt(逐页逐列对照，便于肉眼检查)和preview_*.csv(每页一行的汇总)
    min_status: 状态低于该值的页只显示匹配文本，不做cmp_txt填充（与apply一致）
    """
    import helper as hlp
    hlp.set_logging('match_yinshi')
    index_id = DIRECTIONS[direction]['index_id']
    sutras = _parse_only(sutra)
    dbh = hlp.get_db(db)
    vdict = load_variants()
    _, _, skipped, jobs = _prepare(dbh, direction, '', mapping)
    jobs = [j for j in jobs if any(z.split('_')[0] in sutras for z in j['z_reels'])]
    if not jobs:
        logging.info('no %s jobs for %s: not in the mapping sheet/DB, or it has no usable yinshi z reel'
                     % (direction, sorted(sutras)))
        return
    logging.info('preview %s %s: %s jobs, db=%s (read-only)' % (direction, sorted(sutras), len(jobs), db))

    out, rows, stats = [], [], {}
    totals = {'chars': 0, 'same': 0, 'placeholder': 0, 'diff': 0}
    for j, job in enumerate(jobs):
        logging.info('[%s/%s] %s <- %s' % (j + 1, len(jobs), _span(job['target_reels']), _span(job['reference_reels'])))
        ref_txt, ref_counts = build_reference_txt(dbh, job['reference_reels'], vdict)
        targets, _ = collect_yinshi(dbh, job['target_reels'], vdict)
        out += ['', '#' * 8 + ' %s  <-  %s' % (_span(job['target_reels']), _span(job['reference_reels'])),
                'reference yinshi chars per reel: %s' % {k: v for k, v in ref_counts.items() if v}]
        if not ref_txt:
            out.append('!! no reference yinshi text, nothing to match')
            continue
        for name in sorted_page_names(targets):
            t = targets[name]
            page = t['page']
            row, log = _match_target(job['id'], name, t, ref_txt, vdict, index_id, job['reference_reels'], force=True)
            base_txt, _ = page_text(page, t['idx'], vdict)
            row['target_txt'] = base_txt.replace('\n', '/')
            head = '=== %s | method=%s | chars=%s' % (name, row['method'], row['n_chars'])
            if log is None:
                out += ['', head + ' | %s %s' % (row['action'], row.get('note', ''))]
                rows.append(row)
                continue
            stats[log['status']] = stats.get(log['status'], 0) + 1
            row['match_txt'] = log['match_txt'].replace('\n', '/')
            head += ' | status=%s hit2base=%s similar2hit=%s' % (log['status'], log['r_hit2base'], log['r_similar2hit'])
            if log.get('found_by') == 'short':
                head += ' [short text search]'
            status, ordered, proxies = _fill_cmp(page, t, index_id, vdict, log=log, min_status=min_status)
            if status != 'ok':
                row['action'] = 'not_applied (%s)' % status
                out += ['', head + ' | not applied (%s); matched text:' % status, '  ' + row['match_txt']]
                rows.append(row)
                continue
            cmp_by_idx = {i: p['cmp_txt'] for i, p in zip(ordered, proxies)}
            n_same = sum(1 for i, p in zip(ordered, proxies) if p['cmp_txt'] == p['txt'])
            n_ph = sum(1 for p in proxies if p['cmp_txt'] == '■')
            row.update(action='previewed', applied=True, n_same=n_same, n_placeholder=n_ph,
                       n_diff=len(ordered) - n_same - n_ph)
            for key, v in (('chars', len(ordered)), ('same', n_same), ('placeholder', n_ph), ('diff', row['n_diff'])):
                totals[key] += v
            out += ['', head + ' | same=%s placeholder(■)=%s other-diff=%s' % (n_same, n_ph, row['n_diff'])]
            out += render_page_view(page, t, vdict, cmp_by_idx)
            rows.append(row)

    summary = ['preview  direction=%s  sutra=%s  db=%s  (read-only, nothing written)' % (direction, sorted(sutras), db),
               'jobs=%s  pages=%s  status distribution (2 no match .. 5 exact): %s' % (
                   len(jobs), len(rows), dict(sorted(stats.items()))),
               'applied chars=%(chars)s  identical to own char=%(same)s  placeholder(■)=%(placeholder)s  '
               'other differences (variant chars/misreads)=%(diff)s' % totals,
               'legend: txt = the target char, cmp = cmp_txt that would be filled, ＾ = differs (■ = no counterpart)']
    now = datetime.now().strftime('%Y%m%d-%H%M%S')
    base = 'preview_%s_%s-%s' % (direction, '+'.join(sorted(sutras)), now)
    os.makedirs(report_dir, exist_ok=True)
    txt_path = path.join(report_dir, base + '.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(summary + out) + '\n')
    write_csv(path.join(report_dir, base + '.csv'), rows, PREVIEW_FIELDS)
    for line in summary:
        logging.info(line)
    logging.info('open %s' % txt_path)


# endregion


if __name__ == '__main__':
    import fire

    fire.Fire({'plan': run_plan, 'match': run_match, 'apply': run_apply, 'preview': run_preview})
