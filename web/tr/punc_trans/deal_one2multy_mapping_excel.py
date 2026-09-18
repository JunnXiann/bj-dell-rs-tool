import os
import pymongo
from datetime import datetime, timezone, timedelta
import json
import logging
import pandas as pd
import hashlib
import sys


root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
print(f"root_dir:{root_dir}")
sys.path.append(root_dir)

import helper as hp

cur_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
hp.set_logging("deal_one2multy_mapping_excel.log", False)


# ali-dev
client = hp.connect_db_max("alidev", "mongodb-", True)
# 选择数据库
db = client["rushi-dev"]
jsz_cbeta_mapping_collection = db["jsz_cbeta_mapping_excels"]

# 读取 Excel 文件
excel_file = pd.ExcelFile("web/tr/punc_trans/mapping_excels/1对多映射表41.xlsx")
df = excel_file.parse("Sheet1")

# 遍历处理每一行数据
for index, row in df.iterrows():
    jinghao = row["经号1"]
    cbeta_codes = row["CBETA辅经号"]

    # 构建更新内容
    update_data = {"$set": {"一对多": "Y", "一对多参数": f"all:{cbeta_codes}"}}

    try:
        # 执行更新操作
        result = jsz_cbeta_mapping_collection.update_many(
            {"经号1": jinghao}, update_data
        )

        logging.info(
            f"经号 {jinghao} 更新成功，匹配 {result.matched_count} 条，修改 {result.modified_count} 条"
        )

    except Exception as e:
        logging.error(f"经号 {jinghao} 更新失败: {str(e)}")

client.close()
print("处理完成")
