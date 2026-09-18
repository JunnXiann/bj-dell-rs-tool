import re
import sys
import csv
import logging
import os.path as path
from collections import deque
from functools import cmp_to_key

sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

import helper as hlp
from util.uni2std import normalize
from util.find_match import find_best_match, exact_find_match
from web.tw.reel import (
    get_merged_column_list, get_reel_column_list,
    merge_by_format
)

CACHE_REEL_BDS = deque(maxlen=1000)

CACHE_CBETA_BD_TYPE = {}


def tw_to_cn(text: str) -> str:
    """将台湾标点符号转换为大陆标点符号"""
    replace_map = {
        # 引号
        '﹁': '“', '﹂': '”', '﹃': '“', '﹄': '”',
        '「': '“', '」': '”', '『': '‘', '』': '’',
        # 书名号
        '︽': '《', '︾': '》', '﹤': '《', '﹥': '》',
        # 省略号
        '⋯⋯': '……', '⋯': '…',
        # 破折号
        '──': '——',  # 台湾常用两条破折号替代大陆标准破折号
        # 中文括号
        '【': '[', '】': ']',
    }

    for tw_punc, cn_punc in replace_map.items():
        text = text.replace(tw_punc, cn_punc)

    return text


def trim_txt(txt):
    """文本预处理"""
    # 去掉CBETA文本中以#开头的注释
    txt = re.sub(r'#.+?\n', '', txt)
    # 去掉CBETA文本中以No.开头的注释
    txt = re.sub(r'No.+?\n', '', txt)
    # 处理CBETA校勘记，eg, [嬴>羸] → 羸
    txt = re.sub(r'\[([^]]+)>([^]]+)\]', r'\2', txt)
    # 处理CBETA组字式，如[弓*(乞-乙+小)] → ※
    txt = re.sub(r'\[[^]]+\]', r'※', txt)
    # 去掉特殊符号：1）空白字符(不包括换行)；2）数字、字母、空格、英文括号；3）脚注序号
    txt = re.sub(r'[ \t\r\f\v　\u0020\u3000．※0-9a-zA-Z+\(\)①②③④⑤⑥⑦⑧⑨]+', '', txt)
    # 多个换行变成一个换行
    txt = re.sub(r'\n+', '\n', txt)
    # 半角标点换成全角标点
    half, full = ',?!;:()<>', '，？！；：（）〈〉'
    for i, s in enumerate(half):
        txt = txt.replace(s, full[i])
    # 台湾标点转换为大陆标点
    txt = tw_to_cn(txt)
    return txt


def get_bd_stat(txt):
    """获取标点统计数据"""
    bd_str = '。？！，、；：'
    bd2cnt = {b: txt.count(b) for b in bd_str}
    total_cnt = sum(bd2cnt.values())
    # 去掉句号的标点数
    no_juhao_cnt = total_cnt - bd2cnt['。']
    stat = {'bd2cnt': bd2cnt, 'total_cnt': total_cnt, 'no_juhao_cnt': no_juhao_cnt}
    return stat


def get_cbeta_bd_type(cbeta_id='', jsz_id=''):
    """获取CBETA标点类型"""
    global CACHE_CBETA_BD_TYPE

    if not CACHE_CBETA_BD_TYPE:
        fp = path.join(hlp.BASE_DIR, 'web/tw/data/径山藏对应CBETA经编码及标点类型-0906.csv')
        with open(fp, 'r') as f:
            rows = list(csv.reader(f))[1:]
        CACHE_CBETA_BD_TYPE = rows

    if cbeta_id:
        for r in CACHE_CBETA_BD_TYPE:
            if r[2] == cbeta_id:
                return r[3]
    elif jsz_id:
        for r in CACHE_CBETA_BD_TYPE:
            if r[0] == jsz_id:
                return r[3]


def align_reel_no(reel_no):
    m = re.match(r'(\d+)([xz]\d)?', str(reel_no))
    return f'%03d_%s' % (int(m.group(1)), m.group(2) or 'y')


