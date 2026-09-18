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

query = {
    "$and": [
        {"是否已迁移": "Y"},
        # {"match_rate": {"$gte": 0.99}},
        # {"打标是否异常": "N"}
    ]
}

projection = {"_id": 0, "经号": 1, "卷号": 1}

# 获取符合条件的所有文档（使用无游标超时设置）
cursor = jsz_collection.find(query, projection)
total_count = jsz_collection.count_documents(query)
logging.info(f"从数据库筛选出 {total_count} 条数据")

# 获取当前日期
current_date = datetime.now().strftime("%Y-%m-%d")
output_base_dir = "output/punc_txts"
output_dir = os.path.join(output_base_dir, current_date)
os.makedirs(output_dir, exist_ok=True)

# 遍历查询结果
for doc in cursor:
    try:
        jinghao = doc["经号"]
        juanhao = doc["卷号"]
        # 每次单独查询标点内容
        fresh_doc = jsz_collection.find_one(
            {"经号": jinghao, "卷号": juanhao}, {"标点内容": 1}
        )
        content = fresh_doc.get("标点内容", "") if fresh_doc else ""
        # 替代引号标点
        # - 双引号：「」→ “”
        # - 单引号：『』→‘’
        content = (
            content.replace("「", "“")
            .replace("」", "”")
            .replace("『", "‘")
            .replace("』", "’")
        )

        # 创建经号目录
        jinghao_dir = os.path.join(output_dir, jinghao)
        os.makedirs(jinghao_dir, exist_ok=True)

        # 保存标点内容到文件
        file_path = os.path.join(jinghao_dir, f"{juanhao}.txt")
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(content)
        logging.info(f"已保存 {jinghao} - {juanhao} 到 {file_path}")

    except KeyError as e:
        logging.error(f"文档缺少必要字段: {e}, 文档内容: {doc}")
    except Exception as e:
        logging.error(f"处理异常: {str(e)}")

# 关闭 MongoDB 连接
client.close()
