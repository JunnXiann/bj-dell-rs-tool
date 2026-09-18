import os
from datetime import datetime, timezone
import logging
import pandas as pd
import sys
from multiprocessing import Pool, cpu_count, current_process
import asyncio
import numpy as np
from datetime import datetime, timezone, timedelta
import threading
import time
import re
import pymongo
import hashlib
import os
import json
import traceback


root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.append(root_dir)

from util.punc import (
    transfer_punc_for_stats,
    stat_bd_details_byfile,
    big_model_punc,
    PUNC_STR,
    START_PUNC,
    END_PUNC,
)
from util.punc_lib.best_match_two_txt import BestMatchTwoTxt
from util.punc_lib.punc_config import global_db_vars

import helper as hp

cur_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
hp.set_logging("multy_cmp_wrap_content-" + str(cur_time), False)


IS_BASE_TEXT = lambda x: x not in "\n[]JS_0123456789"
# 大模型名称
BIG_MODEL_NAME = "qwen"  # 首选千问
SECOND_BIG_MODEL_NAME = "doubao"  # 次选豆包
PARAGRAGH_NUM = 50  # 段落判断阈值
IS_SEGMENT_DIFF_USE_AI_PUNC = False  # 是否使用大模型进行差异的文字打标，目前只有无现代标点的需要大模型，其他没匹配到的不管，等待人工顺序比对好再处理
# 创建左右标点的映射字典
PUNC_MAPPING = dict(zip(END_PUNC, START_PUNC))
best_matcher = BestMatchTwoTxt()


def init_pool():
    """初始化每个子进程的独立资源"""

    try:
        logging.info(f"init_pool start")
        global global_db_vars

        # ali-dev测试开发环境
        rushi_dev_client = hp.connect_db_max("alidev", "mongodb-", True)
        rushi_dev_db = rushi_dev_client["rushi-dev"]
        jsz_collection = rushi_dev_db["jsz_wrap_rolls"]
        jsz_source_mapping_collection = rushi_dev_db["jsz_source_mapping_excels"]
        big_model_punc_details_collection = rushi_dev_db["big_model_punc_details"]
        test_sutra_sources_collection = rushi_dev_db["sutra_sources"]
        keep_alive(rushi_dev_client)  # 启动保活线程

        # 校对平台正式环境
        check_online_read_client = hp.connect_db_max(
            "check-read-online", "mongodb-", True
        )
        check_online_read_db = check_online_read_client["tripitaka-product"]
        reel_bd_collection = check_online_read_db["reel_bd"]
        sutra_sources_collection = check_online_read_db["sutra_sources"]
        keep_alive(check_online_read_client)  # 启动保活线程

        # 测试环境
        test_client = hp.connect_db_max("test", "mongodb-", True)
        test_db = test_client["tripitaka-reader-test"]
        test_pubnote_collection = test_db["pubnote"]
        keep_alive(test_client)  # 启动保活线程

        global_db_vars = {
            "rushi_dev_client": rushi_dev_client,
            "check_online_read_client": check_online_read_client,
            "test_client": test_client,
            "test_pubnote_collection": test_pubnote_collection,
            "jsz_collection": jsz_collection,
            "jsz_source_mapping_collection": jsz_source_mapping_collection,
            "big_model_punc_details_collection": big_model_punc_details_collection,
            "reel_bd_collection": reel_bd_collection,
            "sutra_sources_collection": sutra_sources_collection,
            "test_sutra_sources_collection": test_sutra_sources_collection,
        }

        logging.info(f"init_pool 初始化成功（子进程ID: {os.getpid()}）")
        # logging.info(f'global_db_vars: {global_db_vars}')

    except Exception as e:
        logging.error(f"init_pool 初始化失败（子进程ID: {os.getpid()}）: {str(e)}")


# 连接如果因为其他逻辑慢，会导致连接超时断开，所以需要保持连接活跃
def keep_alive(client, interval=300):
    """每5分钟执行一次简单查询保持连接活跃"""

    def run():
        while True:
            try:
                client.admin.command("ping")
            except:
                pass
            time.sleep(interval)

    t = threading.Thread(target=run, daemon=True)
    t.start()


