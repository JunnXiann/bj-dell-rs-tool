#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查 gb18030_2025 字体图片是否存在，据此设置 b_gb18030_2025（有图 True，无图 False，字段缺失则新增）。
图片路径与 helper.get_font_path 一致：<img_dir>/<unicode>.jpg
默认只预览(dry run)，加 --apply 才真正写库。

python3 web/tw/check_gb18030_2025_img.py --colls=unicode,gbhan
python3 web/tw/check_gb18030_2025_img.py --apply
"""
import os
import sys
from os import path as osp

BASE_DIR = osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__))))
sys.path.append(BASE_DIR)
import helper as hp

FIELD = 'b_gb18030_2025'


def check(db, coll, img_dir, apply):
    """ 按图片是否存在，为集合中所有文档设置正确的 b_gb18030_2025（字段不存在则新增）"""
    existing = {os.path.splitext(f)[0] for f in os.listdir(img_dir) if f.lower().endswith('.jpg')}
    print(f'[{coll}] {len(existing)} images in {img_dir}')

    to_true, to_false, total, no_code = [], [], 0, 0
    for doc in db[coll].find({}, {'unicode': 1, FIELD: 1}):
        total += 1
        code = doc.get('unicode')
        if not code:
            no_code += 1
            continue
        want = code in existing
        if doc.get(FIELD) is not want:  # 字段缺失或值不对
            (to_true if want else to_false).append(doc['_id'])
    print(f'[{coll}] docs: {total}, no unicode: {no_code}, '
          f'to set True: {len(to_true)}, to set False: {len(to_false)}')

    if not apply:
        if to_true or to_false:
            print(f'[{coll}] dry run, nothing written (use --apply)')
        return
    for ids, value in ((to_true, True), (to_false, False)):
        if ids:
            r = db[coll].update_many({'_id': {'$in': ids}}, {'$set': {FIELD: value}})
            print(f'[{coll}] set {FIELD}={value}: {r.modified_count} docs')


def main(colls='unicode,gbhan', img_dir='/nas/web-static/tw-aux/fonts/gb18030_2025', apply=False):
    db = hp.get_db('tw-aux')
    if isinstance(colls, str):
        colls = colls.split(',')
    for coll in colls:
        check(db, coll, img_dir, apply)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
