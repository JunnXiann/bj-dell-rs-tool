import os
import sys
import csv
import json
from os import path


def load_json(fn):
    if not path.exists(fn):
        return {}
    with open(fn, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(obj, fn):
    root = path.dirname(fn)
    path.exists(root) or os.makedirs(root)
    with open(fn, 'w', encoding='utf-8') as f:
        json.dump(obj, f)


def load_csv(fn):
    if not path.exists(fn):
        return []
    with open(fn, 'r', encoding='utf-8') as f:
        return list(csv.reader(f))


def save_csv(rows, fn):
    root = path.dirname(fn)
    path.exists(root) or os.makedirs(root)
    with open(fn, 'w', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def merge_data_json(data1, data2):
    data = {}
    for tk, names in data2.items():
        if tk in data1:
            data[tk] = list(set(data1[tk] + names))
        else:
            data[tk] = names
    return data


def get_label_num(n_src):
    """ 根据源字频，计算标注字频 """
    if n_src > 2000:
        n_train = n_test = 200
    elif n_src > 1500:
        n_train = n_test = 180
    elif n_src > 1000:
        n_train = n_test = 160
    elif n_src > 500:
        n_train = n_test = 140
    elif n_src > 240:
        n_train = n_test = 120
    elif n_src > 200:
        n_train = (n_src // 2) + (n_src % 2)
        n_test = n_src // 2
    elif n_src > 120:
        n_train = 100
        n_test = n_src - 100
    elif n_src > 100:
        n_test = 20
        n_train = n_src - 20
    else:
        n_train = (n_src // 5) * 4
        n_test = n_src - n_train
    return n_train, n_test


def get_unicode(char):
    """ 字符转unicode """
    code = char.encode('unicode_escape').decode('utf-8')
    code = 'U+%s' % (code.upper().replace(r'\U', '').lstrip('0'))
    return code


def merge_ocr_res(main_alternatives, sub_alternatives):
    """ 对双引擎的识别结果进行合并、排序、去重，取前10个结果"""
    if isinstance(main_alternatives, str):
        main_alternatives = main_alternatives.split(',')
    if isinstance(sub_alternatives, str):
        sub_alternatives = sub_alternatives.split(',')
    # 合并、排序
    main_lst = [[i, 0, x] for i, x in enumerate(main_alternatives)]
    sub_lst = [[i, 1, x] for i, x in enumerate(sub_alternatives)]
    main_lst.extend(sub_lst)
    sorted_lst = sorted(main_lst, key=lambda x: (x[0], x[1]))
    # 去重
    alternatives_list = []
    for sublst in sorted_lst:
        if sublst[2] not in alternatives_list:
            alternatives_list.append(sublst[2])
    # 取前10个候选文字
    alternatives = ','.join(alternatives_list[:10])
    return alternatives