def get_md5_key(text: str) -> str:
    """生成文本的MD5哈希值作为唯一键"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def generate_file_content(file_path: str, file_name: str, content: str) -> None:
    """
    生成文件内容
    """
    if not os.path.exists(file_path):
        os.makedirs(file_path)
    path = file_path + "/" + file_name
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def search_last_startpunc(prev_segment):
    """
    找到上一个segment的最后一个非换行符，并且不是[JS_123]的字符
    """
    last_non_newline_index = len(prev_segment["base1"]) - 1
    while last_non_newline_index >= 0:
        current_char = prev_segment["base1"][last_non_newline_index]
        # 遇到换行符继续向左
        if current_char == "\n":
            last_non_newline_index -= 1
            continue
        # 遇到]则继续向左直到找到[
        if current_char == "]":
            while (
                last_non_newline_index >= 0
                and prev_segment["base1"][last_non_newline_index] != "["
            ):
                last_non_newline_index -= 1
            last_non_newline_index -= 1  # 找到[后继续左移一位
            continue
        break  # 找到目标字符

    last_char = (
        prev_segment["base1"][last_non_newline_index]
        if last_non_newline_index >= 0
        else ""
    )
    return last_char, last_non_newline_index


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


# 预处理 source 的文本
def process_source_text(text: str) -> str:
    """
    1. 过滤所有注释行（以#开头，含全角#）
    2. 删除所有空行（包括处理后的空字符串）
    3. 删除所有空格（半角/全角/行首尾）
    4. 非空行用¶连接，无空行分隔
    """

    # 1. 按行分割，过滤注释行（支持全角#）
    lines = [
        line
        for line in text.split("\n")
        if not line.lstrip("\r").startswith("#")  # 兼容 Windows 换行，忽略注释
    ]

    # 2. 处理每一行：删除所有空格，过滤空行
    processed = []
    for line in lines:
        # 去除所有空格（半角\u0020、全角\u3000）+ 首尾换行符
        stripped = re.sub(r"[\u0020\u3000\r]", "", line.strip("\n"))
        if stripped:  # 仅保留非空行
            # 去掉一些字符
            stripped = stripped.replace("【", "").replace("】", "").replace("◎", "")
            processed.append(stripped)

    # 3. 用¶连接所有非空行
    return "¶".join(processed)


def get_jsz_wrap_roll(juanhao):
    """
    根据卷号从指定集合中获取数据
    :param juanhao: 卷号
    :return: 排序后的(卷号, 内容)列表
    """
    result = global_db_vars["jsz_collection"].find_one({"卷号": juanhao})
    return result


def get_jsz_sorted_contents(jinghao):
    """
    根据经号从指定集合中获取按卷号排序的(卷号, 内容)列表
    :param jinghao: 经号
    :return: 排序后的(卷号, 内容)列表
    """
    results = (
        global_db_vars["jsz_collection"]
        .find({"经号": jinghao, "是否已迁移": "N"})
        .sort("序号")
    )
    return [(result["卷号"], result["内容"], result["序号"]) for result in results]


def merge_contents(contents):
    """
    将(卷号, 内容)列表拼接成大文本
    :param contents: (卷号, 内容)列表
    :return: 拼接后的大文本
    """
    return "".join([content + "\n" for _, content, _ in contents])


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


def get_roll_pubnote_by_page(jsz_juanhao, page=None):
    """
    获取牌记信息
    跟JS内容里面的页码关系
    a为尾数字*2-1，b为尾数字*2
    [JS_195_948]对应为JS_195_474b
    [JS_195_889]对应为JS_195_445a
    [JS_195_890]对应为JS_195_445b
    牌记表存储格式如下，可能是多个页码一起的
    JS_195_445a-JS_195_445b
    JS_195_521a
    JS_195_496b
    :param juanhao: 卷号
    :param page: 页码
    :param punctuated_content: 处理后的内容
    """
    format_jsz_juanhao = format_juanhao_string(jsz_juanhao)

    nums = page.split("_") if page else []
    # logging.info(f'get_roll_pubnote_by_page,jsz_juanhao:{jsz_juanhao},nums:{nums},page:{page}')
    result = None
    if len(nums) >= 1 and nums[-1].isdigit():

        if int(nums[-1]) % 2 == 0:
            new_page = f"{nums[0]}_{nums[1]}_{int(nums[2])//2}b"
        else:
            new_page = f"{nums[0]}_{nums[1]}_{(int(nums[2])+1)//2}a"

        result = global_db_vars["test_pubnote_collection"].find_one(
            {
                "$and": [
                    {"reel_uid": format_jsz_juanhao},
                    {"page_uid": {"$regex": new_page}},  # 新增LIKE条件
                ]
            },
            projection={"pub_note": 1, "_id": 0},
        )
    else:
        result = global_db_vars["test_pubnote_collection"].find_one(
            {
                {"reel_uid": format_jsz_juanhao},
            },
            projection={"pub_note": 1, "_id": 0},
        )

    logging.info(
        f"get_roll_pubnote_by_page，jsz_juanhao:{jsz_juanhao},new_page：{new_page},format_jsz_juanhao:{format_jsz_juanhao},result:{result}"
    )
    return result.get("pub_note", "") if result else ""


def get_roll_pubnote(jsz_juanhao):
    """
    获取牌记信息
    :param juanhao: 卷号
    :param punctuated_content: 处理后的内容
    """
    format_jsz_juanhao = format_juanhao_string(jsz_juanhao)
    result = test_pubnote_collection.find_one(
        {"reel_uid": format_jsz_juanhao}, projection={"pub_note": 1, "_id": 0}
    )
    return result.get("pub_note", "") if result else ""


def get_roll_pubnotes(jsz_contents):
    """
    获取牌记信息列表
    :param jsz_contents: 卷号列表
    """
    pubnotes = []
    for jsz_content in jsz_contents:
        jsz_jinghao = jsz_content[0]
        pubnotes.append(get_roll_pubnote(jsz_jinghao))
    return "".join([pubnote + "\n" for pubnote in pubnotes])


def update_jsz_wrap_roll_punc_status(jsz_juanhao, punc_res):
    """
    更新 jsz_wrap_rolls api打标状态
    :param jsz_juanhao: JSZ 卷号
    :param punc_res: 打标异常内容
    """
    # 添加牌记信息
    global_db_vars["jsz_collection"].update_one(
        {"卷号": jsz_juanhao}, {"$set": {"打标是否异常": "Y", "打标结果": punc_res}}
    )


def update_punctuated_content(
    jsz_jinghao,
    jsz_juanhao,
    punctuated_content,
    match_info,
    has_modern_bd,
    has_big_model_punc,
    is_best_match,
    source,
):
    """
     统一更新标点内容到不同来源字段
    :param jsz_jinghao: JSZ 经号
    :param jsz_juanhao: JSZ 卷号
    :param punctuated_content: 处理后的内容
    :param match_info: 匹配信息
    :param has_modern_bd: 是否有现代标点
    :param has_big_model_punc: 是否有大模型打标（普通正文，非音释）
    """

    logging.info(f"update_punctuated_content start: {jsz_juanhao} {jsz_jinghao}")

    processed_content = process_last_punc_text(punctuated_content)
    update_fields = {
        "updated_at": datetime.now(timezone(timedelta(hours=8))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    }

    # 动态生成来源字段映射
    source_field = {
        "CBETA": "cbeta_punc_content",
        "FGZ": "fgz_punc_content",
        "WL": "wl_punc_content",
        "XZ": "xz_punc_content",
    }.get(source)

    update_fields[source_field] = processed_content

    # 处理最佳匹配和XZ的特殊字段
    if is_best_match:
        update_fields.update(
            {
                "标点内容": processed_content,
                "是否已迁移": "Y",
                "是否有现代标点": has_modern_bd,
                "是否有大模型打标": has_big_model_punc,
                "匹配信息": match_info,
            }
        )

    # 步骤1：初始化source层结构，存在不操作，不存在则初始化成{}
    global_db_vars["jsz_collection"].update_one(
        {
            "经号": jsz_jinghao,
            "卷号": jsz_juanhao,
            f"source_match_info.{source}": {"$exists": False},
        },
        {"$set": {f"source_match_info.{source}": {}}},
        upsert=False,
    )

    source_match_path = f"source_match_info.{source}"
    update_fields.update(
        {
            f"{source_match_path}.has_modern_bd": has_modern_bd,
            f"{source_match_path}.has_big_model_punc": has_big_model_punc,
        }
    )

    # 执行单个数据库操作
    global_db_vars["jsz_collection"].update_one(
        {"经号": jsz_jinghao, "卷号": jsz_juanhao}, {"$set": update_fields}
    )

    logging.info(f"update_punctuated_content end: {jsz_juanhao} {jsz_jinghao}")


def get_jsz_source_mappings():
    """
    获取 JSZ-SOURCE 映射关系
    """
    if False:
        results = (
            global_db_vars["jsz_source_mapping_collection"]
            .find({"经号1": {"$in": ["JS_1804"]}})
            .sort([("实存卷数", pymongo.ASCENDING)])
            .limit(2)
        )
    else:
        results = (
            global_db_vars["jsz_source_mapping_collection"]
            .find(
                {
                    # "是否如是打标点": "Y",DESCENDING，ASCENDING
                    "是否已迁移": "N",
                }
            )
            .sort([("实存卷数", pymongo.ASCENDING)])
        )

    return {
        (
            result["经号1"],  # 这个字段必须存在，否则应报错
            result.get("实存卷数", 0),  # 默认 0
            result.get("一对多", "N"),  # 默认 N
            json.dumps(result.get("一对多参数", "")),  # 默认空字符串
            result.get("是否需要标点", "Y"),
        ): result
        for result in results
    }


def update_jsz_source_mappings_status(jsz_jinghao, qy_status="Y"):
    """
    将处理后的内容更新到 update_jsz_source_mappings_status 集合的是否已迁移字段
    :param jsz_jinghao: JSZ 经号
    :param qy_status: 迁移状态
    """
    logging.info(f"update_jsz_source_mappings_status: {jsz_jinghao} {qy_status}")
    global_db_vars["jsz_source_mapping_collection"].update_one(
        {"经号1": jsz_jinghao}, {"$set": {"是否已迁移": qy_status}}
    )


def get_source_reel_uids_by_sutra_uid(sutra_uid):
    results = (
        global_db_vars["reel_bd_collection"]
        .find({"sutra_uid": sutra_uid})
        .sort("reel_no")
    )

    reel_uids = [result["reel_uid"] for result in results]
    return reel_uids


def get_source_contents_by_juanhaos(juanhaos):
    results = (
        global_db_vars["reel_bd_collection"]
        .find({"reel_uid": {"$in": juanhaos}})
        .sort("reel_no")
    )

    source_contents = [
        (result["reel_uid"], result["txt"], result["reel_no"]) for result in results
    ]
    return source_contents


def deal_seg_punc_bug(segments):
    """
    预处理下标点的边界问题，主要是径山藏和cbeta文字不一致，导致标点迁移bug
    规则：segment['diff'] < 0 并且包含右标点：比如】）等,具体见END_PUNC，查看上一个segment['base']末尾是否包含左标点，如果包含，则对上一个segment['base']去掉字符串最后那个左标点，具体见START_PUNC
    """
    for i in range(1, len(segments)):
        current_segment = segments[i]
        prev_segment = segments[i - 1]
        # cbeta有多余段落
        cur_len_diff = current_segment.get("len_diff", 0)
        if cur_len_diff < 0:
            # logging.info(f"deal_punc_bug，cbeta有多余段落: {current_segment['cmp0']},len_diff:{current_segment['len_diff']}")
            for punc in END_PUNC:
                # cbeta原带标点的段落
                if punc in current_segment["cmp0"]:
                    # logging.info(f"deal_punc_bug,发现标点，punc:{punc}，当前：{current_segment['cmp0']}，上一个：{prev_segment['base1']}")
                    # 上一个迁移后的带标点的段落
                    # 找到最后一个非\n，并且是非[JS_123]的字符,可能跨标题了，比如下面文字就是去掉了尾巴的\n，去掉了[JS_64_1056]，最后得到（：
                    # 所患即消除。¶（
                    # [JS_64_1056]
                    last_char, last_non_newline_index = search_last_startpunc(
                        prev_segment
                    )
                    matching_start_punc = PUNC_MAPPING.get(punc)
                    # logging.info(f"deal_punc_bug < 0,punc：{punc},matching_start_punc:{matching_start_punc},last_char：{last_char}")
                    if last_char == matching_start_punc:
                        new_base1 = (
                            prev_segment["base1"][:last_non_newline_index]
                            + prev_segment["base1"][last_non_newline_index + 1 :]
                        )
                        # logging.info(f"deal_punc_bug < 0,发现上一个标点，punc:{punc}，原文本:{prev_segment['base1']},准备修改成：{new_base1}")

                        prev_segment["base1"] = new_base1
                        break

        elif cur_len_diff > 0:
            # 如果当前是jsz多余的段落，并且上一个segment以左标点结尾，则去掉上一个segment的左标点，添加到当前segment的后面
            # 比如：合部金光明經序¶《
            # 日嚴寺沙門釋彦琮述
            # 金光明經》
            last_char, last_non_newline_index = search_last_startpunc(prev_segment)
            if last_char in START_PUNC:
                # logging.info(f"deal_punc_bug > 0,last_char：{last_char},last_non_newline_index:{last_non_newline_index}")
                new_base1 = (
                    prev_segment["base1"][:last_non_newline_index]
                    + prev_segment["base1"][last_non_newline_index + 1 :]
                )
                # logging.info(f"deal_punc_bug > 0,发现上一个标点，原文本:{prev_segment['base1']},准备修改成：{new_base1}")
                current_segment["base1"] = current_segment["base1"] + last_char
                prev_segment["base1"] = new_base1

    return segments


def deal_last_punc_bug(text):
    """
    最后预处理下文本一些标点异常
    1. 如果判断是标题，则去掉[]两边的标点，比如下面格式：
    "來
    [JS_64_1067]
    ）¶"
    """
    lines = text.split("\n")
    new_lines = []
    punctuation_pattern = r"[^\w\s\[\]]"  # 匹配除字母、数字、下划线、空格和[]之外的字符

    for line in lines:
        if "[" in line and "]" in line:
            # 去掉[]前后的标点
            line = re.sub(rf"^{punctuation_pattern}+", "", line)
            line = re.sub(rf"{punctuation_pattern}+$", "", line)
        new_lines.append(line + "\n")

    return "".join(new_lines).rstrip("\n")  # 去掉最后多余的换行符


def get_source_reel_big_text(source, sutra_uid, reel_nos):
    """
    获取数据源的经卷内容大文本
    :param collection: MongoDB 集合对象
    :param sutra_uid: 源经号
    :param: reel_nos: 页码
    :return: 排序后的列表
    """

    logging.info(
        f"get_source_reel_big_text > source:{source}, sutra_uid:{sutra_uid}, reel_nos:{reel_nos}"
    )

    # 构建查询条件（强制reel_no为数字类型，非数字的可能是序和跋）
    query = {"sutra_uid": sutra_uid, "source": source, "reel_no": {"$type": "number"}}
    if reel_nos:  # 仅当数组非空时添加reel_no条件
        query["reel_no"] = {"$in": reel_nos}

    # 查询并按reel_no升序排列
    cursor = (
        global_db_vars["reel_bd_collection"]
        .find(
            query,
            projection={"source": 1, "txt": 1, "sutra_uid": 1, "reel_uid": 1, "_id": 0},
        )
        .sort("reel_no", pymongo.ASCENDING)
    )  # 新增排序
    cursor = list(cursor)

    logging.info(
        f"get_source_reel_big_text > source:{source}, sutra_uid:{sutra_uid}, reel_nos:{reel_nos},len:{len(cursor)}"
    )

    return "\n".join([item["txt"] for item in cursor]) if cursor else ""


def get_rs_sutra_uid(sutra_uid, source):
    """
    获取经号对应的rs_sutra_uid，兼容 sutra_uid 为字符串或数组的情况
    """
    query = {
        "source_type": source,
        "$or": [
            {"sutra_uid": sutra_uid},  # 字符串匹配
            {"sutra_uid": {"$in": [sutra_uid]}},  # 数组包含
        ],
    }

    result = global_db_vars["sutra_sources_collection"].find_one(
        query, {"rushi_sutra_uid": 1, "_id": 0}
    )
    logging.info(f"get_rs_sutra_uid: {sutra_uid} {source}, result: {result}")
    return result.get("rushi_sutra_uid") if result else None


def get_source_sutra_uid(rushi_sutra_uid, source):
    """
    获取源经号 sutra_uid
    :param rushi_sutra_uid: 如是经号
    :param source: 来源
    :return: sutra_uid
    """
    result = global_db_vars["sutra_sources_collection"].find_one(
        {"rushi_sutra_uid": rushi_sutra_uid, "source_type": source},
        {"sutra_uid": 1, "assist_sutra_uid": 1, "_id": 0},
    )
    logging.info(f"get_source_sutra_uid: {rushi_sutra_uid} {source}, result: {result}")
    sutra_uid = result.get("sutra_uid") if result else None
    assist_sutra_uid = result.get("assist_sutra_uid") if result else None
    logging.info(f"sutra_uid: {sutra_uid} assist_sutra_uid: {assist_sutra_uid}")

    return sutra_uid, assist_sutra_uid


def cal_diff_rate(input_text, big_cmp_text, jsz_jinghao, jsz_juanhao):
    logging.info(f"cal_diff_rate start: {jsz_jinghao} {jsz_juanhao}")
    # 文本对齐匹配率
    text1_no_punc, matched_paragraph_no_punc, matched_paragraph, align_match_rate = (
        best_matcher.find_best_match(input_text, big_cmp_text)
    )
    logging.info(
        f"find_best_match end,transfer_punc_for_stats start : {jsz_jinghao} {jsz_juanhao}"
    )

    _, segments = transfer_punc_for_stats(input_text, matched_paragraph, IS_BASE_TEXT)
    # logging.info(f'transfer_punc_for_stats,segments_end')
    logging.info(f"transfer_punc_for_stats end : {jsz_jinghao} {jsz_juanhao}")

    # 过滤出 len_diff 不为 0 的数据
    diff_segments = [
        segment
        for segment in segments
        if (segment["len_diff"] != 0 and segment["is_same"] == False)
    ]
    # 分母数量
    denominator = sum(len(segment["base"]) for segment in segments)
    # logging.info(f'jsz_jtransfer_punc_for_stats_end:{jsz_jinghao},diff_segments_len:{len(diff_segments)}')

    # 计算不匹配的分子总数
    misnumerator = sum(
        len(segment["base"]) for segment in diff_segments if segment["len_diff"] > 2
    )
    # 计算不匹配度
    if denominator != 0:
        mismatch_rate = misnumerator / denominator
        # 保留两位小数
        mismatch_rate = round(mismatch_rate, 4)
    else:
        mismatch_rate = 0
    match_rate = round(1 - mismatch_rate, 4)

    logging.info(
        f"jsz_jinghao:{jsz_jinghao},jsz_juanhao:{jsz_juanhao},不匹配分子:{misnumerator},分母：{denominator},nomal_content_length:{len(input_text)} 不匹配度：{mismatch_rate},匹配度: {match_rate}"
    )
    match_info = {
        "match_rate": match_rate,
        "misnumerator": misnumerator,
        "denominator": denominator,
        "minus_numerator": 0,
        "mismatch_rate": mismatch_rate,
        "jsz_content_lenth": len(input_text),
        "align_match_rate": align_match_rate,
    }
    return match_info, matched_paragraph, segments, diff_segments


def punc_rate_stat_by_segment(input_text, big_cmp_text, jsz_jinghao, jsz_juanhao):
    """
    1. 按照diff算法计算匹配度
    2. 2次搜索召回后，再计算匹配度
    """

    match_info, matched_cmp_text, segments, diff_segments = cal_diff_rate(
        input_text, big_cmp_text, jsz_jinghao, jsz_juanhao
    )
    # 如果有 len_diff 不为 0 的数据，保存到 Excel 文件
    todo_segments = []
    if diff_segments:

        # 对未匹配到的段落做2次查询，防止源数据段落混乱；剩下没匹配到的非段落的小字符串，暂时不做AI标点，防止打混乱，这部分人工处理
        todo_segments = [
            segment for segment in diff_segments if segment["len_diff"] >= PARAGRAGH_NUM
        ]
        if todo_segments:
            for todo_segment in todo_segments:
                base_content = todo_segment["base"]
                logging.info(f"对齐算法2次搜索开始，jsz_juanhao:{jsz_juanhao}")
                # 二次查找，从经级别找
                (
                    text1_no_punc,
                    matched_paragraph_no_punc,
                    matched_paragraph,
                    match_rate,
                ) = best_matcher.find_best_match(base_content, big_cmp_text)
                logging.info(
                    f"对齐算法2次搜索segment_content_match_info,jsz_juanhao:{jsz_juanhao},match_rate:{match_rate},\n,base_content:{base_content}，\n matched_paragraph:{matched_paragraph}"
                )
                if match_rate > 0.7:

                    todo_segment["base1"], _ = transfer_punc_for_stats(
                        base_content, matched_paragraph, IS_BASE_TEXT
                    )
                    todo_segment["cmp"] = matched_paragraph_no_punc
                    todo_segment["cmp0"] = matched_paragraph
                else:
                    logging.info(
                        f"对齐算法2次搜索，jsz_juanhao:{jsz_juanhao}，match_rate:{match_rate}，2次没有匹配到，不做打标"
                    )

    else:
        logging.info("jsz_juanhao：{jsz_juanhao},没有 len_diff 不为 0 的数据。")

    # 这里需要把 todo_segments 更新后的base1，赋值给 segments 里对应项的 base1，然后拼接segments的base1作为最后的标点大文本
    for todo_segment in todo_segments:
        # 查找 segments 中 no 相同的项
        for segment in segments:
            if segment["no"] == todo_segment["no"]:
                # 将 todo_segments 里的 base1 赋值给 segments 里对应项的 base1
                # logging.info(f'jsz_juanhao:{jsz_juanhao},origin_segment:{segment},update_todo_segment:{todo_segment}')
                segment["base1"] = todo_segment["base1"]
                segment["cmp"] = todo_segment["cmp"]
                segment["cmp0"] = todo_segment["cmp0"]
                break

    # 计算2次查找的匹配率
    cmp_text2 = "".join([segment["cmp0"] for segment in segments])
    match_info2, matched_cmp_text2, segments2, diff_segments2 = cal_diff_rate(
        input_text, cmp_text2, jsz_jinghao, jsz_juanhao
    )

    # 处理下标点的边界问题，主要是径山藏和cbeta文字不一致，导致标点迁移bug
    segments2 = deal_seg_punc_bug(segments2)

    # 拼接segments的base1作为最后的标点大文本
    jsz_new_content = "".join([segment["base1"] for segment in segments2])
    # 处理下最后的标点问题，比如[]两边标点bug
    jsz_new_content = deal_last_punc_bug(jsz_new_content)
    # 释放内存
    del segments
    del todo_segments
    del diff_segments
    del segments2
    del diff_segments2

    return jsz_new_content, match_info, match_info2, cmp_text2


def get_source_sorted_contents(
    source, source_jinghao, reel_nos, jsz_jinghao, one_2_multy_params
):
    """
    根据经号从指定集合中获取按卷号排序的(卷号, 内容)列表
    :param jinghao: 经号
    :return: 排序后的(卷号, 内容)列表
    """
    # 判断是否为数组
    if isinstance(source_jinghao, list):
        logging.info(f"source_jinghao is list,source_jinghao:{source_jinghao}")
        source_jinghao = ",".join(source_jinghao)
    # 单个字符串，转成数组
    if len(one_2_multy_params) > 0 and isinstance(one_2_multy_params, str):
        one_2_multy_params = [one_2_multy_params]

    logging.info(
        f"get_source_sorted_contents start,source:{source},source_jinghao:{source_jinghao},jsz_jinghao:{jsz_jinghao},one_2_multy_params:{one_2_multy_params},reel_nos:{reel_nos}"
    )

    file_name = source_jinghao
    source_big_txt = ""
    if (
        one_2_multy_params == None
        or one_2_multy_params == ""
        or len(one_2_multy_params) == 0
    ):
        source_big_txt = get_source_reel_big_text(source, source_jinghao, reel_nos)
    else:
        source_contents = []
        # 1对多
        file_name = source + "-" + source_jinghao + "-" + jsz_jinghao
        # {"X0273_010,X0273_001-009,X0275_001,X0274,X0275_001-010"}
        # 按序拼接所有的
        for part in one_2_multy_params:
            logging.info(
                f"part:{part},source:{source},source_jinghao:{source_jinghao},jsz_jinghao:{jsz_jinghao}"
            )
            # 异常数据处理
            if part == "-":
                continue
            source_juanhaos = []
            part = part.strip()
            if "-" in part:
                # 处理连续范围X0273_001-009,T1435_060-061
                prefix, range_part = part.split("_")
                start_end = range_part.split("-")
                if len(start_end) == 2:
                    start = int(start_end[0])
                    end = int(start_end[1])
                    for num in range(start, end + 1):
                        source_juanhaos.append(f"{prefix}_{num:03d}")
            else:
                # 处理单个标识（经号或卷号）
                if "_" in part:  # 卷号（如 X0273_010）
                    source_juanhaos.append(part)
                else:  # 经号（如 X0274）
                    # 获取该经号下的所有卷号并按序号排序
                    jing_juanhaos = get_source_reel_uids_by_sutra_uid(part)
                    source_juanhaos.extend(jing_juanhaos)

            logging.info(f"part:{part},source_juanhaos:{source_juanhaos}")
            # 每个循环都要请求，不然顺序会不一致
            source_content = get_source_contents_by_juanhaos(source_juanhaos)
            if source_content:
                source_contents.extend(source_content)

        # logging.info(f'source_contents:{source_contents}')
        # 将 source 这边的内容按照卷号排序拼接起来成 1 个大的内容
        source_big_txt = merge_contents(source_contents)

    # 预处理source文本，去掉换行符，空格等
    source_big_pre_deal_txt = process_source_text(source_big_txt)
    logging.info(
        f"source_big_pre_deal_txt 处理完成，source_jinghao:{source_jinghao},file_name:{file_name}"
    )

    generate_file_content(
        f"output/source_warp/{source}/origin", f"{file_name}.txt", source_big_txt
    )

    generate_file_content(
        f"output/source_warp/{source}/predeal",
        f"{file_name}.txt",
        source_big_pre_deal_txt,
    )

    logging.info(f"source_big_pre_deal_txt 处理完成,source_jinghao:{source_jinghao}")

    return source_big_pre_deal_txt


"""
多次查找匹配逻辑：
1. 先按对齐的卷序号查找，得到命中率 hit_ratio_1reel
2. hit_ratio_1reel 不够，按前后拼接1卷，先对齐，再查找，得到命中率 hit_ratio_3reel
3. hit_ratio_3reel 不够，按全经，先对齐，再查找，得到命中率 hit_ratio_all
4. hit_ratio_all 不够，做全经范围内2次查找，得到命中率 hit_ratio_all_2search
5. 任一步骤满足，则返回

