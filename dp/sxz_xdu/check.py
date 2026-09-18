import os
import sys
import csv
import fitz  # PyMuPDF
import logging
from PIL import Image
from os import path as osp

BASE_DIR = osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__))))
sys.path.append(BASE_DIR)

import helper as hp


def stat_pdf_page_num():
    """ 统计pdf文件的页数"""
    rows = [['函号', '文件名', '页数']]
    root = '/nas/data/T/原始藏经资料/07思溪藏SX/思溪藏_扬州古籍_PDF'
    for vol in os.listdir(root):
        print(vol)
        vol_path = osp.join(root, vol)
        if not osp.isdir(vol_path):
            continue
        for file in os.listdir(vol_path):
            if not file.endswith('.pdf'):
                continue
            file_path = osp.join(vol_path, file)
            try:
                doc = fitz.open(file_path)
                rows.append([vol, file.replace('.pdf', ''), len(doc)])
            except Exception as e:
                print(f"Error opening {file}: {e}")
    with open(osp.join(BASE_DIR, 'log/pdf_page_num.csv'), 'w') as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def check_page_num_equal():
    """ 检查页码一致性"""
    # 读取文件页码
    with open(osp.join(BASE_DIR, 'log/pdf_page_num.csv'), 'r') as f:
        rows = list(csv.reader(f))[1:]
    pdf_name2num = {'%s-%s' % (int(row[0]), row[1]): int(row[2]) for row in rows if row}
    # 读取数据库sx_volume表的页码
    db = hp.get_db('ax-prod')
    volumes = list(db.sx_volume.find({}, {'pdf_name': 1, 'page_n': 1, 'han': 1, '_id': 0}))
    volume_name2num = {'%s-%s' % (vol['han'], vol['pdf_name']): vol['page_n'] for vol in volumes}
    # 读取数据库sx_pdf_page表的页码
    counts = list(db.sx_pdf_page.aggregate([
        {
            "$project": {
                "_id": 0,
                "key": {
                    "$concat": [{"$toString": "$han"}, "-", "$pdf_name"]
                }
            }
        },
        {'$group': {'_id': '$key', 'count': {'$sum': 1}}},
    ]))
    page_name2num = {c['_id']: c['count'] for c in counts}
    keys = list(set(pdf_name2num.keys()) | set(volume_name2num.keys()) | set(page_name2num.keys()))
    rows2 = [['函号', '文件名', 'pdf文件页数', 'sx_volume页数', 'sx_pdf_page页数', '是否一致']]
    for k in keys:
        nums = [pdf_name2num.get(k, '-'), volume_name2num.get(k, '-'), page_name2num.get(k, '-')]
        equal = nums[0] == nums[1] == nums[2]
        rows2.append([*k.split('-'), *nums, 'Y' if equal else 'N'])
    with open(osp.join(BASE_DIR, 'log/pdf_page_num_equal.csv'), 'w') as f:
        writer = csv.writer(f)
        writer.writerows(rows2)


def update_sx_volume_page_n0():
    """ 更新sx_volume表的page_n字段"""
    # 读取文件页码
    db = hp.get_db('ax-prod')
    with open(osp.join(BASE_DIR, 'log/pdf_page_num_equal.csv'), 'r') as f:
        rows = list(csv.reader(f))[1:]
    for i, r in enumerate(rows):
        han, pdf_name, pdf_page_n, volume_page_n, page_page_n, equal = r
        if equal == 'N' and pdf_page_n == page_page_n:
            print(r)
            ret = db.sx_volume.update_one({'han': int(han), 'pdf_name': pdf_name}, {
                '$set': {'page_n': int(pdf_page_n), 'page_n0': int(volume_page_n)}})
            print(ret.matched_count)


def set_invalid_fold():
    """设置无效扣"""
    db = hp.get_db('ax-prod')
    # 设置重复的实扣
    cond = {'deleted': {'$exists': True}}
    r = db.sx_fold.update_many(cond, {'$set': {'invalid': True}})
    print(r.matched_count)
    # 设置空白扣
    cond = {'fold_mean': None, 'name_mean': None}
    r = db.sx_fold.update_many(cond, {'$set': {'invalid': True}})
    print(r.matched_count)
    # 设置册尾多余的空扣
    volumes = list(db.sx_volume.find({}, {'han': 1, 'vol_ok': 1, 'max_no': 1}))
    for vol in volumes:
        cond = {'fold_mean': None, 'han': vol['han'], 'vol_ok': vol['vol_ok'],
                'fold_no': {'$gt': vol['max_no']}}
        r = db.sx_fold.update_many(cond, {'$set': {'invalid': True}})
        print(vol['han'], vol['vol_ok'], vol['max_no'], r.matched_count)


