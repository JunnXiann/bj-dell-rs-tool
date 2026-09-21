"""福州藏(FZ)与思溪藏(SX)音释比对文本(cmp_txt)的范围匹配

思路：用两张对照表把每个福州藏音释卷(z卷)限定到含有对应音释的思溪藏卷("窗口")，只在窗口内做匹配，
而不是在全部思溪藏音释文本里大海捞针。两个方向共用同一套窗口/取字/匹配逻辑：

    fz2sx        福州藏音释字获得cmp_txt，参考文本来自思溪藏窗口内各卷的音释(E格式)
    sx2fz(默认)  思溪藏音释字(E格式)获得cmp_txt，参考文本来自福州藏z卷的音释

用法（默认只预演，加 --commit 才写库；默认库 tw-test-readonly）：
    python match_yinshi.py preview [--sutra=FZ0002] [--direction=fz2sx|sx2fz] [--db=...]   # 只读，出报告；不填sutra=全部经
    python match_yinshi.py flag_e --value=20260921111 [--field=flag1] [--reel_regex=^SX] [--keep_existing] [--commit]   # 给所有含E格式的页打标记
    python match_yinshi.py plan  [--with_counts]
    python match_yinshi.py match [--direction=fz2sx|sx2fz] [--only=FZ0001_010z1] [--commit [--flag_date=20260921]] [--force] [--set_page_match]
    python match_yinshi.py apply [--direction=fz2sx|sx2fz] [--only=FZ0001_010z1] [--min_status=3] [--overwrite] [--commit [--flag_date=20260921]]

两个xlsx被.gitignore忽略，需手工拷到本目录：福州藏vs思溪藏卷编码.xlsx、福州藏音释卷编码.xlsx
"""
import re
import os
import sys
import csv
import json
import time
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
DEFAULT_DIRECTION = 'sx2fz'
EMPTY_REEL_TYPES = ('空卷', '音释（缺）')
# find_best_match要求至少10字的连续同文才算匹配，更短的音释改用find_short_match
SHORT_TXT_LEN = 30  # 页音释字数不超过该值才启用
SHORT_MIN_SCORE = 80  # 最佳位置的相似度(0-100)至少达到该值
SHORT_MIN_GAP = 10  # 最佳位置比其它位置至少高出该值，重复出现的文本(如“第N卷不出字”)因此不匹配
# 首次匹配只认顺序一致的最长一段；同一页里两块文字前后颠倒时，另一块会被留下，因此再单独找一次
LEFTOVER_MIN_LEN = 10  # 连续没有对应文本的字数不少于该值才单独再找
LEFTOVER_MAX_TRIES = 30  # 每页补找时最多调用几次查找
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
    shared = {}  # (经号, 锚点卷序号) -> [共用同一窗口的z卷]，以及它们各自在表里的思溪藏音释卷
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
        windows[fz] = {'fz_reels': [a for a, _ in rows], 'sx_reels': [b for _, b in rows if b],
                       'reel_type': existing_z[fz]}
        group = shared.setdefault((sutra, m.group(2)), {'zs': [], 'own_sx': []})
        group['zs'].append(fz)
        if sx and sx not in group['own_sx']:  # 思溪藏自己也有音释卷(z1)
            group['own_sx'].append(sx)
    # 共用窗口的z1/z2必须有相同的思溪藏卷：表里通常只有z1行带思溪藏音释卷，z2行是空的，
    # 不统一的话两个z卷会各成一个任务，同一批思溪藏页被匹配两次，后一次的结果覆盖前一次
    for group in shared.values():
        for z in group['zs']:
            base = windows[z]['sx_reels']
            windows[z]['sx_reels'] = base + [o for o in group['own_sx'] if o not in base]
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


FLAG_FIELD = 'flag3'  # 页数据里标记“这次改了哪些页”的字段；match.py等批量脚本也用它，值如151225001、20260206002


def flag_date_prefix(flag_date=None):
    """ 标记的日期部分(YYYYMMDD)：不指定就用今天。日期写错时报错"""
    text = str(flag_date).strip() if flag_date not in (None, '') else datetime.now().strftime('%Y%m%d')
    datetime.strptime(text, '%Y%m%d')
    return int(text)


def status_flag(date_prefix, status_after):
    """ 给改过的页打的标记：日期加3位状态码，如20260921004。状态码是补上音释比对文本后重新算出的整页匹配状态(0-5)，
    整页原来没有匹配的页也一样，按现在算出的状态归类。返回整数，与其它脚本的flag3一致"""
    return date_prefix * 1000 + (2 if status_after in (None, '') else int(status_after))


def _with_retry(fn, tries=3):
    """ 读库偶尔会因网络(如ssh隧道)断开而失败，重试几次；只用于只读查询"""
    from pymongo.errors import PyMongoError
    for k in range(tries):
        try:
            return fn()
        except PyMongoError as e:
            if k == tries - 1:
                raise
            logging.warning('db read failed (%s), retry %s/%s' % (e.__class__.__name__, k + 1, tries - 1))
            time.sleep(2 * (k + 1))


# 只取匹配用到的字段：字数组里有坐标等大量字段，全取会让每页数据大几倍。数组元素个数和顺序不变，下标仍可用于写库
PAGE_FIELDS = {'name': 1, 'match': 1, 'base_txt': 1, 'match_logs': 1, 'chars.char_id': 1, 'chars.cid': 1, 'chars.txt': 1, 'chars.cmp_txt': 1,
               'chars.deleted': 1, 'columns.column_id': 1, 'columns.cid': 1, 'columns.is_center': 1,
               'columns.deleted': 1}


def load_reel(db, reel_code):
    fields = ['reel_code', 'reel_type', 'format', 'start_volume', 'start_page', 'end_volume', 'end_page']
    return _with_retry(lambda: db.reel.find_one({'reel_code': reel_code}, {f: 1 for f in fields}))


