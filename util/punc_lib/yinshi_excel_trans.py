from datetime import datetime
import os
import re
import sys
import fire

import openpyxl
from openpyxl import Workbook

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print(f'root_dir:{root_dir}')
sys.path.append(root_dir)

import helper as hlp


USAGE = """
Usage:
    python yinshi_excel_trans.py export_excel [--bd_type=E|C] [--db=product|dev]
    python yinshi_excel_trans.py import_excel <excel_path> [--db=product|dev]

    可选参数解释：
        --db      指定数据库, 默认product数据库
        --bd_type 指定音释(E)或校讹(C), 默认为E

Examples:
    # 导出product数据库的音释
    python yinshi_excel_trans.py export_excel
    # 导出dev数据库的校讹
    python yinshi_excel_trans.py export_excel --bd_type=C --db=dev
    # 导入音释
    python yinshi_excel_trans.py import_excel ./yinshi.xlsx
    # 导入校讹
    python yinshi_excel_trans.py import_excel ./emendation.xlsx
"""


def export_yinshi_excel(reels, now, bd_type='E'):
    """
        导出数据库中的音释到本地excel文件
    """
    type2zh = {'E': "音释", "C": "校讹"}
    type2db_key = {'E': "yinshi", "C": "emendation"}
    wb = Workbook()
    ws = wb.active
    ws.append(["卷id", "页id", "行id", f'{type2zh[bd_type]}文本', "阅藏链接", "导出时间", "校对人", "完成时间"])
    
    for reel in reels:
        reel_code = reel.get("reel_code", "")
        tr_reel_code = hlp.convert_reel_code(reel_code)
        tr_reel_url = f'https://www.rushi-ai.com/scroll/{tr_reel_code}'
        reel_yinshi = hlp.prop(reel, f'bd_pre_data.{type2db_key[bd_type]}') or {}
        for key, yinshi_list in reel_yinshi.items():
            col_cid= key.split('_')[-1]
            page_name = '_'.join(key.split('_')[:3])
            yinshi_txt = yinshi_list[-1]['txt'] if yinshi_list else ''
            ws.append([reel_code, page_name, col_cid, yinshi_txt, tr_reel_url, now])

    wb.save(f"./{type2zh[bd_type]}数据导出_{now}.xlsx")
    print(f'export reel {type2db_key[bd_type]} done')


def import_yinshi_excel(excel_path, db, bd_type):
    """
    从Excel导入校对数据到数据库
    :param excel_path: Excel 文件路径
    :param db: MongoDB 数据库对象
    :param bd_type: 数据类型（'E' 或 'C')
    """
    type2db_key = {"E": "yinshi", "C": "emendation"}

    wb = openpyxl.load_workbook(excel_path)
    sheet = wb.active

    # 标题：卷id、页id、行id、xx文本、阅藏链接、导出时间、校对人、完成时间
    rows = list(sheet.iter_rows(min_row=2, values_only=True))

    count, skip = 0, 0
    for row in rows:
        reel_code, page_id, col_cid, text, link, export_time, proofreader, finish_time = row[:8]
        if not reel_code or not col_cid:
            skip += 1
            continue

        # 没填完成时间的行，用当前时间
        if not finish_time:
            finish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 生成 key，和导出逻辑对应
        key = f"{page_id}_{col_cid}"

        # 跳过未校对的行 若没填写校对人名称，则认为没校对过，需跳过
        if not proofreader or not text:
            print(f"未校对 卷{reel_code} 页{page_id} 行{col_cid}，跳过")
            skip += 1
            continue
        reel = db.reel.find_one({"reel_code": reel_code}, {"bd_pre_data": 1})
        # 跳过被误改卷id的行
        if not reel:
            print(f"[WARN] 未找到卷 {reel_code}，跳过")
            skip += 1
            continue

        # 获取原来的数据
        bd_data = reel.get("bd_pre_data", {}).get(type2db_key[bd_type], {})
        txt_list = bd_data.get(key, [])
        # 跳过被误改页id或行id的行，因为理论上肯定有初始值[{'txt': 'xxx'}]
        if not txt_list:
            print(f"[WARN] 未找到卷{reel_code} 页{page_id} 行{col_cid}，跳过")
            skip += 1
            continue

        new_entry = {
            "txt": text,
            "proofreader": proofreader,
            "finish_time": finish_time
        }       
        txt_list.append(new_entry)
        # 更新回数据库
        db.reel.update_one(
            {"reel_code": reel_code},
            {"$set": {f"bd_pre_data.{type2db_key[bd_type]}.{key}": txt_list}},
        )
        count += 1

    print(f"成功导入 {count} 条，跳过 {skip} 条。")


class YinshiTransTool:
    def __init__(self, db="product"):
        # 连接数据库
        tw_client = hlp.connect_db_max('tw-product', 'mongodb-', True)
        if db == "dev":
            self.tw_db = tw_client["tripitaka-dev"]
        else:
            self.tw_db = tw_client["tripitaka-product"]

    def export_excel(self, bd_type="E"):
        """导出音释数据到Excel"""
        cond = {"sutra_code": {"$regex": "JS_"}}
        reels = self.tw_db.reel.find(cond, {'reel_code': 1, 'bd_pre_data': 1})
        now = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
        export_yinshi_excel(reels, now, bd_type)

    def import_excel(self, excel_path, bd_type):
        """从Excel导入音释数据"""
        excel_path = os.path.join(excel_path)
        import_yinshi_excel(excel_path, self.tw_db, bd_type)
        

if __name__ == '__main__':
    if len(sys.argv) == 1:
        print(USAGE)
        sys.exit(0)
    
    fire.Fire(YinshiTransTool)
