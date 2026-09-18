import pymongo
import pandas as pd
import os
import pymongo
from datetime import datetime
import sys
import json
import logging
import pandas as pd

"""
径山藏标点统计
"""
root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.append(root_dir)

import helper as hp

hp.set_logging("jsz_punc_stats.log", False)

# 连接
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
    results = jsz_cbeta_mapping_collection.find({}).sort(
        [("实存卷数", pymongo.ASCENDING)]
    )
    return {
        (
            result["经号1"],  # 这个字段必须存在，否则应报错
            result.get("是否有CBETA标点", "N"),  # 默认 0
            result.get("CBETA经号1", "nomatch"),  # 处理可能缺失的字段
            result.get("实存卷数", 0),  # 默认 0
            result.get("一对多", "N"),  # 默认 N
            result.get("一对多参数", "N"),  # 默认空字符串
            result.get("是否如是打标点", "Y"),  # 默认空字符串
            result.get("是否需要标点", "Y"),  # 默认空字符串
        ): result
        for result in results
    }


def get_jsz_match_rate_stats():
    # 获取映射关系数据
    mappings = get_jsz_cbeta_mappings()

    # 定义查询的字段
    projection = {
        "经号": 1,
        "卷号": 1,
        "匹配信息.match_rate": 1,
        "是否有现代标点": 1,
        "是否有大模型打标": 1,
        "是否已迁移": 1,
        "华鲤是否已迁移": 1,
        "匹配信息.misnumerator": 1,
        "匹配信息.denominator": 1,
        "序号": 1,
        "_id": 0,  # 排除 _id 字段
    }

    # 执行查询
    results = jsz_collection.find({}, projection)

    # 将查询结果转换为列表
    data = list(results)

    # 处理嵌套的新匹配信息字段
    for item in data:
        jsz_jinghao = item.get("经号")
        # 查找对应的映射记录
        mapping = next((v for k, v in mappings.items() if k[0] == jsz_jinghao), None)
        # 设置是否有CBETA标点字段，默认N
        item["是否如是打标点"] = mapping.get("是否如是打标点", "Y") if mapping else "Y"
        item["是否需要标点"] = mapping.get("是否需要标点", "Y") if mapping else "Y"

        if "匹配信息" in item:
            logging.info(f"item:{item}")
            new_match_info = item.pop("匹配信息")
            item.update(new_match_info)

        # 增加标点来源判断
        if item["是否如是打标点"] == "N":
            item["标点来源"] = "大模型"
        else:
            if item.get("是否有现代标点") == "N":
                if item.get("是否有大模型打标") == "N":
                    item["标点来源"] = "CBETA"
                else:
                    item["标点来源"] = "大模型"
            # 有现代标点的，不会再去调用大模型，除了音释
            else:
                item["标点来源"] = "CBETA"

        if item["是否需要标点"] == "N":
            item["标点来源"] = "CBETA"

    # 将数据转换为 DataFrame
    df = pd.DataFrame(data)

    # 生成时间戳（精确到秒）
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # 导出为 Excel 文件
    df.to_excel(f"output/stats/径山藏标点匹配率统计_{timestamp}.xlsx", index=False)


if __name__ == "__main__":
    logging.info("start")
    get_jsz_match_rate_stats()
    # 关闭 MongoDB 连接
    client.close()
    logging.info("end")