def load_reel_pages(db, reel):
    import helper as hlp
    from web.tw.reel import get_page_select_cond
    pages = _with_retry(lambda: list(db.page.find(get_page_select_cond(reel), PAGE_FIELDS)))
    pages.sort(key=lambda p: hlp.align_code(p['name']))
    return pages


def collect_yinshi(db, reel_codes, vdict):
    """ 收集若干卷的音释字，按页合并（两卷共用的页只保留一份，字取并集）
    返回({页名: {'page', 'idx': set, 'methods': set, 'reels': set}}, {卷编码: 音释字数})
    """
    targets, counts = {}, {}
    for code in reel_codes:
        counts[code] = 0
        reel = load_reel(db, code)
        if not reel or reel.get('reel_type') in EMPTY_REEL_TYPES:
            continue
        for sel in select_reel_yinshi(reel, load_reel_pages(db, reel), vdict):
            t = targets.setdefault(sel['page']['name'],
                                   {'page': sel['page'], 'idx': set(), 'methods': set(), 'reels': set()})
            t['idx'].update(sel['idx'])
            t['methods'].add(sel['method'])
            t['reels'].add(code)
            counts[code] += len(sel['idx'])
    return targets, counts


def sorted_page_names(targets):
    import helper as hlp
    return sorted(targets, key=hlp.align_code)


def build_reference_txt(db, reel_codes, vdict):
    """ 参考文本：各卷音释文本按阅读顺序拼接，页与页之间用换行隔开
    返回(文本, {卷编码: 音释字数}, [(起点, 终点, 页名, [卷编码])])，后者标出文本各段来自哪一页哪一卷
    """
    targets, counts = collect_yinshi(db, reel_codes, vdict)
    texts, spans, offset = [], [], 0
    for name in sorted_page_names(targets):
        t = targets[name]
        txt = page_text(t['page'], t['idx'], vdict)[0]
        texts.append(txt)
        spans.append((offset, offset + len(txt), name, sorted(t['reels'])))
        offset += len(txt) + 1
    return '\n'.join(texts), counts, spans


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


