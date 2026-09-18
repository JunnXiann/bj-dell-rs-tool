import os
import pymongo
import logging
from pymongo import MongoClient
from datetime import datetime, timezone, timedelta
import sys

"""
手动更新标点内容
"""

root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
print(f"root_dir:{root_dir}")
sys.path.append(root_dir)

import helper as hp

cur_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
hp.set_logging("update_punc_content.log", False)


client = hp.connect_db_max("alidev", "mongodb-", True)
# 选择数据库
db = client["rushi-dev"]
# 选择集合
jsz_collection = db["jsz_wrap_rolls"]


def update_punctuated_content_manual():
    logging.info("update_punctuated_content_manual")

    """手动更新标点内容"""
    try:
        # 获取用户输入
        # juanhao = input("请输入要更新的卷号：").strip()
        # content = input("请输入标点文本内容：")
        if not juanhao or not content:
            logging.warning("卷号或标点内容不能为空")
            print("卷号或标点内容不能为空")
            return

        # 构建更新操作
        result = jsz_collection.update_one(
            {"卷号": juanhao},
            {
                "$set": {
                    "标点内容": content,
                    "updated_at": datetime.now(timezone(timedelta(hours=8))).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                }
            },
        )

        if result.modified_count > 0:
            logging.info(f"卷号 {juanhao} 标点内容更新成功")
            print("更新成功！")
        else:
            logging.warning(f"卷号 {juanhao} 未找到匹配文档")
            print("未找到匹配的卷号")

    except Exception as e:
        logging.error(f"手动更新失败: {str(e)}")
        print(f"更新失败: {str(e)}")


if __name__ == "__main__":

    juanhao = "JS_915_1"
    content = """[JS_44_638]
佛說虚空藏菩薩陀羅尼
宋三藏法師法賢奉詔譯
那謨引尾補羅那曩一缽囉二合娑引哩多二那野那
引嚩婆引娑三酥囉僻叉多四誐誐那曼拏羅五拽
寫引阿引哥引舍誐哩婆二合引野六誐誐那悟引左
囉引野七薩哥羅部引嚩拏曼拏羅八嚩舍拽帝𥟖
二合引九唵引莎悉帝二合末邏引叱尾補囉三婆嚩十達
哩摩二合馱引覩悟引左囉引娑嚩二合引賀引十一
佛說虚空藏菩薩陀羅尼
"""

    update_punctuated_content_manual()
