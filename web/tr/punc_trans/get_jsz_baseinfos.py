from math import log
import os
import pymongo
import logging
import json
import sys
import pandas as pd
from pymongo import MongoClient

root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.append(root_dir)
import helper as hp

hp.set_logging("deal_online_punc_txt.log", False)

# 初始化数据库连接
online_client = hp.connect_db_max("rushi-online", "mongodb-", True)
online_db = online_client["tripitaka-reader-prod"]
online_sutra_collection = online_db["sutra"]
online_sys_conf_collection = online_db["sys_conf"]

save_path = "output/jsz_baseinfos.xlsx"  # 修正文件扩展名


def get_jsz_baseinfos_toexcel():
    # 从 sys_conf 集合中获取 authors, categories, dynasties 的映射
    keys = ["authors", "categories", "dynasties"]
    mappings = {}
    for key in keys:
        doc = online_sys_conf_collection.find_one({"key": key})
        if doc and "value" in doc and "JS" in doc["value"]:
            mappings[key] = doc["value"]["JS"]

    # 从 sutra 集合中获取数据
    fields = {
        "rs_uid": 1,
        "name": 1,
        "authors": 1,
        "categories": 1,
        "dynasties": 1,
        "_id": 0,
    }
    sutra_docs = list(online_sutra_collection.find({}, fields))

    data = []
    for doc in sutra_docs:
        rs_uid = doc.get("rs_uid", "")
        name = doc.get("name", "")
        authors = [
            mappings.get("authors", {}).get(str(author), str(author))
            for author in doc.get("authors", [])
        ]
        categories = [
            mappings.get("categories", {}).get(str(category), str(category))
            for category in doc.get("categories", [])
        ]
        dynasties = [
            mappings.get("dynasties", {}).get(str(dynasty), str(dynasty))
            for dynasty in doc.get("dynasties", [])
        ]

        row = {
            "经号": rs_uid,
            "经名": name,
            "作者": "、".join(authors),
            "部类": "、".join(categories),
            "朝代": "、".join(dynasties),
        }
        data.append(row)

    # 将数据保存到 Excel 文件
    df = pd.DataFrame(data)
    df.to_excel(save_path, index=False)
    print(f"数据已保存到 {save_path}")


if __name__ == "__main__":
    get_jsz_baseinfos_toexcel()
