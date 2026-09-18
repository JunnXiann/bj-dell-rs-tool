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
用迁移算法，从”华鲤打标内容“中迁移标点到”华鲤打标迁移后内容“中
"""


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
    stat_bd_details_byfile,
    big_model_punc,
)
import helper as hp

cur_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
hp.set_logging("deal_huali_punc_txts.log", False)


client = hp.connect_db_max("alidev", "mongodb-", True)
# 选择数据库
db = client["rushi-dev"]
# 选择集合
jsz_collection = db["jsz_wrap_rolls"]


def process_last_punc_text(text: str) -> str:
    """
    入库前处理下标点格式
    1. 替换引号标点
        双引号：「」→ “”
        单引号：『』→‘’
    2. 多个相邻的¶替换为一个¶
    """
    text = (
        text.replace("「", "“").replace("」", "”").replace("『", "‘").replace("』", "’")
    )
    count = 0
    while "¶¶" in text:
        count += 1
        text = text.replace("¶¶", "¶")
        if count > 10:
            break

    return text


def migrate_huali_punc():
    output_dir = "output/huali_punc_txts"
    os.makedirs(output_dir, exist_ok=True)

    # 查询条件保持不变
    query = {
        "华鲤打标内容": {"$exists": True, "$nin": [None, ""]},
        "华鲤是否已迁移": "N",
    }

    # 获取总数量
    total = jsz_collection.count_documents(query)
    logging.info(f"待迁移文档总数: {total}")

    page_size = 10  # 每批处理数量
    processed = 0  # 已处理计数器

    while processed < total:
        # 分批查询（使用skip和limit）
        cursor = (
            jsz_collection.find(
                query, projection=["经号", "卷号", "内容", "华鲤打标内容"]
            )
            .skip(0)
            .limit(page_size)
        )

        operations = []
        for doc in cursor:
            try:
                jinghao = doc["经号"]
                juanhao = doc["卷号"]
                original_content = doc["内容"].replace("EE", "").replace("KK", "")
                huali_content = doc["华鲤打标内容"].replace("\n", "¶").replace(" ", "")

                logging.info(f"处理：{jinghao}-{juanhao}")

                # 迁移标点
                migrated_content, _ = transfer_punc_for_stats(
                    original_content,
                    huali_content,
                    lambda x: x not in "\n[]JS_0123456789",
                )
                migrated_content = process_last_punc_text(migrated_content)
                # 构建更新操作
                operations.append(
                    UpdateOne(
                        {"经号": jinghao, "卷号": juanhao},
                        {
                            "$set": {
                                "华鲤打标迁移后内容": migrated_content,
                                "华鲤是否已迁移": "Y",
                                "更新时间": datetime.now(
                                    timezone(timedelta(hours=8))
                                ).strftime("%Y-%m-%d %H:%M:%S"),
                            }
                        },
                    )
                )

                # 写入文件
                jing_dir = os.path.join(output_dir, jinghao)
                os.makedirs(jing_dir, exist_ok=True)
                with open(
                    os.path.join(jing_dir, f"{juanhao}.txt"), "w", encoding="utf-8"
                ) as f:
                    f.write(migrated_content)

                logging.info(f"已处理：{jinghao}-{juanhao}")
                processed += 1
                logging.info(f"进度: {processed}/{total} ({jinghao}-{juanhao})")

            except Exception as e:
                logging.error(f"处理失败：{jinghao}-{juanhao} - {str(e)}")

        # 批量提交当前页的更新
        if operations:
            jsz_collection.bulk_write(operations)
            logging.info(f"已提交 {len(operations)} 条更新")

        # 释放内存
        del operations
        del cursor


if __name__ == "__main__":
    migrate_huali_punc()
