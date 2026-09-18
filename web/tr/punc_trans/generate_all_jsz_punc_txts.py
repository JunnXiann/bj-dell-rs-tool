from math import log
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
jsz_source_mapping_collection = db["jsz_source_mapping_excels"]


def get_jsz_source_mappings():
    """
    获取 JSZ-SOURCE 映射关系
    """
    results = jsz_source_mapping_collection.find({}).sort(
        [("实存卷数", pymongo.ASCENDING)]
    )
    return {
        (
            result["经号1"],  # 这个字段必须存在，否则应报错
            result.get("实存卷数", 0),  # 默认 0
            result.get("是否需要标点", "Y"),
            result.get("是否如是打标点", "Y"),
        ): result
        for result in results
    }


query = {
    # "$and": [
    #     # {"是否已迁移": "Y"},
    #     # {"match_rate": {"$gte": 0.99}},
    #     # {"打标是否异常": "N"}
    # ]
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

mappings = get_jsz_source_mappings()


# exit('end')
# 遍历查询结果
for doc in cursor:
    try:
        jinghao = doc["经号"]
        juanhao = doc["卷号"]

        # if juanhao != 'JS_1471_4':
        #     continue

        # 每次单独查询标点内容
        fresh_doc = jsz_collection.find_one(
            {"经号": jinghao, "卷号": juanhao},
            {
                "标点内容": 1,
                "华鲤打标迁移后内容": 1,
                "wl_punc_content": 1,
                "xz_punc_content": 1,
                "fgz_punc_content": 1,
                "cbeta_punc_content": 1,
                "_id": 0,
            },
        )

        # logging.info(f'fresh_doc {fresh_doc}')

        rushi_content = fresh_doc.get("标点内容", "") if fresh_doc else ""
        huali_content = fresh_doc.get("华鲤打标迁移后内容", "") if fresh_doc else ""
        wl_punc_content = fresh_doc.get("wl_punc_content", "") if fresh_doc else ""
        xz_punc_content = fresh_doc.get("xz_punc_content", "") if fresh_doc else ""
        fgz_punc_content = fresh_doc.get("fgz_punc_content", "") if fresh_doc else ""
        cbeta_punc_content = (
            fresh_doc.get("cbeta_punc_content", "") if fresh_doc else ""
        )

        logging.info(f"经号: {jinghao}, 卷号: {juanhao}")

        content_type = "rushi"

        content = rushi_content

        if len(xz_punc_content) > 2:
            content_type = "xz"
            content = xz_punc_content
        elif len(wl_punc_content) > 2:
            content_type = "wl"
            content = wl_punc_content
        elif len(fgz_punc_content) > 2:
            content_type = "fgz"
            content = fgz_punc_content
        elif len(cbeta_punc_content) > 2:
            content_type = "cbeta"
            content = cbeta_punc_content
        # 华鲤AI打标做最后的兜底
        elif len(huali_content) > 2:
            content_type = "huali"
            content = huali_content

        # 创建经号目录
        jinghao_dir = os.path.join(output_dir, jinghao)
        os.makedirs(jinghao_dir, exist_ok=True)

        logging.info(
            f"jinghao: {jinghao}, juanhao: {juanhao}, content_type: {content_type}"
        )

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
