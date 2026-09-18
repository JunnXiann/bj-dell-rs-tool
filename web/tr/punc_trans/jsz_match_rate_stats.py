import pymongo
import pandas as pd
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
sys.path.append(root_dir)

from util.punc import (
    call_gj_ai_punc_v3,
    transfer_punc_v2,
    transfer_punc_for_stats,
    PUNC_STR,
)
import helper as hp

hp.set_logging("jsz_stats", False)

# 连接
# ali-dev
client = hp.connect_db("alidev", "mongodb-", True)
# 选择数据库
db = client["rushi-dev"]
# 选择集合
jsz_collection = db["jsz_wrap_rolls"]
cbeta_collection = db["cbeta_wrap_rolls"]
jsz_source_mapping_collection = db["jsz_source_mapping_excels"]


def get_jsz_match_rate_stats():
    # 定义查询的字段
    projection = {
        "经号": 1,
        "卷号": 1,
        "序号": 1,
        "是否已迁移": 1,
        "匹配信息.match_rate": 1,
        "匹配信息.misnumerator": 1,
        "匹配信息.denominator": 1,
        "华鲤是否已迁移": 1,
        "打标是否异常": 1,
        "_id": 0,  # 排除 _id 字段
    }

    # 执行查询
    results = jsz_collection.find({}, projection)

    # 将查询结果转换为列表
    data = list(results)

    # 处理嵌套的新匹配信息字段
    for item in data:
        if "匹配信息" in item:
            logging.info(f"item:{item}")
            new_match_info = item.pop("匹配信息")
            item.update(new_match_info)

    # 将数据转换为 DataFrame
    df = pd.DataFrame(data)

    # 将数据转换为 DataFrame
    df = pd.DataFrame(data)

    # 生成时间戳（精确到秒）
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # 导出为 Excel 文件
    df.to_excel(f"output/stats/径山藏匹配率统计_{timestamp}.xlsx", index=False)


if __name__ == "__main__":
    logging.info("start")
    get_jsz_match_rate_stats()
    # 关闭 MongoDB 连接
    client.close()
    logging.info("end")
