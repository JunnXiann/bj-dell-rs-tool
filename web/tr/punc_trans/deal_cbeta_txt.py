import os
import pymongo
from datetime import datetime
import sys
import json
import logging
import pandas as pd

root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
print(f"root_dir:{root_dir}")
sys.path.append(root_dir)

from util.punc import (
    call_gj_ai_punc_v3,
    transfer_punc_v2,
    transfer_punc_for_stats,
    PUNC_STR,
)
import helper as hp

hp.set_logging("deal_cbeta_txt2", False)

# 本地环境
# client = hp.connect_db('local','mongodb-',True)
# 选择数据库
# db = client["jsz_cbeta_maps"]
# ali-dev
client = hp.connect_db("alidev", "mongodb-", True)
# 选择数据库
db = client["rushi-dev"]
# 选择集合
collection = db["cbeta_wrap_rolls"]

# 获取当前日期，格式为 YYYY-MM-DD
current_date = datetime.now().strftime("%Y-%m-%d")
current_date = "2025-03-23"

# 定义根目录
root_dir = "web/tr/punc_trans/target_txts/cbeta-text-20250323"

# 遍历根目录下的所有文件夹
for second_level_dir in os.listdir(root_dir):
    second_level_path = os.path.join(root_dir, second_level_dir)
    print(f"second_level_path:{second_level_path}")
    if os.path.isdir(second_level_path):
        # 获取经号
        jinghao = second_level_dir
        # 遍历第二层文件夹下的所有文件
        for file_name in os.listdir(second_level_path):
            file_path = os.path.join(second_level_path, file_name)
            # 排除toc序的文本
            if file_name.endswith(".txt") and "toc" not in file_name:
                # 获取卷号
                juanhao = os.path.splitext(file_name)[0]
                sort_no = juanhao.split("_")[1]
                try:
                    # 读取文件内容
                    with open(file_path, "r", encoding="utf-8") as file:
                        content = file.read()
                    # 构建文档
                    document = {
                        "日期": current_date,
                        "经号": jinghao,
                        "卷号": juanhao,
                        "内容": content,
                        "是否已迁移": "N",
                        "序号": sort_no,
                    }
                    # 插入文档到集合中
                    collection.insert_one(document)
                    print(f"成功插入 {jinghao} - {juanhao} 的内容到 MongoDB")
                except Exception as e:
                    print(f"读取 {file_path} 时出错: {e}")

# 关闭连接
client.close()
