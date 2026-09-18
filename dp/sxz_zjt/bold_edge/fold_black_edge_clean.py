# -*- coding: utf-8 -*-
"""
@File    : fold_black_edge_clean.py
@Time    : 2025/5/26 12:54
@Author  : zhujiantao
@Version : 1.0
@Desc    : 清除扣图黑色边框，扣图类型为：pdf上面没有黑色边框，但是从pdf抽取的扣图包含黑色边框。
思路：得到扣图最左最右列对应的横坐标，清除最左最右之外的黑色像素
程序在本地运行,运行之前先执行fold_column_location_find.py得到need_delete_bold_edge_fold_column_list.json
"""
import json
import os.path

import cv2

from dp.sxz_improve.fold_image_download.download_fold_image import download_fold_image_multiprocessing


def download_fold_image():
    """
    下载扣图到本地
    :return:
    """
    with open("need_delete_bold_edge_fold_list.json", "r") as f:
    # with open("download_fail_fold_id_list.json", "r") as f:
        need_delete_bold_edge_fold_list = json.loads(f.read())

    download_fold_image_multiprocessing(need_delete_bold_edge_fold_list)


def get_fold_edge_column_list():
    """
    得到所有扣图左右列位置信息
    :return:
    """
    with open("need_delete_bold_edge_fold_column_list.json", "r") as f:
        need_delete_bold_edge_fold_column_list = json.loads(f.read())
    return need_delete_bold_edge_fold_column_list


def clean_bold_edge(direction="all"):
    """
    清理黑色边框
    :param direction: all表示左右两边 left表示坐标 right表示右边
    :return:
    """
    download_fail_fold_id_list = []

    no_black_edge_fold_image = "no_black_edge_fold_image"

    if not os.path.exists(no_black_edge_fold_image):
        os.makedirs(no_black_edge_fold_image)

    need_delete_bold_edge_fold_column_list = get_fold_edge_column_list()
    for column_dict in need_delete_bold_edge_fold_column_list:
        fold_id = column_dict.get("fold_id")
        max_left_column_dict = column_dict.get("max_left_column")
        max_right_column_dict = column_dict.get("max_right_column")
        # 列开始坐标
        start_x = int(max_left_column_dict.get("x"))
        # 列结束坐标
        end_x = int(max_right_column_dict.get("x") + max_right_column_dict.get("w"))

        fold_image_path = f"download_fold_image/SX_{fold_id}.jpg"
        image = cv2.imread(fold_image_path, cv2.IMREAD_UNCHANGED)

        try:
            h, w = image.shape[:2]
        except AttributeError:
            print(f"{fold_id}获取高宽信息异常")
            download_fail_fold_id_list.append(fold_id)
            continue

        crop_flag = True

        if "all" == direction:
            if 0 != start_x and w != end_x:
                print("左右边都需要剪切")
                image[:, 0: start_x] = 255
                image[:, end_x:] = 255
            else:
                print("左右边都不需要剪切")
                crop_flag = False
        elif "left" == direction:
            if 0 != start_x and w == end_x:
                print("扣图左边去除黑框")
                image[:, 0: start_x] = 255
            else:
                print("左边不需要剪切")
                crop_flag = False
        elif "right" == direction:
            if 0 == start_x and w != end_x:
                print("扣图右边去除黑框")
                image[:, end_x:] = 255
            else:
                print("右边不需要剪切")
                crop_flag = False
        else:
            raise ValueError(f"{direction}参数必须为left、right或者all")

        if crop_flag:
            new_h, new_w = image.shape[:2]
            print(f"{fold_id} start_x={start_x} end_x={end_x} 裁切前宽度={w} 裁切后宽度={new_w}")
            new_fold_image_path = os.path.join(no_black_edge_fold_image, f"{fold_id}.jpg")
            cv2.imwrite(new_fold_image_path, image, [int(cv2.IMWRITE_JPEG_QUALITY), 100])

    with open("download_fail_fold_id_list.json", "w") as f:
        f.write(json.dumps(download_fail_fold_id_list))


if __name__ == "__main__":
    # download_fold_image()
    clean_bold_edge(direction="right")