def get_reel_bd_txt(db, sutra_uid, reel_nos=None):
    """ 获取标点资源文本"""
    # 如果reel_nos为空，表示查全经的正文
    if not reel_nos:
        reel_bds = list(db.reel_bd.find({'sutra_uid': sutra_uid}, {'reel_no': 1, '_id': 0}))
        # 获取正文对应的卷序号（r['reel_no']为int表示正文，序跋之类的reel_no为字符串）
        reel_nos = [r['reel_no'] for r in reel_bds]
        reel_nos.sort(key=lambda x: align_reel_no(x))
    # 统一转成字符串
    reel_nos = [str(n) for n in reel_nos]
    # 先查缓存
    reel_no2txt = {}
    not_in_cache = []
    for rn in reel_nos:
        cache_reel_bd = [c for c in CACHE_REEL_BDS if c['sutra_uid'] == sutra_uid and c['reel_no'] == rn]
        if cache_reel_bd:
            reel_no2txt[rn] = cache_reel_bd[0]['txt']
        else:
            not_in_cache.append(rn)
            if rn.isdigit():
                not_in_cache.append(int(rn))
    # 后查数据库
    if not_in_cache:
        cond = {'sutra_uid': sutra_uid, 'reel_no': {'$in': not_in_cache}}
        reel_bds = list(db.reel_bd.find(cond, {'txt': 1, 'reel_no': 1, 'priority': 1}))
        for rb in reel_bds:
            rn = str(rb['reel_no'])
            CACHE_REEL_BDS.append({'sutra_uid': sutra_uid, 'reel_no': rn,
                                   'priority': rb.get('priority'), 'txt': rb['txt']})
            reel_no2txt[rn] = rb['txt']

    return '\n'.join([reel_no2txt.get(rn, '') for rn in reel_nos])


def get_reel_bd_priority(sutra_uid, reel_no):
    for c in CACHE_REEL_BDS:
        if c['sutra_uid'] == sutra_uid and c['reel_no'] == reel_no:
            return c.get('priority')


def get_base_txt(reel):
    """ 获取标点迁移的基础文本：校对文本中的正文内容"""
    merged_column_list = get_merged_column_list(reel)
    main_txt_cols = []
    no_bd_fmts = ['J', 'L', 'A', 'Y', 'H1', 'G', 'M', 'P', 'E', 'K', 'C']
    for cols_info in merged_column_list:
        if cols_info['col_format'] not in no_bd_fmts:
            main_txt_cols.extend(cols_info['col_txts'])
    base_txt = '\n'.join(main_txt_cols)
    return base_txt


