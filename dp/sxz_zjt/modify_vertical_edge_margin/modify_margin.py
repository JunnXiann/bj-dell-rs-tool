# -*- coding: utf-8 -*-
"""
@File    : modify_margin.py
@Time    : 2025/5/22 16:15
@Author  : zhujiantao
@Version : 1.0
@Desc    : 1. 保持原来的高度
2. 清晰度不受影响
3. 考虑已校对扣图情况，保持字，列等坐标(纵坐标)正确性。
4.需要考虑特殊情况,例如上下空白不适合调整
(1)上下空白高度不超过扣图高度的20%
(2)符合第一点的同时，考虑上下高度突破黑色横线，找到上下空白高度超过栏上下高度
5. 在dell服务器上运行，运行前备份所有扣图
"""
import os
import traceback
import multiprocessing
import sys
from os import path

import cv2
import numpy as np
import pymongo

sys.path.append(path.dirname(path.dirname(path.dirname(path.dirname(path.abspath(__file__))))))

import helper as hp


def modify_fold_margin(image_path: str, top_margin: int, bottom_margin: int):
    """
    调整扣图上下空白高度
    :param image_path: 扣图路径
    :param top_margin: 上方空白
    :param bottom_margin: 下方空白
    :return: 调整结果，调整高度
    """
    try:
        # 读取原始图像（不压缩）
        image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError("无法读取图像，请检查路径。")

        h, w = image.shape[:2]

        # 需要裁剪的高度
        delta_height = int(abs(top_margin - bottom_margin) / 2)

        if top_margin > bottom_margin:
            # 上部空白较高，从顶部截图空白补到扣图下方
            top_crop = image[0: delta_height, :]
            remained_crop = image[delta_height: h, :]
            # 拼接到底部
            result = np.vstack((remained_crop, top_crop))
        else:
            # 下方空白较高
            bottom_crop = image[h - delta_height: h, :]
            remained_crop = image[0: h - delta_height, :]
            # 拼接到顶部
            result = np.vstack((bottom_crop, remained_crop))

        # 保存图像
        cv2.imwrite(image_path, result, [int(cv2.IMWRITE_JPEG_QUALITY), 100])

        # 上方剪切返回负数
        modify_height = -delta_height if top_margin - bottom_margin else delta_height

    except:
        print(traceback.format_exc())
        return False, 0
    else:
        return True, modify_height


def get_fold_id_by_filename(filename: str) -> str:
    """
    通过扣图文件名得到对应的扣id
    :param filename: 例如 SX_1_2_3.jpg
    :return:
    """
    filename_without_suffix = filename.split(".")[0]
    # 去掉SX_
    fold_id = filename_without_suffix[3:]
    return fold_id


def get_mongodb_client():
    """
    得到mongodb链接
    :return:
    """
    return hp.get_db('tw-aux')
    #return pymongo.MongoClient(host='localhost', timeoutMS=5000, socketTimeoutMS=8000)


def get_margin_info_by_fold_id(fold_id: str) -> dict:
    """
    通过扣id得到对应的空白信息
    :param fold_id: 扣id
    :return:
    """
    dbclient = get_mongodb_client()
    print(f"fold_id=={fold_id}")
    fold_dict = dbclient.sx_fold.find_one({"fold_id": fold_id})
    bottom_margin = fold_dict.get("bottom_margin")
    top_bottom_ratio = fold_dict.get("top_bottom_ratio")
    top_margin = fold_dict.get("top_margin")
    fold_height = fold_dict.get("h")
    if all([bottom_margin, top_bottom_ratio, top_margin, fold_height]):
        return {
            "bottom_margin": bottom_margin,
            "top_bottom_ratio": top_bottom_ratio,
            "top_margin": top_margin,
            "fold_height": fold_height
        }
    else:
        return {}


def get_fold_block_top_bottom_y(fold_id: str) -> tuple:
    """
    通过扣id获取栏开始和结束纵坐标
    :param fold_id:
    :return: (栏开始纵坐标、栏结束纵坐标)
    """
    fold_id = f"SX_{fold_id}"
    # 得到数据库链接
    db_work = hp.get_db('tw-work')
    # 443039代表思溪藏 name代表扣id
    cond2 = {'flag': 443039, 'name': fold_id}
    # 得到页信息
    page = db_work.page.find_one(cond2)
    # 思溪藏每张扣图只有一栏
    block = page.get("blocks")[0]
    # 栏开始纵坐标
    block_top_y = block.get("y")
    # 栏结束纵坐标
    block_bottom_y = block_top_y + block.get("h")
    return block_top_y, block_bottom_y


def get_illegal_fold_id_list() -> list:
    """
    得到上下空白不适合调整的扣图id列表
    :return:
    """
    db_client = get_mongodb_client()
    illegal_fold_id_list = db_client.sx_fold.find({
        '$or': [
            {
                '$expr': {
                    '$gte': [
                        '$bottom_margin', {
                            '$multiply': [
                                '$h', 0.20
                            ]
                        }
                    ]
                }
            }, {
                '$expr': {
                    '$gte': [
                        '$top_margin', {
                            '$multiply': [
                                '$h', 0.20
                            ]
                        }
                    ]
                }
            }
        ]
    }, {"_id": 0, "fold_id": 1})

    return illegal_fold_id_list