def set_sx_fold_status():
    """ 设置sx_fold表的status字段"""
    db = hp.get_db('ax-prod')
    # 有效实扣
    r = db.sx_fold.update_many({"fold_mean": {'$ne': None}, 'invalid': None}, {'$set': {'status': 1}})
    print(r.matched_count)
    # 有效空扣
    r = db.sx_fold.update_many({"fold_mean": None, 'invalid': None}, {'$set': {'status': 2}})
    print(r.matched_count)
    # 无效实扣
    r = db.sx_fold.update_many({"fold_mean": {'$ne': None}, 'invalid': True}, {'$set': {'status': 3}})
    print(r.matched_count)
    # 无效空扣
    r = db.sx_fold.update_many({"fold_mean": None, 'invalid': True}, {'$set': {'status': 4}})
    print(r.matched_count)


def export_sx_volume_csv():
    """ 将sx_volume导出为csv"""
    db = hp.get_db('ax-prod')
    cond = {}
    folds = list(db.sx_volume.find(cond))
    rows = [['函号', '文件名', '文件册号', '扣名册号', '最终册号', '页数',
             '起始扣号', '结束扣号', '非空扣数', '空扣数', '空白扣数',
             '首页空扣编号', '中间页空扣编号', '末页空扣编号', '非空扣前的空扣数',
             '末尾有几扣在其它册']]
    fields = ['han', 'pdf_name', 'vol_pdf', 'vol_fold', 'vol_ok', 'page_n',
              'min_no', 'max_no', 'fold_n', 'empty_n', 'blank_n',
              'front_empty', 'mid_empty', 'end_empty', 'start_empty',
              'diff_vol_n']
    for f in folds:
        f['blank_n'] = f.get('page_n', 0) * 10 - f.get('fold_n', 0) - f.get('empty_n', 0)
        rows.append([f.get(field, '-') for field in fields])
    fp = osp.join(BASE_DIR, 'log/sx_volume_check.csv')
    with open(fp, 'w') as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def check_sx_volume():
    """检查fold_n、empty_n的准确性"""
    db = hp.get_db('ax-prod')
    folds = list(db.sx_volume.find({}))
    # 检查有效空扣数量是否一致
    name2num = {'%s-%s' % (f['han'], f['vol_ok']): f['fold_n'] for f in folds}
    counts = list(db.sx_fold.aggregate([
        {'$match': {'fold_mean': {'$ne': None}, 'deleted': None}},
        {
            "$project": {
                "_id": 0,
                "key": {
                    "$concat": [{"$toString": "$han"}, "-", {"$toString": "$vol_ok"}]
                }
            }
        },
        {'$group': {'_id': '$key', 'count': {'$sum': 1}}}
    ]))
    name_2num = {c['_id']: c['count'] for c in counts}
    for k, v in name2num.items():
        v2 = name_2num.get(k, 0)
        if v != v2:
            print(f"{k}\t{v}\t{v2}")


def check_sx_volume_page_n():
    """检查sx_volume的page_n字段是否正确"""
    db = hp.get_db('ax-prod')
    volumes = list(db.sx_volume.find({}, {'_id': 1, 'page_n': 1, 'pdf_name': 1}))
    name2num = {f"{v['pdf_name']}": v['page_n'] * 10 for v in volumes}
    counts = list(db.sx_fold.aggregate([
        {'$group': {'_id': f'$pdf_name', 'count': {'$sum': 1}}},
    ]))
    name2num2 = {c['_id']: c['count'] for c in counts}
    for name, num in name2num.items():
        num2 = name2num2.get(name, None)
        if not num2 or num != num2:
            print(f"{name}\t{num}\t{num2}")


def check_sx_fold_and_image():
    """ 检查数据库的sx_fold表和实际图片的宽高是否一致"""
    hp.set_logging('check_sx_fold_and_image')
    db = hp.get_db('ax-prod')
    folds = list(db.sx_fold.find({'status': 1}, {'fold_id': 1, 'w': 1, 'h': 1}))
    root = '/nas/data/T/big/SX'
    total = len(folds)
    for i, fd in enumerate(folds):
        fid = fd['fold_id']
        print('[%s/%s]%s' % (i + 1, total, fid))
        fp = osp.join(root, *fid.split('_')[:-1], 'SX_%s.jpg' % fid)
        img = Image.open(fp)
        w, h = img.size
        if w != fd['w'] or h != fd['h']:
            logging.info(f"{fid}: ({fd['w']}, {fd['h']}) != ({w}, {h})")


def process():
    pass


def main(func='process', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
