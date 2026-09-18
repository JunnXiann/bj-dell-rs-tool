import sys
import csv
import math
import logging
from os import path as osp
from datetime import datetime

BASE_DIR = osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__))))
META_DIR = osp.join(BASE_DIR, 'web/tw/data/check-char')

sys.path.append(BASE_DIR)

import helper as hp
from util import uni2std
from web.tw.char import update_chars

db_work = hp.get_db('tw-work')
flag = 'flag5'


def init_flag(coll):
    """初始化flag"""
    hp.set_logging('init_flag')
    sources = db_work[coll].distinct('source')
    for source in sources:
        print(source)
        r = db_work[coll].update_many({'source': source}, {'$set': {flag: 0}})
        logging.info(f'字表{coll}初始化{flag}，分类{source}有{r.matched_count}条数据')
    db_work[coll].create_index(flag)


def get_lines(filename, strip=True):
    """获取文本行，去掉注释行"""
    with open(osp.join(META_DIR, filename), 'r', encoding='utf-8') as f:
        lines = f.readlines()
    if strip:
        lines = [ln.strip() for ln in lines if not ln.startswith('#')]
    else:
        lines = [ln for ln in lines if not ln.startswith('#')]
    return lines


def get_sources(coll, rule='原字'):
    """获取数据分类"""
    assert rule in ['原字', '通字', '新增']
    lines = get_lines('径山藏字数据分类统计.txt')
    sources = []
    for ln in lines:
        no, _coll, source, cnt, _rule = ln.split('\t')
        if _coll == coll and _rule == rule:
            sources.append(source)
    return sources


def set_flag_11(coll):
    """1.不参与检校/1.新增的字图"""
    logging.info('set_flag_11')
    sources = get_sources(coll, '新增')
    for source in sources:
        cond = {flag: 0, 'source': source}
        r = db_work[coll].update_many(cond, {'$set': {flag: 11}})
        logging.info('%s\t%s\t%s' % (coll, source, r.matched_count))


def set_flag_12(coll):
    """1.不参与检校/2. 通字校对的字数据"""
    logging.info('set_flag_12')
    sources = get_sources(coll, '通字')
    for source in sources:
        cond = {flag: 0, 'source': source}
        r = db_work[coll].update_many(cond, {'$set': {flag: 12}})
        logging.info('%s\t%s\t%s' % (coll, source, r.matched_count))


def set_flag_13(coll):
    """1.不参与检校/3.同形字组的字种"""
    logging.info('set_flag_13')
    lines = get_lines('径山藏同形字组.txt')
    tks = list(set([i for ln in lines for i in ln.split('\t')]))

    sources = get_sources(coll, '原字')
    for source in sources:
        cond = {flag: 0, 'source': source, 'txt': {'$in': tks}}
        r = db_work[coll].update_many(cond, {'$set': {flag: 13}})
        logging.info('%s\t%s\t%s' % (coll, source, r.matched_count))


def set_flag_14(coll):
    """1.不参与检校/4.已经经过反复校对的低频字数据"""
    logging.info('set_flag_14')
    lines = get_lines('径山藏低频字种对应的字数据.txt')
    names = [ln.split('\t')[1] for ln in lines if ln.split('\t')[0] == coll]

    cond = {flag: 0, 'name': {'$in': names}}
    r = db_work[coll].update_many(cond, {'$set': {flag: 14}})
    logging.info('%s chars updated' % r.matched_count)


def set_flag_15(coll):
    """1.不参与检校/5. txt为■□"""
    logging.info('set_flag_15')
    sources = get_sources(coll, '原字')
    for source in sources:
        cond = {flag: 0, 'source': source, 'txt': {'$in': ['■', '□']}}
        r = db_work[coll].update_many(cond, {'$set': {flag: 15}})
        logging.info('%s\t%s\t%s' % (coll, source, r.matched_count))


def set_flag_16(coll):
    """1.不参与检校/6.txt为不在引擎字种范围内、启用状态的字种"""
    logging.info('set_flag_16')
    # 0923引擎字种
    tks_0923 = get_lines('JS0923引擎字种.txt')
    # 异体字管理中的禁用字种
    vts = list(db_work.variant.find(
        {'activated': '否'}, {'v_code': 1, 'txt': 1, '_id': 0}))
    tks = [vt.get('txt') or vt.get('v_code') for vt in vts]
    # 并集（引擎字种+禁用字种）
    exclude_tks = list(set(tks) | set(tks_0923))

    sources = get_sources(coll, '原字')
    for source in sources:
        # 排除引擎字种+禁用字种
        cond = {flag: 0, 'source': source, 'txt': {'$nin': exclude_tks}}
        r = db_work[coll].update_many(cond, {'$set': {flag: 16}})
        logging.info('%s\t%s\t%s' % (coll, source, r.matched_count))


def set_flag_1(coll):
    """1.不参与检校"""
    hp.set_logging('set_flag_1')
    set_flag_11(coll)
    set_flag_12(coll)
    set_flag_13(coll)
    set_flag_14(coll)
    set_flag_15(coll)
    set_flag_16(coll)