def update_margin_modify_result(fold_id: str, delta_height: int):
    """
    根据fold_id更新调整结果
    :param delta_height: 调整的高度 整数表示
    :param fold_id: 扣图id
    :return:
    """
    db_client = get_mongodb_client()
    query = {
        'fold_id': fold_id,
        'deleted': {
            '$exists': False
        }
    }

    new_field = {
        "$set": {
            "top_bottom_margin": 1,
            "modify_height": delta_height
        }
    }

    r = db_client.sx_fold.update_one(query, new_field)
    print(f"{fold_id}更新调整记录数量{r.matched_count}")


def modify_fold_margin_in_dir(han_dir_list: list, han_dir_list_order: int):
    """
    批量处理涵路径下所有扣图
    :param han_dir_list: 涵路径列表
    :param han_dir_list_order: 涵路径列表序号
    :return:
    """
    log_dir = "log_dir"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 得到不适合调整的扣图id列表
    illegal_fold_id_list = get_illegal_fold_id_list()
    for tmp_han_dir in han_dir_list:
        print(f"tmp_han_dir===={tmp_han_dir}")
        if os.path.isfile(tmp_han_dir):
            continue
        # 遍历对应的涵路径
        for tmp_volume_dir in os.listdir(tmp_han_dir):
            print(f"tmp_volume_dir====={tmp_volume_dir}")
            # 遍历所有册路径
            abs_tmp_volume_dir = os.path.join(tmp_han_dir, tmp_volume_dir)
            print(f"abs_tmp_volume_dir==={abs_tmp_volume_dir}")
            if os.path.isfile(abs_tmp_volume_dir):
                continue
            for tmp_file in os.listdir(abs_tmp_volume_dir):
                # 得到扣图绝对路径
                abs_fold_image_dir = os.path.join(abs_tmp_volume_dir, tmp_file)
                # 通过文件名得到对应的扣id
                fold_id = get_fold_id_by_filename(tmp_file)
                print(f"当前fold_id======{fold_id}")
                if fold_id in illegal_fold_id_list:
                    print(f"{fold_id}上下空白高度不适合调整...")
                    continue
                # 从数据库得到扣图上下高度信息
                margin_dict = get_margin_info_by_fold_id(fold_id)
                if not margin_dict:
                    # 打印日志
                    log_file = os.path.join(log_dir, f"no_margin_data_{han_dir_list_order}.txt")
                    with open(log_file, "a") as f:
                        f.write(f"{fold_id}\n")
                    continue
                else:
                    bottom_margin = margin_dict.get("bottom_margin")
                    top_bottom_ratio = margin_dict.get("top_bottom_ratio")
                    top_margin = margin_dict.get("top_margin")
                    fold_height = margin_dict.get("fold_height")

                    block_top_y, block_bottom_y = get_fold_block_top_bottom_y(fold_id)
                    # 如果栏开始纵坐标大于上方空白高度，或者扣图高度减去栏结束纵坐标小于下方空白高度
                    if block_top_y < top_margin or block_bottom_y > (fold_height - bottom_margin):
                        print(f"{fold_id}空白高度有问题...")
                        log_file = os.path.join(log_dir, f"error_margin_{han_dir_list_order}.txt")
                        with open(log_file, "a") as f:
                            f.write(f"{fold_id}\n")
                        continue
                    if 0.8 < top_bottom_ratio < 1.2:
                        print(f"{fold_id}上下空白在正常范围不需要调整")
                    else:
                        result, delta_height = modify_fold_margin(abs_fold_image_dir, top_margin, bottom_margin)
                        if result is True:
                            # 更新mongodb记录
                            update_margin_modify_result(fold_id, delta_height)
                        else:
                            print("裁剪扣图异常...")
                            log_file = os.path.join(log_dir, f"error_modify_fold_{han_dir_list_order}.txt")
                            with open(log_file, "a") as f:
                                f.write(f"{fold_id}\n")


def modify_fold_margin_in_multiprocessing():
    """
    多进程调整所有扣图
    :return:
    """
    # 在dell服务器运行
    SX_FOLD_DIR = "/home/zjt/SX_part"
    # 得到所有涵路径
    han_dir_list = [os.path.join(SX_FOLD_DIR, tmp_dir) for tmp_dir in os.listdir(SX_FOLD_DIR)]
    print(han_dir_list)
    # 将所有涵路径分为8个列表
    chunks = np.array_split(han_dir_list, 8)
    chunk_list = [chunk.tolist() for chunk in chunks]
    print(chunk_list)

    # 启动多进程
    processes = []
    for i in range(8):
        p = multiprocessing.Process(target=modify_fold_margin_in_dir, args=(chunk_list[i], i))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()


if __name__ == "__main__":
    modify_fold_margin_in_multiprocessing()
