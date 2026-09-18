# -*- coding: utf-8 -*-
"""
@File    : fold_joint.py
@Time    : 2025/6/5 11:01
@Author  : zhujiantao
@Version : 1.0
@Desc    : 拼接被切破的扣图，例如版心列，正文
"""
import json
import os.path

import cv2
from PIL import Image

from dp.sxz_improve.fold_image_download import download_fold_image

# 残留版心列图片宽度
MAX_CROP_WIDTH = 50


def merge_images(background_path: str, foreground_path: str, output_path: str, direction="left", delta_height=0, left_delta_width=0, right_delta_width=0):
    """
    拼接两张图片
    :param right_delta_width: 右边需要强制去掉的宽度 如果direction等于right，则剪除被拼接图片的右边，如果direction等于left，则剪除残留版心列图片的右边
    :param left_delta_width: 左边需要强制去掉的宽度 如果direction等于right，则剪除残留版心列图片的左边，如果direction等于left，则剪除被拼接图片的左边
    :param delta_height: 残留版心列图片调整的上下空白高度，大于0表示上面空白减少 小于0表示上面空白增加
    :param background_path: 被拼接的图片
    :param foreground_path: 残留版心列图片
    :param output_path: 拼接后的扣图路径
    :param direction: 被拼接扣图的方向,left拼接左边 right拼接右边
    :return:
    """
    import cv2
    import numpy as np

    # 读取两张图片
    background = cv2.imread(background_path)
    foreground = cv2.imread(foreground_path)

    # 确保两张图片高度一致，如果不一致可以进行调整
    if background.shape[0] != foreground.shape[0]:
        height = min(background.shape[0], foreground.shape[0])
        background = cv2.resize(background, (background.shape[1], height))
        foreground = cv2.resize(foreground, (foreground.shape[1], height))

    foreground_h, foreground_w, _ = foreground.shape
    background_h, background_w, _ = background.shape


    # 残留版心列图片上下空白调整
    if delta_height > 0:
        # 上方空白剪切
        top_crop = foreground[0: delta_height, :]
        remained_crop = foreground[delta_height: foreground_h, :]
        # 拼接到底部
        foreground = np.vstack((remained_crop, top_crop))
    else:
        # 下方空白剪切
        bottom_crop = foreground[foreground_h + delta_height: foreground_h, :]
        remained_crop = foreground[0: foreground_h + delta_height, :]
        # 拼接到顶部
        foreground = np.vstack((bottom_crop, remained_crop))

    if "right" == direction:
        if right_delta_width > 0:
            # 被拼接图右边裁剪
            background = background[:, 0:(background_w - right_delta_width)]
        if left_delta_width > 0:
            # 残留版心列图片左边裁剪
            foreground = foreground[:, left_delta_width:]
        merged_image = cv2.hconcat([background, foreground])
    elif "left" == direction:
        if right_delta_width > 0:
            # 被拼接图右边裁剪
            foreground = foreground[:, 0:(background_w - right_delta_width)]
        if left_delta_width > 0:
            # 残留版心列图片左边裁剪
            background = background[:, left_delta_width:]
        # 将 foreground 拼接到 background 的右边
        merged_image = cv2.hconcat([foreground, background])
    else:
        raise ValueError("需要指定拼接的方向")

    # 保存拼接后的图片
    cv2.imwrite(output_path, merged_image, [cv2.IMWRITE_JPEG_QUALITY, 100])