注意：
1. 这里的命中率统一用 diff算法给的命中率，异体字、差异值<=2的，都认为是命中
2. 1对多的按经级别

"""


def multy_search_find_best_match(
    jinghao, juanhao, sort_no, is_one_2_multy, one_2_multy_params, origin_text
):
    # 不用外面的
    one_2_multy_params = None
    logging.info(
        f"multy_search_find_best_match start，jinghao:{jinghao},one_2_multy_params：{one_2_multy_params}"
    )
    rs_sutra_uid = get_rs_sutra_uid(jinghao, "JSZ")

    one_2_multy_params = json.loads(one_2_multy_params) if one_2_multy_params else {}
    logging.info(
        f"multy_search_find_best_match after_deal one_2_multy_params:{one_2_multy_params}"
    )

    sources = ["XZ", "WL", "FGZ", "CBETA"]
    MATCH_RATE_LIMIT = 0.98  # 匹配率阈值，超过则不再搜索
    best_match = {"rate": 0, "source": "", "type": ""}
    matchs = {}

    logging.info(
        f"multy_search_find_best_match loop sources,rs_sutra_uid:{rs_sutra_uid},jinghao:{jinghao}"
    )

    for source in sources:
        source_sutra_uid, assist_sutra_uid = get_source_sutra_uid(rs_sutra_uid, source)
        if source_sutra_uid == None:
            logging.info(
                f"multy_search_find_best_match source:{source} ,rs_sutra_uid:{rs_sutra_uid} not found,continue"
            )
            continue

        logging.info(
            f"loop sources,source:{source},source_sutra_uid:{source_sutra_uid},rs_sutra_uid:{rs_sutra_uid}，assist_sutra_uid：{assist_sutra_uid}"
        )
        if assist_sutra_uid and len(assist_sutra_uid) > 0:
            one_2_multy_params = assist_sutra_uid

        # 处理一对多情况
        if one_2_multy_params:
            logging.info(
                f"db_find_multy,source:{source},jinghao:{jinghao},one_2_multy_params:{one_2_multy_params}"
            )
            source_text = get_source_sorted_contents(
                source, source_sutra_uid, [], jinghao, one_2_multy_params
            )
            if len(source_text) == 0:
                logging.info(
                    f"source:{source},jinghao:{jinghao},source_sutra_uid:{source_sutra_uid}，one_2_multy_params:{one_2_multy_params}，source_text为空，不做处理"
                )
                continue

            matchs, best_match, current_match_rate = check_and_save_match(
                matchs,
                best_match,
                source,
                source_sutra_uid,
                jinghao,
                juanhao,
                origin_text,
                [],
                source_text,
                "all_reel",
            )

        else:
            reel_configs = [
                ("1_reel", [sort_no]),
                ("3_reel", [sort_no - 1, sort_no, sort_no + 1]),
                ("all_reel", []),
            ]

            logging.info(f"source:{source},reel_configs:{reel_configs}")

            # 遍历卷配置生成匹配项
            for reel_type, reel_nos in reel_configs:
                logging.info(
                    f"multy_search_find_best_match loop reel_configs,source:{source},reel_type:{reel_type},reel_nos:{reel_nos},one_2_multy_params:{one_2_multy_params}"
                )

                source_text = get_source_sorted_contents(
                    source, source_sutra_uid, reel_nos, jinghao, one_2_multy_params
                )
                if len(source_text) == 0:
                    logging.info(
                        f"source:{source},jinghao:{jinghao},source_sutra_uid:{source_sutra_uid}，source_text为空，不做处理"
                    )
                    continue

                matchs, best_match, current_match_rate = check_and_save_match(
                    matchs,
                    best_match,
                    source,
                    source_sutra_uid,
                    jinghao,
                    juanhao,
                    origin_text,
                    reel_nos,
                    source_text,
                    reel_type,
                )

                # 如果匹配率打标，则终止
                if current_match_rate >= MATCH_RATE_LIMIT:
                    logging.info(
                        f"source_sutra_uid:{source_sutra_uid},reel_type:{reel_type},current_match_rate:{current_match_rate} >= MATCH_RATE_LIMIT:{MATCH_RATE_LIMIT}，终止匹配"
                    )
                    break

    logging.info(f"best_match {best_match}")
    # 标记最佳匹配项
    if best_match["source"] in matchs:
        matchs[best_match["source"]]["is_best_match"] = True

    logging.info(f"multy_search_find_best_match jinghao:{jinghao},juanhao:{juanhao}")

    return matchs


def check_and_save_match(
    matchs,
    best_match,
    source,
    source_sutra_uid,
    jinghao,
    juanhao,
    origin_text,
    reel_nos,
    source_text,
    reel_type,
):
    # 获取匹配信息
    jsz_new_content, match_info, match_info2, cmp_text2 = get_match_info(
        source, source_sutra_uid, jinghao, juanhao, origin_text, reel_nos, source_text
    )

    # 构造匹配条目
    match_entry = {
        "jsz_new_content": jsz_new_content,
        "match_info": match_info,
        "match_info2": match_info2,
        "cmp_text2": cmp_text2,
        "source": source,
        "type": reel_type,
        "is_best_match": False,
    }

    # 更新最佳匹配
    if match_info2["match_rate"] > best_match["rate"]:
        best_match.update(
            {"rate": match_info2["match_rate"], "source": source, "type": reel_type}
        )

    # 每个source只记录1个匹配最高的
    matchs[source] = match_entry

    # 保存并检查匹配率
    save_match_info(
        match_info, match_info2, cmp_text2, jinghao, juanhao, source, reel_type
    )

    return matchs, best_match, match_info2["match_rate"]


def save_match_info(
    match_info, match_info2, cmp_text2, jinghao, juanhao, source, reel_type
):
    """
    保存匹配信息到source_match_info字段
    :param source: 数据源类型（XZ/WL/FGZ/CBETA）
    :param reel_type: 层级类型（1reel/3reel/all_reel）
    """
    logging.info(
        f"save_match_info start：source:{source}, reel_type: {reel_type},jinghao: {jinghao}, juanhao: {juanhao}"
    )

    # logging.info(f"save_match_info start：source:{source}, reel_type: {reel_type},jinghao: {jinghao}, juanhao: {juanhao},\n 匹配信息：match_info:{match_info}, match_info2:{match_info2}, \n cmp_text2:{cmp_text2}")
    # Step 0: 强制修复 source_match_info 字段类型，如果它是字符串（非法），转为 {}
    doc = global_db_vars["jsz_collection"].find_one(
        {"经号": jinghao, "卷号": juanhao}, {"source_match_info": 1}
    )
    if doc:
        smi = doc.get("source_match_info")
        if smi is None or not isinstance(smi, dict):
            global_db_vars["jsz_collection"].update_one(
                {"经号": jinghao, "卷号": juanhao},
                {"$set": {"source_match_info": {}}},
                upsert=False,
            )

    # 步骤1：初始化source层结构，存在不操作，不存在则初始化成{}
    global_db_vars["jsz_collection"].update_one(
        {
            "经号": jinghao,
            "卷号": juanhao,
            f"source_match_info.{source}": {"$exists": False},
        },
        {"$set": {f"source_match_info.{source}": {}}},
        upsert=False,
    )

    # 步骤2：初始化reel_type层结构
    global_db_vars["jsz_collection"].update_one(
        {
            "经号": jinghao,
            "卷号": juanhao,
            f"source_match_info.{source}.{reel_type}": {"$exists": False},
        },
        {"$set": {f"source_match_info.{source}.{reel_type}": {}}},
        upsert=False,
    )

    logging.info(f"层级结构初始化成功：{source} → {reel_type}")

    # 步骤3：更新具体字段（此时路径结构已确保存在）
    global_db_vars["jsz_collection"].update_one(
        {"经号": jinghao, "卷号": juanhao},
        {
            "$set": {
                f"source_match_info.{source}.{reel_type}.match_info": match_info,
                f"source_match_info.{source}.{reel_type}.match_info2": match_info2,
                f"source_match_info.{source}.{reel_type}.cmp_text2": cmp_text2,
            }
        },
        upsert=False,
    )


def get_match_info(
    source, sutra_uid, jinghao, juanhao, origin_text, reel_nos, source_text=""
):
    """
    计算两个文本的匹配信息
    """
    logging.info(
        f"get_match_info start,sutra_uid:{sutra_uid},jinghao:{jinghao},juanhao:{juanhao},reel_nos:{reel_nos}"
    )

    # diff算法匹配率
    return punc_rate_stat_by_segment(origin_text, source_text, jinghao, juanhao)


async def cached_big_model_punc(
    big_model_name: str, text: str, jsz_juanhao: str
) -> dict:
    """
    带缓存的标点处理函数
    返回格式：{'code': 0, 'msg': '', 'data': '标点结果'}

    注意：
    1. 调用完这个函数后，必须再调用迁移函数，否则打标后行数可能会不一致
    2. 大模型打标的换行符\n要替代成¶
    """

    md5_key = get_md5_key(text)
    logging.info(f"开始处理标点，文本长度: {len(text)}，jsz_juanhao:{jsz_juanhao}")
    result = {"code": 0, "msg": "", "data": text}

    try:

        # if jsz_juanhao == 'JS_2077_3':
        #     raise ValueError("JS_2077_3人工认为打标失败，jsz_juanhao:{jsz_juanhao}")
        # 查询缓存,这里不用大模型参数，有些是doubao打的，默认是qwen调用
        cached = global_db_vars["big_model_punc_details_collection"].find_one(
            {"md5_key": md5_key, "status": "Y"}, projection={"punc_text": 1}
        )

        if cached:
            result["data"] = cached["punc_text"].replace("\n", "¶").replace(" ", "")
            logging.info(f"标点缓存命中，文本长度: {len(text)}")
            return result

        logging.info(f"标点缓存未命中，开始调用大模型: jsz_juanhao:{jsz_juanhao}")
        # 判断卷是否打标异常
        jsz_wrap_roll = get_jsz_wrap_roll(jsz_juanhao)
        # 兼容代码：如果是老的，则换新模型打
        if jsz_wrap_roll and jsz_wrap_roll["打标是否异常"] == "Y":
            logging.error(
                f"卷打标异常，jsz_juanhao:{jsz_juanhao},改用其他大模型：{SECOND_BIG_MODEL_NAME}"
            )
            big_model_name = SECOND_BIG_MODEL_NAME

        # 无缓存时调用原始方法
        punc_result = await async_big_model_punc(big_model_name, text, jsz_juanhao)
        if not isinstance(punc_result, dict):  # 确保返回的是字典
            logging.error(
                f"标点API返回无效格式: {type(punc_result)}，punc_result:{punc_result},jsz_juanhao:{jsz_juanhao}"
            )
            raise ValueError("标点API返回无效格式，jsz_juanhao:{jsz_juanhao}")
        if punc_result["code"] != 0:
            msgs = punc_result.get("msg", "")
            # 敏感词
            if "data_inspection_failed" in msgs:
                update_jsz_wrap_roll_punc_status(jsz_juanhao, msgs)
                # 尝试用新模型打标
                logging.error(
                    f"标点API打标失败，jsz_juanhao:{jsz_juanhao},改用其他大模型：{SECOND_BIG_MODEL_NAME}"
                )
                big_model_name = SECOND_BIG_MODEL_NAME
                punc_result = await async_big_model_punc(
                    big_model_name, text, jsz_juanhao
                )
                if punc_result["code"] != 0:
                    logging.error(
                        f"第二个大模型标点API打标失败，jsz_juanhao:{jsz_juanhao}"
                    )
                    raise ValueError(
                        "第二个大模型标点API打标失败，jsz_juanhao:{jsz_juanhao}"
                    )
            else:
                logging.error(f"标点API打标失败，jsz_juanhao:{jsz_juanhao}")
                raise ValueError("标点API打标失败，jsz_juanhao:{jsz_juanhao}")

        logging.info(f"标点缓存未命中，标点缓存更新准备插入: jsz_juanhao:{jsz_juanhao}")
        logging.info(
            f"jsz_juanhao:{jsz_juanhao},punc_content:{punc_result.get('data', text)}"
        )

        # 构建存储文档
        doc = {
            "big_model_name": big_model_name,
            "md5_key": md5_key,
            "text": text,
            "punc_text": punc_result.get("data", text),
            "response": punc_result,
            "status": "Y" if punc_result["code"] == 0 else "N",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 更新或插入记录,md5_key+big_model_name唯一
        insert_res = global_db_vars["big_model_punc_details_collection"].update_one(
            {"md5_key": md5_key, "big_model_name": big_model_name},
            {"$set": doc},
            upsert=True,
        )
        logging.info(f"标点缓存更新或插入结果: {insert_res}，jsz_juanhao:{jsz_juanhao}")

        result["data"] = doc["punc_text"].replace("\n", "¶").replace(" ", "")

    except Exception as e:
        logging.error(f"标点API标点缓存处理失败: {str(e)}，jsz_juanhao:{jsz_juanhao}")
        result.update(code=1, msg=str(e), data=text)
        raise

    return result


def get_text_split_blocks(input_text):
    """
    获取文本按照格式标注划分的切割块
    """
    lines = input_text.splitlines()
    line_num = len(lines)
    # logging.info(f'lines:\n{lines}')
    normal_blocks = []
    normal_sort_blocks = []  # 带序列的
    special_blocks = []  # 元素格式为 (起始行索引, 块内容)
    current_block = []
    block_start = None
    current_prefix = None
    current_page = None
    pre_page = None
    special_block_matched_page = None

    # 收集所有特殊块
    for i, line in enumerate(lines):
        new_page = False
        # 记录当前page
        if line.strip().startswith("[") and line.strip().endswith("]"):
            # 上一次的page
            pre_page = current_page
            current_page = line.strip()[1:-1]
            # 第一次赋值用
            pre_page = current_page if pre_page is None else pre_page
            new_page = True

        special_block_matched_page = pre_page if new_page else current_page

        # E代表音释，K代表牌记，其他格式如需新增请判断这里
        if line.startswith(("EE", "KK")):
            prefix = line[:2]
            if block_start is None:  # 开始新块
                block_start = i
                current_prefix = prefix
                current_block = [line]
            elif prefix == current_prefix:  # 继续当前块
                current_block.append(line)
            else:  # 不同前缀，结束当前块，开始新块
                special_blocks.append(
                    (
                        block_start,
                        current_block,
                        current_prefix,
                        special_block_matched_page,
                    )
                )
                block_start = i
                current_prefix = prefix
                current_block = [line]
        else:
            if current_block:  # 结束当前块
                special_blocks.append(
                    (
                        block_start,
                        current_block,
                        current_prefix,
                        special_block_matched_page,
                    )
                )
                current_block = []
                block_start = None
                current_prefix = None
            # normal_sort_blocks.append((i,line))
            normal_blocks.append(line)

    # 处理最后一个块
    if current_block:
        special_blocks.append(
            (block_start, current_block, current_prefix, special_block_matched_page)
        )

    return (line_num, normal_blocks, special_blocks)


async def merge_text_block(line_num, punc_big_normal_text, special_blocks, jsz_juanhao):
    """
    合并正常文本和特殊格式标注的文本块
    """

    normal_lines = punc_big_normal_text.split("\n")
    # 初始化结果列表
    result = []
    special_index = 0
    normal_index = 0
    i = 0

    # 行数理论上不变，最后都走的diff迁移
    while i < line_num:
        # 检查当前行是否是特殊块起始行
        if (
            special_index < len(special_blocks)
            and i == special_blocks[special_index][0]
        ):
            block = special_blocks[special_index][1]
            prefix = special_blocks[special_index][2]
            page = special_blocks[special_index][3]
            special_text = "\n".join(block)
            special_text = special_text.replace("EE", "").replace("KK", "")
            # 牌记从数据库读取
            if prefix == "KK":
                pre_punc_special_text = get_roll_pubnote_by_page(jsz_juanhao, page)
            # 音释从大模型读取
            else:
                logging.info(
                    f"特殊块,大模型打标，jsz_juanhao:{jsz_juanhao}.special_text:\n{special_text}"
                )
                punc_res = await cached_big_model_punc(
                    BIG_MODEL_NAME, special_text, jsz_juanhao
                )
                pre_punc_special_text = punc_res.get("data", special_text)

            # 特殊块，最后统一用diff迁移
            punc_special_text, _ = transfer_punc_for_stats(
                special_text, pre_punc_special_text, IS_BASE_TEXT
            )
            # logging.info(f'特殊块special_text:\n{special_text}')
            # logging.info(f'特殊块punc_special_text:\n{punc_special_text}')
            result.append(punc_special_text)

            special_index += 1
            i += len(block)  # 跳过整个块
        else:
            # 填充普通行内容
            if normal_index < len(normal_lines):
                result.append(normal_lines[normal_index])
                normal_index += 1
            i += 1
    # logging.info(f'result:\n{result}')

    result = "\n".join(result)
    return result + "\n"


async def process_punc_text(
    input_text,
    jsz_jinghao,
    jsz_juanhao,
    jsz_sort_no,
    is_one_2_multy,
    one_2_multy_params,
    is_need_punc,
):
    """
    算法描述：
    文本按照不同的格式标注，做不同的处理，cbeta有的直接迁移，没有的调用标点接口
    EE和KK是特殊块，所有相邻的EE和KK块分别会一起打包成段（去掉前缀EE和KK）,音释调用大模型，牌记调用数据库
    调用完后会统一用diff() 做迁移，保证原格式不变
    所有的正常行会打包成段调用diff()函数，调用后行数不变
    最后输出的内容，要求顺序跟原先保持一致。
    """
    logging.info(f"process_punc_text start")
    # 获取切块
    line_num, normal_blocks, special_blocks = get_text_split_blocks(input_text)
    # logging.info(f'line_num:{line_num},\n normal_blocks:{normal_blocks},\n normal_sort_blocks:{normal_sort_blocks}, \n special_blocks:{special_blocks}')

    # 普通文本打标点
    big_normal_text = "\n".join(normal_blocks)
    # 拿普通文本去匹配（去除了音释、牌记等干扰）
    matchs = multy_search_find_best_match(
        jsz_jinghao,
        jsz_juanhao,
        jsz_sort_no,
        is_one_2_multy,
        one_2_multy_params,
        big_normal_text,
    )
    logging.info(
        f"process_punc_text,jsz_jinghao:{jsz_jinghao},jsz_juanhao:{jsz_juanhao}"
    )
    for key, match in matchs.items():
        logging.info(f'key:{key},match:{match["type"]}')
        jsz_new_content = match["jsz_new_content"]
        match_info = match["match_info"]
        match_info2 = match["match_info2"]
        match_rate = match_info2.get("match_rate", 0) if match_info2 else 0

        cmp_text2 = match["cmp_text2"]
        source = match["source"]
        type = match["type"]
        is_best_match = match["is_best_match"]

        cmp_file_path = f"output/best_match"
        cmp_file_name = f"{jsz_jinghao}_{jsz_juanhao}_{source}_{type}.txt"

        cmp_txt_file_path = generate_file_content(
            cmp_file_path, cmp_file_name, cmp_text2
        )

        logging.info(
            f"source:{source},type:{type},match_info:{match_info},match_info2:{match_info2},cmp_text2:{cmp_text2},cmp_txt_file_path:{cmp_txt_file_path}"
        )
        has_big_model_punc = "N"
        has_modern_bd = "Y"
        # 如果不用打标点，则普通块直接赋值
        if is_need_punc == "N":
            logging.info(f"jsz_jinghao:{jsz_jinghao} 普通块不用打标点，直接赋值")
            punc_big_normal_text = big_normal_text
            match_info2 = {}
        else:
            # 判断cmp_text是否有现代标点
            has_modern_bd, bd_ratio = stat_bd_details_byfile(cmp_txt_file_path)
            logging.info(
                f"starthas_modern_bd_check: jsz_jinghao:{jsz_jinghao} has_modern_bd:{has_modern_bd},bd_ratio:{bd_ratio}，match_rate:{match_rate}"
            )
            # 如果没有现代标点，那么cmp_text改用大模型打标
            # 如果匹配率高，则直接用迁移,设置长度限制，防止超大文件打标
            if (
                has_modern_bd == "N"
                and match_rate < 0.5
                and len(big_normal_text) < 50000
            ):
                logging.info(
                    f"jsz_jinghao:{jsz_jinghao} 没有现代标点，jsz_juanhao:{jsz_juanhao},改用大模型打标--开始,原长度:{len(big_normal_text)}"
                )
                punc_res = await cached_big_model_punc(
                    BIG_MODEL_NAME, big_normal_text, jsz_juanhao
                )
                cmp_text = punc_res.get("data", big_normal_text)
                logging.info(
                    f"jsz_jinghao:{jsz_jinghao} 没有现代标点，jsz_juanhao:{jsz_juanhao},改用大模型打标--完成,原长度:{len(big_normal_text)},打标后长度:{len(cmp_text)}"
                )
                logging.info(f"重新打标后的cmp_text:\n{cmp_text}")
                punc_big_normal_text, match_info, match_info2, cmp_text2 = (
                    punc_rate_stat_by_segment(
                        big_normal_text, cmp_text, jsz_jinghao, jsz_juanhao
                    )
                )
            # 有现代标点的，直接从match结果赋值
            else:
                logging.info(
                    f"jsz_jinghao:{jsz_jinghao} 有现代标点，jsz_juanhao:{jsz_juanhao},直接从match结果赋值--开始,原长度:{len(big_normal_text)}"
                )
                punc_big_normal_text = jsz_new_content

        # logging.info(f'big_normal_text before:\n{big_normal_text}')
        # logging.info(f'last_punc_big_normal_text after:\n{punc_big_normal_text}')

        # 合并后的标点文本
        merged_punc_text = await merge_text_block(
            line_num, punc_big_normal_text, special_blocks, jsz_juanhao
        )
        # 1. 没有现代标点 2. 有现代标点，但是普通文本存在大模型打标
        has_big_model_punc = "Y" if has_modern_bd == "N" else has_big_model_punc

        generate_file_content(
            f"output/jsz_warp/punc_full/{jsz_jinghao}",
            f"{source}_{jsz_juanhao}.txt",
            merged_punc_text,
        )

        generate_file_content(
            f"output/jsz_warp/origin/{jsz_jinghao}",
            f"{source}_{jsz_juanhao}.txt",
            input_text,
        )

        # 最后，将处理后的内容更新到 jsz_wrap_rolls 集合的标点内容字段
        update_punctuated_content(
            jsz_jinghao,
            jsz_juanhao,
            merged_punc_text,
            match_info2,
            has_modern_bd,
            has_big_model_punc,
            is_best_match,
            source,
        )


async def deal_one_mapping(
    jsz_jinghao, is_one_2_multy, one_2_multy_params, is_need_punc
):
    try:

        logging.info(
            f"\n\n deal_one_mapping_start,jsz_jinghao:{jsz_jinghao},is_one_2_multy:{is_one_2_multy},one_2_multy_params:{one_2_multy_params}"
        )

        # 从 jsz_wrap_rolls 集合中根据 jsz 经号获取(卷号, 内容)列表
        jsz_contents = get_jsz_sorted_contents(jsz_jinghao)
        if len(jsz_contents) == 0:
            logging.error(
                f"deal_one_mapping_ept，jsz_jinghao:{jsz_jinghao} 未找到没执行的卷"
            )
            # 更新映射表任务
            update_jsz_source_mappings_status(jsz_jinghao, "Y")
            return
        logging.info(f"jsz_jinghao:{jsz_jinghao},jsz_contents_len:{len(jsz_contents)}")

        # 将 jsz 这边的内容按照卷号排序拼接起来成 1 个大的内容
        jsz_big_txt = merge_contents(jsz_contents)
        logging.info(f"jsz_big_txt 处理完成")

        generate_file_content(
            f"output/jsz_warp/origin", f"{jsz_jinghao}.txt", jsz_big_txt
        )
        has_ept = False

        # 循环处理每个 jsz_content
        for jsz_juanhao, jsz_content, jsz_sort_no in jsz_contents:
            try:
                logging.info(f"卷号 {jsz_juanhao} 开始处理")

                # 临时特殊处理，针对卷
                # if jsz_juanhao not in ['JS_1182_015']:
                #     logging.info(f'卷号:{jsz_juanhao} 不处理')
                #     continue

                # 标点处理
                await process_punc_text(
                    jsz_content,
                    jsz_jinghao,
                    jsz_juanhao,
                    jsz_sort_no,
                    is_one_2_multy,
                    one_2_multy_params,
                    is_need_punc,
                )

                logging.info(f"卷号 {jsz_juanhao} 标点内容更新完成")

                # 只处理一个卷
                # break

            except Exception as e:
                has_ept = True
                logging.error(
                    f"deal_one_mapping_loop error: {str(e)},jsz_jinghao:{jsz_jinghao}，ept:{traceback.format_exc()}"
                )

        # 更新经级别的状态
        if not has_ept:
            update_jsz_source_mappings_status(jsz_jinghao, "Y")

        logging.info(f"全部文本处理完毕,jsz_jinghao:{jsz_jinghao}")

    except Exception as e:
        logging.error(
            f"deal_one_mapping error: {str(e)},jsz_jinghao:{jsz_jinghao},ept:{traceback.format_exc()}"
        )


# 将 big_model_punc 改为协程版本
async def async_big_model_punc(model_name, text, jsz_juanhao):
    return await big_model_punc(model_name, text, jsz_juanhao)


async def process_chunk(chunk, chunk_index):
    """处理任务分块"""
    index = 1
    total_num = len(chunk)
    for mapping in chunk:
        try:
            jsz_jinghao, juan_num, is_one_2_multy, one_2_multy_params, is_need_punc = (
                mapping
            )
            logging.info(
                f"process_chunk，current_pid:{os.getpid()},chunk_index:{chunk_index},process:{index}/{total_num},juan_num:{juan_num},jsz_jinghao:{jsz_jinghao},is_one_2_multy:{is_one_2_multy},one_2_multy_params:{one_2_multy_params},is_need_punc:{is_need_punc}"
            )
            index += 1

            await deal_one_mapping(
                jsz_jinghao, is_one_2_multy, one_2_multy_params, is_need_punc
            )
        except Exception as e:
            logging.error(f"任务处理失败: {str(e)},ept:{traceback.format_exc()}")


def process_chunk_wrapper(chunk, chunk_index):
    """子进程内创建独立事件循环"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(process_chunk(chunk, chunk_index))


