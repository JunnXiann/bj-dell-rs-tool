import os
import sys

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print(f'root_dir:{root_dir}')
sys.path.append(root_dir)

import helper as hlp
from util import punc


def get_tr_reel_column_list(reel, txt_type):
    """获取阅藏平台的卷相关行数据
    注：reel需要包含需要pages和format字段
    注：阅藏平台卷数据已去除重复页文本，不需要cut_txt参数
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
    """
    col_list = []
    pages = reel.get('pages') or []
    name2format = {p['ouid']: p for p in reel.get('format') or []}

    for page in pages:
        page_name = page.get('ouid')
        if not page.get('cids'):
            continue

        page_format = name2format.get(page_name) or {}
        col_cid2col_format = {cid: fmt for fmt, cid in page_format.get('columns') or []}
        col_cid2char_format = {}
        for fmt, cid, start, end in page_format.get('chars') or []:
            col_cid2char_format.setdefault(cid, []).append([fmt, start, end])
        col_cid2char_cids = {}
        for [_block_cid, column_char_cids] in page['cids']:
            for [_column_cid, char_intervals] in column_char_cids:
                col_cid2char_cids[_column_cid] = char_intervals

        for [_block_cid, col_txts]in page[txt_type]:
            for [_col_cid, col_txt] in col_txts:
                col = dict()
                col['page_name'] = page_name
                col['col_txt'] = col_txt
                col['col_cid'] = _col_cid
                col['col_format'] = col_cid2col_format.get(_col_cid) or 'T'  # 缺省为正文
                # 单行单个字  char_intervals为[start_cid]
                # 单行多个字 char_intervals为[[start_cid, end_cid], ...]
                col['char_cids'] = col_cid2char_cids.get(_col_cid) or []
                col['char_format'] = col_cid2char_format.get(_col_cid) or []

                col_list.append(col)

    return col_list


def get_charfmt_index2(col, column_txt, fmt_start, fmt_end):
    """
    p:当前页
    column_cid: 当前行
    column_txt: 当前行文本内容
    fmt_start: 字格式开始的字id
    fmt_end: 字格式结束的字id

    注: 字格式所在区间为 column_txt[column_start_index:column_end_index + 1]
    """
    char_format_intervals = hlp.expand_nums(col['char_cids'])
    _start_cid = char_format_intervals[0]
    _end_cid = char_format_intervals[-1]
    
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


def fmt_xiaozi(col_list):
    for col in col_list:
        column_txt = col['col_txt']
        for char_fmt in col['char_format']:
            if char_fmt[0] == 'N':
                fmt_start, fmt_end = char_fmt[1], char_fmt[2]
                start, end = get_charfmt_index2(col, column_txt, fmt_start, fmt_end)
                column_txt = column_txt[:start] + '（' + column_txt[start:end+1] + '）' + column_txt[end+1:]
        
        col['col_txt'] = column_txt.replace('¶', '\n')


def export_reel_txt_fmt_xiaozi(sutra_code):
    """
        导出阅藏平台经的卷文本txt，小字外面加（）
    """
    reel_codes = tr_db.reel.find({'sutra_uid': sutra_code}, {'uid': 1})
    for reel_code in reel_codes:
        reel = tr_db.reel.find_one({'uid': reel_code['uid']})
        reel_col_list = get_tr_reel_column_list(reel, 'std_txt')
        fmt_xiaozi(reel_col_list)
        os.makedirs(sutra_code, exist_ok=True)
        txt_name = reel.get('uid') + '.txt'
        file_path = os.path.join(sutra_code, txt_name)
        reel_content = ''
        for col in reel_col_list:
            reel_content += col['col_txt']
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(reel_content)


if __name__ == '__main__':
    tr_client = hlp.connect_db_max('tr-readprod', 'mongodb-', True)
    tr_db = tr_client['tripitaka-reader-prod']

    sutra_code = "JS1607"
    export_reel_txt_fmt_xiaozi(sutra_code)
