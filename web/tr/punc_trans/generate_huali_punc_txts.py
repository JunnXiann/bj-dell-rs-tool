import os
import pymongo
import logging
import os
from pymongo import UpdateOne
from pymongo import MongoClient
import time
import datetime
import json
import logging
import pandas as pd
import hashlib
import sys
from multiprocessing import Pool, cpu_count
import asyncio
from functools import partial
from datetime import datetime, timezone, timedelta
import json
import logging
import pandas as pd
import hashlib
import sys
from multiprocessing import Pool, cpu_count
import asyncio
from functools import partial

"""
导出 如是打标不存在的”华鲤打标迁移后内容“ 到 txt文件夹，
"""

root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
print(f"root_dir:{root_dir}")
sys.path.append(root_dir)

import helper as hp

hp.set_logging("export_huali_punc.log", False)

# 初始化数据库连接
client = hp.connect_db_max("alidev", "mongodb-", True)
db = client["rushi-dev"]
jsz_collection = db["jsz_wrap_rolls"]


def export_migrated_contents():
    output_dir = "/Users/zlj/www/rushi/rs-tool/output/diff_huali_punc_txts_0404"
    os.makedirs(output_dir, exist_ok=True)

    # 查询条件：已迁移且内容存在
    query = {
        "华鲤是否已迁移": "Y",
        "是否已迁移": "N",
        "华鲤打标迁移后内容": {"$exists": True, "$nin": [None, ""]},
    }

    # 执行查询
    docs = jsz_collection.find(query, projection=["经号", "卷号", "华鲤打标迁移后内容"])

    for doc in docs:
        try:
            jinghao = doc["经号"]
            juanhao = doc["卷号"]
            content = doc["华鲤打标迁移后内容"]
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
            jing_dir = os.path.join(output_dir, jinghao)
            os.makedirs(jing_dir, exist_ok=True)

            # 写入文件
            file_path = os.path.join(jing_dir, f"{juanhao}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            logging.info(f"成功导出：{jinghao}/{juanhao}.txt")

        except Exception as e:
            logging.error(f"导出失败：{jinghao}-{juanhao} - {str(e)}")

    client.close()


if __name__ == "__main__":
    export_migrated_contents()
