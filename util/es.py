import re
import os
import sys
import math
import logging
from os import path
from glob2 import glob
from datetime import datetime
from functools import partial
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ElasticsearchException

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

import helper as hp
from util.gaiji import replace_gaiji

BM_PATH = r'/data/es/BM_u8/'  # BM_u8所在路径
# BM_PATH = r'/Users/xiandu/Develop/cbeta-txt/BM_u8'  # BM_u8所在路径
LINE_REGEX = r'^([A-Z]{1,2})(\d+)n([A-Za-z]?\d+)[A-Za-z_]?p([A-Za-z]?\d+)[a-z]\d+([=#\-\?\w]{3})(.*)$'  # BM_u8行首格式


def get_es():
    config = hp.load_config() or {}
    hosts = [config and config.get('esearch') or dict(host='localhost', port=9200)]
    es = Elasticsearch(hosts=hosts)
    return es


def check_exists(index='cbeta-ik2'):
    """ 检查索引"""
    es = get_es()
    r = es.indices.exists(index=index, ignore=[400, 404])
    print('index %s %s exists' % (index, 'not' if not r else ''))


def delete_index(index, query=None):
    """ 删除索引"""
    es = get_es()
    if query:
        es.delete_by_query(index=index, body={'query': query})
    else:
        es.indices.delete(index=index, ignore=[400, 404])


def get_index(index='cbeta-ik', splitter='ik', mode='create'):
    """ 获取索引函数"""
    es = get_es()

    if mode == 'create':
        es.indices.create(index=index, ignore=400)
    elif mode == 'update':
        es.indices.open(index=index, ignore=400)

    mapping = {}
    if splitter == 'ik':
        mapping = {'properties': {'rows': {
            'type': 'text',
            'analyzer': 'ik_max_word',
            'search_analyzer': 'ik_smart'
        }}}
    elif splitter == 'jieba':
        mapping = {'properties': {'rows': {
            'type': 'text',
            'analyzer': 'jieba_index',
            'search_analyzer': 'jieba_index'
        }}}

    es.indices.put_mapping(index=index, body=mapping)
    return partial(es.index, index=index, ignore=[])


def check_cbeta_line():
    """ 检查行栏号格式"""
    files = sorted(glob(path.join(BM_PATH, '**', r'new.txt')))
    for i, fn in enumerate(files):
        lines = open(fn, 'r').readlines()
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            m = re.match(LINE_REGEX, ln)
            if not m:
                print('[%s]%s' % (fn.replace(BM_PATH, ''), ln))


def split_cbeta_file(fn):
    """ 分割CBETA文件"""

    def reset_last_two():
        if len(items) < 2:
            return
        sutra_no1 = items[-2][0][1].split('_')[2]
        sutra_no2 = items[-1][0][1].split('_')[2]
        if sutra_no2 != sutra_no1:
            return
        last_two = items[-2] + items[-1]
        idx = int(len(last_two) / 2)
        items[-2] = last_two[0:idx]
        items[-1] = last_two[idx:]

    with open(fn, 'r', encoding='utf-8') as f:
        fn_lines = f.readlines()

    limit = 2000
    pre_sutra_no = ''
    items, lines = [], []
    for line in fn_lines:
        line = line.strip()
        if not line:
            continue
        m = re.match(LINE_REGEX, line)
        if not m:
            logging.info('[error]%s' % line)
            continue
        tptk_id, volume_no, sutra_no, page_no, txt = m.group(1), m.group(2), m.group(3), m.group(4), m.group(6)
        # replace gaiji
        txt = replace_gaiji(txt)
        # filter junk
        txt = re.sub('\n', '', txt)
        txt = re.sub('<p>', '\n', txt)
        txt = re.sub('<.*?>', '', txt)
        txt = re.sub(r'\[.>(.)\]', lambda m: m.group(1), txt)
        txt = re.sub(r'\[[\x00-\xff＊]*\]', '', txt)
        if not txt:
            continue
        if pre_sutra_no and sutra_no != pre_sutra_no:  # 切换经号
            items.append(lines)
            reset_last_two()
            lines = []
        elif len(''.join([r[0] for r in lines])) >= limit:  # 字数超限
            items.append(lines)
            lines = []
        page_id = '%s_%s_%s_%s' % (tptk_id, volume_no, sutra_no, page_no)
        lines.append([txt, page_id])
        pre_sutra_no = sutra_no

    if lines:
        items.append(lines)
        reset_last_two()

    return items


