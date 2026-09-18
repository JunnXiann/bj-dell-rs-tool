# -*- coding: utf-8 -*-
"""
@File    : write_joint_add_fold_id_list.py
@Time    : 2025/5/23 03:12
@Author  : zhujiantao
@Version : 1.0
@Desc    : 从joint_add.txt读取内容，得到加宽扣id列表追加到joint_add_fold_id_list.json文件
"""

import json

def write_joint_add_fold_id_list():
    """
    将所有拼接过的文件写入到json文件
    :return: 
    """
    with open("joint_add.txt", "r") as f:
        content = f.read()
    
    joint_add_fold_id_list = []
    
    for line in content.split("\n"):
        no_empty_line = line.strip()
        if no_empty_line:
            fold_id = line.split("/")[-1].split(".")[0][3:]
            joint_add_fold_id_list.append(fold_id)
        
    with open("joint_add_fold_id_list.json", "w") as f:
        f.write(json.dumps(joint_add_fold_id_list))


write_joint_add_fold_id_list()