def get_tw_tks(activated='否'):
    """从异体字管理表中获取禁用/启用的字种"""
    vts = list(db_work.variant.find(
        {'activated': activated}, {'v_code': 1, 'txt': 1, '_id': 0}))
    tks = [vt.get('txt') or vt.get('v_code') for vt in vts]
    return tks


def get_invalid_tks():
    """获取无效字种"""
    tks1 = get_tw_tks(activated='否')
    lines = get_lines('JS0923引擎标注数据字频统计.txt')
    tks2 = [ln.split('\t')[0] for ln in lines if int(ln.split('\t')[1]) < 10]
    return list(set(tks1) | set(tks2))


def get_mixed_tks():
    """径山藏易混字组"""
    mixed_tks = set()
    lines = get_lines('径山藏易混字组.txt')
    for ln in lines:
        if ln.count('#') == 1:
            mixed_tks.add(ln)
        elif ln.count('#') > 1:
            tks = ln.split('#')
            for tk1 in tks:
                for tk2 in tks:
                    mixed_tks.add('%s#%s' % (tk1, tk2))
    return list(mixed_tks)


TK2STD = {}


def get_tk2std():
    """加载异体字表的字种正字字典"""
    if TK2STD:
        return TK2STD
    vts = list(db_work.variant.find(
        {}, {'v_code': 1, 'txt': 1, 'nor_txt': 1, 'activated': 1, '_id': 1}))
    for vt in vts:
        if vt.get('v_code'):
            TK2STD[vt['v_code']] = vt.get('nor_txt')
        elif vt.get('txt') and vt.get('activated') != '否':  # 通字字种如果被禁用，不使用该数据
            TK2STD[vt['txt']] = vt.get('nor_txt')
    return TK2STD


def get_nor_txt(txt):
    """获取字种的正字"""
    tk2std = get_tk2std()
    nor_txt = tk2std.get(txt)
    if not nor_txt:
        nor_txt = uni2std.get_stdtxt(txt, '', 0) or txt
    return nor_txt


def set_flag_2(coll):
    """2.参与检校"""

    def add_char(k, n):
        stat[k] = stat.get(k) or []
        stat[k].append(n)

    def is_mixed_tks(tk1, tk2):
        return f'{tk1}#{tk2}' in mixed_tks or f'{tk2}#{tk1}' in mixed_tks

    hp.set_logging('set_flag_2')

    mixed_tks = get_mixed_tks()
    invalid_tks = get_invalid_tks()
    disabled_tks = get_tw_tks(activated='否')
    tks_0923 = get_lines('JS0923引擎字种.txt')

    size = 10000 * 50  # 50万
    total = db_work[coll].count_documents({flag: 0})
    group_cnt = math.ceil(total / size)
    project = {'txt': 1, 'name': 1, 'remark': 1, '_id': 0,
               'ocr_res.JSYZ_KM_0923.ocr_txt': 1,
               'ocr_res.JSYZ_CC_0923.ocr_txt': 1}
    chars = list(db_work[coll].find({flag: 0}, project).limit(size))
    idx = 1
    while len(chars):
        logging.info('[%s]第%s/%s组(每组%s条)' % (coll, idx, group_cnt, size))
        # 分类统计
        stat = {}
        for ch in chars:
            name = ch['name']
            txt = hp.prop(ch, 'txt')
            remark = ch.get('remark') or ''
            kmt = hp.prop(ch, 'ocr_res.JSYZ_KM_0923.ocr_txt')
            cct = hp.prop(ch, 'ocr_res.JSYZ_CC_0923.ocr_txt')
            if not txt or not kmt or not cct:
                add_char(9, name)
                logging.info('[e1]文本不全,txt=%s,km=%s,cc=%s' % (txt, kmt, cct))
                continue
            txts = [txt, kmt, cct]
            valid_txts = [t for t in txts if t not in invalid_tks]
            # 1. 有效文本不足三个
            if len(valid_txts) < 3:
                # 1. txt为不在引擎字种范围内、禁用状态的字种
                if txt not in tks_0923 and txt in disabled_tks:
                    case = 1
                # 2. 备注E99的字图（视为缺少txt）
                elif 'E99' in remark or 'e99' in remark:
                    case = 2
                # 3. 其余情况
                else:
                    case = 3
                key = f'21{case}{len(valid_txts)}'
                add_char(key, name)
            # 2. 有效文本有三个
            else:
                # 1.原字一致
                if txt == kmt and txt == cct:
                    add_char(221, name)
                # 2.原字不一致
                else:
                    txt1 = get_nor_txt(txt)
                    kmt1 = get_nor_txt(kmt)
                    cct1 = get_nor_txt(cct)
                    # 1.正字一致
                    if txt1 == kmt1 and txt1 == cct1:
                        # 1.txt与其中一个相同
                        if txt == kmt or txt == cct:
                            # 1.txt与另一个是易混字组
                            if txt == kmt and is_mixed_tks(txt, cct):
                                add_char(222111, name)
                            elif txt == cct and is_mixed_tks(txt, kmt):
                                add_char(222111, name)
                            # 2.txt与另一个不是易混字组
                            else:
                                add_char(222112, name)
                        # 2.txt与二者都不同
                        else:
                            # 1.km=cc
                            if kmt == cct:
                                # 1.txt与km、cc是易混字组
                                if is_mixed_tks(txt, cct):
                                    add_char(2221211, name)
                                # 2.txt与km、cc不是易混字组
                                else:
                                    add_char(2221212, name)
                            # 2.km!=cc
                            else:
                                t_m_k = is_mixed_tks(txt, kmt)
                                t_m_c = is_mixed_tks(txt, cct)
                                # 1.txt与km、cc是易混字组
                                if t_m_k and t_m_c:
                                    add_char(2221221, name)
                                # 2.txt与km是易混字组，与cc不是易混字组
                                elif t_m_k and not t_m_c:
                                    add_char(2221222, name)
                                # 3.txt与cc是易混字组，与km不是易混字组
                                elif not t_m_k and t_m_c:
                                    add_char(2221223, name)
                                # 4.txt与km、cc都不是易混字组
                                elif not t_m_k and not t_m_c:
                                    add_char(2221224, name)
                    # 2.正字不一致
                    else:
                        # 1.txt'与其中一个相同（txt'=km' 或 txt'=cc'）
                        if txt1 == kmt1 or txt1 == cct1:
                            add_char(22221, name)
                        # 2.txt'与二者都不同（txt'≠km' 且 txt'≠cc'）
                        else:
                            add_char(22222, name)
        # 写数据库
        for k2, names2 in stat.items():
            logging.info('flag=%s有%s条' % (k2, len(names2)))
            update_chars(db_work, coll, names2, flag, int(k2))
        # 查找下一组
        if len(chars) < size:
            break
        chars = list(db_work[coll].find({flag: 0}, project).limit(size))
        idx += 1


