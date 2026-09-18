# coding: utf-8
import os

import cv2
import pymupdf as pdf
import numpy as np
import pymongo


"""
错误扣图重新切割
"""


def extract_pdf_page(pdf_path: str, page_index: int, pid: str):
    """
    抽取pdf对应的页到本地
    :param pid: pdf页编号
    :param pdf_path: pdf路径
    :param page_index: pdf页对应的序号
    :return:
    """
    if not os.path.exists("tmp"):
        os.makedirs("tmp")

    pdf_page_path = os.path.join("tmp", f"{pid}.jpg")
    with pdf.open(pdf_path) as doc:
        for pi in range(doc.page_count):
            if pi == page_index:
                page = doc[pi]
                pix = page.get_pixmap(dpi=120)  # 创建页面内容的光栅图像
                pix.save(pdf_page_path, jpg_quality=100)
    return pdf_page_path


def group_and_average(xs, threshold=256, target_count=6):
    """
    将相邻分割线横坐标拟合
    :param xs:
    :param threshold: 最大相邻差距
    :param target_count: 最终拟合出的横坐标数量
    :return:
    """
    if not xs:
        raise ValueError("输入列表为空")

    xs = sorted(xs)
    groups = []
    current_group = [xs[0]]

    for x in xs[1:]:
        if abs(x - current_group[-1]) < threshold:
            current_group.append(x)
        else:
            groups.append(current_group)
            current_group = [x]
    groups.append(current_group)

    if len(groups) != target_count:
        # raise ValueError(f"分组数量为 {len(groups)}，不等于目标 {target_count}，分组结果: {groups}")
        print(f"分组数量为 {len(groups)}，不等于目标 {target_count}，分组结果: {groups}")
        # return [0, 0, 0, 0, 0, 0]

    averages = [round(sum(group) / len(group)) for group in groups]
    return averages


def find_vertical_lines(image_path, middle_line_y, pixel_range=(0, 248), vertical_threshold=25, page_direction=None):
    """
    找到竖向分割线横坐标列表
    :param page_direction: up表示查找页面上半部分分割线，down表示查找页面下半部分分割线 none表示不区分上下页面
    :param image_path: pdf页图
    :param middle_line_y: 中间分割线纵坐标
    :param pixel_range: 分割线灰度范围
    :param vertical_threshold: 竖线分割线长度阈值
    :return:
    """
    # 读取图像
    image = cv2.imread(image_path)
    if image is None:
        print("无法读取图像，请检查图像路径。")
        return

    # 转换为灰度图像
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    height, width = gray.shape

    # 检查中间分割线像素是否在特定范围
    # print(middle_line_y)
    middle_line_pixels = gray[middle_line_y, :]
    valid_middle_pixels = np.where((middle_line_pixels >= pixel_range[0]) & (middle_line_pixels <= pixel_range[1]))[0]

    vertical_lines = []
    for col in valid_middle_pixels:
        # 从中间分割线向上检查竖向分割线连续长度
        up_length = 0
        for y in range(middle_line_y, 0, -1):
            if gray[y, col] >= pixel_range[0] and gray[y, col] <= pixel_range[1]:
                up_length += 1
            else:
                break

        # 从中间分割线向下检查竖向分割线连续长度
        down_length = 0
        for y in range(middle_line_y, height):
            if gray[y, col] >= pixel_range[0] and gray[y, col] <= pixel_range[1]:
                down_length += 1
            else:
                break
        if "up" == page_direction:
            total_length = up_length - 1
        elif "down" == page_direction:
            total_length = down_length - 1
        else:
            total_length = up_length + down_length - 1  # 中间分割线那一行重复计算了一次，需要减去 1

        if total_length >= vertical_threshold:
            vertical_lines.append(col)

    # if not vertical_lines:
    #     print(f"image_path={image_path}获取切割线横向坐标错误...")
    #     raise

    # 合并相近纵向分割线横坐标
    if not vertical_lines:
        return []
    vertical_lines = group_and_average(vertical_lines)

    # 在图像上绘制纵向分割线
    # for col in vertical_lines:
    #     cv2.line(image, (col, 0), (col, height), (0, 0, 255), 2)

    # # 显示结果图像
    # cv2.imshow('Image with Vertical Lines', image)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
    # basename = os.path.basename(image_path)
    # cv2.imwrite(f"pdf_page_with_divider_line/{basename}", image, [cv2.IMWRITE_JPEG_QUALITY, 100])

    return vertical_lines