async def main_async(pool, max_cpu_num):
    try:
        logging.info(f"main_async start")
        current_pid = os.getpid()
        process_name = current_process().name
        logging.info(f"当前进程ID: {current_pid} | 进程名称: {process_name}")

        all_tasks = list(get_jsz_source_mappings())  # 将生成器转为列表
        total_num = len(all_tasks)
        logging.info(f"总任务数:{total_num}")

        # 将任务分割成块，打乱数组顺序
        np.random.shuffle(all_tasks)
        task_chunks = np.array_split(all_tasks, max_cpu_num)

        logging.info(f"分割后的任务task_chunks:{len(task_chunks)}")

        # 使用starmap_async执行并行任务
        results = pool.starmap_async(
            process_chunk_wrapper,
            [(chunk, i + 1) for i, chunk in enumerate(task_chunks)],
        )
        logging.info(f"并行后任务results:{results}")
        # 获取并处理结果
        completed_tasks = []
        chunk_results = results.get()  # 这一步get才会执行
        for chunk_result in chunk_results:
            if chunk_result:  # 过滤空结果
                completed_tasks.extend(chunk_result)
        logging.info(f"并行后结果completed_tasks:{completed_tasks}")

    except Exception as e:
        logging.error(f"任务拆分失败: {str(e)},ept:{traceback.format_exc()}")
    finally:
        # 确保资源释放
        if "rushi_dev_client" in globals():
            rushi_dev_client.close()
        if "check_online_read_client" in globals():
            check_online_read_client.close()
        if "test_client" in globals():
            test_client.close()
        # 关闭线程池
        if "pool" in globals():
            pool.close()
            pool.join()


def main():
    """主函数"""
    # 初始化多进程池
    max_cpu_num = cpu_count() - 2
    max_cpu_num = 15
    logging.info(f"max_cpu_num:{max_cpu_num}")
    try:
        init_pool()
        # 每个子进程只处理一个任务后重启
        with Pool(
            processes=max_cpu_num, initializer=init_pool, maxtasksperchild=1
        ) as pool:
            logging.info(f"进程池 pool:{pool}")
            asyncio.run(main_async(pool, max_cpu_num))

    except Exception as e:
        logging.error(f"主程序异常: {str(e)},ept:{traceback.format_exc()}")
    finally:
        logging.info("资源清理完成")
        pool.close()
        pool.join()


if __name__ == "__main__":
    logging.info("\n\n main start")
    main()
    logging.info("main end \n\n")