def get_bd_match_data(db, reel_code='', reel=None, bd_source=''):
    """获取标点文本匹配数据"""
    # 获取卷数据
    fields = ['sutra_code', 'reel_no', 'reel_type', 'pages', 'format', 'bd_match_data']
    fields += ['start_column', 'start_volume', 'start_page', 'end_volume', 'end_page', 'end_column']
    reel = reel or db.reel.find_one({'reel_code': reel_code}, {f: 1 for f in fields})
    if reel['reel_type'] in ['图像', '目录', '科判', '空卷']:
        print(f"[DEBUG] {reel_code}: reel_type is {reel['reel_type']}, returning None")
        return

    # 1.获取卷数据的正文内容（排除标题、作译者、音释等）
    base_txt = get_base_txt(reel)
    if not base_txt:
        print(f"[DEBUG] {reel_code}: no base_txt")
        return

    # 2.查找如是经编码
    sutra_source = db.sutra_source.find_one({'sutra_uid': reel['sutra_code']}) or {}
    rs_sutra_uid = sutra_source.get('rushi_sutra_uid')
    if not rs_sutra_uid:
        print(f"[DEBUG] {reel_code}: no rushi_sutra_uid for sutra_code {reel['sutra_code']}")
        return

    # 3.根据如是经编码查找有哪些标点来源
    source_types = ['XZ', 'WL', 'FGZ', 'CBETA', 'HLAI']
    cond = {'rushi_sutra_uid': rs_sutra_uid, 'source_type': {'$in': source_types}}
    sutra_sources = list(db.sutra_source.find(cond, {'source_type': 1, 'sutra_uid': 1, 'assist_sutra_uid': 1}))
    # 去掉CBETA的AI標點等
    for s in sutra_sources:
        if s['source_type'] == 'CBETA':
            bd_type = get_cbeta_bd_type(s['sutra_uid'])
            if bd_type not in ['新式標點']:  # AI標點、基本句讀、原書標點等
                s['deleted'] = True
    # sutra_sources = [s for s in sutra_sources if not s.get('deleted')]
    # 如果指定了bd_source，则仅保留指定的内容
    type2zh = dict(zip(source_types, ['学者', '网络', '佛光藏', 'CBETA', '华鲤']))
    if bd_source:
        sutra_sources = [s for s in sutra_sources if bd_source in [s['source_type'], type2zh.get(s['source_type'])]]
    if not sutra_sources:
        print(f"[DEBUG] {reel_code}: no sutra_sources for rushi_sutra_uid {rs_sutra_uid}")
        return

    # 4.根据标点来源从标点资源中查找匹配文本
    sutra_sources.sort(key=lambda x: source_types.index(x['source_type']))
    bd_match_data = {}
    for ss in sutra_sources:
        bd_source = type2zh.get(ss['source_type']) or ss['source_type']
        # 4.1 根据辅助经号进行查找
        # ['X1342', 'X1542_001', 'X1315_042-045']
        assist_sutra_uids = ss.get('assist_sutra_uid')
        if assist_sutra_uids:
            bd_txts = []
            if isinstance(assist_sutra_uids, str):
                assist_sutra_uids = [assist_sutra_uids]
            for item in assist_sutra_uids:
                if '_' in item:
                    if '-' in item:  # 'X1315_042-045'
                        sutra_uid, nos = item.split('_', 1)
                        s, e = nos.split('-', 1)
                        bd_txts.append(get_reel_bd_txt(db, sutra_uid, list(range(int(s), int(e) + 1))))
                    else:  # 'X1542_001'
                        sutra_uid, reel_no = item.split('_', 1)
                        bd_txts.append(get_reel_bd_txt(db, sutra_uid, [int(reel_no)]))
                else:  # 'X1342'
                    bd_txts.append(get_reel_bd_txt(db, item))
            bd_txt = '\n'.join(bd_txts)
            match_txt, stat, refind_len = find_best_match(base_txt, trim_txt(bd_txt))[:3]
            bd_match_data[bd_source] = {
                'source': bd_source, 'sutra_uid': assist_sutra_uids, 'refind_len': refind_len,
                'step': 'assist', 'stat': stat, 'bd_stat': get_bd_stat(match_txt),
                'match_txt': match_txt
            }
            continue
        # 4.2 根据经号和卷序号查找
        ratio_limit = 0.96  # 匹配率阈值
        # 获取卷序号对应的那一卷标点资源的文本，进行第一次查找
        reel_no = reel['reel_no']  # 序跋的reel_no为string类型
        match_txt, stat, refind_len, step, sutra_uid = '', {}, 0, 0, ''
        sutra_uids = ss['sutra_uid'] if isinstance(ss['sutra_uid'], list) else [ss['sutra_uid']]
        for suid in sutra_uids:
            sutra_uid = suid
            step = 1  # 查找步骤
            bd_txt = get_reel_bd_txt(db, suid, [reel_no])
            print(f"[DEBUG] {reel_code}: Trying suid={suid}, reel_no={reel_no}, bd_txt_len={len(bd_txt)}")
            r1 = find_best_match(base_txt, trim_txt(bd_txt))[:3]
            print(f"[DEBUG] {reel_code}: r1 match_ratio={r1[1]['base']['match_ratio'] if r1[1] else 'N/A'}")
            if not stat or r1[1]['base']['match_ratio'] > stat['base']['match_ratio']:
                match_txt, stat, refind_len = r1
            if stat['base']['match_ratio'] < ratio_limit:
                # 匹配率不够，获取前中后三卷标点资源文本后，进行第二次查找
                if isinstance(reel_no, str):  # string
                    _reel_no = int(reel_no.split('x')[0].split('z')[0])
                    reel_nos = [_reel_no - 1, reel_no, _reel_no, _reel_no + 1]
                else:  # int
                    reel_nos = [reel_no - 1, reel_no, reel_no + 1]
                bd_txt2 = get_reel_bd_txt(db, suid, reel_nos)
                print(f"[DEBUG] {reel_code}: Trying suid={suid}, reel_nos={reel_nos}, bd_txt2_len={len(bd_txt2)}")
                r2 = find_best_match(base_txt, trim_txt(bd_txt2))[:3]
                print(f"[DEBUG] {reel_code}: r2 match_ratio={r2[1]['base']['match_ratio'] if r2[1] else 'N/A'}")
                if r2[1]['base']['match_ratio'] > stat['base']['match_ratio']:
                    step = 2
                    match_txt, stat, refind_len = r2
                if stat['base']['match_ratio'] < ratio_limit:
                    # 匹配率不够，获取整部经的标点资源文本后，进行第三次查找
                    bd_txt3 = get_reel_bd_txt(db, suid)
                    print(f"[DEBUG] {reel_code}: Trying suid={suid}, all reels, bd_txt3_len={len(bd_txt3)}")
                    r3 = find_best_match(base_txt, trim_txt(bd_txt3))[:3]
                    print(f"[DEBUG] {reel_code}: r3 match_ratio={r3[1]['base']['match_ratio'] if r3[1] else 'N/A'}")
                    if r3[1]['base']['match_ratio'] > stat['base']['match_ratio']:
                        step = 3
                        match_txt, stat, refind_len = r3
        if match_txt:
            bd_match_data[bd_source] = {
                'source': bd_source, 'sutra_uid': sutra_uid, 'refind_len': refind_len,
                'step': step, 'stat': stat, 'bd_stat': get_bd_stat(match_txt),
                'match_txt': match_txt
            }
            if step == 1:
                bd_match_data[bd_source]['priority'] = get_reel_bd_priority(sutra_uid, reel_no)
        else:
            print(f"[DEBUG] {reel_code}: No match_txt found for any suid in {sutra_uids}")

    return bd_match_data