def get_client():
    return pymongo.MongoClient(host='localhost', timeoutMS=5000, socketTimeoutMS=8000)


def gen_img(gray, xs: list, tp: int, bt: int, yc: int, hc: int, sc=1, idx=0):
    # todo 默认左序排列(非001含)
    _idx = -1
    # 上方扣纵坐标开始位置tp, 纵坐标结束位置yc-hc; 下方扣纵坐标开始位置yc+hc, 纵坐标结束位置bt
    for y1, y2 in [(tp, yc - hc), (yc + hc, bt)]:
        # 遍历第一个到倒数第二个扣中间分割线
        for i, x1 in enumerate(xs[:-1]):
            # 横坐标结束位置x2位后面横坐标
            x2, _idx, up = xs[i + 1], _idx + 1, y2 < yc
            x1_, y1_, x2_, y2_ = map(int, [x1 * sc, y1 * sc, x2 * sc, y2 * sc])
            im = gray[y1_: y2_, x1_: x2_]
            # 下面的扣图进行翻转
            im = im if up else cv2.flip(im, -1)
            if _idx == idx:
                return im


def generate_crop_image(pdf_page_path: str, fold_id: str, idx: int, xs: list, tp: int, bt: int, yc: int, hc: int, sc=1):
    """

    :param pdf_page_path: pdf页图
    :param idx: 扣在页内的序号
    :param fold_id: 扣id
    :param xs: 竖向分割线横坐标列表
    :param tp: 上方分割线纵坐标
    :param bt: 下方分割线纵坐标
    :param yc: 中间线纵坐标
    :param hc: 中间间隔半高
    :param sc:
    :return:
    """
    img = cv2.imread(pdf_page_path, cv2.IMREAD_COLOR)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = gen_img(img, xs, tp, bt, yc, hc, sc=1, idx=idx)

    if not os.path.exists("crop_new_fold"):
        os.makedirs("crop_new_fold")

    new_fold_path = os.path.join("crop_new_fold", f"{fold_id}.jpg")
    cv2.imwrite(new_fold_path, gray, [cv2.IMWRITE_JPEG_QUALITY, 100])


def crop_fold(fold_id_list: list):
    """
    根据扣id从pdf切割对应扣图
    :param fold_id_list: ['1_2_3', '2_3_4', ...]
    :return:
    """

    db_client = get_client()

    fold_list = []
    for fold_id in fold_id_list:
        fold_dict = db_client.sx_pdf.sx_fold.find_one({"fold_id": fold_id})
        fold_list.append(fold_dict)

    # 获取数据库客户端
    for fold_dict in fold_list:
        # 扣号
        fold_id = fold_dict.get("fold_id")
        print(f"开始切割扣图{fold_id}")
        # 页pid
        pid = fold_dict.get("pid")
        # 扣在pdf页中的序号
        idx = fold_dict.get("idx")

        pdf_page_dict = list(db_client.sx_pdf.sx_pdf_page.find({"pid": pid}))[0]
        # 含号
        han = pdf_page_dict.get("han")
        han_full_name = (3 - len(str(han))) * "0" + str(han)
        # pdf名称
        pdf_name = pdf_page_dict.get("pdf_name")
        pdf_name_with_suffix = f"{pdf_name}.pdf"
        # 页号
        pi = pdf_page_dict.get("pi")
        # 中间分割线纵坐标
        yc = pdf_page_dict.get("dim").get("yc")
        # 上面分割线纵坐标
        tp = pdf_page_dict.get("dim").get("tp")
        # 下面分割线纵坐标
        bt = pdf_page_dict.get("dim").get("bt")
        # 中间间隔半高
        hc = pdf_page_dict.get("dim").get("hc")


        pdf_file_path = os.path.join("/Users/zhujiantao/Downloads/思溪藏_扬州古籍_PDF(最终)", han_full_name, pdf_name_with_suffix)
        pdf_page_path = extract_pdf_page(pdf_file_path, pi, pid)

        pixel_range = (0, 248)  # 中间分割线和竖向分割线像素值范围
        vertical_threshold = 25  # 半个竖向分割线连续长度阈值

        new_xs = find_vertical_lines(pdf_page_path, yc, pixel_range, vertical_threshold)
        if not new_xs:
            raise ValueError(f"{pdf_page_path}没有找到对应分割线")

        generate_crop_image(pdf_page_path, fold_id, idx, new_xs, tp, bt, yc, hc, sc = 1)
