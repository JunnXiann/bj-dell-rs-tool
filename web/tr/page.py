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


def create_index():
    db = hp.get_db('tr-prod')
    db.page.create_index('flag')


def update_page_ouid2():
    db = hp.get_db('tr-test')
    cond = {}  # 需根据实际情况修改
    pages = list(db.page.find(cond, {'ouid': 1, '_id': 0}))
    for i, p in enumerate(pages):
        print('[%s/%s]%s' % (i, len(pages), p['ouid']))
        ouid2 = hp.align_code(p['ouid'])
        db.page.update_one({'ouid': p['ouid']}, {'$set': {'ouid2': ouid2}})


def update_punc_txt():
    db = hp.get_db('tr-test')
    pages = list(db.page.find({}, {'ouid': 1, '_id': 0}))
    ouids = [p['ouid'] for p in pages]
    cond = {'ouid': {'$in': ouids}}  # 需根据实际情况修改
    db2 = hp.get_db('tr-prod')
    pages2 = list(db2.page.find(cond, {'ouid': 1, 'punc_txt': 1, '_id': 0}))
    for i, p in enumerate(pages2):
        print('[%s/%s]%s' % (i, len(pages2), p['ouid']))
        if not p.get('punc_txt'):
            continue
        db.page.update_one({'ouid': p['ouid']}, {'$set': {'punc_txt': p['punc_txt']}})


def main(func='', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