def get_status(r1=None, r2=None, stat=None):
    """根据两个匹配率，返回状态"""
    r1 = r1 or hlp.prop(stat, 'base.match_ratio', 0)
    r2 = r2 or hlp.prop(stat, 'cmp.match_ratio', 0)
    status = 0, '不及格'
    # if r1 >= 1.0 and r2 >= 1.0:
    #     status = 100, '完美1'
    # elif (r1 >= 1.0 or r2 >= 1.0) and (r1 > 0.98 and r2 > 0.98):
    #     status = 100, '完美2'
    if r1 >= 0.98 and r2 >= 0.98:
        status = 98, '优秀1'
    elif (r1 >= 0.98 or r2 >= 0.98) and (r1 > 0.95 and r2 > 0.95):
        status = 98, '优秀2'
    elif r1 >= 0.95 and r2 >= 0.95:
        status = 95, '不错1'
    elif (r1 >= 0.95 or r2 >= 0.95) and (r1 > 0.9 and r2 > 0.9):
        status = 95, '不错2'
    elif r1 >= 0.9 and r2 >= 0.9:
        status = 90, '良好1'
    elif (r1 >= 0.9 or r2 >= 0.9) and (r1 > 0.85 and r2 > 0.85):
        status = 90, '良好2'
    elif r1 >= 0.8 and r2 >= 0.8:
        status = 80, '及格'
    return status


