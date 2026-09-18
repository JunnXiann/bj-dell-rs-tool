"""
统计字格式音释、校讹出现位置
"""
from datetime import datetime
import os
import sys

from openpyxl import Workbook

root_dir = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)

import helper as hlp


tw_client = hlp.connect_db_max('tw-product', 'mongodb-', True)
# 选择数据库
tw_db = tw_client["tripitaka-product"]

cond = {"sutra_code": {"$regex": "JS_"}}
reels = list(tw_db.reel.find(cond, {"reel_code": 1, "format": 1}))

wb = Workbook()
ws = wb.active
ws.append(["卷id", "页id", "行id", "校对平台链接"])

seen = set()  # 用于存放已出现的组合

# find_type = "E"
find_type = "C"

for reel in reels:
    reel_code = reel.get('reel_code')
    reel_format = reel.get('format')
    for page_formt in reel_format:
        if not page_formt.get('chars'):
            continue
        
        page_name = page_formt['name']
        for char_fmt in page_formt.get('chars'):
            if char_fmt[0] == find_type:
                col_cid = char_fmt[1]
                url = f'https://work.tripitakas.net/reel/fmt/{reel_code}#{page_name}_{col_cid}'
                entry = (reel_code, page_name, col_cid, url)  # 用元组存放组合
                if entry not in seen:
                    seen.add(entry)
                    ws.append(entry)

now = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
wb.save(f"./字格式{find_type}位置_{now}.xlsx")
