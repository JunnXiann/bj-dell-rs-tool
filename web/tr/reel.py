import os
import re
import shutil
import sys
import csv
import json
import logging
from os import path
from glob2 import glob
from datetime import datetime

sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

import helper as hp
from util import punc


def get_no(nid):
    arr = nid.replace('b', '').split('c')
    block_no = int(arr[0])
    column_no, char_no = -1, -1
    if len(arr) >= 2:
        column_no = int(arr[1])
    if len(arr) == 3:
        char_no = int(arr[2])
    return block_no, column_no, char_no


def cmp_nid(nid1, nid2, level=None):
    # nid 指的是序号id，包括block_id/column_id/char_id
    block_no1, column_no1, char_no1 = get_no(nid1)
    block_no2, column_no2, char_no2 = get_no(nid2)
    if block_no1 != block_no2:  # level in block/column/char
        return 1 if block_no1 > block_no2 else -1
    elif level in ['block', 1]:
        return 0
    if column_no1 != column_no2:  # level in column/char
        return 1 if column_no1 > column_no2 else -1
    elif level in ['column', 2]:
        return 0
    if char_no1 != char_no2:
        return 1 if char_no1 > char_no2 else -1
    return 0


def reduce_cids(cids):
    """ 合并连续的cid"""

    def reduce():
        if not item[1] or item[1] == item[0]:
            return item[0]
        return item

    items, item = [], []
    for i, c in enumerate(cids):
        if not i:  # 初始化
            item = [c, 0]
            continue
        pre = cids[i - 1]
        if c - pre == 1:  # 连续序号
            item[1] = c
        else:
            items.append(reduce())
            item = [c, 0]
    items.append(reduce())
    return items


def get_page_cids(page):
    """获取页数据的cids"""
    if not page.get('chars'):
        return []

    rows = []
    for blk in page['blocks']:
        blk_cols = [c for c in page['columns'] if c['column_id'].startswith(f'{blk["block_id"]}c')]
        rows2 = []
        for col in blk_cols:
            col_char_cids = [c['cid'] for c in page['chars'] if c['char_id'].startswith(f'{col["column_id"]}c')]
            rows2.append([col['cid'], reduce_cids(col_char_cids)])
        rows.append([blk['cid'], rows2])
    return rows


def get_structured_page_txt(page, txt_type, start_col_cid=None, end_col_cid=None):
    """从页数据中获取结构化的文本"""
    if not page.get('chars'):
        return []

    colcid2id = {c['cid']: c['column_id'] for c in page['columns']}
    snid = start_col_cid and colcid2id.get(start_col_cid) or ''
    enid = end_col_cid and colcid2id.get(end_col_cid) or ''

    rows = []
    for blk in page['blocks']:
        if snid and cmp_nid(blk['block_id'], snid, 1) < 0:
            continue
        if enid and cmp_nid(blk['block_id'], enid, 1) > 0:
            continue
        blk_cols = [c for c in page['columns'] if c['column_id'].startswith(f'{blk["block_id"]}c')
                    and not c.get('is_center')]
        rows2 = []
        for col in blk_cols:
            if snid and cmp_nid(col['column_id'], snid, 2) < 0:
                continue
            if enid and cmp_nid(col['column_id'], enid, 2) > 0:
                continue
            col_chars = [c for c in page['chars'] if c['char_id'].startswith(f'{col["column_id"]}c')]
            col_txt = ''.join([c.get(txt_type) or '■' for c in col_chars])
            rows2.append([col['cid'], col_txt])
        rows.append([blk['cid'], rows2])
    return rows


def get_raw_txt(structured_page_txt):
    """从结构化的文本中获取原始文本"""
    return '\n'.join([col_txt for _, block in structured_page_txt for _, col_txt in block])


def get_reel_txt(reel, txt_type):
    txt = ''
    for p in reel['pages']:
        txt += get_raw_txt(p[txt_type])
    return txt


def transfer_punc_to_std_txt(structured_std_txt, punc_txt):
    """ 将punc_txt中的标点迁移至structured_std_txt中"""
    std_txt = structured_std_txt
    raw_txt = get_raw_txt(std_txt).replace('\n', '¶')
    std_txt2 = punc.transfer_punc(raw_txt, punc_txt)
    std_txt2_lines = std_txt2.split('\n')
    idx = 0
    for i, blk in enumerate(std_txt):
        for j, col in enumerate(blk[1]):
            std_txt[i][1][j][1] = std_txt2_lines[idx]
            idx += 1
    return std_txt


