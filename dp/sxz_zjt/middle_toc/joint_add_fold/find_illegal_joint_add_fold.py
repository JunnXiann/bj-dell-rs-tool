# -*- coding: utf-8 -*-
"""
@File    : find_error_joint_add_fold.py
@Time    : 2025/5/23 12:49
@Author  : zhujiantao
@Version : 1.0
@Desc    : 根据有效版心列扣图id，过滤出错误加宽的扣图，错误加宽的扣图需要恢复到未加宽之前状态
"""
import json
import os.path


def get_illegal_joint_fold_id_list():
    """
    得到加宽的扣图id
    :return:
    """
    with open("joint_add_fold_id_list.json", "r") as f:
        joint_add_fold_id_list = json.loads(f.read())

    has_middle_toc_list = []
    file_order_list = [1, 3, 4, 5]
    for i in file_order_list:
        file_path = os.path.join("../legal_middle_toc_find_ocr_chars", f"has_middle_toc_fold_id_list_{i}.json")
        with open(file_path) as f:
            tmp_list = json.loads(f.read())
            has_middle_toc_list.extend([tmp[3: ] for tmp in tmp_list])

    print(f"版心列扣图数量={set(has_middle_toc_list)}")
    legal_fold_set = set(set(joint_add_fold_id_list) & set(has_middle_toc_list))
    print(f"加宽扣图数量={len(joint_add_fold_id_list)}")
    print(f"正确加宽扣图数量={len(legal_fold_set)}")
    illegal_fold_set = (set(joint_add_fold_id_list) - legal_fold_set)
    print(f"错误加宽扣图数量={len(illegal_fold_set)}")


get_illegal_joint_fold_id_list()



