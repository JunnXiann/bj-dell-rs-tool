import os
import re
import sys
import logging
import pandas as pd

root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.append(root_dir)

import helper as hp

db_work = hp.get_db("tw-work")


def import_txt(source=None, folder_path=None):
    hp.set_logging("reel_bd_import_txt")
    """遍历文件夹及其子文件夹，导入所有符合条件的 txt 文件到 reel_bd"""
    update_cnt = 0
    insert_cnt = 0
    for root, dirs, files in os.walk(folder_path):
        for filename in files:
            if filename.endswith(".txt") and "_" in filename:
                file_path = os.path.join(root, filename)
                # 获取不带后缀的文件名
                reel_uid = os.path.splitext(filename)[0]
                # 分割文件名
                parts = reel_uid.split("_")
                if len(parts) != 2:
                    continue
                reel_no = parts[1]
                # 判断是否是数字
                res = is_integer(reel_no)
                if not res:
                    continue
                sutra_uid = parts[0]
                reel_no = int(reel_no)
                with open(file_path, "r", encoding="utf-8") as file:
                    txt = file.read()
                    reel_bd = {
                        "rs_sutra_uid": None,
                        "sutra_uid": sutra_uid,
                        "reel_uid": reel_uid,
                        "reel_no": reel_no,
                        "txt": txt,
                        "source": source,
                    }
                    reel_bd0 = db_work.reel_bd.find_one(
                        {'sutra_uid': sutra_uid, 'reel_uid': reel_uid, 'source': source})
                    if reel_bd0:
                        update_cnt += 1
                        r = db_work.reel_bd.update_one({'_id': reel_bd0['_id']}, {'$set': {'txt': txt}})
                        logging.info("\t%s\t%s\t%s" % (sutra_uid, reel_uid, r.matched_count))
                    else:
                        insert_cnt += 1
                        r = db_work.reel_bd.insert_one(reel_bd)
                        logging.info("\t%s\t%s\t%s" % (sutra_uid, reel_uid, r.inserted_id))

    print('update_cnt\t%s' % update_cnt)
    print('insert_cnt\t%s' % insert_cnt)


def update_sutra_name():
    """更新reel_bd表的经名和作译者"""
    hp.set_logging("update_sutra_name")
    data = pd.read_excel(r"D:\bd/径山藏对应CBETA经号及标点-20250310.xlsx")

    reel_dict = {}
    sutra_dict = {}
    for index, row in data.iterrows():
        sutra_uid = row["CBETA经号"]
        sutra_name = row["CBETA经名"]
        author = row["作译者"]

        if pd.isna(sutra_name):
            sutra_name = None
        if pd.isna(author):
            author = None

        if sutra_uid == "-":
            continue
        # 构造字典（如果 author 是 None，则不包含该字段）
        entry = {"sutra_name": sutra_name}
        if author is not None:
            entry["author"] = author

        if "_" in sutra_uid:
            # 处理 T0220_001-100 这类的经编码
            # 拆分字符串，获取前缀和范围
            prefix, num_range = sutra_uid.split("_")
            start, end = map(int, num_range.split("-"))

            # 生成列表，保持3位数字补零
            reel_uids = [f"{prefix}_{i:03}" for i in range(start, end + 1)]
            for reel_uid in reel_uids:
                reel_dict[reel_uid] = entry
        else:
            sutra_dict[sutra_uid] = entry

    # 更新经名和作译者
    for reel_uid, v in reel_dict.items():
        r = db_work.reel_bd.update_many(
            {"reel_uid": reel_uid, "source": "cbeta"}, {"$set": v}
        )
        logging.info("\t%s\t%s" % (reel_uid, r.matched_count))

    for sutra_uid, v in sutra_dict.items():
        r = db_work.reel_bd.update_many(
            {"sutra_uid": sutra_uid, "source": "cbeta"}, {"$set": v}
        )
        logging.info("\t%s\t%s" % (sutra_uid, r.matched_count))


def is_integer(str):
    return re.match(r"^[-+]?\d+$", str) is not None


def update_sutra_name_by_catelog(source, txt_path):
    """根据catalog.txt更新reel_bd没有经名的数据"""
    # 查询出所有含经目的sutra_uid
    sutra_uids = db_work.reel_bd.distinct(
        "sutra_uid", {"sutra_name": {"$exists": True}, 'source': 'CBETA'}
    )

    with open(txt_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines:
            arr = line.split(",")
            prefix = arr[0].strip()
            sutra_num = arr[4].strip()
            sutra_uid = "%s%s" % (prefix, sutra_num)
            sutra_name = arr[6].strip()
            author = arr[7].strip()
            entry = {"sutra_name": sutra_name}
            if author:
                entry["author"] = author
            # 更新没有经名的数据
            if sutra_uid not in sutra_uids:
                r = db_work.reel_bd.update_many({"sutra_uid": sutra_uid, 'source': source}, {"$set": entry})
                print(sutra_uid, '\t', r.matched_count)


def process():
    # folder_path = r'cbeta更新文本0904\juan'
    # import_txt( 'CBETA',  folder_path) # 插入标点信息到reel_bd
    # update_sutra_name() # 更新reel_bd表的经名和作译者
    # txt_path = r'catalog目标格式.txt'
    # update_sutra_name_by_catelog('CBETA', txt_path)  # 根据catalog.txt更新reel_bd没有经名的数据
    pass


def main(func="process", **kwargs):
    eval(func)(**kwargs)


if __name__ == "__main__":
    import fire

    fire.Fire(main)
