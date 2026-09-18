import os
import sys
import csv
import math
import pymongo
import logging
import os.path as path
from bson import Binary
from datetime import datetime

sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

import helper as hp
from util.uni2std import is_family


def set_img(db):
    now = datetime.now()
    root = '/data/tw-imgs/img/chars'
    chars = list(db.char2.find({}, {'name': 1, '_id': 0}))
    names = [c['name'] for c in chars]
    chars2 = list(db.img_js.find({}, {'pnm': 1, 'cid': 1, '_id': 0}))
    names2 = ['%s_%s' % (c['pnm'], c['cid']) for c in chars2]
    names = list(set(names) - set(names2))
    for i, name in enumerate(names):
        print(i, name)
        pnm, cid = name.rsplit('_', 1)
        fn = '%s/%s/%s_%s.jpg' % (root, pnm.replace('_', '/'), name, hp.md5_encode(name))
        if not path.exists(fn):
            continue
        data = Binary(open(fn, 'rb').read())
        db['img_js'].insert_one({
            'pnm': pnm, 'cid': int(cid), 'type': 'char',
            'data': data, 'udt': now
        })


def get_db_img():
    uri = 'mongodb://localhost:28018/'
    db_img = pymongo.MongoClient(
        uri, connectTimeoutMS=2000, serverSelectionTimeoutMS=2000,
        maxPoolSize=10, waitQueueTimeoutMS=5000, connect=False
    )
    return db_img['img']


def stat_center_char_cnt(db):
    """统计版心列字数"""
    stat = []
    cond = {'source': 'JS5', 'columns.is_center': True}
    pages = list(db.page.find(cond, {'name': 1, 'columns': 1, 'chars': 1}))
    for page in pages:
        center_columns = [c for c in page['columns'] if not c.get('deleted') and c.get('is_center')]
        center_column_id = center_columns and center_columns[0]['column_id'] or ''
        if center_column_id:
            cnt = len([c for c in page['chars'] if not c.get('deleted') and
                       c['char_id'].startswith(center_column_id + 'c')])
            stat.append([page['name'], cnt])
    total = sum([row[1] for row in stat])
    print(total)
    with open('stat.txt', 'w') as f:
        f.writelines(['%s\t%s\n' % (row[0], row[1]) for row in stat])


def update_chars(db, coll, char_names, field, value):
    cnt = 0
    size = 100000
    char_names = list(char_names)
    group_cnt = math.ceil(len(char_names) / size)
    for i in range(group_cnt):
        _names = char_names[i * size:(i + 1) * size]
        cond = {'name': {'$in': _names}, field: {'$ne': value}}
        r = db[coll].update_many(cond, {'$set': {field: value}})
        cnt += r.matched_count
    return cnt


def update_cmp_txt(db, page_sources='', char_coll=''):
    """ 更新字数据cmp_txt"""
    hp.set_logging('update_cmp_txt')

    cond = {'source': {'$in': page_sources.split('/')}}
    pages = list(db.page.find(cond, {'name': 1, 'chars': 1}))
    logging.info('%s pages found' % len(pages))
    stat = {}
    for i, p in enumerate(pages):
        for c in p.get('chars', []):
            if c.get('deleted'):
                continue
            cmp_txt = str(c.get('cmp_txt'))
            char_name = '%s_%s' % (p['name'], c['cid'])
            stat[cmp_txt] = stat.get(cmp_txt) or []
            stat[cmp_txt].append(char_name)

    items = [[k, v, len(v)] for k, v in stat.items()]
    items.sort(key=lambda x: x[2])
    idx, total = 1, len(items)
    for cmp_txt, names, _ in items:
        if cmp_txt == 'None':
            cmp_txt = None
        cnt = update_chars(db, char_coll, names, 'cmp_txt', cmp_txt)
        logging.info('[%s/%s]%s, %s chars, %s updated.' % (idx, total, cmp_txt, len(names), cnt))
        idx += 1


def batch_update_cmp_txt(db):
    update_cmp_txt(db, 'JT_40239', 'char1')


def get_code2txt(db, txt_type='uni_txt', v_codes=None):
    cond = {'v_code': {'$exists': True}}
    if v_codes:
        cond = {'v_code': {'$in': v_codes}}
    vts = list(db.variant.find(cond, {'v_code': 1, 'uni_txt': 1, 'nor_txt': 1, '_id': 0}))
    return {vt.get('v_code'): vt.get(txt_type) or vt.get('nor_txt') or '' for vt in vts}


