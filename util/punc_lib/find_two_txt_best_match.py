import os
from datetime import datetime, timezone
import logging
import sys
from datetime import datetime, timezone, timedelta
import re
import os
import pandas as pd


root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)

from util.punc import transfer_punc_for_stats
from util.punc_lib.best_match_two_txt import BestMatchTwoTxt
import helper as hlp

cur_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
hlp.set_logging("find_best_match_text-" + str(cur_time), False)

PARAGRAGH_NUM = 50  # 段落判断阈值

best_matcher = BestMatchTwoTxt()


# 预处理 source 的文本
def process_source_text(text: str) -> str:
    """
    1. 过滤所有注释行（以#开头，含全角#）
    2. 删除所有空行（包括处理后的空字符串）
    3. 删除所有空格（半角/全角/行首尾）
    4. TODO 替代带圈字
    5. TODO 去掉干扰[p23]类型标题
    6. 非空行用¶连接，无空行分隔
    7. 去掉[JS_123]类似格式
    """

    # 过滤JS_前缀数字格式
    text = re.sub(r"\[JS_\d+(_\d+)?\]", "", text)

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


def save_excel(output_dir, name, segments):
    # 将segments输出到Excel文件
    try:
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)

        # 将segments转换为DataFrame
        segments_df = pd.DataFrame(segments)

        # 保存到Excel文件
        excel_path = f"{output_dir}/{name}.xlsx"
        segments_df.to_excel(excel_path, index=False)
        logging.info(f"segments已保存到Excel文件: {excel_path}")
    except Exception as e:
        logging.error(f"保存segments到Excel失败: {str(e)}")


def cal_diff_rate(input_text, cmp_text):
    logging.info(f"cal_diff_rate start")
    # 文本对齐匹配率
    text1_no_punc, matched_paragraph_no_punc, matched_paragraph, align_match_rate = (
        best_matcher.find_best_match(input_text, cmp_text)
    )
    logging.info(f"find_best_match end,transfer_punc_for_stats start ")

    _, segments = transfer_punc_for_stats(input_text, matched_paragraph, "")
    logging.info(f"transfer_punc_for_stats end ")

    # 过滤出 len_diff 不为 0 的数据
    diff_segments = [
        segment
        for segment in segments
        if (segment["len_diff"] != 0 and segment["is_same"] == False)
    ]

    # 分母数量
    denominator = sum(len(segment["base"]) for segment in segments)

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
        f"不匹配分子:{misnumerator},分母：{denominator},nomal_content_length:{len(input_text)} 不匹配度：{mismatch_rate},匹配度: {match_rate}"
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


def punc_rate_stat_by_segment(input_text, cmp_text, is_two_search):
    """
    1. 按照diff算法计算匹配度
    2. 2次搜索召回后，再计算匹配度
    """

    match_info, matched_cmp_text, segments, diff_segments = cal_diff_rate(
        input_text, cmp_text
    )
    # save_excel("output/test", "full_segments", segments)

    todo_segments = []
    if diff_segments and is_two_search:

        # 对未匹配到的段落做2次查询，防止源数据段落混乱；剩下没匹配到的非段落的小字符串，暂时不做AI标点，防止打混乱，这部分人工处理
        todo_segments = [
            segment for segment in diff_segments if segment["len_diff"] >= PARAGRAGH_NUM
        ]
        if todo_segments:
            for todo_segment in todo_segments:
                base_content = todo_segment["base"]
                logging.info(f"对齐算法2次搜索开始")
                # 二次查找
                (
                    text1_no_punc,
                    matched_paragraph_no_punc,
                    matched_paragraph,
                    match_rate,
                ) = best_matcher.find_best_match(base_content, cmp_text)
                logging.info(
                    f"对齐算法2次搜索segment_content_match_info,match_rate:{match_rate},\n,base_content:{base_content}，\n matched_paragraph:{matched_paragraph}"
                )
                if match_rate > 0.7:

                    todo_segment["base1"], _ = transfer_punc_for_stats(
                        base_content, matched_paragraph, ""
                    )
                    todo_segment["cmp"] = matched_paragraph_no_punc
                    todo_segment["cmp0"] = matched_paragraph
                else:
                    logging.info(
                        f"对齐算法2次搜索，match_rate:{match_rate}，2次没有匹配到，不做打标"
                    )

        # logging.info(f"todo_segments:{todo_segments}")
        # 这里需要把 todo_segments 更新后的base1，赋值给 segments 里对应项的 base1，然后拼接segments的base1作为最后的标点大文本
        for todo_segment in todo_segments:
            for segment in segments:
                if segment["no"] == todo_segment["no"]:
                    segment["base1"] = todo_segment["base1"]
                    segment["cmp"] = todo_segment["cmp"]
                    segment["cmp0"] = todo_segment["cmp0"]
                    # logging.info(f"更新segment:{segment}")
                    break

    # 拼接比对大文本
    cmp_text_new = "".join([segment["cmp0"] for segment in segments])
    # 拼接segments的base1作为最后的标点大文本
    bd_text = "".join([segment["base1"] for segment in segments])
    match_info2, matched_cmp_text2, segments2, diff_segments2 = cal_diff_rate(
        input_text, cmp_text_new
    )
    # save_excel("output/test", "full_segments2", segments2)

    return bd_text, cmp_text_new, match_info2


"""
查找对齐文本，无数据库版本
input_text: 原文
cmp_text: 比对文本
is_two_search: 是否2次搜索,限制在cmp_text内搜索，建议开启，匹配率会更高

"""


def find_best_match_text(input_text, cmp_text, is_two_search=True):
    cmp_text = process_source_text(cmp_text)
    # logging.info(
    #     f"find_best_match_text start\n input_text:{input_text}\n cmp_text:{cmp_text}\n is_two_search:{is_two_search}"
    # )

    bd_text, cmp_text_new, match_info = punc_rate_stat_by_segment(
        input_text, cmp_text, is_two_search
    )

    logging.info(
        f"find_best_match_text end\n match_rate:{match_info['match_rate']},cmp_text_new:\n{cmp_text_new}"
    )

    return match_info["match_rate"], cmp_text_new


if __name__ == "__main__":
    logging.info("\n\n main start")
    is_two_search = True

    input_text = best_matcher.read_text_file(
        f"web/tr/punc_trans/test_datas/JS_1118_8_nopunc.txt"
    )
    cmp_text = best_matcher.read_text_file(
        f"web/tr/punc_trans/test_datas/T1435_test.txt"
    )

    result = find_best_match_text(input_text, cmp_text, is_two_search)
    # logging.info(f"result:{result}")
    logging.info("main end \n\n")
