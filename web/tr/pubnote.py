import re
import sys
import csv
import logging
from os import path as osp
from datetime import datetime

sys.path.append(osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__)))))

import helper as hp
from util.diff import diff
from util.uni2std import is_family
from web.tw.page import get_base_txt, get_page_cids

cache = {}


def step1_import_base_csv(db):
    """ 将金雷的整理结果导入数据库"""
    fp = osp.join(hp.BASE_DIR, 'web/tr/data/牌记资料整理-金雷.csv')
    with open(fp, 'r', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    items = []
    head = ['sn', 'vol', 'no', 'word_txt', 'sutra_name', 'reel_no', 'vol_page',
            'page_name', 'reel_code', 'uni_txt', 'src', 'remark',
            'std_txt', 'page_name2', 'reel_code2']
    for r in rows[1:]:
        item = dict(zip(head, r))
        for k, v in item.items():
            item[k] = v.strip()
        items.append(item)
    db.pubnote0.delete_many({})
    r = db.pubnote0.insert_many(items)
    print(len(items), len(r.inserted_ids))


def split_vol_page_info(vol_page_info):
    """ 拆分word中合并的册页信息"""
    vol, pages = vol_page_info.split('／')
    pages = re.sub('[第页]', '', pages)
    page_nos = []
    for seg in pages.split('、'):
        if '～' not in seg:
            page_nos.append(int(seg))
        else:
            start, end = seg.split('～')
            page_nos += list(range(int(start), int(end) + 1))
    return [f'{vol}／第{n}页' for n in page_nos]


def step2_check_and_split(db):
    """在金雷整理的基础上，将合并的页码拆分成多条"""
    items2, idx = [], 1
    items1 = list(db.pubnote0.find({}, {'_id': 0}))
    for it in items1:
        if '～' in it['vol_page'] or '、' in it['vol_page']:
            vol_pages = split_vol_page_info(it['vol_page'])
            for vol_page in vol_pages:
                it2 = it.copy()
                it2['sn'] = idx
                idx += 1
                it2['vol_page'] = vol_page
                it2['vol_page_splited'] = True
                fields = ['page_name', 'reel_code', 'uni_txt', 'src', 'std_txt']
                for f in fields:
                    it2[f] = ''
                items2.append(it2)
        else:
            it['sn'] = idx
            idx += 1
            it['vol_page_splited'] = False
            items2.append(it)
    db.pubnote.delete_many({})
    r = db.pubnote.insert_many(items2)
    print(len(items2), len(r.inserted_ids))


def get_force_same():
    """diff时强制认同的表"""
    if 'force_same' not in cache:
        fp = osp.join(hp.BASE_DIR, 'web/tr/data/diff强制认同表.txt')
        with open(fp, 'r') as f:
            lines = [ln.strip() for ln in f.readlines() if ln.strip() and not ln.startswith('#')]
            cache['force_same'] = {ln.split(':')[0]: ln.split(':')[1] for ln in lines}
    return cache['force_same']


def reset_same(base, cmp):
    """ 校准diff的is_same判断"""

    def check(a, b):
        if a in ['', '□'] and len(b) == 1:
            return True
        if b in ['', '□'] and len(a) == 1:
            return True
        if len(a) == 1 and len(b) == 1:
            if force_same.get(a) == b or force_same.get(b) == a:
                return True
            if is_family(a, b):
                return True

    if abs(len(base) - len(cmp)) >= 2:
        return False

    force_same = get_force_same()
    if len(base) <= 1 and len(cmp) <= 1:
        return check(base, cmp)

    # 补齐长度
    if len(base) - len(cmp) == 1:
        if check(base[0], cmp[0]):
            cmp = cmp + '□'
        else:
            cmp = '□' + cmp
    elif len(base) - len(cmp) == -1:
        if check(base[0], cmp[0]):
            base = '□' + base
        else:
            base = base + '□'
    # 逐字比较
    for i, t in enumerate(base):
        if not check(t, cmp[i]):
            return False
    return True


def trim(txt):
    """去掉标点、数字和#¶"""
    punc = ';|。？！，、；：“”‘’「」『』﹃﹄﹁﹂（）()《》〈〉［］〔〕【】——……－～'
    return re.sub(r'[%s\s\d#¶]' % punc, '', txt)


def get_page_names_from_vol_page(vol_page):
    """ 将Word中的册页信息转换为平台的页编码，word一页对应平台两页"""
    vol_page = re.sub(r'[\s第册页]', '', vol_page)
    vol, page = vol_page.rsplit('／', 1)
    if '目录' in vol_page:  # 目录页需要特别处理
        vol = 230
        trans = {'66': 1193, '79': 1220, '89': 1240, '103': 1268, '107': 1275}
        page = trans.get(page)
    elif re.match(r'^\d+$', page):
        page = int(page) * 2
    return [f'JS_{vol}_{int(page) - 1}', f'JS_{vol}_{page}']


def get_reel_codes(page_name):
    """ 从页编码获取卷编码"""
    db = hp.get_db('tw-work')
    vol, page = page_name.rsplit('_', 1)
    vol_no = int(vol.replace('JS_', ''))
    cond = {'reel_code': {'$regex': 'JS_'},
            'start_volume': vol, 'start_page': {'$lte': int(page)},
            'end_volume': vol, 'end_page': {'$gte': int(page)}}
    reels = list(db.reel.find(cond, {'reel_code': 1, '_id': 0}))
    if not reels:  # 跨册的情况1
        cond = {'reel_code': {'$regex': 'JS_'},
                'start_volume': f'JS_{vol_no - 1}',
                'end_volume': vol, 'end_page': {'$gte': int(page)}}
        reels = list(db.reel.find(cond, {'reel_code': 1, '_id': 0}))
    if not reels:  # 跨册的情况2
        cond = {'reel_code': {'$regex': 'JS_'},
                'start_volume': vol, 'start_page': {'$lte': int(page)},
                'end_volume': f'JS_{vol_no + 1}'}
        reels = list(db.reel.find(cond, {'reel_code': 1, '_id': 0}))
    reel_codes = [r['reel_code'] for r in reels]
    reel_codes.sort(key=lambda x: hp.align_code(x))
    return reel_codes


def get_pubnote_txt(reel_code, page_name):
    """ 获取刊记文本"""

    def get_pubnotes(items, pn_type):
        items.sort(key=lambda x: x[0])  # 按序号排序
        _start = 0
        for i, it in enumerate(items):
            if i and it[0] - items[i][0] > 2:  # 序号不连续，参数设置为2，以防版心列间断
                _txt = ''.join([f'{k[0]}#{k[1]}' for k in items[_start: i]])
                pubnotes.append([pn_type, _txt])
                _start = i
        if _start < len(items):
            _txt = ''.join([f'{k[0]}#{k[1]}' for k in items[_start:]])
            pubnotes.append([pn_type, _txt])

    def check_col_cid(_col_cid):
        _col_idx = col_cid2idx.get(col_cid)
        if _col_idx is None:
            return False
        if page_name == f'{reel["start_volume"]}_{reel["start_page"]}' and reel.get('start_column'):
            start_col_idx = col_cid2idx.get(reel['start_column'])
            if _col_idx < start_col_idx:
                return False
        if page_name == f'{reel["end_volume"]}_{reel["end_page"]}' and reel.get('end_column'):
            end_col_idx = col_cid2idx.get(reel['end_column'])
            if _col_idx > end_col_idx:
                return False
        return True

    db = hp.get_db('tw-work')
    page = db.page.find_one({'name': page_name})
    fields = ['start_volume', 'start_page', 'start_column', 'end_volume', 'end_page', 'end_column']
    reel = db.reel.find_one({'reel_code': reel_code}, {
        'format': {'$elemMatch': {'name': page_name}}, **{f: 1 for f in fields}, '_id': 0})
    if not page or not reel.get('format'):
        return []
    lines = get_base_txt(db, page).split('\n')
    cids = get_page_cids(page)
    col_cid2idx = {c[0]: i for i, c in enumerate(cids)}
    fmt = reel['format'][0]

    pubnotes = []
    # 从行标记中查找刊记
    items1 = []
    for fc in fmt.get('columns', []):
        if fc[0] == 'K':
            col_cid = fc[1]
            if not check_col_cid(col_cid):
                continue
            col_idx = col_cid2idx.get(col_cid)
            txt = lines[col_idx]
            col_no = col_idx + 1
            items1.append([col_no, txt])
    get_pubnotes(items1, 'column')
    # 从字标记中查找刊记
    items2 = []
    for fc in fmt.get('chars', []):
        if fc[0] == 'K':
            col_cid = fc[1]
            if not check_col_cid(col_cid):
                continue
            col_idx = col_cid2idx.get(col_cid)
            char_cids = cids[col_idx][1]
            char_cid2idx = {int(c): i for i, c in enumerate(char_cids)}
            start, end = char_cid2idx.get(int(fc[2])), char_cid2idx.get(int(fc[3]))
            txt = lines[col_idx][start: end + 1]
            col_no = col_idx + 1
            items2.append([col_no, txt])
    get_pubnotes(items2, 'char')
    return pubnotes


def get_txt_similarity(word_txt, uni_txt):
    """ 计算文本相似度"""
    word_txt = trim(word_txt)
    uni_txt = trim(uni_txt)
    segments = diff(word_txt, uni_txt, lambda x: True, lambda x: True, True,
                    normalize=True, reset_same=reset_same)
    same_len = len(''.join([s['base'] for s in segments if s.get('is_same')]))
    r_same = round(same_len / len(word_txt), 2)
    similar_len = len(''.join([s['base'] for s in segments if len(s.get('base')) == len(s.get('cmp'))]))
    r_similar = round(similar_len / len(word_txt), 2)
    diff_segs = ['%s#%s|%s#%s' % (s['base0'], s['cmp0'], s['base'], s['cmp']) for s in segments if not s.get('is_same')]
    return r_same, r_similar, diff_segs


def get_valid(len_wt, len_pt, r_same):
    is_valid = False
    gap = abs(len_wt - len_pt)
    if len_wt >= 100:
        if r_same > 0.9 and gap <= 10:
            is_valid = True
    elif len_wt >= 50:
        if r_same > 0.8 and gap <= 8:
            is_valid = True
    elif len_wt >= 10:
        if r_same > 0.7 and gap <= 5:
            is_valid = True
    else:
        if r_same > 0.6 and gap <= 3:
            is_valid = True
    return is_valid


def get_cmp_info(word_txt, pubnote_txt):
    """ 获取两份文本的比对信息"""
    r_same, r_similar, diff_segs = get_txt_similarity(word_txt, pubnote_txt)
    len_wt, len_pt = len(trim(word_txt)), len(trim(pubnote_txt))
    gap = len_wt - len_pt
    is_valid = get_valid(len_wt, len_pt, r_same)
    return dict(len_wt=len_wt, len_pt=len_pt, gap=gap, r_same=r_same,
                r_similar=r_similar, is_valid=is_valid, diff_segs=diff_segs)


def get_pubnote_info(vol_page, word_txt):
    """ 根据word的册页信息和牌记，计算tw平台的牌记信息"""
    logs = []
    page_names = get_page_names_from_vol_page(vol_page)
    for page_name in page_names:
        reel_codes = get_reel_codes(page_name)  # 已排序
        for i, reel_code in enumerate(reel_codes):
            items = get_pubnote_txt(reel_code, page_name)
            for pn_type, pubnote_txt in items:
                item = dict(page_name=page_name, reel_code=reel_code,
                            pn_type=pn_type, pubnote_txt=pubnote_txt)
                if pubnote_txt:
                    item.update(get_cmp_info(word_txt, pubnote_txt))
                logs.append(item)
    logs.sort(key=lambda x: [abs(x.get('gap', 100)), x.get('r_same', 0)])
    return logs


def is_perfect(log):
    if log.get('r_same') >= 1.0:
        return True
    return False


def get_log_judge(logs):
    valid_cnt, invalid_cnt = 0, 0
    perfect_cnt, unperfect_cnt = 0, 0
    for log in logs:
        if not log.get('pubnote_txt'):
            continue
        if log.get('is_valid'):
            valid_cnt += 1
        else:
            invalid_cnt += 1
        if is_perfect(log):
            perfect_cnt += 1
        else:
            unperfect_cnt += 1
    return dict(valid_cnt=valid_cnt, invalid_cnt=invalid_cnt,
                perfect_cnt=perfect_cnt, unperfect_cnt=unperfect_cnt)


def step3_set_pubnote():
    """拆分页面后，设置牌记信息"""
    db = hp.get_db('tw-lab')
    # cond = {'page_name': {'$nin': ['', None]}, 'pubnote': None}
    dt = datetime.now().strftime('%Y%m%d')
    cond = {'deleted': None, 'src': '国图径山藏', 'sn': {'$gt': 950}}
    # cond = {'sn': 9132}
    pubnotes = list(db.pubnote.find(cond))
    for i, pn in enumerate(pubnotes):
        if not pn.get('vol_page'):
            continue
        print('[%s/%s]%s,%s' % (i + 1, len(pubnotes), pn['sn'], pn['vol_page']))
        try:
            logs = get_pubnote_info(pn['vol_page'], pn['word_txt'])
            judge = get_log_judge(logs)
            db.pubnote.update_one({'_id': pn['_id']}, {'$set': {
                f'logs-{dt}': logs, f'judge-{dt}': judge, **judge, 'flag': dt}})
        except Exception as err:
            logging.error(str(err))


def step4_set_merged_pubnote():
    """ 处理跨页的牌记"""
    db = hp.get_db('tw-lab')
    cond = {'deleted': None, 'src': '国图径山藏-合并'}
    pubnotes = list(db.pubnote.find(cond))
    dt = datetime.now().strftime('%Y%m%d')
    for i, pn in enumerate(pubnotes):
        print('[%s/%s]%s' % (i + 1, len(pubnotes), pn['vol_page']))
        if not pn.get('start_page_name') or not pn.get('end_page_name'):
            continue
        reel_codes1 = get_reel_codes(pn['start_page_name'])
        reel_codes2 = get_reel_codes(pn['end_page_name'])
        reel_codes = [r for r in reel_codes1 if r in reel_codes2]
        assert len(reel_codes) == 1
        reel_code = reel_codes[0]

        items = []
        vol, start_page_no = pn['start_page_name'].rsplit('_', 1)
        vol, end_page_no = pn['end_page_name'].rsplit('_', 1)
        for n in range(int(start_page_no), int(end_page_no) + 1):
            items.extend(get_pubnote_txt(reel_code, f'{vol}_{n}'))

        logs = []
        for pn_type in ['column', 'char']:
            pubnote_txt = ''.join([r[1] for r in items if r[0] == pn_type])
            item = dict(reel_code=reel_code, pn_type=pn_type, pubnote_txt=pubnote_txt)
            if pubnote_txt:
                item.update(get_cmp_info(pn['word_txt'], pubnote_txt))
                logs.append(item)
        judge = get_log_judge(logs)
        db.pubnote.update_one({'_id': pn['_id']}, {'$set': {
            f'logs-{dt}': logs, f'judge-{dt}': judge, **judge}})


def import_fix_pubnotes():
    """导入金雷检查确认后的牌记"""
    db = hp.get_db('tw-lab')
    fp = osp.join(hp.BASE_DIR, 'web/tr/data/牌记页码检查确认-金雷-0813.csv')
    with open(fp, 'r', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    print(rows[0])
    head, pre = rows[0], dict()
    for r in rows[1:]:
        item = dict(zip(head, r))
        cond = {'vol_page': item['vol_page'], 'batch': 'checked-0814'}
        cnt = db.pubnote.count_documents(cond)
        if cnt != 1:
            print(item['vol_page'], cnt)
            continue
        if '合并' in item['remark']:
            remark = '与%s合并' % pre.get('vol_page')
            db.pubnote.update_one(cond, {'$set': {'deleted': True, 'remark': remark}})
            continue
        info = {'page_name': item['page_name'], 'end_page_name': item['end_page_name'],
                'reel_code': item['reel_code'], 'src': item['src']}
        if '国图径山藏' not in item['src']:
            db.pubnote.update_one(cond, {'$set': {**info, 'txt': item['word_txt']}})
        else:
            db.pubnote.update_one(cond, {'$set': info})
        pre = item


def stat_diff_segs():
    """ 统计diff_segs字段的频率"""
    db = hp.get_db('tw-lab')
    diff_seg_cnt = dict()
    cond = {'deleted': None}
    pubnotes = list(db.pubnote.find(cond, {'logs.diff_segs': 1, '_id': 0}))
    for i, pn in enumerate(pubnotes):
        print('[%s/%s]' % (i + 1, len(pubnotes)))
        for log in pn.get('logs', []):
            for ds in log.get('diff_segs', []):
                ds1, ds2 = ds.split('|')[1].split('#')
                if len(ds1) in [1, 2] and len(ds1) == len(ds2):
                    key = f'{ds1}#{ds2}'
                    diff_seg_cnt[key] = diff_seg_cnt.get(key, 0) + 1
    diff_seg_cnt = [[k, v] for k, v in diff_seg_cnt.items()]
    diff_seg_cnt.sort(key=lambda x: x[1], reverse=True)
    fp = osp.join(hp.BASE_DIR, 'log/pubnote_diff_segs.txt')
    with open(fp, 'w', encoding='utf-8') as f:
        lines = [f'{i[0]}\t{i[1]}\n' for i in diff_seg_cnt]
        f.writelines(lines)


def case1():
    reel_code = 'JS_2031_1'
    page_name = 'JS_190_1123'
    items = get_pubnote_txt(reel_code, page_name)
    print(items)


def process():
    step3_set_pubnote()


def main(func='process', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