def build_index_v1(mode='update'):
    """ 扫描文件夹，按页构建es索引"""
    hp.set_logging('build_index.log')

    index = get_index('cbeta-ik', mode)
    # tripitakas = ['T', 'X', 'J', 'A', 'B', 'C', 'F', 'G', 'GA', 'GB', 'K', 'L', 'M', 'P', 'S', 'U']
    tripitakas = ['GA', 'GB']
    for t in tripitakas:
        files = sorted(glob(path.join(BM_PATH, t, '**', r'new.txt')))
        for i, fn in enumerate(files):
            logging.info('-----%s-----' % fn)
            rows_list = split_cbeta_file(fn)
            for j, rows in enumerate(rows_list):
                txt = ''.join([r[0] for r in rows])
                page_ids = list(set([r[1] for r in rows]))
                tid, volume_no, sutra_no, _ = page_ids[0].split('_')
                try:
                    index(body=dict(tripitaka_id=tid, sutra_id=tid + sutra_no, volume_id=tid + volume_no,
                                    page_ids=page_ids, sn=j + 1, txt=txt, char_count=len(txt),
                                    create_time=datetime.now()))
                except ElasticsearchException as e:
                    logging.error('[%s]%s failed. %s' % (j + 1, page_ids, str(e)))


def build_index_v2(mode='update'):
    """ 按文件构建es索引"""
    hp.set_logging('build_index_v2.log')

    index = get_index('cbeta-ik1', mode)
    txt_path = r'/data/es/cbeta-text/'  # 分卷文本所在路径
    tripitakas = ['T', 'X', 'J', 'A', 'B', 'C', 'F', 'G', 'GA', 'GB', 'K', 'L', 'M', 'P', 'S', 'U']
    for t in tripitakas:
        for root, dirs, files in os.walk(path.join(txt_path, t)):
            for fn in files:
                print('-----%s-----' % path.join(root, fn))
                if not re.match(r'.*_\d+.txt$', fn):
                    continue
                juan_id = fn.strip('.txt')
                lines = open(path.join(root, fn), 'r').readlines()
                lines = [ln.strip() for ln in lines if ln.strip() and not ln.startswith('#')]
                txt = replace_gaiji('\n'.join(lines))
                try:
                    index(body=dict(tripitaka_id=juan_id[0], sutra_id=juan_id.split('_')[0], juan_id=juan_id,
                                    txt=txt, char_count=len(txt), create_time=datetime.now()))
                except ElasticsearchException as e:
                    logging.error('[%s]%s' % (fn, str(e)))


def build_index_v3(index_id='klwb-ik', mode='update'):
    """ 按文件构建es索引"""
    hp.set_logging('build_index_v3.log')

    index = get_index(index_id, mode)
    root = r'/home/smjs/xiandu/klwb'
    for dr in os.listdir(root):
        sutra_id, sutra_name = dr.split('_', 1)
        for fn in os.listdir(path.join(root, dr)):
            logging.info('-----%s-----' % path.join(root, dr, fn))
            if not fn.endswith('.txt'):
                continue
            txt = open(path.join(root, dr, fn), 'r').read()
            txt = re.sub('[^\u3400-\uFAD9\U00020000-\U0003134A]', '', txt)  # 非中文字符
            # 拆分成多段
            size = 2000
            char_count = len(txt)
            group_count = math.ceil(char_count / size)
            for n in range(group_count):
                _txt = txt[n * size:(n + 1) * size]
                logging.info('[%s/%s]%s chars, %s...' % (n + 1, group_count, len(_txt), _txt[:10]))
                try:
                    index(body=dict(sutra_id=sutra_id, volume_id=fn.strip('.txt'), sn=n + 1,
                                    txt=_txt, char_count=len(txt), create_time=datetime.now()))
                except ElasticsearchException as e:
                    logging.error('[%s]%s' % (fn, str(e)))


