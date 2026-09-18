from math import log
import os
import pymongo
import logging
import json
import sys
from pymongo import MongoClient

root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.append(root_dir)
import helper as hp

hp.set_logging("deal_online_punc_txt.log", False)

# 初始化数据库连接
online_client = hp.connect_db_max("rushi-online", "mongodb-", True)
online_db = online_client["tripitaka-reader-prod"]
online_reel_collection = online_db["reel"]

# ali-dev
dev_client = hp.connect_db_max("alidev", "mongodb-", True)
# 选择数据库
dev_db = dev_client["rushi-dev"]
# 选择集合
jsz_collection = dev_db["jsz_wrap_rolls"]


save_path = "output/rushi_to_huali_txts"


def get_reel_ouid(uid):
    # 分割字符串为前缀和数字部分
    prefix = uid[:2]  # 提取 "JS"
    number_part = uid[2:]  # 提取 "0099_001"

    # 去掉 "0099" 中的前导零
    main_number = number_part.split("_")[0]  # 提取 "0099"
    main_number = str(int(main_number))  # 去掉前导零，变成 "99"

    # 去掉 "_001" 中的前导零
    sub_number = number_part.split("_")[1]  # 提取 "001"
    sub_number = str(int(sub_number))  # 去掉前导零，变成 "1"

    # 拼接最终结果
    transformed = f"{prefix}_{main_number}_{sub_number}"

    return transformed


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


def generate_one_roll_txt(juanhao):
    """
    生成一个卷的标点文本
    规则：按照¶标点来展示换行
    :param juanhao: 卷号
    :return: None
    """
    uid = format_juanhao_string(juanhao)
    logging.info(f"juanhao:{juanhao}, uid:{uid}")
    reel = online_reel_collection.find_one({"uid": uid}, {"pages": 1, "format": 1})
    logging.info("reel: %s", uid)
    pages = reel.get("pages", [])
    # logging.info(f'pages:{pages}')
    origin_txt_path, transformed_txt_path = "", ""

    for page in pages:
        ouid = get_reel_ouid(uid)
        parts = ouid.split("_")
        sutra_ouid = "_".join(parts[:2])
        std_txts = page.get("std_txt", [])

        origin_txts_path = os.path.join(save_path + "/origin_txts", sutra_ouid)
        not os.path.exists(origin_txts_path) and os.makedirs(origin_txts_path)
        origin_txt_path = os.path.join(origin_txts_path, "%s.txt" % ouid)

        # logging.info(f'sutra_ouid:{sutra_ouid},ouid:{ouid},page_ouid:{page['ouid']}')

        with open(origin_txt_path, "a", encoding="utf-8") as f:
            f.write("[%s]\n" % page["ouid"])
        for std_txt in std_txts:
            for txt in std_txt[1]:
                res_txt = txt[1]
                with open(origin_txt_path, "a", encoding="utf-8") as f:
                    f.write("%s\n" % res_txt)

        transformed_txts_path = os.path.join(
            save_path + "/transformed_txts", sutra_ouid
        )
        not os.path.exists(transformed_txts_path) and os.makedirs(transformed_txts_path)
        transformed_txt_path = os.path.join(transformed_txts_path, "%s.txt" % ouid)

        # logging.info(f'sutra_ouid:{sutra_ouid},ouid:{ouid},transformed_txt_path:{transformed_txt_path}')
        transformed_txt = ""
        for std_txt in std_txts:
            for txt in std_txt[1]:
                transformed_txt += txt[1]
        # 按照¶标点来展示换行
        transformed_txt = transformed_txt.replace("\n", "").replace("¶", "\n")
        with open(transformed_txt_path, "a", encoding="utf-8") as f:
            f.write("%s" % transformed_txt)

    # 存档数据库
    with open(origin_txt_path, "r", encoding="utf-8") as f:
        new_punc_content = f.read()

    with open(transformed_txt_path, "r", encoding="utf-8") as f:
        segmented_punc_content = f.read()

    jsz_collection.update_one(
        {"卷号": juanhao},
        {
            "$set": {
                "新标点内容": new_punc_content,
                "正常分段标点内容": segmented_punc_content,
                "新是否已迁移": "Y",
            }
        },
    )
    logging.info(f"数据库更新完成：{juanhao}")


def generate_high_match_rolls():
    """生成高匹配度的卷文本"""
    query = {"匹配信息.match_rate": {"$gte": 0.99}, "是否已迁移": "Y"}
    projection = {"_id": 0, "经号": 1, "卷号": 1}

    try:
        results = jsz_collection.find(query, projection)
        # 先获取总数
        count = jsz_collection.count_documents(query)
        logging.info(f"查询到 {count} 个卷")
        # exit('end')
        for index, doc in enumerate(results):
            logging.info(f"正在处理第 {index+1}/{count} 个卷, 经号={doc['经号']}")
            if juanhao := doc.get("卷号"):
                logging.info(f"正在生成: 经号={doc['经号']} 卷号={juanhao}")
                generate_one_roll_txt(juanhao)
            # break

    except Exception as e:
        logging.error(f"处理出错: {str(e)}")
    finally:
        online_client.close()
        dev_client.close()


if __name__ == "__main__":
    generate_high_match_rolls()
