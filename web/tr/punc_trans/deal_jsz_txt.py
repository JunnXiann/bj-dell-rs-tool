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


import helper as hp

# 连接到本地 MongoDB 服务器
client = hp.connect_db("alidev", "mongodb-", True)
# 选择数据库
db = client["rushi-dev"]
# 选择集合
collection = db["jsz_wrap_rolls"]

# 获取当前日期，格式为 YYYY-MM-DD
current_date = datetime.now().strftime("%Y-%m-%d")

# 定义根目录
root_dir = "origin_txts/reel-txt-20250320"

# 遍历根目录下的所有文件夹
for dir_name in os.listdir(root_dir):
    dir_path = os.path.join(root_dir, dir_name)
    print(f"dir_name:{dir_name},dir_path:{dir_path}")
    if os.path.isdir(dir_path):
        # 获取经号
        jinghao = dir_name
        # 遍历文件夹下的所有文件
        for file_name in os.listdir(dir_path):
            file_path = os.path.join(dir_path, file_name)
            if file_name.endswith(".txt"):
                # 获取卷号
                juanhao = os.path.splitext(file_name)[0]
                try:
                    # 读取文件内容
                    with open(file_path, "r", encoding="utf-8") as file:
                        content = file.read()

                    # 构建查询条件
                    filter_query = {"经号": jinghao, "卷号": juanhao}

                    # 构建更新内容
                    update_data = {"$set": {"是否已迁移": "N", "内容": content}}

                    # 更新或插入文档
                    result = collection.update_one(
                        filter_query, update_data, upsert=True
                    )

                    if result.upserted_id:
                        print(f"成功插入 {jinghao} - {juanhao} 的内容到 MongoDB")
                    else:
                        print(f"成功更新 {jinghao} - {juanhao} 的内容到 MongoDB")

                except Exception as e:
                    print(f"读取 {file_path} 时出错: {e}")

# 关闭连接
client.close()