def merge_images_v1(background_path: str, foreground_path: str, output_path: str, direction="left"):
    """
    升级版，去除相同部分后再进行拼接，可以解决版心列重影问题
    :param background_path: 被拼接的图片
    :param foreground_path: 残留版心列图片
    :param output_path: 拼接后的扣图路径
    :param direction:  被拼接扣图的方向,left拼接左边 right拼接右边
    :return:
    """
    import cv2
    import numpy as np

    # 读取图片
    left_img = cv2.imread(background_path)
    right_img = cv2.imread(foreground_path)

    # 确保两张图片高度一致，如果不一致可以进行调整
    if left_img.shape[0] != right_img.shape[0]:
        height = min(left_img.shape[0], right_img.shape[0])
        left_img = cv2.resize(left_img, (left_img.shape[1], height))
        right_img = cv2.resize(right_img, (right_img.shape[1], height))

    # 将图像转换为灰度图
    left_gray = cv2.cvtColor(left_img, cv2.COLOR_BGR2GRAY)
    right_gray = cv2.cvtColor(right_img, cv2.COLOR_BGR2GRAY)

    # 设定搜索窗口的宽度（可调节）
    max_overlap_width = MAX_CROP_WIDTH

    # 计算重叠区域的最佳匹配偏移
    best_offset = 0
    min_diff = float('inf')

    for offset in range(10, max_overlap_width):
        # 200: 1200 仅检测上下黑色横线中间部分
        left_crop = left_gray[200: 1200, -offset:]
        right_crop = right_gray[200: 1200, :offset]

        # 计算差异（均方误差）
        diff = np.mean((left_crop.astype("float") - right_crop.astype("float")) ** 2)

        if diff < min_diff:
            min_diff = diff
            best_offset = offset

    # 拼接图像：保留左图全部 + 右图去除重叠区域
    right_non_overlap = right_img[:, best_offset:]
    stitched_img = np.hstack((left_img, right_non_overlap))

    # 保存或显示
    cv2.imwrite(output_path, stitched_img, [cv2.IMWRITE_JPEG_QUALITY, 100])
    # # 或使用以下命令显示：
    # cv2.imshow("Stitched", stitched_img)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()


def is_column_blank(image, col, threshold=240):
    """判断图像的某一列是否为空白（亮度高于 threshold 认为是白）"""
    for y in range(image.height):
        r, g, b = image.getpixel((col, y))
        if min(r, g, b) < threshold:
            return False
    return True


def crop_image_whitespace(image_path, save_path=None, threshold=64, direction="left"):
    """
    裁剪图片空白边缘
    参数：
        - image_path: 输入图像路径
        - save_path: 保存路径（可选）
        - threshold: 空白判定阈值（0-255）
        - direction: 裁剪方向 "left" 或 "right"
    """
    image = Image.open(image_path).convert("RGB")

    if direction == "left":
        crop_pos = 0
        for col in range(image.width):
            if not is_column_blank(image, col, threshold):
                crop_pos = col
                break
        box = (crop_pos, 0, image.width, image.height)

    elif direction == "right":
        crop_pos = image.width
        for col in reversed(range(image.width)):
            if not is_column_blank(image, col, threshold):
                crop_pos = col + 1
                break
        box = (0, 0, crop_pos, image.height)

    else:
        raise ValueError("方向参数应为 'left' 或 'right'")

    cropped = image.crop(box)

    if save_path:
        cropped.save(save_path)
        print(f"裁剪完成，保存到：{save_path}")
    else:
        cropped.show()

    return cropped


def crop_middle_text_img(image_path: str, max_with=10, direction="left"):
    """
    得到扣图残损版心列或者正文
    :param max_with: 需要裁切的宽度
    :param image_path: 扣图路径
    :param direction: 扣图方向
    :return:
    """
    # 读取图像
    img = cv2.imread(image_path)
    height, width, _ = img.shape
    if "left" == direction:
        # 裁剪图像
        cropped_img = img[:, :max_with]
    elif "right" == direction:
        cropped_img = img[:, width-max_with:]
    else:
        raise Exception("裁剪方向错误")
    cv2.imwrite("error_column.jpg", cropped_img, [cv2.IMWRITE_JPEG_QUALITY, 100])


