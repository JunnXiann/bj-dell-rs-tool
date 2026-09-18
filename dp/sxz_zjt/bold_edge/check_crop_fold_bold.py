# -*- coding: utf-8 -*-
"""
@File    : check_crop_fold_bold.py
@Time    : 2025/5/21 14:43
@Author  : zhujiantao
@Version : 1.0
@Desc    : 找到pdf显示没有黑色边框，但是抽取出来的包含黑色边框的扣图
运行之前先运行find_bold_edge_fold.py得到dell_bold_edge_fold_id_list.json内容
"""
import os
import json

from dp.sxz_improve.crop_fold import crop_fold
from dp.sxz_improve.bold_edge.find_bold_edge_fold import black_pixel_ratio_edges, max_black_continuous_ratio_edges


def crop_fold_image(fold_id_list: list):
    """
    从pdf裁剪扣图
    :param fold_id_list: 扣图id列表
    :return:
    """
    # 从pdf裁剪对应的扣图
    crop_fold.crop_fold(fold_id_list)



def get_bold_edge_fold_id_list(tmp_dir):
    """
    得到所有黑色边框扣id列表
    :param tmp_dir: 扣图所在路径
    :return:
    """
    fold_id_list = []

    # 裁剪出来的扣图会比

    # 边缘黑色像素占比（4个版心千字文字体的高度）
    LEFT_RATIO_THRESHOLD = 0.04
    RIGHT_RATIO_THRESHOLD = 0.04

    # 连续黑色像素占比（1个经文文字字体的高度）
    LEFT_MAX_BLACK_CONTINUOUS_RATIO = 0.1
    RIGHT_MAX_BLACK_CONTINUOUS_RATIO = 0.1

    for file in os.listdir(tmp_dir):

        file_path = os.path.join(tmp_dir, file)
        print(f"遍历图片=={file_path}")
        if not file.endswith(".jpg"):
            continue

        left_ratio, right_ratio = black_pixel_ratio_edges(file_path, 60, 60)

        if left_ratio >= LEFT_RATIO_THRESHOLD or right_ratio >= RIGHT_RATIO_THRESHOLD:

            left_max_black_continuous_ratio, right_max_black_continuous_ratio = max_black_continuous_ratio_edges(file_path, 60, 60)
            if (left_max_black_continuous_ratio > LEFT_MAX_BLACK_CONTINUOUS_RATIO
                    or right_max_black_continuous_ratio > RIGHT_MAX_BLACK_CONTINUOUS_RATIO):
                # 边缘连续黑色像素过大,可定位黑色边框
                fold_id = file.split(".")[0]
                fold_id_list.append(fold_id)
    return fold_id_list


if __name__ == "__main__":
    with open("dell_bold_edge_fold_id_list.json", "r") as f:
        # 得到线上包含黑色边框的扣图id
        dell_fold_id_list = json.loads(f.read())

    # 裁剪pdf对应扣图,这一步比较运行比较耗时
    crop_fold_image(dell_fold_id_list)

    # 得到pdf上面扣图有黑色边框的扣图
    pdf_fold_list = get_bold_edge_fold_id_list("crop_new_fold")

    # 找到需要替换线上的扣图id
    need_update_fold_id_list = list(set(dell_fold_id_list) - set(pdf_fold_list))
    print("需要替换的扣图如下:")
    print(need_update_fold_id_list)
