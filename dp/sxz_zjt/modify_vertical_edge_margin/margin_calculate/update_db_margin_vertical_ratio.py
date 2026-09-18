"""
@File    : update_db_margin_vertical_ratio.py
@Time    : 2025/5/27 13:53
@Author  : zhujiantao
@Version : 1.0
@Desc    : 将计算出来的扣图上下空白高度及比例(在json数据库)更新到线上mongodb数据库,在dell服务器上运行
"""
import os
import json
import sys
from os import path
import multiprocessing


sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))
import helper as hp


db_aux = hp.get_db('tw-aux')


def insert_margin_vertical_to_mongodb(file_order):
    """
    将扣图上下空白高度及比例插入到数据库中
    :param file_order: 文本后缀序号
    :return:
    """
    margin_dir = "margin_dir"
    tmp_path = os.path.join(margin_dir, f"margin_{file_order}.json")
    with open(tmp_path, "r") as f:
        tmp_list = json.loads(f.read())
        for tmp_dict in tmp_list:
            top_margin = tmp_dict.get("top_margin")
            bottom_margin = tmp_dict.get("bottom_margin")
            top_bottom_ratio = top_margin / bottom_margin
            fold_id = tmp_dict.get("fold_id")

            query = {
                'fold_id': fold_id,
                'deleted': {
                    '$exists': False
                }
            }

            new_field = {
                "$set": {
                    "top_margin": top_margin,
                    "bottom_margin": bottom_margin,
                    "top_bottom_ratio": top_bottom_ratio
                }
            }

            r = db_aux.sx_fold.update_one(query, new_field)
            print(f"fold_id----->{fold_id}  {r.matched_count}")


if __name__ == "__main__":
    processes = []
    for i in range(0, 12):
        p = multiprocessing.Process(target=insert_margin_vertical_to_mongodb, args=(i, ))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()