def select_bd_match_data(reel, bd_source=''):
    """根据标点来源，获取匹配文本信息"""

    bd_match_data = reel.get('bd_match_data')
    if not bd_match_data:
        return {}

    if bd_source:
        return bd_match_data.get(bd_source) or {}

    # 综合考虑优先级、匹配率以及标点来源进行选择
    sources = ['学者', '网络', '佛光藏']
    cbeta_data = bd_match_data.get('CBETA') or {}
    if cbeta_data and hlp.prop(cbeta_data, 'bd_stat.no_juhao_cnt', 0) != 0:
        sutra_code = reel.get('sutra_code') or ''
        cbeta_bd_type = get_cbeta_bd_type(jsz_id=sutra_code)
        if not cbeta_bd_type or cbeta_bd_type == '新式標點':
            sources.append('CBETA')
    bd_match_data_list = [v for k, v in bd_match_data.items() if k in sources]
    if bd_match_data_list:
        bd_match_data_list.sort(key=lambda x: [
            -(x.get('priority') or 0),
            -get_status(stat=x['stat'])[0],
            hlp.pos(sources, x['source'])
        ])
        match_data = bd_match_data_list[0]
    elif bd_match_data.get('华鲤'):
        match_data = bd_match_data['华鲤']
    else:
        match_data = {}

    return match_data


def batch_init_bd_match_data():
    """批量初始化设置标点文本匹配数据"""
    hlp.set_logging('batch_init_bd_match_data')

    # 准备参数，需要根据实际情况修改
    reset = True
    db = hlp.get_db('tw-work')
    # cond = {'reel_code': {'$regex': '^SX_'}}
    cond = {'reel_code': {'$in': ['SX_136_7']}} # SX_136_7

    reels = list(db.reel.find(cond, {'reel_code': 1, '_id': 0}))

    empty_bd_match_reels = []

    for i, rl in enumerate(reels):
        logging.info('[%s/%s]%s' % (i, len(reels), rl['reel_code']))
        if rl.get('bd_match_data') and not reset:
            continue
        try:
            bd_match_data = get_bd_match_data(db, rl['reel_code']) or {}
            if not bd_match_data:
                empty_bd_match_reels.append(rl['reel_code'])
            for k, v in bd_match_data.items():
                # 设置超长文本标记
                if hlp.prop(v, 'stat.cmp.match_length', 0) > 3 * hlp.prop(v, 'stat.base.match_length', 0):
                    v['txt'] = '==匹配文本超长=='

            logging.info(';'.join([f'{k}:{hlp.prop(v, "stat.base.match_ratio")}' for k, v in bd_match_data.items()]))
            print(bd_match_data)
            # db.reel.update_one({'reel_code': rl['reel_code']}, {'$set': {
            #     'bd_match_data': bd_match_data, 'flag': 1}})
        except Exception as e:
            logging.error("[%s]%s." % (e.__class__.__name__, str(e)))

    if empty_bd_match_reels:
        print("Reels with empty bd_match_data:")
        for rc in empty_bd_match_reels:
            print(rc)
    else:
        print("No empty bd_match_data found.")


