# -*- coding: utf-8 -*-
"""
@File    : compare_clarity.py
@Time    : 2025/5/22 16:15
@Author  : zhujiantao
@Version : 1.0
@Desc    : 对比图片清晰度
"""

import cv2
import os


def calculate_sharpness(image_path):
    """计算图像的清晰度，拉普拉斯方差法"""
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    laplacian_var = cv2.Laplacian(img, cv2.CV_64F).var()
    return laplacian_var


def compare_images_sharpness(image_paths):
    """对比多张图片清晰度"""
    results = []
    for path in image_paths:
        sharpness = calculate_sharpness(path)
        if sharpness is not None:
            results.append((path, sharpness))
        else:
            print(f"无法读取图像: {path}")

    # 按清晰度从高到低排序
    results.sort(key=lambda x: x[1], reverse=True)

    print("\n=== 图像清晰度对比（越高越清晰） ===")
    for path, sharpness in results:
        print(f"{path} -> 清晰度: {sharpness:.2f}")


# # 示例：对比文件夹中的所有 .jpg 文件
# if __name__ == "__main__":
#     image_dir = "your/image/directory"  # 修改为你的目录路径
#     image_files = [os.path.join(image_dir, f) for f in os.listdir(image_dir) if f.endswith(".jpg")]
#     compare_images_sharpness(image_files)