def joint_image(joint_image: str, crop_image: str, direction="left"):
    """
    拼接扣图版心列
    :param joint_image: 需要拼接的扣图
    :param crop_image: 被裁剪的扣图
    :param direction: 需要拼接的扣图拼接方向
    :return:
    """
    if "left" == direction:
        # 扣图左边需要拼接
        # 左侧裁剪空白
        crop_image_whitespace(joint_image, f"tmp/no_white_edge_{joint_image}", direction="left")
        # 右侧裁剪空白
        crop_image_whitespace(crop_image, f"tmp/no_white_edge_{crop_image}", direction="right")
        # 裁剪右侧残损版心
        crop_middle_text_img(f"tmp/no_white_edge_{crop_image}", max_with=MAX_CROP_WIDTH, direction="right")
        # 拼接
        merge_images(
            f"tmp/no_white_edge_{joint_image}",
            "error_column.jpg",
            f"fold_image/{os.path.basename(joint_image)}",
            "left",
            delta_height=0,
            left_delta_width=0,
            right_delta_width=0
        )
    else:
        # 扣图右侧需要拼接
        # 右侧裁剪空白
        crop_image_whitespace(joint_image, f"tmp/no_white_edge_{joint_image}", direction="right")
        # 左侧裁剪空白
        crop_image_whitespace(crop_image, f"tmp/no_white_edge_{crop_image}", direction="left")
        # 裁剪左侧残损版心
        crop_middle_text_img(f"tmp/no_white_edge_{crop_image}", max_with=MAX_CROP_WIDTH, direction="left")
        # 拼接扣图，如果版心重影，则下面函数替换为merge_images_v1
        merge_images(f"tmp/no_white_edge_{joint_image}",
                     "error_column.jpg",
                     f"fold_image/{os.path.basename(joint_image)}",
                     "right",
                     delta_height=0,
                     left_delta_width=0,
                     right_delta_width=0
                    )


def sort_key(s):
    return int(''.join(s.replace('SX_', '').split('_')))


def fill_fold_id_direction_list():
    """
    fold_id_direction_list填充为元素为{"fold_id": "1_1_1", "direction": ""}
    :return:
    """
    with open("fold_id_direction_list.json", "r") as f1:
        fold_id_list = json.loads(f1.read())

    _fold_id_direction_list = [{"fold_id": tmp[3:], "direction": ""} for tmp in sorted(fold_id_list, key=sort_key)]

    with open("fold_id_direction_list.json", "w") as f2:
        f2.write(json.dumps(_fold_id_direction_list))


if __name__ == "__main__":

    # 第一步 填充fold_id_direction_list.json
    # fill_fold_id_direction_list()

    # #获取扣图列表
    with open("fold_id_direction_list.json", "r") as f:
        fold_id_direction_list = json.loads(f.read())

    # 第二步 从pdf生成的扣图中得到需要拼接的扣图

    # # 第三步填充相邻的扣图id到fold_id_direction_list.json，下载需要的相邻扣图(也可以从pdf生成的扣图中得到)
    # for tmp in fold_id_direction_list:
    #     fold_id = tmp.get("fold_id")
    #     direction = tmp.get("direction")
    #
    #     han = fold_id.split("_")[0]
    #     volume = fold_id.split("_")[1]
    #
    #     if "right" == direction:
    #         # 右边的扣id为fold_id - 1
    #         seq = int(fold_id.split("_")[2]) - 1
    #         fold_id = f"{han}_{volume}_{seq}"
    #         tmp.update({"crop_fold_id": fold_id})
    #     else:
    #         seq = int(fold_id.split("_")[2]) + 1
    #         fold_id = f"{han}_{volume}_{seq}"
    #         tmp.update({"crop_fold_id": fold_id})
    # with open("fold_id_direction_list.json", "w") as f:
    #     f.write(json.dumps(fold_id_direction_list))
    # download_fold_image.download_fold_image_multiprocessing([tmp.get("crop_fold_id") for tmp in fold_id_direction_list])

    # 第四步 拼接扣图
    for tmp in fold_id_direction_list:
        fold_id = tmp.get("fold_id")
        crop_fold_id = tmp.get("crop_fold_id")
        direction = tmp.get("direction")

        joint_image(
            f"download_fold_image/SX_{fold_id}.jpg",
            f"download_fold_image/SX_{crop_fold_id}.jpg",
            direction
        )