def get_merged_bd_txt_list(reel, merged_column_list, bd_match_txt):
    """ 获取根据不同类型基础文本合并后的标点文本"""
    bd_txt_list = []
    bd_pre_data = hlp.prop(reel, 'bd_pre_data', {})
    no_bd_fmts = ['J', 'L', 'A', 'Y', 'H1', 'H2', 'H3', 'H4', 'H5', 'G', 'M', 'P', 'I']
    for cols_info in merged_column_list:
        _bd_txt = ''
        _base_txt = '¶'.join(cols_info['col_txts'])
        page_name, col_format = cols_info['page_name'], cols_info['col_format']
        if col_format in no_bd_fmts:  # 无需标点，直接用原文本
            _bd_txt = _base_txt
        elif col_format in ['E', 'K', 'C']:  # 音释、牌记、校讹从数据库取标点文本
            format_map = {'E': 'yinshi', 'K': 'colophon', 'C': 'emendation'}
            col_id = cols_info['page_name'] + '_' + str(cols_info['col_cid'])
            items = hlp.prop(bd_pre_data, f'{format_map[col_format]}.{col_id}', [])
            _bd_txt = items[-1]['txt'] if items else ''
        else:  # 余下格式需要标点
            if len(_base_txt) < 30:
                # 正文过短时不标点，变黑框提示标点校对人员重点关注
                _bd_txt = '■' * len(_base_txt)
            else:
                _bd_txt = find_best_match(_base_txt, bd_match_txt, False)[0]
        bd_txt_list.append({'col_format': col_format, 'txt': _bd_txt})
    return bd_txt_list


def get_selected_bd_info(db, reel_code='', reel=None):
    """重置tw平台径山藏的bd_txt_list数据"""
    fields = ['sutra_code', 'reel_no', 'reel_type', 'pages', 'format',
              'bd_source', 'bd_txt_list', 'bd_pre_data', 'bd_match_data']
    reel = reel or db.reel.find_one({'reel_code': reel_code}, {f: 1 for f in fields})
    if not reel.get('bd_match_data'):
        return {}

    merged_column_list = get_merged_column_list(reel)
    md = select_bd_match_data(reel)
    bd_txt_list = get_merged_bd_txt_list(reel, merged_column_list, md.get('match_txt', ''))
    return {
        'bd_txt_list': bd_txt_list, 'bd_source': md.get('source', ''),
        'match_ratio': hlp.prop(md, 'stat.base.match_ratio', 0)
    }


def batch_init_bd_txt_list():
    """批量重置tw平台径山藏的bd_txt_list数据"""
    hlp.set_logging('batch_init_bd_txt_list')

    # 准备参数，需要根据实际情况修改
    reset = True
    db = hlp.get_db('tw-work')
    # cond = {'reel_code': {'$regex': '^JS_'}, 'flag': 1, 'bd_logs': None}
    cond = {'reel_code': {'$regex': 'JS_1573_'}}

    reels = list(db.reel.find(cond, {'reel_code': 1, 'bd_source': 1, '_id': 0}))
    for i, rl in enumerate(reels):
        logging.info('[%s/%s]%s' % (i, len(reels), rl['reel_code']))
        if rl.get('bd_source') and not reset:
            continue
        try:
            bd_info = get_selected_bd_info(db, rl['reel_code'])
            bd_info['flag'] = 2
            db.reel.update_one({'reel_code': rl['reel_code']}, {'$set': bd_info})
        except Exception as e:
            logging.error("[%s]%s." % (e.__class__.__name__, str(e)))

def count_sx_without_cbeta():
    db = hlp.get_db('tw-work')
    cond = {'reel_code': {'$regex': '^SX_'}}
    reels = list(db.reel.find(cond, {'reel_code': 1, 'bd_match_data': 1, '_id': 0}))
    no_cbeta = []
    for rl in reels:
        bd_match_data = rl.get('bd_match_data', {})
        if not bd_match_data or 'CBETA' not in bd_match_data:
            no_cbeta.append(rl['reel_code'])
    print(f"没有bd_match_data.CBETA的卷数量: {len(no_cbeta)}")
    print("reel_code 列表:")
    for rc in no_cbeta:
        print(rc)
        