def transfer_punc_by_pos(base_txt, punc_txt):
    """按位置进行标点迁移（从正字文本至其它文本）"""
    for i, t in enumerate(punc_txt):
        if punc.is_punc(t):
            base_txt = base_txt[:i] + t + base_txt[i:]
    return base_txt


def get_page_txts(page, start_col_cid=None, end_col_cid=None):
    """获取页文本"""
    fields = ['ori_txt', 'uni_txt', 'std_txt', 'sim_txt']
    ret = {f: get_structured_page_txt(page, f, start_col_cid, end_col_cid) for f in fields}
    if page.get('punc_txt'):
        # 从punc_txt中迁移标点至正字文本
        ret['std_txt'] = transfer_punc_to_std_txt(ret['std_txt'], page['punc_txt'])
        # 从正字文本中按位置迁移标点至其它文本
        for txt_type in ['ori_txt', 'uni_txt', 'sim_txt']:
            structured_txt = ret[txt_type]
            for i, blk in enumerate(structured_txt):
                for j, col in enumerate(blk[1]):
                    std_col_txt = ret['std_txt'][i][1][j][1]
                    if len(col[1]) != len(punc.trim_punc(std_col_txt)):
                        logging.info('[%s]column txt not equal, %s || %s' % (page['uid'], col[1], std_col_txt))
                        continue
                    txt = transfer_punc_by_pos(col[1], std_col_txt)
                    structured_txt[i][1][j][1] = txt
            ret[txt_type] = structured_txt
    return ret


def get_reel_pages(db, reel):
    """ 获取reel表中pages字段所需的内容"""
    salt = hp.get_config('img.hash_salt')
    start = hp.align_code(reel['start_page_ouid'])
    end = hp.align_code(reel['end_page_ouid'])
    cond = {'ouid2': {'$gte': start, '$lte': end}}
    fields = ['uid', 'ouid', 'blocks', 'columns', 'chars', 'punc_txt', 'images']
    pages = list(db.page.find(cond, {f: 1 for f in fields}).sort('ouid2', 1))
    ret = []
    for page in pages:
        # uid/ouid
        meta = {'uid': page['uid'], 'ouid': page['ouid']}
        # ori_txt/uni_txt/std_txt/sim_txt
        start_col_cid, end_col_cid = None, None
        if page['ouid'] == reel['start_page_ouid'] and reel.get('start_column_cid'):
            start_col_cid = reel['start_column_cid']
        if page['ouid'] == reel['end_page_ouid'] and reel.get('end_column_cid'):
            end_col_cid = reel['end_column_cid']
        meta.update(get_page_txts(page, start_col_cid, end_col_cid))
        # cids/img_name
        meta.update({'cids': get_page_cids(page)})
        # suffix = hp.md5_encode(page['ouid'], salt)
        suffix = hp.md5_encode(page['ouid'])
        meta['img_name'] = '%s_%s.jpg' % (page['ouid'], suffix)
        if page.get('images'):
            meta['images'] = page['images']
        ret.append(meta)
    return ret


