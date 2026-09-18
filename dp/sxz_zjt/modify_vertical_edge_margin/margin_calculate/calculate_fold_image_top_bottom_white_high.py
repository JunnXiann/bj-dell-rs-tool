# -*- coding: utf-8 -*-
"""
@File    : calculate_fold_image_top_bottom_white_high.py
@Time    : 2025/5/27 13:53
@Author  : zhujiantao
@Version : 1.0
@Desc    : 计算得到扣图上下空白高度及上下空白高度比例，在dell服务器上运行 sx_embed_add_w_fold.json为加宽扣图 sx_embed_fold.json为非加宽扣图
输入为包含fold_id列表的json文件，输出为对应的json文件，没有直接从数据库读取和写入数据库原因是：
1.所有扣图在dell服务器上，同时dell服务器上数据库是生产环境，可以避免写入数据库脏数据。
"""

import json
import os.path

from PIL import Image
import numpy as np


def find_black_horizontal_line(image_np, start, end, step, threshold=50, black_pixel_ratio=0.1) -> int or None:
    """
    查找具有较高黑色像素比例的横线位置。
    """
    h, w = image_np.shape
    for y in range(start, end, step):
        row = image_np[y, :]
        black_pixels = np.sum(row < threshold)
        if black_pixels / w > black_pixel_ratio:
            if y < 10:
                continue
            return y
    return None


def get_fold_image_path(fold_id: str) -> str:
    """
    获取扣图路径
    :param fold_id:
    :return:
    """
    # 扣图父路径
    pre_dir = "/nas/data/T/big/SX"
    han_dir = fold_id.split("_")[0]
    volume_dir = fold_id.split("_")[1]
    fold_path = os.path.join(pre_dir, han_dir, volume_dir, f"SX_{fold_id}.jpg")
    return fold_path


def analyze_image_margins(fold_id: str) -> dict:
    """
    得到图片上下空白高度
    :param fold_id: 扣图id
    :return:
    """
    image_path = get_fold_image_path(fold_id)
    # 打开图像并转换为灰度图
    image = Image.open(image_path).convert("L")
    image_np = np.array(image)
    height, width = image_np.shape

    # 查找上、下方黑色边框线位置
    top_line_y = find_black_horizontal_line(image_np, 0, height, 1)
    bottom_line_y = find_black_horizontal_line(image_np, height - 1, -1, -1)

    if top_line_y is None or bottom_line_y is None:
        raise ValueError("未能检测到图像的上下黑色横线")

    # 计算留白高度
    top_margin = top_line_y
    bottom_margin = height - bottom_line_y

    return {
        "fold_id": fold_id,
        "top_margin": top_margin,
        "bottom_margin": bottom_margin,
        "height": height,
        "width": width
    }


def get_fold_image_margins(fold_id_list: list, list_order: int):
    """
    找到扣图上下空白并固化到json文件
    :param list_order: 序号，用户json文件后缀
    :param fold_id_list: 扣图id列表
    :return:
    """
    if not os.path.exists("no_fold_dir"):
        os.makedirs("no_fold_dir")
    if not os.path.exists("error_fold_dir"):
        os.makedirs("error_fold_dir")
    if not os.path.exists("margin_dir"):
        os.makedirs("margin_dir")

    margin_dict_list = []
    for fold_id in fold_id_list:
        print(f"fold_id=={fold_id}")
        try:
            margin_dict = analyze_image_margins(fold_id)
            margin_dict_list.append(margin_dict)
        except FileNotFoundError:
            with open(f"no_fold_dir/error_fold_id_list_{list_order}.txt", "a") as f:
                f.write(f"{fold_id}\n")
        except Exception:
            with open(f"error_fold_dir/error_fold_id_list_{list_order}.txt", "a") as f:
                f.write(f"{fold_id}\n")

    with open(f"margin_dir/margin_{list_order}.json", "w") as f:
        f.write(json.dumps(margin_dict_list))


# 示例调用
if __name__ == "__main__":

    import multiprocessing

    process_count = 12

    # with open("sx_embed_fold.json", "r") as f:
    with open("sx_embed_add_w_fold.json", "r") as f:
        fold_id_dict_list = json.loads(f.read())

    total_fold_id_list = [tmp.get("fold_id") for tmp in fold_id_dict_list]

    chunks = np.array_split(total_fold_id_list, process_count)
    chunk_list = [chunk.tolist() for chunk in chunks]

    processes = []
    for i in range(0, process_count):
        p = multiprocessing.Process(target=get_fold_image_margins, args=(chunk_list[i], i))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()
