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

from util.punc import transfer_punc_v2, transfer_punc_for_stats
import helper as hp


# 测试环境
test_client = hp.connect_db("test", "mongodb-", True)
test_db = test_client["tripitaka-reader-test"]
test_pubnote_collection = test_db["pubnote"]


def format_juanhao_string(input_str):
    """
    格式化经号字符串
    :param input_str: 输入的经号字符串
    :return: 格式化后的经号字符串
    """
    parts = input_str.split("_")
    if len(parts) == 3 and parts[0] == "JS":
        second_part = parts[1].zfill(4)
        third_part = parts[2].zfill(3)
        return f"JS{second_part}_{third_part}"
    return input_str


def get_roll_pubnote(jsz_juanhao):
    """
    添加牌记信息
    :param juanhao: 卷号
    :param punctuated_content: 处理后的内容
    """
    format_jsz_juanhao = format_juanhao_string(jsz_juanhao)
    result = test_pubnote_collection.find_one(
        {"reel_uid": format_jsz_juanhao}, projection={"pub_note": 1, "_id": 0}
    )
    print(
        f"jsz_juanhao:{jsz_juanhao},format_jsz_juanhao:{format_jsz_juanhao},result:{result}"
    )
    if result:
        pubnote = result.get("pub_note", "")
        if pubnote:
            return pubnote
    return ""


if __name__ == "__main__":
    # 替换为实际的 JSZ 经号和 CBETA 经号
    # jsz_jinghao = "JS_1437"
    # cbeta_jinghao = "T0213"
    jsz_juanhao = (
        "JS_4"  #  注释掉的代码，原本定义了一个变量cbeta_jinghao并赋值为字符串"T0213"
    )
    get_roll_pubnote(jsz_juanhao)

    # 关闭连接
    client.close()
    test_client.close()
    logging.info("end")