def reset_newline(reel, txt_type):
    """ 检查、更新换行符
        注：reel需要包括pages和format两个字段
    """
    pages, formats = reel['pages'], reel['format']
    txt0 = ''.join([get_raw_txt(p[txt_type]) for p in pages])  # 初始文本
    pre = None  # 上一行
    fmt_dict = {fmt['ouid']: fmt for fmt in formats}
    for i, p in enumerate(reel['pages']):
        # if i > len(formats) - 1:
        #     continue
        # if not formats[i].get('columns'):
        #     continue
        # column_fmts = formats[i]['columns']
        fmt = fmt_dict.get(p['ouid'])
        if not fmt:
            continue
        if not fmt.get('columns'):
            continue
        column_fmts = fmt['columns']
        columncid2fmt = {cid: fmt for fmt, cid in column_fmts}
        char_fmts = fmt.get('chars') or []  # 不是每页都有字格式
        columncid2charfmts = {}
        for [fmt, ccid, start_cid, end_cid] in char_fmts:
            if ccid not in columncid2charfmts:
                columncid2charfmts[ccid] = []
            columncid2charfmts[ccid].append([fmt, start_cid, end_cid])  # 单行可能有多个字格式
        for j, [block_cid, column_txts] in enumerate(p[txt_type]):
            for k, [column_cid, column_txt] in enumerate(column_txts):
                # 行格式处理
                fmt = columncid2fmt.get(column_cid)
                if pre and pre[0] != fmt and not pre[1].endswith('¶'):  # 格式改变，上一行应有换行
                    pages[pre[2]][txt_type][pre[3]][1][pre[4]][1] = pre[1] + '¶'
                # 标题等格式后应该有换行符，连续多行标题只有最后一行有换行符
                elif fmt in ['J', 'L', 'H1', 'H2', 'H3', 'H4', 'H5', 'A', 'Y']:
                    # 检查当前行行尾，应该有换行符
                    if not column_txt.endswith('¶'):
                        p[txt_type][j][1][k][1] = column_txt + '¶'
                    # 检查上一行行尾
                    if pre:
                        p0 = pages[pre[2]]  # 上一行所在页
                        # 上一行与当前行格式相同，则上一行行尾不应有换行符
                        if pre[0] == fmt and pre[1].endswith('¶'):
                            p0[txt_type][pre[3]][1][pre[4]][1] = pre[1][:-1]
                        # 上一行与当前行格式不同，则上一行行尾应该有换行符
                        if pre[0] != fmt and not pre[1].endswith('¶'):
                            p0[txt_type][pre[3]][1][pre[4]][1] = pre[1] + '¶'
                # 目录每行都应该有换行符
                elif fmt in ['M']:
                    if not column_txt.endswith('¶'):
                        p[txt_type][j][1][k][1] = column_txt + '¶'

                # 字格式处理
                charfmts = columncid2charfmts.get(column_cid) or []
                for charfmt in charfmts:
                    column_txt = p[txt_type][j][1][k][1]  # 获取最新当前行(必要，单行有多个字格式时，会修改行内容，每次循环需要使用最新的行内容)
                    fmt_char, fmt_start, fmt_end = charfmt[0], charfmt[1], charfmt[2]
                    # 单个字的字格式，起始值为空
                    if not fmt_start:
                        fmt_start = fmt_end
                    # 字格式为标题等格式时，应该单独一行
                    if fmt_char in ['J', 'L', 'H1', 'H2', 'H3', 'H4', 'H5', 'A', 'Y']:
                        column_start_index, column_end_index = get_charfmt_index(p, column_cid, column_txt, fmt_start, fmt_end)
                                        
                        if column_start_index == 0:  # 标题等字格式从行首开始时，需保证上一行行尾有换行
                            if pre:
                                p0 = pages[pre[2]]  # 上一行所在页
                                if not pre[1].endswith('¶'):
                                    p0[txt_type][pre[3]][1][pre[4]][1] = pre[1] + '¶'
                        else:  # 标题等字格式从行中间开始，需保证开始前一位是换行
                            if column_txt[column_start_index - 1] != '¶':
                                column_txt = column_txt[:column_start_index] + '¶' + column_txt[column_start_index:]
                                # 字格式内容中间添加'¶'，字格式末尾标志column_end_index变长1位
                                column_end_index += 1

                        if column_end_index == len(column_txt) - 1: # 标题等字格式从行尾结束时, 需保证行末有换行
                            if column_txt[column_end_index] != '¶':
                                column_txt += '¶'
                        else:  # 标题等字格式从行中间结束时, 需保证字格式后一位是换行
                            if column_txt[column_end_index + 1] != '¶':
                                column_txt = column_txt[:column_end_index + 1] + '¶' + column_txt[column_end_index + 1:]
                        # 更新当前行
                        p[txt_type][j][1][k][1] = column_txt

                pre = [fmt, column_txt, i, j, k] 
    txt1 = ''.join([get_raw_txt(p[txt_type]) for p in pages])  # 更新文本
    changed = txt0 != txt1
    return changed


def reset_punc(reel, txt_type):
    """ 更新标点符号（1.若行首出现关闭标点，则移到上一行行末 2.若行末出现开始引号，则移到下一行行首）
        注：reel需要包括pages字段
        zhj: 行格式已处理该问题，字格式不用重复处理
    """

    def get_page_txt(page):
        return ''.join([column for _, block in page for _, column in block])

    txt0 = ''.join([get_page_txt(p[txt_type]) for p in reel['pages']])  # 初始文本
    last = None  # 上一行
    for i, p in enumerate(reel['pages']):
        for j, [block_cid, column_txts] in enumerate(p[txt_type]):
            for k, [column_cid, column_txt] in enumerate(column_txts):
                if last:
                    txt0, i0, j0, k0 = last
                    p0 = reel['pages'][last[1]]  # 上一行所在页
                    # 当前行（原书换行）行首的结束引号，应该移动至上一行的行尾
                    if column_txt[0] in ['”', '’', '」', '』']:
                        p0[txt_type][j0][1][k0][1] = txt0 + column_txt[0]
                        p[txt_type][j][1][k][1] = column_txt[1:]
                    # 上一行（原书换行）行尾的开始引号，应该移动至当前行的行首
                    if txt0[-1] in ['“', '‘', '「', '『']:
                        p[txt_type][j][1][k][1] = txt0[-1] + column_txt
                        p0[txt_type][j0][1][k0][1] = txt0[:-1]
                last = [column_txt, i, j, k]
    txt1 = ''.join([get_page_txt(p[txt_type]) for p in reel['pages']])  # 更新文本
    changed = txt0 != txt1
    return changed