def stat_flag(colls=''):
    """ 统计flag"""
    colls = colls and colls.split(',')
    if not colls:
        colls = ['char1', 'char2', 'char3', 'char4', 'char5', 'char6']

    rows = []
    total = {}
    head = ['字表', f'{flag}值', '对齐编码', '字频', '比例']
    # 分表计算
    for coll in colls:
        print(coll)
        groups = list(db_work[coll].aggregate([
            {'$group': {'_id': f'${flag}', 'count': {'$sum': 1}}}
        ]))
        coll_cnt = sum([g['count'] for g in groups])
        for g in groups:
            code = str(g['_id']).ljust(8, '0')
            ratio = round(g['count'] / coll_cnt, 6)
            rows.append([coll, g['_id'], code, g['count'], ratio])
            total[g['_id']] = total.get(g['_id'], 0) + g['count']
    # 合计
    total_cnt = sum([int(v) for v in total.values()])
    for k, v in total.items():
        code = str(k).ljust(8, '0')
        ratio = round(v / total_cnt, 6)
        rows.append(['all', k, code, v, ratio])

    rows.sort(key=lambda x: (x[0], x[2]))
    rows.insert(0, head)
    dt = datetime.now().strftime('%Y%m%d-%H%M%S')
    fp = osp.join(BASE_DIR, 'log', f'{flag}字频统计-{dt}.csv')
    with open(fp, 'w', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def stat_txt2ocr(flag_value=222112, b='km', colls=''):
    """统计某个flag值下A#B的频率（A为txt，B为km_txt or cc_txt）"""
    colls = colls and colls.split(',')
    if not colls:
        colls = ['char1', 'char2', 'char3', 'char4', 'char5', 'char6']

    rows = []
    total = {}
    head = ['字表', f'A#B', '频率']
    # 分表计算
    for coll in colls:
        stat = {}
        ocr_field = f'ocr_res.JSYZ_{b.upper()}_0923.ocr_txt'
        chars = list(db_work[coll].find(
            {flag: int(flag_value)}, {'txt': 1, ocr_field: 1, '_id': 0}))
        print(coll, len(chars))
        for ch in chars:
            key = '%s#%s' % (hp.prop(ch, 'txt'), hp.prop(ch, ocr_field))
            stat[key] = stat.get(key, 0) + 1
            total[key] = total.get(key, 0) + 1
        rows.extend([[coll, k, v] for k, v in stat.items()])

    # 合计
    rows.extend([['all', k, v] for k, v in total.items()])

    rows.sort(key=lambda x: (x[0], x[1], x[2]))
    rows.insert(0, head)
    dt = datetime.now().strftime('%Y%m%d-%H%M%S')
    fp = osp.join(BASE_DIR, 'log', f'A#B字频统计-{flag}={flag_value}-{dt}.csv')
    with open(fp, 'w', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def case1():
    lines = open('/Volumes/v2/00Inbox/DailyUse/temp3.txt', 'r').readlines()
    for ln in lines:
        print(ln.strip())
        stat_txt2ocr(int(ln.strip()))


def process(coll):
    init_flag(coll)
    set_flag_1(coll)
    set_flag_2(coll)


def main(func='case1', **kwargs):
    eval(func)(**kwargs)
    print('finished.')


if __name__ == '__main__':
    import fire

    fire.Fire(main)