def set_bd_match_flag():
    """检查sutra_source的sutra_uid为数组的记录"""
    db = hlp.get_db('tw-work')

    source_types = ['XZ', 'WL', 'FGZ', 'CBETA', 'HLAI']
    cond = {"sutra_uid": {"$type": "array"}, 'source_type': {'$in': source_types}}
    sutra_sources = list(db.sutra_source.find(cond, {'rushi_sutra_uid': 1, 'sutra_uid': 1, '_id': 0}))
    rushi_sutra_uids = list(set([s['rushi_sutra_uid'] for s in sutra_sources]))

    cond = {"rushi_sutra_uid": {"$in": rushi_sutra_uids}, 'source_type': 'JSZ'}
    sutra_sources = list(db.sutra_source.find(cond, {'sutra_uid': 1, '_id': 0}))
    sutra_uids = set()
    for s in sutra_sources:
        if isinstance(s['sutra_uid'], list):
            sutra_uids.update(s['sutra_uid'])
        else:
            sutra_uids.add(s['sutra_uid'])

    cond = {'sutra_code': {'$in': list(sutra_uids)}}
    r = db.reel.update_many(cond, {'$set': {'flag': 0}})
    print(r.matched_count, r.modified_count)


def reset_bd_match_data():
    hlp.set_logging('reset_bd_match_data')
    db = hlp.get_db('tw-work')
    cond = {'reel_code': {'$regex': 'JS_'}}
    # cond = {'reel_code': 'JS_2_7'}

    reels = list(db.reel.find(cond, {'reel_code': 1, '_id': 0}))
    for i, rl in enumerate(reels):
        logging.info('[%s/%s]%s' % (i, len(reels), rl['reel_code']))
        reel = db.reel.find_one({'reel_code': rl['reel_code']})
        if not reel.get('bd_match_data'):
            continue
        changed = False
        base_txt = get_base_txt(reel)

        for k, v in reel['bd_match_data'].items():
            if v.get('stat'):
                continue
            changed = True
            # v['match_txt'] = v.pop('txt', '')
            v['match_txt'] = v['txt']
            r = exact_find_match(base_txt, v['match_txt'], refind=False)
            for f in ['len', 'len2', 'ratios', 'ratio']:
                v.pop(f, 0)
            v['stat'] = r[1]
        if changed:
            db.reel.update_one({'reel_code': reel['reel_code']}, {'$set': {'bd_match_data': reel['bd_match_data']}})


def get_stage(r):
    r = float(r)
    if r >= 1.0:
        s = 100
    elif r >= 0.98:
        s = 98
    elif r >= 0.95:
        s = 95
    elif r > 0.9:
        s = 90
    elif r > 0.85:
        s = 85
    elif r > 0.8:
        s = 80
    elif r > 0.6:
        s = 60
    else:
        s = 0
    return s


def align_code(code):
    m = re.match(r'([A-Z]{2})_(\d+)([a-z])?_(\d+)([xz]\d)?', code)
    return f'%s_%04d_%s_%03d_%s' % (
        m.group(1), int(m.group(2)), m.group(3) or '0', int(m.group(4)), m.group(5) or 'y')


