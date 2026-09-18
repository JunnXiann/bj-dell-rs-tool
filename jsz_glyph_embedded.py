from pymongo import MongoClient
import helper as hp
import pandas as pd
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.utils import get_column_letter
import os
import xlsxwriter

db = hp.get_db('tw-aux')  # uses mongodb-tw-aux in app.yml
coll = db['glyph_jsz']

BATCH = "M2-1"
OUT_XLSX = f"M2-1.xlsx"
BASE_DES = "/nas/web-static/tw-aux/des_imgs"
BASE_HANYI = "/nas/web-static/tw-aux/hanyi_chars"
BASE_REV1 = "/nas/web-static/tw-aux/review1_imgs"
BASE_REV2 = "/nas/web-static/tw-aux/review2_imgs"
BASE_REV3 = "/nas/web-static/tw-aux/review3_imgs"

def char_image_path(char_name):
    if not char_name:
        return ""
    parts = char_name.split('_')
    if len(parts) >= 2:
        prefix = parts[0]
        rest = parts[1:3]
        return f"{BASE_HANYI}/{prefix}/" + "/".join(rest) + f"/{char_name}.jpg"
    return f"{BASE_HANYI}/{char_name}.jpg"

# query = {"pay_batch": {"$regex": f'^{BATCH}'}}
query = {"review_batch": {"$regex": f'^{BATCH}'}}
proj = {
    "unicode": 1, "std": 1, "txt": 1, "description": 1, "char_name": 1,
    "txt_kind": 1, "review1": 1, "review2": 1, "review3": 1, "review4": 1, "review5": 1, "review6": 1, "review7": 1, "review8": 1, "pass1": 1, "pass2": 1, "pass3": 1,
    "std_cnt": 1, "des_img": 1, "review1_img": 1, "review2_img": 1, "review3_img": 1, "work_batch": 1, "pay_batch": 1, "review_batch": 1, "review_work_batch": 1, "remark": 1, "stage": 1, "review_cnt": 1, "is_manual": 1,
    "review0": 1, "pass4": 1, "review9": 1, "pass5": 1, "review10": 1 
}

# 字体5 (hanyi5)
# 字体6 (hanyi6)
# 通過4 (pass4)
# 綜合意見4 (review9)
# 通過5 (pass5)
# 綜合意見5 (review10)

cursor = coll.find(query, proj).sort([("std_cnt", -1), ("std", 1)])
rows = []
for d in cursor:
    uni = d.get("unicode")
    # only include image paths for these three when corresponding flag == '是'
    des_path = f"{BASE_DES}/{uni}.jpg" if uni and d.get("des_img") == "是" else ""
    rev1_path = f"{BASE_REV1}/{uni}.jpg" if uni and d.get("review1_img") == "是" else ""
    rev2_path = f"{BASE_REV2}/{uni}.jpg" if uni and d.get("review2_img") == "是" else ""
    rev3_path = f"{BASE_REV3}/{uni}.jpg" if uni and d.get("review3_img") == "是" else ""
    rows.append({
        "unicode": uni,
        "正字": d.get("std", ""),
        "字種": d.get("txt", ""),
        "自造字": d.get("is_manual", ""),
        "字體特徵說明": d.get("description", ""),
        "字體特徵說明圖片": des_path,
        "备注": d.get("remark", ""),
        "當前字圖圖片": char_image_path(d.get("char_name", "")),
        "當前字圖編碼": d.get("char_name", ""),
        "Unicode通字（字体效果）": d.get("txt_kind", ""),
        "审1意見": d.get("review1", ""),
        "审2意見": d.get("review2", ""),
        "审3意見": d.get("review3", ""),
        "审4意見": d.get("review4", ""),
        "审5意見": d.get("review5", ""),
        "截圖1": rev1_path,
        "截圖2": rev2_path,
        "截圖3": rev3_path,
        "通過1": d.get("pass1", ""),
        "綜合意見0": d.get("review0", ""),
        "綜合意見1": d.get("review6", ""),
        "通过2": d.get("pass2", ""),
        "综合意见2": d.get("review7", ""),
        "通过3": d.get("pass3", ""),
        "综合意见3": d.get("review8", ""), # 修改为 review8 以符合逻辑推断
        "通过4": d.get("pass4", ""),
        "综合意见4": d.get("review9", ""),
        "通过5": d.get("pass5", ""),
        "综合意见5": d.get("review10", ""),
        "工作批次": d.get("work_batch", ""),
        "交付批次": d.get("pay_batch", ""),
        "验收批次": d.get("review_batch", ""),
        "校次": d.get("review_cnt", ""),
        "验收工作批次": d.get("review_work_batch", ""),
        "工作阶段": d.get("stage", ""),
        "正字数量": d.get("std_cnt", "")
    })

import xlsxwriter
import os

# ... (Keep all your MongoDB extraction logic above exactly the same) ...
# 'rows' is your list of dictionaries

# 1. Initialize the Workbook and Worksheet directly with xlsxwriter
workbook = xlsxwriter.Workbook(OUT_XLSX)
worksheet = workbook.add_worksheet('Sheet1')

IMG_COLS = ["字體特徵說明圖片", "當前字圖圖片", "截圖1", "截圖2", "截圖3"] 

# Get headers from the first row's keys
headers = list(rows[0].keys()) if rows else []

# 2. Write the Header Row
header_format = workbook.add_format({'bold': True, 'bottom': 1})
for col_idx, header in enumerate(headers):
    worksheet.write(0, col_idx, header, header_format)
    # Set a decent column width for image columns
    if header in IMG_COLS:
        worksheet.set_column(col_idx, col_idx, 15)

# 3. Iterate through the rows and write data sequentially
for row_num, row_data in enumerate(rows):
    excel_row = row_num + 1 
    
    for col_idx, col_name in enumerate(headers):
        val = row_data.get(col_name, "")
        
        # If it's an image column, use embed_image
        if col_name in IMG_COLS:
            img_path = val
            if img_path and os.path.exists(img_path):
                # Write the image natively as a Rich Data Type
                worksheet.embed_image(excel_row, col_idx, img_path)
            else:
                # Fallback if image doesn't exist
                worksheet.write(excel_row, col_idx, img_path if img_path else "")
        else:
            # Standard text/number writing
            worksheet.write(excel_row, col_idx, val)

# 4. Set a default row height so the embedded images aren't microscopic
worksheet.set_default_row(60) 

# Close and save the clean XML structure
workbook.close()
print(f"Exported {len(rows)} rows to {OUT_XLSX} using native Rich Data embedded images.")

# jsz_glyph_embedded.py