def update_eq2cb(db):
    """ 更新字数据eq2cb"""
    stat = {}
    cond = {'source': {
        '$in': ['JS5C', 'JS5A1', 'JS5B1-1', 'JS5B1', 'JS5-L2', 'JS5A1-1', 'JS5A0', 'JS5B2', 'JS5A2', 'JS5A2-1']}}
    char_coll = 'char5'
    code2txt = get_code2txt(db, 'nor_txt')
    chars = list(db[char_coll].find(cond, {'name': 1, 'cmp_txt': 1, 'txt': 1, '_id': 0}))
    print('%s chars found' % len(chars))
    for i, c in enumerate(chars):
        txt = code2txt.get(c['txt']) or c['txt']
        if c.get('cmp_txt') in [None, '', '■']:  # None
            stat['None'] = stat.get('None', [])
            stat['None'].append(c['name'])
        elif c['cmp_txt'] == txt or is_family(c['cmp_txt'], txt):  # True
            stat['True'] = stat.get('True', [])
            stat['True'].append(c['name'])
        else:  # False
            stat['False'] = stat.get('False', [])
            stat['False'].append(c['name'])

    for v, names in stat.items():
        print('%s, %s' % (v, len(names)))
        if v == 'False':
            cnt = update_chars(db, char_coll, names, 'eq2cb', False)
        elif v == 'True':
            cnt = update_chars(db, char_coll, names, 'eq2cb', True)
        else:
            cnt = update_chars(db, char_coll, names, 'eq2cb', None)
        print('%s updated' % cnt)


def update_uni_txt(db):
    """ 更新字数据uni_txt"""
    hp.set_logging('update_uni_txt')

    i = 3
    source, coll = 'JS%s-L' % i, 'char%s' % i
    cond = {'source': source}
    fields = ['ocr_txt', 'ocr_col', 'cmp_txt', 'cmb_txt']
    chars = list(db[coll].find(cond, {f: 1 for f in fields + ['name', 'alternatives']}))
    total = len(chars)
    code2txt = get_code2txt(db)
    missed = []
    cnt = 0
    for i, ch in enumerate(chars):
        logging.info('[%s/%s]%s' % (i, total, ch['name']))
        info = {}
        for f in fields:
            t = ch.get(f) or ''
            if t.startswith('v') and len(t) > 1:
                t2 = code2txt.get(t)
                if not t2:
                    missed.append(t)
                else:
                    info[f] = t2

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
            info['alternatives'] = ','.join(alts)

        if info:
            db[coll].update_one({'_id': ch['_id']}, {'$set': info})
            cnt += 1
    logging.info('%s updated' % cnt)
    logging.info('missed codes: %s' % missed)


