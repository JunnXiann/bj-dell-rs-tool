# -*- coding: utf-8 -*-
"""
@File    : find_similar_fold_content.py
@Time    : 2025/5/27 15:29
@Author  : zhujiantao
@Version : 1.0
@Desc    : 查找扣内容相似度大于90%的扣图信息，结果写入到similar_results.json中
"""
import os
import json
import difflib
from itertools import combinations
from multiprocessing import Pool, cpu_count


def read_txt_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"❌ 无法读取文件 {filepath}: {e}")
        return ""


def find_all_txt_files(root_dir):
    txt_files = []
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".txt"):
                txt_files.append(os.path.join(root, file))
    return txt_files

def compare_file_pair(args):
    file1, file2, threshold = args
    content1 = read_txt_file(file1)
    content2 = read_txt_file(file2)
    if not content1 or not content2:
        return None
    obj = difflib.SequenceMatcher(None, content1, content2)
    similarity = obj.ratio()
    longest_match_obj = obj.find_longest_match()
    a = longest_match_obj.a
    size = longest_match_obj.size
    longest_match_str = content1[a: size +1]
    if similarity >= threshold:
        return (file1, file2, similarity, longest_match_str)
    return None

def find_similar_txt_files_parallel(directory, threshold=0.9, num_workers=None):
    txt_files = find_all_txt_files(directory)
    file_pairs = list(combinations(txt_files, 2))
    args_list = [(f1, f2, threshold) for f1, f2 in file_pairs]

    if num_workers is None:
        num_workers = min(cpu_count(), 8)  # 限制最大并发进程数为 8，避免开太多

    with Pool(num_workers) as pool:
        results = pool.map(compare_file_pair, args_list)

    return [res for res in results if res is not None]


# 示例调用
if __name__ == "__main__":
    similar_fold_list = []
    for volume_id in range(1, 549):
        sx_path = f"../SX/{volume_id}"  # 替换为你的目录路径
        threshold = 0.90
        similar_pairs = find_similar_txt_files_parallel(sx_path, threshold)

        print("以下是内容近似的txt文件对（使用多进程加速）：")
        for f1, f2, sim, longest_match_str in similar_pairs:
            print(f"\n文件1: {f1}\n文件2: {f2}\n相似度: {sim:.4f} 最长对照文本：{longest_match_str}")
            similar_fold_list.append({"最长相同文本": longest_match_str, "文本路径": [f1, f2], "相似度百分比": round(sim*100, 2) })

        with open("similar_results.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(similar_fold_list, ensure_ascii=False))
