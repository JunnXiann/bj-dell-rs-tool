# !/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from os import path
import pandas as pd

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))
import helper as hp

db_aux = hp.get_db('tw-aux')


def update_degree():
    db_aux.sx_fold.update_many({}, {'$unset': {'degree': ""}})
    data = pd.read_excel(r'../../02_Data/SX-degree.xlsx')

    for index, row in data.iterrows():
        fold_id = row['fold_id']
        error_type = row['outlier']
        degree = row['degree']

        if error_type == '异常':
            continue
        
        r = db_aux.sx_fold.update_one({'fold_id': fold_id}, {'$set': {'degree': degree}})
        print(fold_id, '\t', degree, '\t', r.matched_count)


if __name__ == '__main__':
    update_degree()