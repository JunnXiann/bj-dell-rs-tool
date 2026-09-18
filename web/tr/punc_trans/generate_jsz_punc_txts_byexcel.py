import pymongo
import pandas as pd
import os
import pymongo
from datetime import datetime
import sys
import json
import logging
import pandas as pd
from datetime import datetime


root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.append(root_dir)

import helper as hp

hp.set_logging("generate_jsz_punc_txts", False)

# 连接
# ali-dev
client = hp.connect_db("alidev", "mongodb-", True)
# 选择数据库
db = client["rushi-dev"]
# 选择集合
jsz_collection = db["jsz_wrap_rolls"]

# 读取 Excel 文件
excel_file = "output/stats/径山藏匹配率统计_20250330-091007.xlsx"
df = pd.read_excel(excel_file)

# 筛选出是否已迁移是 Y 并且 match_rate >= 0.99 的数据
filtered_df = df[
    (df["是否已迁移"] == "Y") & (df["match_rate"] >= 0.99) & (df["打标是否异常"] == "N")
]
logging.info(f"筛选出 {len(filtered_df)} 条数据")
logging.info(f"筛选出的数据：{filtered_df}")

# 获取当前日期
current_date = datetime.now().strftime("%Y-%m-%d")
output_base_dir = "output/punc_txts/"
output_dir = os.path.join(output_base_dir, current_date)
os.makedirs(output_dir, exist_ok=True)

# 遍历筛选后的数据
for index, row in filtered_df.iterrows():
    jinghao = row["经号"]
    juanhao = row["卷号"]
    logging.info(f"index:{index}, jinghao:{jinghao}, juanhao:{juanhao}")

    # 从 MongoDB 中查找对应的文档
    result = jsz_collection.find_one(
        {"经号": jinghao, "卷号": juanhao, "是否已迁移": "Y"}
    )

    if result and "标点内容" in result:
        # 创建经号目录
        jinghao_dir = os.path.join(output_dir, jinghao)
        os.makedirs(jinghao_dir, exist_ok=True)

        # 保存标点内容到文件
        file_path = os.path.join(jinghao_dir, f"{juanhao}.txt")
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(result["标点内容"])
        print(f"已保存 {jinghao} - {juanhao} 的标点内容到 {file_path}")
    else:
        print(f"未找到 {jinghao} - {juanhao} 的标点内容")

# 关闭 MongoDB 连接
client.close()
