import os
import sys

import pandas as pd

root_dir = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)

import helper as hp

def get_cmp_bd_statistic():
    """
    获取比对统计数据
    """
    # punctuations = "。？！，、；："
    source_order = ["网络", "佛光藏", "CBETA", "华鲤"]

    tw_client = hp.connect_db_max('tw-product', 'mongodb-', True)
    # 选择数据库
    tw_db = tw_client["tripitaka-product"]

    cond = {"sutra_code": {"$regex": "JS_"}}
    reels = list(tw_db.reel.find(cond, {"sutra_code": 1, "reel_code": 1,
                                        "sutra_name": 1, "bd_match_data": 1,
                                        "reel_type": 1
                                        }))
    sutra_codes = [reel['sutra_code'] for reel in reels]
    
    cond = {"sutra_code": {"$in": sutra_codes}}
    sutras = list(tw_db.sutra.find(cond, {"sutra_code": 1, "author": 1}))
    sutra_code_to_author = {sutra['sutra_code']: sutra['author'] for sutra in sutras}

    data = []
    for reel_doc in reels:
        author = sutra_code_to_author.get(reel_doc.get("sutra_code"), "")
        col_info = {"经号": reel_doc.get("sutra_code"), "经名": reel_doc.get("sutra_name"), 
                    "卷号": reel_doc.get("reel_code"), "卷类型": reel_doc.get("reel_type"), "作译者": author}
        
        bd_match_data = reel_doc.get("bd_match_data", {})
        if reel_doc.get("bd_match_data", {}):
            for source in source_order:
                if source in bd_match_data:
                    col_info["来源"] = bd_match_data[source].get("source", "")
                    col_info["匹配率"] = bd_match_data[source].get("ratio", "")
                    txt = bd_match_data[source].get("txt", "")
                    col_info["。"] = txt.count("。")
                    col_info["？"] = txt.count("？")
                    col_info["！"] = txt.count("！")
                    col_info["，"] = txt.count("，")
                    col_info["、"] = txt.count("、")
                    col_info["；"] = txt.count("；")
                    col_info["："] = txt.count("：")
                    break

        data.append(col_info)
    df = pd.DataFrame(data)
    df.to_excel("cmp_bd_statistic2.xlsx")


if __name__ == "__main__":
    get_cmp_bd_statistic()
