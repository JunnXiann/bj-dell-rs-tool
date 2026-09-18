import helper as hp
from util.punc import (
    call_gj_ai_punc_v3,
    transfer_punc_v2,
    transfer_punc_for_stats,
    PUNC_STR,
    stat_bd_details_byfile,
    big_model_punc,
)
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
从华鲤打包的txt文件夹中，更新对应卷内容到 ”华鲤打标内容“ 中
"""

root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
print(f"root_dir:{root_dir}")
sys.path.append(root_dir)


cur_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
hp.set_logging("deal_huali_punc_txts.log", False)


client = hp.connect_db_max("alidev", "mongodb-", True)
# 选择数据库
db = client["rushi-dev"]


# 选择集合
jsz_collection = db["jsz_wrap_rolls"]


def update_huali_contents():

    # 基础路径
    base_dir = "web/tr/punc_trans/huali_txts/folders_batch_2plus"

    try:
        # 遍历经号文件夹
        for jinghao in os.listdir(base_dir):
            jing_dir = os.path.join(base_dir, jinghao)
            operations = []
            logging.info(f"jinghao:{jinghao}")

            if os.path.isdir(jing_dir):
                # 遍历卷号文件
                for filename in os.listdir(jing_dir):
                    if filename.endswith(".txt"):
                        # 提取卷号（去掉.txt后缀）
                        juanhao = os.path.splitext(filename)[0]

                        # 读取文件内容
                        file_path = os.path.join(jing_dir, filename)
                        logging.info(
                            f"jinghao{jinghao},juanhao:{juanhao},file_path:{file_path}"
                        )
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                content = f.read().strip()

                                # 构建更新操作
                                operations.append(
                                    UpdateOne(
                                        {"经号": jinghao, "卷号": juanhao},
                                        {"$set": {"华鲤打标内容": content}},
                                        upsert=False,  # 仅更新，不插入新文档
                                    )
                                )
                                logging.info(f"已缓存更新操作：{jinghao}-{juanhao}")

                        except Exception as e:
                            logging.error(f"文件读取失败：{file_path} - {str(e)}")

            # 批量执行更新操作
            if operations:
                # logging.info(f"operations: {operations}")
                result = jsz_collection.bulk_write(operations)
                logging.info(
                    f"更新完成！匹配文档数：{result.matched_count}, 修改数：{result.modified_count}"
                )
            else:
                logging.warning("未找到需要更新的文件")

    except Exception as e:

        logging.error(f"处理过程中发生错误：{str(e)}")
    finally:
        client.close()


if __name__ == "__main__":
    update_huali_contents()