def trim_no_need_punc(reel, txt_type):
    """ 清除不必要的标点符号
        注：reel需要包括pages字段
        todo: 仅处理了行格式，尚未处理字格式
    """
    pages, formats = reel['pages'], reel['format']
    txt0 = ''.join([get_raw_txt(p[txt_type]) for p in pages])  # 初始文本
    for i, p in enumerate(reel['pages']):
        if i > len(formats) - 1:
            continue
        # 检查行格式
        column_fmts = formats[i].get('columns')
        if column_fmts:
            columncid2fmt = {cid: fmt for fmt, cid in column_fmts}
            for j, [block_cid, column_txts] in enumerate(p[txt_type]):
                for k, [column_cid, column_txt] in enumerate(column_txts):
                    fmt = columncid2fmt.get(column_cid)
                    # 标题等格式中，不应包含标点符号
                    if fmt in ['J', 'L', 'H1', 'H2', 'H3', 'H4', 'H5', 'A', 'Y', 'G', 'M', 'P', 'I']:
                        column_txt = remove_paragraph_symbols(column_txt)
                        p[txt_type][j][1][k][1] = re.sub('[%s]+' % punc.PUNC_STR, '', column_txt)  # 去除标点符号

        # 检查字格式
        char_fmts = formats[i].get('chars')  # [[字格式标记，行cid，开始字cid，结束字cid], ...]
        if char_fmts:
            columncid2charfmts = {}
            for [fmt, ccid, start_cid, end_cid] in char_fmts:
                if ccid not in columncid2charfmts:
                    columncid2charfmts[ccid] = []
                columncid2charfmts[ccid].append([fmt, start_cid, end_cid])
            for j, [block_cid, column_txts] in enumerate(p[txt_type]):
                for k, [column_cid, origin_column_txt] in enumerate(column_txts):
                    charfmts = columncid2charfmts.get(column_cid) or []
                    for char_fmt in charfmts:
                        column_txt = p[txt_type][j][1][k][1]  # 获取最新当前行(必要，单行有多个字格式时，会修改行内容，每次循环需要使用最新的行内容)
                        fmt, fmt_start, fmt_end = char_fmt[0], char_fmt[1], char_fmt[2]
                        # 单个字的字格式，起始值为空
                        if not fmt_start:
                            fmt_start = fmt_end
                        # 标题、科判等格式中，不应包含标点符号
                        if fmt in ['J', 'L', 'H1', 'H2', 'H3', 'H4', 'H5', 'A', 'Y', 'T', 'P', 'PZ']:
                            column_start_index, column_end_index = get_charfmt_index(p, column_cid, column_txt, fmt_start, fmt_end)

                            # 字格式去掉内部的换行
                            change_len = len(remove_paragraph_symbols(column_txt[column_start_index:column_end_index + 1]))
                            column_txt = column_txt[:column_start_index] + \
                                        remove_paragraph_symbols(column_txt[column_start_index:column_end_index + 1]) + \
                                        (column_txt[column_end_index + 1:] if column_txt[column_end_index + 1:] else '')
                            # 字格式去除标点符号
                            new_end_index = column_start_index + change_len - 1
                            p[txt_type][j][1][k][1] = column_txt[:column_start_index] + \
                                        re.sub('[%s]+' % punc.PUNC_STR, '', column_txt[column_start_index:new_end_index + 1]) + \
                                        (column_txt[column_end_index + 1:] if column_txt[column_end_index + 1:] else '')

    txt1 = ''.join([get_raw_txt(p[txt_type]) for p in pages])  # 更新文本
    changed = txt0 != txt1
    return changed

def remove_paragraph_symbols(text):
    #移除所有的"¶"符号,保留"¶"结尾
    return text.replace('¶', '') + ('¶' if text.endswith('¶') else '')