def build_index_v4(index_id='jsz-ik', mode='update'):
    """按页构建径山藏索引"""
    hp.set_logging('build_index_v4.log')
    # 1 数据准备
    db_work = hp.get_db('tw-work')
    # 1.1提前准备好页编码经编码
    page2sutra = get_page2sutra()
    # 1.2 准备通字转换表
    txt_type = 'uni_txt'
    vts = list(db_work.variant.find({'v_code': {'$exists': True}}, {'v_code': 1, 'uni_txt': 1}))
    code2txt = {vt.get('v_code'): vt.get(txt_type) for vt in vts}
    # 2 创建索引
    index = get_index(index_id, mode)
    # 3 获取创建索引的页编码
    names = db_work.page.distinct('name', {'source': {'$nin': ['JS-IMG', 'JS-MENU']}, 'name': {'$regex': 'JS_'}})
    sorted_lst = sorted(names, key=lambda x: [int(y) for y in x.split('_') if y.isdigit()])
    # 3.1 页编码按每1000个进行拆分成数组
    split_lst = [sorted_lst[i:i + 1000] for i in range(0, len(sorted_lst), 1000)]
    # 4 循环遍历页编码数组，创建索引
    i = 0
    for names in split_lst:
        pages = list(db_work.page.find({'name': {'$in': names}}))
        pages = sorted(pages, key=lambda page: [int(y) for y in page['name'].split('_') if y.isdigit()])
        for page in pages:
            txt = trans_txt(page, code2txt)
            if not txt:
                logging.error('[%s]%s failed. %s' % (i, page['name'], 'txt=None'))
                continue
            # 4.1 准备参数
            sutra_id = page2sutra[page['name']]  # 经编码
            page_ids = [page['name']]  # 页编码
            tid, volume_no, sutra_no = page_ids[0].split('_')
            # 4.2 写入索引
            logging.info('[%s]\t%s\t%s' % (i, page['name'], len(txt)))
            try:
                index(body=dict(tripitaka_id=tid, sutra_id=sutra_id, volume_id='%s_%s' % (tid, volume_no),
                                page_ids=page_ids, sn=int(sutra_no), txt=txt, char_count=len(txt),
                                create_time=datetime.now()))
            except ElasticsearchException as e:
                logging.error('[%s]\t%s\t failed. %s' % (i, page['name'], str(e)))


def trans_txt(page, code2txt=None, wrap='\n'):
    """ 将径山藏原字文本转换为正字文本或通字文本"""
    chars = page.get('chars')
    if not chars:
        return ''
    pre, txt = {}, ''
    cen_column_ids = [c.get('column_id') for c in page.get('columns', []) if
                      c.get('is_center') and not c.get('deleted')]
    for c in chars:
        if c.get('deleted'):
            continue
        c_column_id = c.get('char_id').rsplit('c', 1)[0]
        if c_column_id in cen_column_ids:
            continue
        if pre.get('block_no') and c.get('block_no') and int(pre['block_no']) != int(c['block_no']):
            txt += wrap
        elif pre.get('column_no') and c.get('column_no') and int(pre['column_no']) != int(c['column_no']):
            txt += wrap
        t = c.get('txt', '')
        if t.startswith('v') and len(t) > 1:
            t = code2txt.get(t) or '□'
        if t in ['fw', 'fh']:
            t = {'fw': 'ஜ', 'fh': '※'}.get(t)
        txt += t
        pre = c
    return txt.rstrip(wrap)


def get_page2sutra():
    """径山藏页编码对应的经号"""
    with open('径山藏页编码对应的经号.txt', 'r', encoding='utf-8') as f:
        return {line.split('\t')[1].strip(): line.split('\t')[0].strip() for line in f.readlines()}


def main(func='', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
