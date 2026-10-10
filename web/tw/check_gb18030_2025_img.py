#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查 gb18030_2025 字体图片是否存在，不存在则将 b_gb18030_2025 置为 False。
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
    existing = {os.path.splitext(f)[0] for f in os.listdir(img_dir) if f.lower().endswith('.jpg')}
    print(f'[{coll}] {len(existing)} images in {img_dir}')

    missing_ids, total = [], 0
    for doc in db[coll].find({FIELD: True}, {'unicode': 1}):
        total += 1
        if doc.get('unicode') not in existing:
            missing_ids.append(doc['_id'])
    print(f'[{coll}] {FIELD}=True: {total}, image missing: {len(missing_ids)}')

    if apply and missing_ids:
        r = db[coll].update_many({'_id': {'$in': missing_ids}}, {'$set': {FIELD: False}})
        print(f'[{coll}] updated {r.modified_count} docs')
    elif missing_ids:
        print(f'[{coll}] dry run, nothing written (use --apply)')


def main(colls='unicode,gbhan', img_dir='/nas/web-static/tw-aux/fonts/gb18030_2025', apply=False):
    db = hp.get_db('tw-aux')
    if isinstance(colls, str):
        colls = colls.split(',')
    for coll in colls:
        check(db, coll, img_dir, apply)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