def get_charfmt_index(p, column_cid, column_txt, fmt_start, fmt_end):
    """
    p:当前页
    column_cid: 当前行
    column_txt: 当前行文本内容
    fmt_start: 字格式开始的字id
    fmt_end: 字格式结束的字id

    注: 字格式所在区间为 column_txt[column_start_index:column_end_index + 1]
    """
    for [_block_cid, column_char_cids] in p['cids']:
        for [_column_cid, char_format_intervals] in column_char_cids:
            if _column_cid == column_cid:
                if isinstance(char_format_intervals[0], int):
                    # 单行单个字  column_char_cids为 [[column_cid, [start_cid]], ...]
                    _start_cid = _end_cid = char_format_intervals[0]
                else:  
                    # 单行多个字 column_char_cids为 [[column_cid, [[start_cid, end_cid]]], ...]  注：char_format_intervals比单个字还多一层[]
                    _start_cid = char_format_intervals[0][0]
                    _end_cid = char_format_intervals[0][1]
                
                start_pass = fmt_start - _start_cid  # 在column_txt里字格式开始与行开始字差距几个字
                end_pass = _end_cid - fmt_end  # 在column_txt里字格式结束和行结尾字差距几个字

                # 找到字格式开始位置（跳过标点及'¶'）
                column_start_index = 0
                cnt = 0
                for i, char in enumerate(column_txt):
                    if char in punc.PUNC_STR or char == '¶':
                        continue
                    if cnt == start_pass:
                        column_start_index = i
                        break
                    cnt += 1
                
                # 找到字格式结束位置（跳过标点及'¶', 倒序） 
                column_end_index = len(column_txt) - 1
                cnt = 0
                for i in reversed(range(len(column_txt))):
                    char = column_txt[i]
                    if char in punc.PUNC_STR or char == '¶':
                        continue
                    if cnt == end_pass:
                        column_end_index = i  # 结束索引是开区间
                        break
                    cnt += 1

                return column_start_index, column_end_index


def update_reel_pages():
    """ 获取reel表中pages字段所需的内容"""
    hp.set_logging('update_reel_pages')

    db = hp.get_db('tr-test')
    # cond = {'uid': 'JS0134_006'}
    cond = {'flag': {'$ne': 5}}  # 需根据实际情况修改
    reels = list(db.reel.find(cond, {'uid': 1}))
    for i, rl in enumerate(reels):
        logging.info('[%s/%s]%s' % (i, len(reels), rl['uid']))
        fields = ['start_page_ouid', 'end_page_ouid', 'uid',
                  'start_column_cid', 'end_column_cid', 'pages', 'format']
        reel = db.reel.find_one({'_id': rl['_id']}, {f: 1 for f in fields})
        reel['pages'] = get_reel_pages(db, reel)
        changed = False
        txt_types = ['std_txt', 'sim_txt', 'uni_txt', 'ori_txt']
        for txt_type in txt_types:
            if reset_punc(reel, txt_type):
                changed = True
            if reset_newline(reel, txt_type):
                changed = True
            if trim_no_need_punc(reel, txt_type):
                changed = True
        if changed:
            logging.info('update %s' % reel['uid'])
            db.reel.update_one({'_id': reel['_id']}, {'$set': {'pages': reel['pages'], 'flag': 5}})


def update_page_range():
    """ 设置reel表的页数据范围"""
    db = hp.get_db('tr-test')
    cond = {}  # 需根据实际情况修改
    fields = ['uid', 'start_volume', 'end_volume', 'start_page', 'end_page']
    reels = list(db.reel.find(cond, {f: 1 for f in fields}))
    for i, rl in enumerate(reels):
        print('[%s/%s]%s' % (i, len(reels), rl['uid']))
        start_page_ouid = f"{rl['start_volume']}_{rl['start_page']}"
        end_page_ouid = f"{rl['end_volume']}_{rl['end_page']}"
        info = {'start_page_ouid': start_page_ouid, 'end_page_ouid': end_page_ouid}
        db.reel.update_one({'_id': rl['_id']}, {'$set': info})


# def case1():
#     db = hp.get_db('tr-prod')
#     cond = {'uid': 'JS0002_003'}
#     fields = ['start_page_ouid', 'end_page_ouid',
#               'start_column_cid', 'end_column_cid', 'pages', 'format']
#     reel = db.reel.find_one(cond, {f: 1 for f in fields})
#     r = trim_no_need_punc(reel, 'std_txt')
#     print(r)

def case1():
    db = hp.get_db('tr-readprod')
    cond = {'uid': 'JS0001_013'}
    fields = ['start_page_ouid', 'end_page_ouid',
              'start_column_cid', 'end_column_cid', 'pages', 'format']
    reel = db.reel.find_one(cond, {f: 1 for f in fields})
    r = reset_newline(reel, 'std_txt')
    print(r)
    # r = trim_no_need_punc(reel, 'std_txt')
    # print(r)


def main(func='case1', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
