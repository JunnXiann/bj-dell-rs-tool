import os
import re
import sys
import logging
import pandas as pd
from striprtf.striprtf import rtf_to_text
from collections import defaultdict

root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.append(root_dir)

import helper as hp

hp.set_logging("predeal_source_txts", False)
# ali-dev测试开发环境
rushi_dev_client = hp.connect_db_max("alidev", "mongodb-", True)
rushi_dev_db = rushi_dev_client["rushi-dev"]
jsz_cbeta_mapping_collection = rushi_dev_db["jsz_cbeta_mapping_excels"]


# 处理佛光藏的目录结构
def predeal_fgz_catelog():
    target_folder = os.path.join(root_dir, "web/tr/punc_trans/fg_txts/佛光藏20250521")
    keywords = ["註解", "題解", "凡例"]

    # 递归删除包含关键字的txt文件
    for root, dirs, files in os.walk(target_folder, topdown=False):
        logging.info(f"root: {root}, dirs: {dirs}")
        # 删除匹配文件
        for filename in files:
            if filename.endswith(".txt") and any(kw in filename for kw in keywords):
                os.remove(os.path.join(root, filename))
                logging.info(f"Deleted: {os.path.join(root, filename)}")

        # 删除空目录（从最底层开始处理）
        current_dir = root
        # 仅处理目标目录范围内的路径
        while current_dir.startswith(target_folder):
            if os.path.exists(current_dir) and not os.listdir(current_dir):
                try:
                    if current_dir != target_folder:  # 保留根目标目录
                        os.rmdir(current_dir)
                        logging.info(f"Removed empty directory: {current_dir}")
                except OSError:
                    pass
                # 向上检查父目录（但仍在目标目录范围内）
                current_dir = os.path.dirname(current_dir)
            else:
                break

    logging.info(f"end")


# 处理网络来源的目录结构（大毗婆沙论WL0001）
def predeal_wl_catelog_for_wl0001():
    # 定义路径
    source_folder = os.path.join(root_dir, "web/tr/punc_trans/wl_txts/大毗婆沙论WL0001")
    output_folder = os.path.join(root_dir, "web/tr/punc_trans/wl_txts/predeal")
    os.makedirs(output_folder, exist_ok=True)

    # 中文数字映射表（示例需要可以扩展）
    cn_num_map = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
        "百": 100,
        "千": 1000,
        "零": 0,
    }

    def cn_to_arabic(cn_num):
        # 实现中文数字转阿拉伯数字的逻辑
        result = 0
        temp = 0
        for char in cn_num:
            val = cn_num_map[char]
            if val >= 10:
                if temp == 0:
                    temp = 1
                result += temp * val
                temp = 0
            else:
                temp = temp * 10 + val
        return result + temp

    # 匹配文件名格式的正则表达式，允许中文破折号（—）和短横线（-）
    pattern = re.compile(r"(\d+)_(.*?)第([\u4e00-\u9fa5]+)[\u2014\-—]+(.*)")

    # 按中文数字分组存储文件
    file_groups = defaultdict(list)

    # 遍历源文件夹
    for filename in os.listdir(source_folder):
        logging.info(f"filename: {filename}")
        if filename.endswith(".txt"):
            match = pattern.match(filename)
            logging.info(f"match: {match}")
            if match:
                prefix_num = int(match.group(1))
                cn_number = match.group(3)
                arabic_num = cn_to_arabic(cn_number)

                # 转换为3位数字字符串
                formatted_num = f"{arabic_num:03d}"
                file_groups[formatted_num].append((prefix_num, filename))

    logging.info(f"file_groups: {file_groups}")
    # 处理每个分组
    for group_num, files in file_groups.items():
        # 按前缀数字排序
        sorted_files = sorted(files, key=lambda x: x[0])

        # 合并文件内容
        combined_content = []
        for prefix_num, filename in sorted_files:
            filepath = os.path.join(source_folder, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                combined_content.append(f.read())

        # 写入新文件
        output_filename = f"WL0001_{group_num}.txt"
        output_path = os.path.join(output_folder, output_filename)
        logging.info(f"output_path: {output_path}")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(combined_content))

        logging.info(f"Created merged file: {output_path}")


def predeal_multy_mapping():
    # 查询所有需要处理的文档
    cursor = jsz_cbeta_mapping_collection.find(
        {
            "一对多": "Y",
            # "一对多参数": {"$regex": "^all:"}
        }
    )

    # 批量更新处理
    for doc in cursor:
        # 分割参数并构建新格式
        old_param = doc.get("一对多参数", "")
        if old_param.startswith("all:"):
            new_param = {"cbeta": old_param.split("all:")[1].strip()}

            # 更新文档
            jsz_cbeta_mapping_collection.update_one(
                {"_id": doc["_id"]}, {"$set": {"一对多参数": new_param}}
            )
            logging.info(f"Updated document {doc['_id']}")


def remove_circled_numbers(text):
    """移除文本中的带圈数字（Unicode 范围）"""
    # 匹配 ①-⑳ (U+2460-U+2473) 和 ㉑-㉟ (U+3251-U+325F)
    circled_numbers_pattern = re.compile(r"[\u2460-\u2473\u3251-\u325F]")
    return circled_numbers_pattern.sub("", text)


def clean_question_marks(text):
    """处理以 # 开头、?结尾的行，删除 ?"""
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        if line.startswith("#") and line.endswith("?"):
            line = line[:-1]  # 删除最后一个字符（？）
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def predeal_xuezhe_content():
    """处理 RTF 文件并保存为 TXT"""
    input_dir = r"D:\XZ0001"
    output_dir = r"D:\XZ0001_txt"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for filename in os.listdir(input_dir):
        if filename.lower().endswith(".rtf"):
            input_path = os.path.join(input_dir, filename)
            output_filename = os.path.splitext(filename)[0] + ".txt"
            output_path = os.path.join(output_dir, output_filename)

            try:
                # 读取 RTF 文件
                with open(input_path, "r", encoding="utf-8", errors="ignore") as f:
                    rtf_content = f.read()

                # 转换 RTF 为纯文本
                plain_text = rtf_to_text(rtf_content)

                # 移除带圈数字
                cleaned_text = remove_circled_numbers(plain_text)

                # 处理 # 开头、?结尾的行
                final_text = clean_question_marks(cleaned_text)

                # 保存为 TXT
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(final_text)
                print(f"处理成功: {filename} -> {output_filename}")

            except Exception as e:
                print(f"处理失败: {filename} - {str(e)}")


def process():
    # predeal_fgz_catelog()
    # predeal_wl_catelog_for_wl0001()  # 添加新的处理函数调用
    # predeal_xuezhe_content()  # 处理 RTF 文件并保存为 TXT
    predeal_multy_mapping()  # 添加新的处理函数调用
    pass


def main(func="process", **kwargs):
    eval(func)(**kwargs)


if __name__ == "__main__":
    import fire

    fire.Fire(main)