def export_stat(out_dir=''):
    """导出统计数据"""
    db = hlp.get_db('tw-work')
    # cond = {'reel_code': 'JS_2_6'}
    cond = {'reel_code': {'$regex': '^JS_'}}

    reels = list(db.reel.find(cond, {'reel_code': 1, '_id': 0}))
    reel_codes = [r['reel_code'] for r in reels]
    reel_codes.sort(key=lambda x: align_code(x))

    head1 = ['卷编码', '卷类型', '经名', '是否需要标点']
    head2 = ['学者', '网络', '佛光藏', 'CBETA', '华鲤']
    head3 = ['择定来源', '重查文本长度', '步骤', '【校对文本】长度', '匹配率', '匹配等级',
             '【比对文本】长度', '匹配率', '匹配等级', '除句号外的标点数量', '【总体匹配情况】']
    head = head1 + head2 + head3
    rows = [head]
    for i, rc in enumerate(reel_codes):
        print('[%s/%s]%s' % (i + 1, len(reel_codes), rc))
        fields = ['reel_code', 'reel_type', 'sutra_name']
        append = ['bd_source', 'bd_match_data']
        reel = db.reel.find_one({'reel_code': rc}, {f: 1 for f in fields + append})
        # head1 基本信息
        row = [reel.get(f) for f in fields]
        need_punc = 'Y'
        if reel['reel_type'] in ['图像', '目录', '科判', '空卷']:
            need_punc = 'N'
        row.append(need_punc)
        # head2 各来源的匹配情况
        bd_match_data_dict = reel.get('bd_match_data', {})
        if not bd_match_data_dict:
            rows.append(row)
            continue
        for s in head2:
            d = bd_match_data_dict.get(s, {})
            keys = ['source', 'refind_len', 'step', 'stat', 'bd_stat']
            info = {k: d.get(k) for k in keys if d.get(k)}
            row.append(str(info))
        # head3 择定的标点来源
        md = select_bd_match_data(reel, reel.get('bd_source', ''))
        md['len'] = hlp.prop(md, 'stat.base.init_length', 0)
        md['ratio'] = hlp.prop(md, 'stat.base.match_ratio', 0)
        md['stage'] = get_stage(md['ratio'])
        md['len2'] = hlp.prop(md, 'stat.cmp.init_length', 0)
        md['ratio2'] = hlp.prop(md, 'stat.cmp.match_ratio', 0)
        md['stage2'] = get_stage(md['ratio2'])
        md['no_juhao_cnt'] = hlp.prop(md, 'bd_stat.no_juhao_cnt')
        keys2 = ['source', 'refind_len', 'step', 'len', 'ratio', 'stage',
                 'len2', 'ratio2', 'stage2', 'no_juhao_cnt']
        row.extend([md.get(k, '-') for k in keys2])
        if md.get('stat'):
            row.append(get_status(stat=md['stat'])[1])
        rows.append(row)
    out_dir = out_dir or path.join(hlp.BASE_DIR, 'tmp')
    with open(path.join(out_dir, 'js_bd_match.csv'), 'w') as wf:
        writer = csv.writer(wf)
        writer.writerows(rows)


def export_txt(out_dir=''):
    db = hlp.get_db('tw-local')
    # cond = {'reel_code': {'$regex': 'JS_'}, 'flag': 5}
    cond = {'reel_code': 'JS_2_31'}

    reels = list(db.reel.find(cond, {'reel_code': 1, '_id': 0}))
    for i, rl in enumerate(reels):
        print('[%s/%s]%s' % (i + 1, len(reels), rl['reel_code']))
        fields = ['pages', 'format'] + [
            'start_column', 'start_volume', 'start_page', 'end_volume', 'end_page', 'end_column']
        reel = db.reel.find_one({'reel_code': rl['reel_code']}, {f: 1 for f in fields})
        reel_column_list = get_reel_column_list(reel, True)
        merged_column_list = merge_by_format(reel_column_list)
        # 合并卷文本
        txt_list = []
        ignore_fmts = ['G', 'E', 'K', 'C']
        newline_fmts = ['J', 'L', 'A', 'Y', 'H1', 'M', 'P']
        for cols_info in merged_column_list:
            if cols_info['col_format'] in ignore_fmts:
                continue
            if cols_info['col_format'] in newline_fmts:
                txt_list.append('#' + '\n'.join(cols_info['col_txts']))
            else:
                txt_list.append(''.join(cols_info['col_txts']))
        reel_txt = '\n'.join(txt_list)
        reel_txt = normalize(reel_txt)
        out_dir = out_dir or path.join(hlp.BASE_DIR, 'tmp')
        with open(path.join(out_dir, f'{rl["reel_code"]}.txt'), 'w') as f:
            f.write(reel_txt)


def case1():
    cb_bd_type = get_cbeta_bd_type()
    print(len(cb_bd_type))


def process():
    # check_bd_match_flag()
    batch_init_bd_match_data()
    # reset_bd_match_data()
    # batch_init_bd_txt_list()
    # export_stat()
    # export_txt()
    pass


def main(func='process', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
