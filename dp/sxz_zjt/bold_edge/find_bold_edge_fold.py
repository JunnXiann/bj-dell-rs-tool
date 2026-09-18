# -*- coding: utf-8 -*-
"""
@File    : find_bold_edge_fold.py
@Time    : 2025/5/21 14:43
@Author  : zhujiantao
@Version : 1.0
@Desc    : 在dell服务器上检测线上扣图含黑色边框的扣图，得到扣图id列表
"""
import json
import os

import cv2
import numpy as np
import multiprocessing


def black_pixel_ratio_edges(_image_path, left_width_threshold=50, right_width_threshold=50):
    """
    检测图片左右边缘像素黑色占比
    当边缘黑色像素比例代表切破的严重程度
    :param _image_path:
    :return:
    """
    # 读取图片为灰度图片
    img = cv2.imread(_image_path, 0)
    # 获取图像的高度和宽度
    height, width = img.shape

    # 检测图片左边横坐标10个像素最大黑色像素占比
    _max_left_ratio = 0
    for i in range(left_width_threshold):
        # 左侧边缘黑色像素计数
        left_black_count = 0
        for y in range(height):
            if img[y, i] < 128:
                left_black_count += 1
        _left_ratio = left_black_count / height
        # 取最大占比
        _max_left_ratio = _left_ratio if _left_ratio > _max_left_ratio else _max_left_ratio

    _max_right_ratio = 0
    for i in range(right_width_threshold):
        # 右侧边缘黑色像素计数
        right_black_count = 0
        for y in range(height):
            if img[y, width - 1 - i] < 128:
                right_black_count += 1
        _right_ratio = right_black_count / height
        _max_right_ratio = _right_ratio if _right_ratio > _max_right_ratio else _max_right_ratio

    return _max_left_ratio, _max_right_ratio


def max_black_continuous_ratio_edges(image_path, left_width_threshold=50, right_width_threshold=50):
    """
    检测边缘最大连续黑色像素区域对边缘占比
    比例过大应该是非字体
    :param image_path:
    :return:
    """
    # 读取图片并转为灰度图
    img = cv2.imread(image_path, 0)
    height, width = img.shape

    # 检测左侧边缘最大连续黑色像素区域占比
    left_max_length = 0
    for i in range(left_width_threshold):
        current_length = 0
        for y in range(height):
            if img[y, i] < 128:
                current_length += 1
            else:
                if current_length > left_max_length:
                    left_max_length = current_length
                current_length = 0
        if current_length > left_max_length:
            left_max_length = current_length
    _left_ratio = left_max_length / height if height > 0 else 0

    # 检测右侧边缘最大连续黑色像素区域占比
    right_max_length = 0
    for i in range(right_width_threshold):
        current_length = 0
        for y in range(height):
            if img[y, width - 1 - i] < 128:
                current_length += 1
            else:
                if current_length > right_max_length:
                    right_max_length = current_length
                current_length = 0
        if current_length > right_max_length:
            right_max_length = current_length
    _right_ratio = right_max_length / height if height > 0 else 0

    return _left_ratio, _right_ratio


def get_bold_edge_fold_id_list(tmp_dir_list: list, list_order: int):
    """
    得到所有黑色边框扣id列表
    :param list_order:
    :param tmp_dir_list: 涵路径列表
    :return:
    """
    jpg_info_list = []
    for tmp_dir in tmp_dir_list:

        # 边缘黑色像素占比（4个版心千字文字体的高度）
        LEFT_RATIO_THRESHOLD = 0.04
        RIGHT_RATIO_THRESHOLD = 0.04

        # 连续黑色像素占比（1个经文文字字体的高度）
        LEFT_MAX_BLACK_CONTINUOUS_RATIO = 0.1
        RIGHT_MAX_BLACK_CONTINUOUS_RATIO = 0.1

        for volume_dir in os.listdir(tmp_dir):
            # 遍历册路径

            for file in os.listdir(os.path.join(tmp_dir, volume_dir)):

                file_path = os.path.join(tmp_dir, volume_dir, file)
                print(f"遍历图片=={file_path}")
                if not file.endswith(".jpg"):
                    continue

                left_ratio, right_ratio = black_pixel_ratio_edges(file_path)

                if left_ratio >= LEFT_RATIO_THRESHOLD or right_ratio >= RIGHT_RATIO_THRESHOLD:

                    left_max_black_continuous_ratio, right_max_black_continuous_ratio = max_black_continuous_ratio_edges(file_path)
                    if (left_max_black_continuous_ratio > LEFT_MAX_BLACK_CONTINUOUS_RATIO
                            or right_max_black_continuous_ratio > RIGHT_MAX_BLACK_CONTINUOUS_RATIO):
                        # 边缘连续黑色像素过大,可定位黑色边框
                        jpg_info_list.append({"filename": file, "left_ratio": left_ratio, "right_ratio": right_ratio})

    if not os.path.exists("tmp"):
        os.makedirs("tmp")
    else:
        for filename in os.listdir("tmp"):
            file_path = os.path.join("tmp", filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

    with open(f"result/{list_order}.json", "w") as f:
        f.write(json.dumps(jpg_info_list))


if __name__ == "__main__":
    # 在dell服务器运行，找到所有黑色边框扣图
    # 得到所有涵路径
    han_dir_list = [os.path.join("/nas/data/T/big/SX", tmp_dir) for tmp_dir in os.listdir("/nas/data/T/big/SX")]
    # 将所有涵路径分为8个列表
    chunks = np.array_split(han_dir_list, 16)
    chunk_list = [chunk.tolist() for chunk in chunks]

    # 启动多进程
    processes = []
    for i in range(16):
        p = multiprocessing.Process(target=get_bold_edge_fold_id_list, args=(chunk_list[i], i))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()