def batch_reset_cencol(db):
    """ 重置版心列的值 """
    fn = path.join(hp.BASE_DIR, 'txt', 'cencol_unequal.csv')
    with open(fn, 'r', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    for i, row in enumerate(rows):
        name, ptxt, ctxt = row
        if not ptxt:
            continue
        vol = int(name.split('_')[1])
        batch = 3 if vol <= 39 else 4 if vol <= 80 else 5 if vol <= 124 else 1 if vol <= 176 else 2
        msg = '\t'.join([str(batch), name, ptxt, ctxt])
        print('[%s/%s]%s' % (i + 1, len(rows), msg))
        r = db['char%s' % batch].update_one({'name': name}, {'$set': {'alternatives': ptxt}})
        if not r.matched_count:
            db['char6'].update_one({'name': name}, {'$set': {'alternatives': ptxt}})


def update_box(db):
    """ 解决径山藏切分系统性问题的遗留问题"""
    hp.set_logging('update_box')

    lines = open(path.join(hp.BASE_DIR, 'txt/log', 'js-names.txt'), 'r').readlines()
    char_names = [ln.strip() for ln in lines]
    # char_names = ['JS_226_160_140']
    for char_name in char_names:
        name, cid = char_name.rsplit('_', 1)
        cid = int(cid)
        page = db.page.find_one({'name': name, 'chars.cid': cid}, {'name': 1, 'chars.$': 1, 'bid': 1})
        page2 = db.page.find_one({'name': name}, {'name': 1, 'chars': 1})
        if not page or not page2 or not page.get('chars') or not page2.get('chars'):
            logging.info('[%s]not found.' % char_name)
            continue
        cid2char2 = {c['cid']: c for c in page2.get('chars') or []}
        char2 = cid2char2.get(cid)
        # 更新字框坐标
        pos = {f: char2[f] for f in ['x', 'y', 'w', 'h']}
        update = {'chars.$.%s' % k: v for k, v in pos.items()}
        # db.page.update_one({'name': name, 'chars.cid': cid}, {'$set': update})
        if page.get('bid'):
            page2char = db.page2char.find_one({'bid': page.get('bid')}) or {}
            char_coll = page2char.get('char_collection')
            logging.info('[%s]%s, %s' % (char_name, char_coll, pos))
            # db[char_coll].update_one({'name': char_name}, {'$set': {'pos': pos}})
            db[char_coll].update_one({'name': char_name}, {'$set': {'flag': 'box-1021'}})


def is_valid_txt(txt):
    return txt not in [None, '■', '']


def get_cmb_txt(ch):
    """ 选择综合文本"""
    alternatives = ch.get('alternatives') or ''
    if ',' in alternatives:
        alternatives = alternatives.split(',')
    if not alternatives:
        return ''
    # 以字框OCR为初始值
    cmb_txt = alternatives[0]
    # 如果比对文本更合适，则选用比对文本
    if is_valid_txt(ch.get('cmp_txt')) and cmb_txt != ch['cmp_txt'] and not cmb_txt.startswith('v'):
        if cmb_txt != ch.get('ocr_col') and (ch['cmp_txt'] == ch.get('ocr_col') or ch['cmp_txt'] in alternatives):
            cmb_txt = ch['cmp_txt']
    if cmb_txt in 'fh/hs/cs/zs/xt/fw/□/■'.split('/'):  # 替换特殊符号
        if is_valid_txt(ch.get('ocr_col')):
            cmb_txt = ch['ocr_col']
        if is_valid_txt(ch.get('cmp_txt')):
            cmb_txt = ch['cmp_txt']
    return cmb_txt


def get_cmb_txt2(ch):
    """ 选择综合文本"""
    alternatives = ch.get('alternatives') or ''
    if ',' in alternatives:
        alternatives = alternatives.split(',')
    if not alternatives:
        return ''
    # 以字框OCR为初始值
    cmb_txt = alternatives[0]
    # 如果比对文本更合适，则选用比对文本
    if is_valid_txt(ch.get('cmp_txt')) and cmb_txt != ch['cmp_txt'] and not cmb_txt.startswith('v'):
        if cmb_txt != ch.get('ocr_col') and ch['cmp_txt'] == ch.get('ocr_col'):
            cmb_txt = ch['cmp_txt']
    return cmb_txt


def calc_cmb_txt(db):
    """ 计算cmb_txt新旧策略不一致"""
    hp.set_logging('calc_cmb_txt')

    coll = 'char2'
    cond = {'ocr_txt': {'$regex': '^[^v]'}}
    chars = list(db[coll].find(cond, {'_id': 0, 'name': 1, 'alternatives': 1, 'cmp_txt': 1, 'ocr_col': 1}))
    stat = {}
    names = []
    for ch in chars:
        t1 = get_cmb_txt(ch)
        t2 = get_cmb_txt2(ch)
        if t1 != t2:
            key = '%s#%s' % (t1, t2)
            stat[key] = stat.get(key, 0) + 1
            logging.info('[%s]%s#%s' % (ch['name'], t1, t2))
            names.append(ch['name'])
    logging.info(str(stat))
    update_chars(db, coll, names, 'flag', 10)


def check_alternatives(db):
    hp.set_logging('check_alternatives')

    coll = 'char3'
    sources = 'JS4A3/JS4B2/JS4C2/JS4A2-1/JS4A0/JS4A2/JS4C/JS4A1/JS4A1-1/JS4B1'.split('/')
    cond = {'source': {'$in': sources}}
    chars = list(db[coll].find(cond, {'_id': 0, 'name': 1, 'alternatives': 1, 'ocr_col': 1}))
    logging.info('%s chars total' % len(chars))
    names = []
    for ch in chars:
        t1 = ch.get('ocr_col') or ''
        t2 = ch.get('alternatives') or ''
        if t1 not in t2.split(','):
            logging.info('[%s]%s#%s' % (ch['name'], ch['ocr_col'], ch['alternatives']))
            names.append(ch['name'])
    logging.info('%s error chars' % len(names))
    logging.info(names)


def stat_ori_freq():
    """ 统计原字文本频次"""
    db = hp.get_db('tw-work')
    stat = {}
    for i in range(1, 7):
        print('char%s' % i)
        coll = 'char%s' % i
        items = list(db[coll].aggregate([
            {'$group': {'_id': '$txt', 'count': {'$sum': 1}}}
        ]))
        for item in items:
            stat[item['_id']] = stat.get(item['_id'], 0) + item['count']
    rows = sorted(stat.items(), key=lambda x: x[1], reverse=True)
    with open(path.join(hp.BASE_DIR, 'log', 'ori_freq.csv'), 'w') as f:
        writer = csv.writer(f, delimiter='\t')
        writer.writerows(rows)


def stat_ori_freq2():
    """统计原字字种"""
    db = hp.get_db('tw-work')
    vts = list(db.variant.find({}, {'_id': 0, 'txt': 1, 'v_code': 1, 'uni_txt': 1, 'nor_txt': 1}))
    tk2vt = {vt.get('txt') or vt.get('v_code'): vt for vt in vts}
    uni2std = get_uni2std_dict()
    items = []
    with open(path.join(hp.BASE_DIR, 'log', 'ori_freq.csv'), 'r') as f:
        rows = list(csv.reader(f, delimiter='\t'))
    for r in rows:
        tk, freq = r[0], int(r[1])
        vt = tk2vt.get(tk) or {}
        uni_txt = vt.get('uni_txt') or ''
        nor_txt = vt.get('nor_txt') or ''
        std_txt = uni2std.get(tk) or uni2std.get(nor_txt) or ''
        items.append(dict(tk=tk, freq=freq, uni_txt=uni_txt, nor_txt=nor_txt, std_txt=std_txt))

    db2 = hp.get_db('tw-dev')
    # db2.ori_tk.delete_many({})
    r = db2.ori_tk.insert_many(items)
    print(len(r.inserted_ids))


def stat_cmp_freq(db, tk):
    stat = {}
    for j in range(1, 7):
        items = db[f'char{j}'].aggregate([
            {'$match': {'txt': tk}},
            {'$group': {'_id': '$cmp_txt', 'count': {'$sum': 1}}},
        ])
        for it in items:
            stat[it['_id']] = stat.get(it['_id']) or {}
            stat[it['_id']][j] = stat[it['_id']].get(j, 0) + it['count']
    summary = []
    for cmp_txt, cnts in stat.items():
        summary.append([cmp_txt, sum(cnts.values())])
    summary = sorted(summary, key=lambda x: x[1], reverse=True)
    summary = ';'.join([f'{x[0]}#{x[1]}' for x in summary])
    # summary = ';'.join([x[0] for x in summary])
    return summary, stat


def get_uni2std_dict(kind='max'):
    """获取通字转正字字典"""
    fp = path.join(hp.BASE_DIR, 'web/tw/data/uni2std-20250221.csv')
    with open(fp, 'r', encoding='utf-8') as f:
        rows = list(csv.reader(f, delimiter='\t'))[1:]
    if kind == 'max':
        return {row[0]: row[2] for row in rows}
    else:
        return {row[0]: row[4] for row in rows}


def stat_cmp_txt(i=0):
    hp.set_logging('stat_cmp_txt_%s' % i)
    db = hp.get_db('tw-work')
    uni2std = get_uni2std_dict()
    db2 = hp.get_db('tw-dev')
    doc = db2.ori_tk.find_one_and_update({'status': None}, {'$set': {'status': 1}})
    while doc:
        logging.info('%s, %s' % (doc['tk'], doc['freq']))
        cmp_txts, stat = stat_cmp_freq(db, doc['tk'])
        cmp_stds = []
        for item in cmp_txts.split(';'):
            cmp_txt, cnt = item.split('#')
            cmp_stds.append(uni2std.get(cmp_txt) or cmp_txt)
        cmp_stds = ';'.join(cmp_stds)
        db2.ori_tk.update_one({'_id': doc['_id']}, {'$set': {
            'status': 2, 'cmp_txts': cmp_txts,
            'cmp_stds': cmp_stds,
            'cmp_detail': str(stat),
            'std_in_cmp_std': doc['std_txt'] in cmp_stds
        }})
        doc = db2.ori_tk.find_one_and_update({'status': None}, {'$set': {'status': 1}})


def multi_stat_cmp_txt():
    """ 多进程构建数据"""
    cmd = 'nohup python3 %s/web/tw/char.py --func=stat_cmp_txt --i=%s&'
    for i in range(6):
        cmd_i = cmd % (hp.BASE_DIR, i)
        print(cmd_i)
        os.system(cmd_i)


def update_std_txt():
    uni2std = get_uni2std_dict()
    db = hp.get_db('tw-dev')
    cond = {'std_txt': {'$in': [None, '']}}
    items = list(db.ori_tk.aggregate([
        {'$match': cond},
        {'$group': {'_id': '$uni_txt', 'count': {'$sum': 1}}}
    ]))
    items.sort(key=lambda x: x['count'])
    for i, it in enumerate(items):
        print('[%s/%s]%s, %s' % (i, len(items), it['_id'], it['count']))
        std_txt = uni2std.get(it['_id'])
        if std_txt:
            db.ori_tk.update_many({**cond, 'uni_txt': it['_id']}, {'$set': {'std_txt': std_txt}})


def watch():
    db = hp.get_db('tw-dev')
    # r = db.ori_tk.update_many({'status': 1}, {'$set': {'status': None}})
    # print(r.matched_count)
    # return
    print(datetime.now())
    print(db.ori_tk.count_documents({'status': None}))
    print(db.ori_tk.count_documents({'status': 1}))
    print(db.ori_tk.count_documents({'status': 2}))


def process():
    # get_uni2std_dict()
    # watch()
    # stat_cmp_txt()
    # stat_ori_freq2()
    # multi_stat_cmp_txt()
    update_std_txt()


def main(func='process', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
