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

hp.set_logging("test", False)

# ali-dev
client = hp.connect_db("alidev", "mongodb-", True)
# 选择数据库
db = client["rushi-dev"]
# 选择集合
jsz_collection = db["jsz_wrap_rolls"]
cbeta_collection = db["cbeta_wrap_rolls"]
jsz_cbeta_mapping_collection = db["jsz_cbeta_mapping_excels"]


def get_jsz_cbeta_mappings():
    """
    获取 JSZ-CBETA 映射关系
    """
    results = jsz_cbeta_mapping_collection.find(
        {
            "是否有CBETA标点": {"$in": ["Y", "Y1"]},
            # "是否已迁移": "N"
        }
    ).sort([("实存卷数", pymongo.ASCENDING)])
    return {
        (result["经号1"], result["CBETA经号1"], result["实存卷数"]): result
        for result in results
    }


if __name__ == "__main__":
    datas = get_jsz_cbeta_mappings()
    # 将字典的值转换为列表
    data_list = list(datas.values())
    # 将数据转换为 DataFrame
    df = pd.DataFrame(data_list)
    # 保存为 Excel 文件
    base_path = f"output/test"
    df.to_excel(f"{base_path}/jsz_cbeta_task_sort_mappings.xlsx", index=True)

    # 关闭连接
    client.close()
    logging.info("end")