def run_plan(db='tw-test-readonly', direction=DEFAULT_DIRECTION, with_counts=False, mapping=MAPPING_XLSX,
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


def locate_source(ref_txt, spans, match_txt):
    """ 匹配文本来自参考文本的哪些页。返回([(页名, [卷编码])], 备注)；找不到位置时返回([], 原因)
    匹配文本通常是参考文本的原样摘录，直接查找；含■占位等不能原样找到时，退回模糊定位
    """
    m = (match_txt or '').strip('\n')
    if not m:
        return [], 'no match text'
    start = ref_txt.find(m)
    note = ''
    if start >= 0:
        end = start + len(m)
        if ref_txt.count(m) > 1:
            note = 'same text appears %s times in the reference' % ref_txt.count(m)
    else:
        from rapidfuzz import fuzz
        al = fuzz.partial_ratio_alignment(m, ref_txt)
        if al is None or al.score < 60:
            return [], 'source not located'
        start, end, note = al.dest_start, al.dest_end, 'source located by fuzzy search'
    return [(name, reels) for a, b, name, reels in spans if a < end and b > start], note


def _source_fields(hit):
    reels = sorted({r for _, rs in hit for r in rs})
    return {'source_reels': ','.join(reels), 'source_pages': ','.join(name for name, _ in hit)}


REPORT_FIELDS = ['sutra', 'job', 'reference', 'page', 'method', 'n_chars', 'status', 'r_hit2base', 'r_similar2hit',
                 'r_similar2base', 'len_match_txt', 'page_chars', 'page_match_from', 'page_status_before',
                 'page_status_after', 'page_change', 'page_r_hit_before', 'page_r_hit_after', 'page_r_similar_before',
                 'page_r_similar_after', 'found_by', 'leftover_chars', 'source_reels', 'source_pages', 'source_note',
                 'applied', 'n_same', 'n_placeholder', 'n_diff', 'action', 'flag', 'note', 'target_txt', 'match_txt']
SUMMARY_FIELDS = ['sutra', 'jobs', 'empty_jobs', 'reference', 'pages', 'status_5', 'status_4', 'status_3', 'status_2',
                  'no_status', 'leftover_pages', 'page_status_before', 'page_status_after', 'pages_improved',
                  'avg_page_similar_before', 'avg_page_similar_after', 'avg_hit2base', 'avg_similar2hit', 'chars', 'same', 'placeholder', 'diff', 'pct_same',
                  'review_pages']


def page_status_summary(rows):
    """ 整页匹配状态补上音释比对文本前后的汇总：返回(之前的分布, 之后的分布, 状态提高的页数, 页数, 前后平均整页相似率, 会填入cmp_txt的页数)
    分布如'5:12 4:30 3:8 2:3 -:1'，'-'是原来没有整页匹配的页。只统计有整页对比的页(page_change有值)"""
    rs = [r for r in rows if r.get('page_change')]

    def dist(key):
        c = {}
        for r in rs:
            k = r.get(key) if r.get(key) != '' else '-'
            c[k] = c.get(k, 0) + 1
        return ' '.join('%s:%s' % (k, c[k]) for k in sorted(c, key=lambda x: -1 if x == '-' else x, reverse=True))

    avg = lambda key: round(sum(r.get(key) or 0 for r in rs) / len(rs), 3) if rs else ''
    return (dist('page_status_before'), dist('page_status_after'), sum(1 for r in rs if r['page_change'] == 'improved'),
            len(rs), avg('page_r_similar_before'), avg('page_r_similar_after'),
            sum(1 for r in rs if r['page_change'] != 'not applied'))


def summarize_sutras(rows):
    """ 按经汇总页级结果：各状态的页数、平均匹配率、填充字数，以及需要人工看的页(状态2、无状态)
    rows是各页的报告行(REPORT_FIELDS)，没有sutra的行忽略
    """
    groups = {}
    for r in rows:
        if r.get('sutra'):
            groups.setdefault(r['sutra'], []).append(r)
    out = []
    for sutra, rs in groups.items():
        with_status = [r for r in rs if r.get('status')]
        ps = page_status_summary(rs)
        rated = [r for r in with_status if r.get('r_hit2base') is not None]  # 跳过已完成的页没有匹配率
        n = len(rated)
        same = sum(r.get('n_same') or 0 for r in rs)
        ph = sum(r.get('n_placeholder') or 0 for r in rs)
        diff = sum(r.get('n_diff') or 0 for r in rs)
        out.append({
            'sutra': sutra,
            'jobs': ','.join(dict.fromkeys(r['job'] for r in rs if r.get('job'))),
            'empty_jobs': ','.join(dict.fromkeys(
                '%s(%s)' % (r['job'], r['action']) for r in rs
                if r.get('action') in ('no_target', 'no_reference', 'job_error'))),
            'reference': ' | '.join(dict.fromkeys(r['reference'] for r in rs if r.get('reference'))),
            'pages': len([r for r in rs if r.get('page')]),
            'status_5': sum(1 for r in with_status if r['status'] == 5),
            'status_4': sum(1 for r in with_status if r['status'] == 4),
            'status_3': sum(1 for r in with_status if r['status'] == 3),
            'status_2': sum(1 for r in with_status if r['status'] == 2),
            'no_status': len([r for r in rs if r.get('page') and not r.get('status')]),
            'leftover_pages': sum(1 for r in rs if r.get('leftover_chars')),
            'page_status_before': ps[0], 'page_status_after': ps[1], 'pages_improved': ps[2],
            'avg_page_similar_before': ps[4], 'avg_page_similar_after': ps[5],
            'avg_hit2base': round(sum(r['r_hit2base'] for r in rated) / n, 3) if n else '',
            'avg_similar2hit': round(sum(r['r_similar2hit'] or 0 for r in rated) / n, 3) if n else '',
            'chars': sum(r.get('n_chars') or 0 for r in rs),
            'same': same, 'placeholder': ph, 'diff': diff,
            'pct_same': round(100.0 * same / (same + ph + diff), 1) if same + ph + diff else '',
            'review_pages': ','.join(r['page'] for r in rs if r.get('page') and (r.get('status') or 0) < 3),
        })
    return out


def leftover_segments(cmps):
    """ 把按阅读顺序的cmp_txt列表切成连续的段：[(是否没有对应文本, 起, 止)]；空或■表示没有对应文本"""
    segs = []
    for i, c in enumerate(cmps):
        missing = not c or c == '■'
        if segs and segs[-1][0] == missing:
            segs[-1][2] = i + 1
        else:
            segs.append([missing, i, i + 1])
    return [tuple(x) for x in segs]


def assemble_match_txt(cmps, segments, rescued):
    """ 按目标字的顺序拼出新的匹配文本：有对应文本的段用已对上的cmp_txt，补找到的(rescued: [(起, 止, 文本)]，
    起止是cmps下标)按位置放回，仍然没有对应文本的字略去（应用时它们仍是■）"""
    parts = []
    for missing, a, b in segments:
        if not missing:
            parts.append(''.join(cmps[a:b]))
        else:
            parts += [txt for ra, rb, txt in sorted(rescued) if a <= ra and rb <= b]
    return '\n'.join(parts)


def leftover_candidates(cols, a, b):
    """ 没有对应文本的一段字[a, b)里，可以单独去找的子段：起止都落在列的边界上，不少于LEFTOVER_MIN_LEN字，从长到短
    cols是按阅读顺序每个字所在的列。整段里若夹着另一版写法不同的字，整段找不到，去掉它们所在的列后往往能找到"""
    bounds = [a] + [i for i in range(a + 1, b) if cols[i] != cols[i - 1]] + [b]
    cands = [(x, y) for i, x in enumerate(bounds) for y in bounds[i + 1:] if y - x >= LEFTOVER_MIN_LEN]
    return sorted(cands, key=lambda c: c[0] - c[1])


def rescue_leftovers(page, t, vdict, index_id, first_match, ref_txt):
    """ 首次匹配后，把没有对应文本的目标字再单独到参考文本里找，处理同一页两块文字前后顺序颠倒的情况
    返回(新匹配文本, 补找到的字数, [补找到的文本])；没有补找到时原样返回(first_match, 0, [])
    """
    from util.find_match import find_best_match
    from web.tw.match import get_match_info
    status, ordered, proxies = _fill_cmp(page, t, index_id, vdict, min_status=0, overwrite=True,
                                         log={'index_id': index_id, 'match_txt': first_match, 'status': 5})
    if status != 'ok':
        return first_match, 0, []
    cmps = [p.get('cmp_txt') for p in proxies]
    cols = [page['chars'][i]['char_id'].rsplit('c', 1)[0] for i in ordered]
    segments = leftover_segments(cmps)
    todo = [(a, b) for missing, a, b in segments if missing and b - a >= LEFTOVER_MIN_LEN]
    rescued, tries = [], 0
    while todo and tries < LEFTOVER_MAX_TRIES:
        a, b = todo.pop(0)
        for x, y in leftover_candidates(cols, a, b):
            if tries >= LEFTOVER_MAX_TRIES:
                break
            tries += 1
            run_txt = ''.join(p['txt'] for p in proxies[x:y])
            m2 = find_best_match(run_txt, ref_txt)[0].strip('\n')
            if not m2 or m2 in first_match or any(m2 in r[2] for r in rescued):  # 没找到，或就是已经用过的那段
                continue
            if get_match_info(run_txt, m2)['status'] < 3:
                continue
            rescued.append((x, y, m2))
            todo += [(u, v) for u, v in ((a, x), (y, b)) if v - u >= LEFTOVER_MIN_LEN]  # 剩下的两头还可以再找
            break
    if not rescued:
        return first_match, 0, []
    return (assemble_match_txt(cmps, segments, rescued), sum(y - x for x, y, _ in rescued),
            [m for _, _, m in sorted(rescued)])


PAGE_MATCH_FIELDS = ['page_chars', 'page_match_from', 'page_status_before', 'page_status_after', 'page_change',
                      'page_r_hit_before', 'page_r_hit_after', 'page_r_similar_before', 'page_r_similar_after']


def page_match_change(page, index_id, log, applied):
    """ 整页匹配状态在补上音释比对文本前后的对比，不写库
    整页状态(page.match)是各条match_logs里最好的一条，每条都拿整页文本去比：思溪藏页的音释字不在cbeta里，
    这些字算作没匹配上，拉低整页状态。音释字得到福州藏的比对文本后，把这些字的命中数加到整页原有的命中数上，
    按平台自己的规则(get_status)重新算状态，再和原有的最好一条比，取更好的。
    index_id：本工具写入的日志id，计算“之前”时不算这一条。log：本页音释的匹配日志。applied：这条日志会不会被填入cmp_txt，
    没填就等于没变化，但整页原来完全没有匹配的页例外：音释匹配是它现在唯一的匹配，照样按它重新算状态。
    假设整页原有的命中里不含音释字，命中数以整页字数封顶。
    返回PAGE_MATCH_FIELDS里的字段
    """
    from web.tw.match import get_best_match, get_status
    others = [dict(x) for x in page.get('match_logs') or [] if x.get('index_id') != index_id]
    prev = get_best_match(others)
    if not prev and isinstance(page.get('match'), dict) and page['match'].get('index_id') != index_id:
        prev = dict(page['match'])
    prev = prev or {}
    base_len = prev.get('len_base_txt') or len(_select_all(page))

    def count(d, key, ratio_key):  # 字数：优先用记录里的字数，没有就用比例推算
        return d[key] if d.get(key) is not None else round((d.get(ratio_key) or 0) * base_len)

    before = {'status': prev.get('status'), 'r_hit2base': prev.get('r_hit2base'),
              'r_similar2base': prev.get('r_similar2base')}
    after = before
    if (applied or prev.get('status') is None) and base_len:
        hit = min(base_len, count(prev, 'len_hit', 'r_hit2base') + (log.get('len_hit') or 0))
        similar = min(hit, count(prev, 'len_similar', 'r_similar2base') + (log.get('len_similar') or 0))
        r_hit, r_sim2base = round(hit / base_len, 3), round(similar / base_len, 3)
        r_sim2hit = round(similar / hit, 3) if hit else 0
        # get_status把“匹配文本长度不小于整页的2倍”当作不匹配。原有匹配文本可能是不相干的一段(长度常接近整页，
        # 状态2的页尤其如此)，把它的长度加上音释匹配文本的长度会误超过2倍，所以匹配文本长度按命中字数算
        combined = {'status': get_status(r_hit, r_sim2hit, r_hit, page.get('base_txt') or ''),
                    'r_hit2base': r_hit, 'r_similar2hit': r_sim2hit, 'r_similar2base': r_sim2base}
        prev_hit, prev_similar = count(prev, 'len_hit', 'r_hit2base'), count(prev, 'len_similar', 'r_similar2base')
        earlier = dict({'r_similar2base': round(prev_similar / base_len, 3),  # 旧记录缺比例时按字数补上，比较要用
                        'r_similar2hit': round(prev_similar / prev_hit, 3) if prev_hit else 0}, **prev)
        best = get_best_match([earlier, combined] if prev.get('status') else [combined])
        after = best if best is combined else before
    change = 'not applied' if not applied else (
        'improved' if (after.get('status') or 0) > (before.get('status') or 0) else 'same status')
    pick = lambda d, k: d.get(k) if d.get(k) is not None else ''
    return {'page_chars': base_len, 'page_match_from': prev.get('index_id') or '',
            'page_status_before': pick(before, 'status'), 'page_status_after': pick(after, 'status'),
            'page_change': change,
            'page_r_hit_before': pick(before, 'r_hit2base'), 'page_r_hit_after': pick(after, 'r_hit2base'),
            'page_r_similar_before': pick(before, 'r_similar2base'),
            'page_r_similar_after': pick(after, 'r_similar2base')}


def _match_target(job_id, name, t, ref_txt, vdict, index_id, reference_reels, force=False, spans=None, min_status=3):
    """ 为一页目标音释字在参考文本里查找匹配。返回(报告行, match_log或None)，不写库
    spans是build_reference_txt给出的各页位置，有则在报告和日志里记下匹配文本来自参考的哪些页/卷
    min_status：报告里整页状态的前后对比按“状态不低于它才会填入cmp_txt”来算
    """
    from util.find_match import find_best_match
    from web.tw.match import get_match_info
    page = t['page']
    base_txt, ordered = page_text(page, t['idx'], vdict)
    row = {'sutra': job_id.split('_')[0], 'job': job_id, 'reference': _span(reference_reels), 'page': name,
           'method': ','.join(sorted(t['methods'])), 'n_chars': len(ordered)}
    if not ordered:  # 短的音释也要匹配，只有完全没字时才无可查找
        return dict(row, action='skipped_empty'), None
    own = _own_log(page, index_id)
    if own and own.get('status') == 5 and not force:
        return dict(row, action='skipped_done', status=5), None
    try:
        match_txt, by = find_best_match(base_txt, ref_txt)[0], 'find_best_match'
        if not match_txt.strip() and len(ordered) <= SHORT_TXT_LEN:
            match_txt, by = find_short_match(base_txt, ref_txt), 'short'
        pieces, leftover = [match_txt], 0  # pieces：匹配文本由参考文本里哪几段拼成，用于查来源页
        if by == 'find_best_match' and match_txt.strip():
            new_txt, leftover, found = rescue_leftovers(page, t, vdict, index_id, match_txt, ref_txt)
            if leftover:
                match_txt, pieces = new_txt, pieces + found
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
    row['found_by'] = by
    if leftover:
        row.update(leftover_chars=leftover, note='leftover pass: +%s chars' % leftover)
        log['leftover_chars'] = leftover
    row.update(page_match_change(page, index_id, log, info['status'] >= min_status))
    if spans is not None:
        hits, notes = [], []
        for piece in pieces:
            h, n = locate_source(ref_txt, spans, piece)
            hits += [x for x in h if x not in hits]
            if n and n not in notes:
                notes.append(n)
        row.update(_source_fields(hits), source_note='; '.join(notes))
        log.update(_source_fields(hits))
    return row, log


def _fill_cmp(page, t, index_id, vdict, log=None, min_status=3, overwrite=False):
    """ 在内存里把匹配文本填入目标音释字的cmp_txt，不写库。log默认取页里index_id对应的日志
    返回(状态, 按阅读顺序的字下标, 替身字列表)；状态：ok/no_log/status_too_low/apply_failed
    用单字的比对文本做替身参与对齐，避免异体字编码(多个字符)破坏字数对应
    overwrite：替身从空cmp_txt开始，等于按最新的匹配文本重填，而不是保留已有的cmp_txt
    """
    from web.tw.page import apply_txt2missingchars
    log = log or _own_log(page, index_id)
    if not log:
        return 'no_log', [], []
    if (log.get('status') or 0) < min_status:
        return 'status_too_low', [], []
    ordered = order_chars(page, t['idx'])
    proxies = [{'txt': norm_char(page['chars'][i], vdict),
                'cmp_txt': None if overwrite else page['chars'][i].get('cmp_txt')} for i in ordered]
    view = dict(page, match_logs=[log])
    if not apply_txt2missingchars(None, view, index_id=index_id, field='cmp_txt', chars=proxies):
        return 'apply_failed', ordered, []
    return 'ok', ordered, proxies


def _cmp_changes(page, ordered, proxies):
    """ 填充后发生变化的字：{page['chars']下标: 新cmp_txt}；新值为空的字不算(不会把已有内容清掉)"""
    return {i: p['cmp_txt'] for i, p in zip(ordered, proxies)
            if p.get('cmp_txt') and p['cmp_txt'] != page['chars'][i].get('cmp_txt')}


def run_match(direction=DEFAULT_DIRECTION, db='tw-test-readonly', only='', commit=False, force=False, set_page_match=False,
              min_status=3, flag_date=None, mapping=MAPPING_XLSX, report_dir=REPORT_DIR):
    """ 在窗口内为目标页查找参考文本，写入match_logs（index_id见DIRECTIONS）。
    默认预演不写库；已有完全匹配(status=5)的页跳过，force可重跑；
    默认不改page.match(音释文本占比会扭曲整页状态)，set_page_match可开启
    min_status：只用于报告里整页状态前后对比(page_status_after)，假设状态不低于它的页才会填入cmp_txt；match本身不受它影响
    flag_date：写库(--commit)时给被改的页打标记(字段见FLAG_FIELD)用的日期YYYYMMDD，不指定就是今天；
    标记=日期+补上音释比对文本后重新算出的整页匹配状态(0-5)，如20260921004
    """
    import helper as hlp
    from web.tw.match import get_best_match
    hlp.set_logging('match_yinshi')
    index_id = DIRECTIONS[direction]['index_id']
    dbh = hlp.get_db(db)
    vdict = load_variants()
    _, _, _, jobs = _prepare(dbh, direction, only, mapping)
    date_prefix = flag_date_prefix(flag_date)
    logging.info('%s: %s jobs, commit=%s, db=%s%s' % (direction, len(jobs), commit, db, (
        ', pages written get %s=%s000..%s005 (whole-page status after yinshi)' % (
            FLAG_FIELD, date_prefix, date_prefix)) if commit else ''))

    report, stats = [], {}
    for j, job in enumerate(jobs):
        logging.info('[%s/%s] %s <- %s' % (j + 1, len(jobs), _span(job['target_reels']), _span(job['reference_reels'])))
        ref_txt, ref_counts, spans = build_reference_txt(dbh, job['reference_reels'], vdict)
        targets, _ = collect_yinshi(dbh, job['target_reels'], vdict)
        if not ref_txt:
            report.append({'sutra': job['id'].split('_')[0], 'job': job['id'], 'action': 'no_reference',
                           'note': 'no yinshi text in %s' % ref_counts})
            continue
        if not targets:
            report.append({'sutra': job['id'].split('_')[0], 'job': job['id'], 'action': 'no_target',
                           'note': 'no yinshi chars in %s' % _span(job['target_reels'])})
            continue
        for name in sorted_page_names(targets):
            page = targets[name]['page']
            row, log = _match_target(job['id'], name, targets[name], ref_txt, vdict, index_id,
                                     job['reference_reels'], force, spans, min_status)
            if log is not None:
                logs = [l for l in page.get('match_logs') or [] if l.get('index_id') != index_id] + [log]
                if commit:
                    row['flag'] = status_flag(date_prefix, row.get('page_status_after'))
                    update = {'match_logs': logs, FLAG_FIELD: row['flag']}
                    if set_page_match:
                        update['match'] = get_best_match(logs)
                    dbh.page.update_one({'_id': page['_id']}, {'$set': update})
                row['action'] = 'written' if commit else 'dry_run'
                stats[log['status']] = stats.get(log['status'], 0) + 1
            report.append(row)
    now = datetime.now().strftime('%Y%m%d-%H%M%S')
    write_csv(path.join(report_dir, 'match_%s-%s.csv' % (direction, now)), report, REPORT_FIELDS)
    write_csv(path.join(report_dir, 'match_%s-%s_by_sutra.csv' % (direction, now)), summarize_sutras(report),
              SUMMARY_FIELDS)
    logging.info('status distribution (2 no match .. 5 exact): %s' % dict(sorted(stats.items())))


def run_apply(direction=DEFAULT_DIRECTION, db='tw-test-readonly', only='', min_status=3, commit=False, overwrite=False,
              flag_date=None, mapping=MAPPING_XLSX, report_dir=REPORT_DIR):
    """ 把match_logs里状态>=min_status的匹配文本填入目标音释字的cmp_txt
    默认只填空缺或■的字，不覆盖已有内容；overwrite=True时按最新的匹配文本重填这些音释字，已有的cmp_txt会被改写
    （包括人工改过的，所以先不加--commit看报告里的overwritten数）
    flag_date：写库(--commit)时给被改的页(cmp_txt真的有变化的页)打标记(字段见FLAG_FIELD)用的日期YYYYMMDD，不指定就是今天；
    标记=日期+补上音释比对文本后重新算出的整页匹配状态(0-5)，如20260921004
    """
    import helper as hlp
    hlp.set_logging('match_yinshi')
    index_id = DIRECTIONS[direction]['index_id']
    dbh = hlp.get_db(db)
    vdict = load_variants()
    _, _, _, jobs = _prepare(dbh, direction, only, mapping)
    date_prefix = flag_date_prefix(flag_date)
    logging.info('%s: %s jobs, min_status=%s, commit=%s, overwrite=%s, db=%s%s' % (
        direction, len(jobs), min_status, commit, overwrite, db, (
            ', pages changed get %s=%s000..%s005 (whole-page status after yinshi)' % (
                FLAG_FIELD, date_prefix, date_prefix)) if commit else ''))

    report = []
    for j, job in enumerate(jobs):
        logging.info('[%s/%s] %s' % (j + 1, len(jobs), _span(job['target_reels'])))
        targets, _ = collect_yinshi(dbh, job['target_reels'], vdict)
        for name in sorted_page_names(targets):
            t = targets[name]
            page = t['page']
            row = {'job': job['id'], 'page': name, 'method': ','.join(sorted(t['methods'])), 'n_chars': len(t['idx'])}
            status, ordered, proxies = _fill_cmp(page, t, index_id, vdict, min_status=min_status, overwrite=overwrite)
            log = _own_log(page, index_id)
            if status != 'ok':
                report.append(dict(row, action=status, status=log and log.get('status')))
                continue
            row.update(page_match_change(page, index_id, log, True))
            changes = _cmp_changes(page, ordered, proxies)
            if commit and changes:
                row['flag'] = status_flag(date_prefix, row.get('page_status_after'))
                dbh.page.update_one({'_id': page['_id']},
                                    {'$set': dict({'chars.%s.cmp_txt' % i: v for i, v in changes.items()},
                                                  **{FLAG_FIELD: row['flag']})})
            report.append(dict(row, action='written' if commit else 'dry_run', status=log.get('status'),
                               note='%s chars changed (%s overwrote an existing cmp_txt), %s placeholders' % (
                                   len(changes), sum(1 for i in changes if page['chars'][i].get('cmp_txt')),
                                   sum(1 for v in changes.values() if v == '■'))))
    now = datetime.now().strftime('%Y%m%d-%H%M%S')
    write_csv(path.join(report_dir, 'apply_%s-%s.csv' % (direction, now)), report, REPORT_FIELDS)


def render_page_view(page, t, vdict, cmp_by_idx):
    """ 一页音释的列对照，每列三行：原字(txt)、比对字(cmp)、差异标记（＾表示与原字不同，含■占位）"""
    lines = []
    for col_id, ids in group_columns(page, t['idx']):
        own = ''.join(norm_char(page['chars'][i], vdict) for i in ids)
        cmp = ''.join((cmp_by_idx.get(i) or '＿')[0] for i in ids)
        marks = ''.join('　' if a == b else '＾' for a, b in zip(own, cmp))
        lines += ['%-5s txt: %s' % (col_id, own), '%-5s cmp: %s' % ('', cmp), '%-5s      %s' % ('', marks)]
    return lines


def _sutra_of(job):
    return job['z_reels'][0].split('_')[0]


def _sutra_line(r):
    return ('%s  pages=%s  windows without pages=%s  yinshi status 5/4/3/2=%s/%s/%s/%s  no_status=%s  avg hit2base=%s similar2hit=%s  '
            'yinshi chars=%s; of the applied chars: same=%s placeholder=%s diff=%s (%s%% same)  '
            'whole-page status %s -> %s (improved %s, avg similar2base %s -> %s)' % (
                r['sutra'], r['pages'], len(r['empty_jobs'].split(',')) if r['empty_jobs'] else 0, r['status_5'], r['status_4'], r['status_3'], r['status_2'], r['no_status'],
                r['avg_hit2base'], r['avg_similar2hit'], r['chars'], r['same'], r['placeholder'], r['diff'],
                r['pct_same'], r['page_status_before'], r['page_status_after'], r['pages_improved'],
                r['avg_page_similar_before'], r['avg_page_similar_after']))


def run_preview(sutra='', direction=DEFAULT_DIRECTION, db='tw-test-readonly', min_status=3, detail=True, overwrite=False,
                mapping=MAPPING_XLSX, report_dir=REPORT_DIR):
    """ 试跑并出报告，全程只读库：在内存里完成match和apply，没有任何写库的代码路径。
    sutra: 福州藏经号，如 FZ0002 或 FZ0002,FZ0003（两个方向都用福州藏经号）；不填=所有有音释卷的经
    detail: False时不输出逐页逐列对照，只保留汇总和pages.csv（全库运行时文件更小）
    min_status: 状态低于该值的页只显示匹配文本，不做cmp_txt填充（与apply一致）
    overwrite: 与apply的overwrite一致，忽略已有的cmp_txt，按新匹配文本重填后对照
    输出目录 report_dir/preview_<方向>_<经>-<时间>/：
        summary.txt          总览和每部经一行的汇总
        summary_by_sutra.csv 每部经一行：各状态页数、平均匹配率、填充字数、需人工看的页
        pages.csv            每页一行：匹配到哪些卷/哪些页(source_reels/source_pages)、匹配率、填充统计、原文与匹配文本
        <经号>.txt           该经逐页逐列对照（detail=True时）
    """
    import helper as hlp
    hlp.set_logging('match_yinshi')
    index_id = DIRECTIONS[direction]['index_id']
    sutras = _parse_only(sutra)
    dbh = hlp.get_db(db)
    vdict = load_variants()
    _, _, skipped, jobs = _prepare(dbh, direction, '', mapping)
    if sutras:
        jobs = [j for j in jobs if any(z.split('_')[0] in sutras for z in j['z_reels'])]
    if not jobs:
        logging.info('no %s jobs for %s: not in the mapping sheet/DB, or it has no usable yinshi z reel'
                     % (direction, sorted(sutras) or 'all'))
        return
    logging.info('preview %s %s: %s jobs, db=%s (read-only)' % (direction, sorted(sutras) or 'all', len(jobs), db))

    now = datetime.now().strftime('%Y%m%d-%H%M%S')
    label = '+'.join(sorted(sutras)) if 0 < len(sutras) <= 3 else ('%s_sutras' % len(sutras) if sutras else 'all')
    out_dir = path.join(report_dir, 'preview_%s_%s-%s' % (direction, label, now))
    sections, rows, stats = {}, [], {}  # 经号 -> 详细行

    def write_outputs():
        summary = summarize_sutras(rows)
        head = ['preview  direction=%s  sutra=%s  db=%s  (read-only, nothing written)' % (
                    direction, sorted(sutras) or 'all', db),
                'jobs=%s  pages=%s  status distribution (2 no match .. 5 exact): %s' % (
                    len(jobs), len([r for r in rows if r.get('page')]), dict(sorted(stats.items()))),
                'whole-page match status before -> after the yinshi cmp_txt is added, over the %s pages this run '
                'matched yinshi on (%s of them reach --min_status, so their cmp_txt would be filled; the rest stay '
                'as they are): %s -> %s; improved %s pages; avg whole-page similar2base %s -> %s' % (
                    (lambda t: (t[3], t[6], t[0] or '-', t[1] or '-', t[2], t[4], t[5]))(page_status_summary(rows))),
                'whole-page status: 0 = too short to search, 1 = nothing found, 2 = no match, 3 = medium, '
                '4 = high, 5 = exact; "-" = no earlier whole-page match',
                'legend: txt = the target char, cmp = cmp_txt that would be filled, ＾ = differs (■ = no counterpart)',
                'files: summary_by_sutra.csv (one row per sutra), pages.csv (one row per page, with the source '
                'reels/pages), <sutra>.txt (column by column)', '', 'per sutra:'] + [_sutra_line(r) for r in summary]
        os.makedirs(out_dir, exist_ok=True)
        with open(path.join(out_dir, 'summary.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(head) + '\n')
        write_csv(path.join(out_dir, 'summary_by_sutra.csv'), summary, SUMMARY_FIELDS)
        write_csv(path.join(out_dir, 'pages.csv'), rows, REPORT_FIELDS)
        if detail:
            by_sutra = {r['sutra']: r for r in summary}
            for name, lines in sections.items():
                with open(path.join(out_dir, name + '.txt'), 'w', encoding='utf-8') as f:
                    f.write('\n'.join([_sutra_line(by_sutra[name])] + lines) + '\n' if name in by_sutra
                            else '\n'.join(lines) + '\n')
        for line in head:
            logging.info(line)
        logging.info('reports in %s' % out_dir)

    try:
        for j, job in enumerate(jobs):
            logging.info('[%s/%s] %s <- %s' % (j + 1, len(jobs), _span(job['target_reels']), _span(job['reference_reels'])))
            out = sections.setdefault(_sutra_of(job), [])
            try:
                _preview_job(job, dbh, vdict, index_id, min_status, detail, out, rows, stats, direction, overwrite)
            except Exception as e:  # 单个任务出错不影响其它经的报告
                logging.exception('job %s failed' % job['id'])
                out.append('!! job %s failed: %s' % (job['id'], e))
                rows.append({'sutra': _sutra_of(job), 'job': job['id'], 'action': 'job_error', 'note': str(e)})
    finally:
        write_outputs()


def _preview_job(job, dbh, vdict, index_id, min_status, detail, out, rows, stats, direction=DEFAULT_DIRECTION, overwrite=False):
    """ 试跑一个任务：逐页匹配并在内存里填cmp_txt，结果追加到out(详细行)、rows(页级报告行)、stats(状态分布)"""
    ref_txt, ref_counts, spans = build_reference_txt(dbh, job['reference_reels'], vdict)
    targets, target_counts = collect_yinshi(dbh, job['target_reels'], vdict)
    out += ['', '#' * 8 + ' %s  <-  %s' % (_span(job['target_reels']), _span(job['reference_reels'])),
            'reference yinshi chars per reel: %s' % {k: v for k, v in ref_counts.items() if v},
            'target yinshi chars per reel: %s' % {k: v for k, v in target_counts.items() if v}]
    base = {'sutra': _sutra_of(job), 'job': job['id'], 'reference': _span(job['reference_reels'])}
    if not ref_txt:
        out.append('!! no reference yinshi text, nothing to match')
        rows.append(dict(base, action='no_reference', note='no yinshi text in %s' % ref_counts))
        return
    if not targets:
        out.append('!! no target yinshi chars (%s reels have no E-format columns / no text), nothing to match'
                   % DIRECTIONS[direction]['target'])
        rows.append(dict(base, action='no_target', note='no yinshi chars in %s' % _span(job['target_reels'])))
        return
    for name in sorted_page_names(targets):
        t = targets[name]
        page = t['page']
        row, log = _match_target(job['id'], name, t, ref_txt, vdict, index_id, job['reference_reels'], force=True,
                                 spans=spans, min_status=min_status)
        base_txt, _ = page_text(page, t['idx'], vdict)
        row['target_txt'] = base_txt.replace('\n', '/')
        head = '=== %s | method=%s | chars=%s' % (name, row['method'], row['n_chars'])
        rows.append(row)
        if log is None:
            out += ['', head + ' | %s %s' % (row['action'], row.get('note', ''))]
            continue
        stats[log['status']] = stats.get(log['status'], 0) + 1
        row['match_txt'] = log['match_txt'].replace('\n', '/')
        head += ' | status=%s hit2base=%s similar2hit=%s' % (log['status'], log['r_hit2base'], log['r_similar2hit'])
        if log.get('found_by') == 'short':
            head += ' [short text search]'
        if log.get('leftover_chars'):
            head += ' [leftover pass +%s chars]' % log['leftover_chars']
        head += (' | matched %s: %s' % (row['source_reels'], row['source_pages'])
                 if row.get('source_reels') else ' | no source located')
        status, ordered, proxies = _fill_cmp(page, t, index_id, vdict, log=log, min_status=min_status, overwrite=overwrite)
        if status != 'ok':
            row['action'] = 'not_applied (%s)' % status
            out += ['', head + ' | not applied (%s); matched text:' % status, '  ' + row['match_txt']]
            continue
        cmp_by_idx = {i: p['cmp_txt'] for i, p in zip(ordered, proxies)}
        n_same = sum(1 for i, p in zip(ordered, proxies) if p['cmp_txt'] == p['txt'])
        n_ph = sum(1 for p in proxies if p['cmp_txt'] == '■')
        row.update(action='previewed', applied=True, n_same=n_same, n_placeholder=n_ph,
                   n_diff=len(ordered) - n_same - n_ph)
        out += ['', head + ' | same=%s placeholder(■)=%s other-diff=%s' % (n_same, n_ph, row['n_diff'])]
        if detail:
            out += render_page_view(page, t, vdict, cmp_by_idx)

def has_e_format(fmt):
    """ reel.format里的一条(某页的格式)是否含E(音释)：整列的columns=[[格式, 列cid]]或字的chars=[[格式, 列cid, 起, 止]]"""
    return any(x and x[0] == 'E' for x in (fmt.get('columns') or []) + (fmt.get('chars') or []))


def find_e_pages(db, reel_regex=''):
    """ 库里所有含E(音释)格式的页：{页名: [有E格式的卷编码]}。E格式记在卷的format里，按页名对应，不必读页，
    也不限于对照表里的经"""
    cond = {'format.0': {'$exists': True}}
    if reel_regex:
        cond['reel_code'] = {'$regex': reel_regex}
    proj = {'reel_code': 1, 'format.name': 1, 'format.columns': 1, 'format.chars': 1}

    def scan():
        pages = {}
        for reel in db.reel.find(cond, proj):
            for fmt in reel.get('format') or []:
                if fmt.get('name') and has_e_format(fmt):
                    pages.setdefault(fmt['name'], []).append(reel['reel_code'])
        return pages
    return _with_retry(scan)


def run_flag_e(value, field='flag1', db='tw-test-readonly', reel_regex='', keep_existing=False, commit=False,
               report_dir=REPORT_DIR):
    """ 给库里所有含E(音释)格式的页打标记，不限于对照表里的经，也不需要匹配。默认只预演，加--commit才写库。
    value：写入的值，如--value=20260921111；field：写入的字段，默认flag1
    reel_regex：只看卷编码符合它的卷，如--reel_regex=^SX(默认全部)
    keep_existing：页上该字段已有别的值时不改（不加则覆盖）。flag1在别的脚本里也用作批次标记和查询条件，
    覆盖前先看预演报告里的prev_flag，或加keep_existing
    输出flag_e-<时间>.csv：每页一行(页名、有E格式的卷、原来的值、处理结果)
    """
    import helper as hlp
    hlp.set_logging('match_yinshi')
    value = int(str(value).strip())
    dbh = hlp.get_db(db)
    epages = find_e_pages(dbh, reel_regex)
    names = sorted(epages, key=hlp.align_code)
    logging.info('%s pages with E format found in %s reel filter=%r, db=%s, commit=%s' % (
        len(names), 'all reels' if not reel_regex else 'the reels matching', reel_regex, db, commit))

    rows, before = [], {}
    for i in range(0, len(names), 500):
        chunk = names[i:i + 500]
        found = {d['name']: d for d in _with_retry(lambda: list(dbh.page.find({'name': {'$in': chunk}}, {'name': 1, field: 1})))}
        todo = []
        for name in chunk:
            doc = found.get(name)
            prev = doc.get(field) if doc else None
            has_prev = prev not in (None, '')
            if not doc:
                action = 'no_page'
            elif prev == value:
                action = 'already_set'
            elif has_prev and keep_existing:
                action = 'kept_existing'
            else:
                action = 'written' if commit else 'dry_run'
                todo.append(name)
                if has_prev:
                    before[prev] = before.get(prev, 0) + 1
            rows.append({'page': name, 'reels': ','.join(epages[name]), 'prev_flag': '' if prev is None else prev,
                         'action': action})
        if commit and todo:
            _with_retry(lambda: dbh.page.update_many({'name': {'$in': todo}}, {'$set': {field: value}}))
    now = datetime.now().strftime('%Y%m%d-%H%M%S')
    write_csv(path.join(report_dir, 'flag_e-%s.csv' % now), rows, ['page', 'reels', 'prev_flag', 'action'])
    count = {}
    for r in rows:
        count[r['action']] = count.get(r['action'], 0) + 1
    logging.info('%s=%s: %s' % (field, value, count))
    if before:
        top = sorted(before.items(), key=lambda kv: -kv[1])
        logging.warning('%s pages already had another %s value that %s: %s' % (
            sum(before.values()), field, 'is overwritten' if commit else 'would be overwritten',
            ', '.join('%s x%s' % kv for kv in top[:10]) + (' ...' if len(top) > 10 else '')))


# endregion


if __name__ == '__main__':
    import fire

    fire.Fire({'plan': run_plan, 'match': run_match, 'apply': run_apply, 'preview': run_preview, 'flag_e': run_flag_e})
