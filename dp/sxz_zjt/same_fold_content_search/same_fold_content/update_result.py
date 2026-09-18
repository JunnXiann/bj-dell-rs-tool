# -*- coding: utf-8 -*-
"""
@File    : update_result.py
@Time    : 2025/5/27 15:29
@Author  : zhujiantao
@Version : 1.0
@Desc    : 更新相同扣内容json文件，添加每扣是否相同涵、相同册、扣图url、扣图所在pdf页图url,最终生成result.json
"""
import json


def update_same_fold_content_result_json():
    """
    全文匹配结果 更新结果json文件，将key改为对应扣的文本内容
    :return:
    """
    with open("result.json", "r") as f:
        data_dict = json.loads(f.read())

    with open("fold_pdf_pge_url.json", "r") as f:
        fold_pdf_pge_url_dict = json.loads(f.read())

    new_result_list = []

    for tmp_hash_value, tmp_fold_id_list in data_dict.items():

        tmp_fold_txt = f"{tmp_fold_id_list[0]}.txt"
        new_tmp_fold_id_list = []

        with open(tmp_fold_txt, "r") as f:
            tmp_fold_content = f.read()

        tmp_han_list = []
        tmp_volume_list = []

        for tmp_fold_id in tmp_fold_id_list:
            tmp_fold_id = tmp_fold_id.split("/")[2]

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
                "fold_content": tmp_fold_content,
                "same_han": "是" if same_han_flag else "否",
                "same_volume": "是" if same_volume_flag else "否",
                "fold_id_list": new_tmp_fold_id_list
            }
        )

    with open("new_result.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(new_result_list, ensure_ascii=False))


# update_same_fold_content_result_json()


def update_top_n_row_same_result_json(row_count: int):
    """
    前row_count行匹配结果 更新结果json文件，将key改为对应扣的文本内容
    :return:
    """
    with open("result.json", "r") as f:
        data_dict = json.loads(f.read())

    with open("fold_pdf_pge_url.json", "r") as f:
        fold_pdf_pge_url_dict = json.loads(f.read())

    new_result_list = []

    for tmp_top_3_row_content, tmp_fold_id_list in data_dict.items():

        new_tmp_fold_id_list = []

        tmp_han_list = []
        tmp_volume_list = []

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
                "fold_content": tmp_top_3_row_content,
                "same_han": "是" if same_han_flag else "否",
                "same_volume": "是" if same_volume_flag else "否",
                "fold_id_list": new_tmp_fold_id_list
            }
        )

    with open(f"result.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(new_result_list, ensure_ascii=False))


update_top_n_row_same_result_json(6)
