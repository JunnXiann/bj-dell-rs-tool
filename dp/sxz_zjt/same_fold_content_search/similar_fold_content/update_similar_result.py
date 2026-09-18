# -*- coding: utf-8 -*-
"""
@File    : update_similar_result.py
@Time    : 2025/5/27 15:29
@Author  : zhujiantao
@Version : 1.0
@Desc    : 更新内容相似扣结果json文件，添加对应扣图、pdf页图url，去重，添加扣图路径，最终结果写入到updated_similar_results.json
"""
import json
import os.path


def update_similar_result_json():
    """
    添加扣图url,pdf页图url
    :return:
    """
    with open("similar_results.json", "r") as f:
        data_dict_list = json.loads(f.read())

    with open("fold_pdf_pge_url.json", "r") as f:
        fold_pdf_pge_url_dict = json.loads(f.read())

    new_result_list = []

    for tmp_dict in data_dict_list:

        new_tmp_fold_id_list = []
        tmp_han_list = []
        tmp_volume_list = []

        tmp_fold_id_list = tmp_dict.get("文本路径")
        fold_content = tmp_dict.get("最长相同文本")
        similar_percentage = tmp_dict.get("相似度百分比")

        for tmp_fold_id in tmp_fold_id_list:
            tmp_fold_id = tmp_fold_id.split("/")[2]
            # 去掉文件名后缀.txt
            tmp_fold_id = tmp_fold_id.split(".")[0]

            url_part = "https://work.tripitakas.net/page/"
            tmp_fold_url = url_part + tmp_fold_id

            tmp_han_id = tmp_fold_id.split("_")[1]
            tmp_han_list.append(tmp_han_id)
            tmp_volume_id = tmp_fold_id.split("_")[2]
            tmp_volume_list.append(tmp_volume_id)

            pdf_page_url = fold_pdf_pge_url_dict.get(tmp_fold_id).get("pdf_page_url")

            new_tmp_fold_id_list.append(
                {
                    "fold_url": tmp_fold_url,
                    "pdf_page_url": pdf_page_url
                 }
            )

        same_han_flag = len(set(tmp_han_list)) == 1
        if same_han_flag:
            same_volume_flag = len(set(tmp_volume_list)) == 1
        else:
            same_volume_flag = False


        new_result_list.append(
            {
                "fold_content": fold_content,
                "same_han": "是" if same_han_flag else "否",
                "same_volume": "是" if same_volume_flag else "否",
                "fold_id_list": new_tmp_fold_id_list,
                "similar_percentage": similar_percentage
            }
        )

    with open(f"updated_similar_results.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(new_result_list, ensure_ascii=False))


# update_similar_result_json()


def delete_same_fold_compare_result():
    """
    删除扣内容相同对比结果
    :return:
    """
    with open("updated_similar_results.json", "r") as f:
        data_dict_list = json.loads(f.read())

    new_result_list = []

    for tmp_dict in data_dict_list:
        if 100.0 != tmp_dict.get("similar_percentage"):
            new_result_list.append(tmp_dict)

    with open(f"updated_similar_results.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(new_result_list, ensure_ascii=False))


# delete_same_fold_compare_result()


def add_page_flag():
    """
    给信息添加是否相同页，是否上下页标志
    :return:
    """
    with open("updated_similar_results.json", "r") as f:
        data_dict_list = json.loads(f.read())

    for tmp_dict in data_dict_list:
        if "是" == tmp_dict.get("same_han") and "是" == tmp_dict.get("same_volume"):
            tmp_fold_id_list = tmp_dict.get("fold_id_list")
            pdf_page_num_list = [
                int(tmp.get("pdf_page_url").split("/")[-1].split(".")[0].split("_")[-1])
                for tmp in tmp_fold_id_list
            ]
            if 0 == abs(pdf_page_num_list[0] - pdf_page_num_list[1]):
                tmp_dict.update({"same_pdf_page": "是", "adjacent": "否"})
            elif 1 == abs(pdf_page_num_list[0] - pdf_page_num_list[1]):
                tmp_dict.update({"same_pdf_page": "否", "adjacent": "是"})
            else:
                tmp_dict.update({"same_pdf_page": "否", "adjacent": "否"})
        else:
            tmp_dict.update({"same_pdf_page": "否", "adjacent": "否"})

    with open(f"updated_similar_results.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(data_dict_list, ensure_ascii=False))


# add_page_flag()


def add_fold_image_path():
    """
    给信息添加是否相同页，是否上下页标志
    :return:
    """
    with open("updated_similar_results.json", "r") as f:
        data_dict_list = json.loads(f.read())

    for tmp_dict in data_dict_list:
        fold_id_list = tmp_dict.get("fold_id_list")
        for tmp in fold_id_list:
            fold_url = tmp.get("fold_url")
            fold_image_name = fold_url.split("/")[-1]
            fold_image_path = os.path.join("similar_fold", f"{fold_image_name}.jpg")
            tmp.update({"fold_image_path": fold_image_path})

    with open(f"updated_similar_results.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(data_dict_list, ensure_ascii=False))


# add_fold_image_path()


def print_same_han_volume_count():
    """
    得到同含同册数量
    :return:
    """
    with open("updated_similar_results.json", "r") as f:
        data_dict_list = json.loads(f.read())

    same_han_volume_count = 0

    for tmp_dict in data_dict_list:
        if "是" == tmp_dict.get("same_han") and "是" == tmp_dict.get("same_volume"):
            same_han_volume_count += 1

    print(same_han_volume_count)
