import sys
import os
import pandas as pd
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import helper as hp

db_aux = hp.get_db('tw-aux')

def extract187():
    cursor = db_aux.gbhan.find({"remark": {"$regex": "重做字体"}})
    data = []
    simsun_paths = []
    gb18030_paths = []
    standard_paths_list = []
    standards_names_list = []
    max_standards = 0

    for doc in cursor:
        unicode = doc.get("unicode")
        gb18030 = doc.get("gb18030")
        txt = doc.get("txt")
        pdf_name = doc.get("pdf_name")
        page_num = doc.get("page_num")
        standards = doc.get("standards", [])
        remark = doc.get("remark", "")

        simsun_path = os.path.join("/nas/web-static/tw-aux/fonts/simsun/", f"{unicode}.jpg")
        gb18030_path = os.path.join("/nas/web-static/tw-aux/fonts/gb18030/", f"{unicode}.jpg")
        standard_paths = [
            os.path.join("/nas/web-static/tw-aux/unicode", pdf_name, str(page_num), f"{unicode}_{s}.jpg")
            for s in standards
        ]
        max_standards = max(max_standards, len(standard_paths))

        simsun_paths.append(simsun_path)
        gb18030_paths.append(gb18030_path)
        standard_paths_list.append(standard_paths)
        standards_names_list.append(standards)

        row = {
            "编码": unicode,
            "txt": txt,
            "中易": "simsun" if os.path.exists(simsun_path) else "-",
            "GB18030": gb18030 if gb18030 else "",
            "备注": remark,
        }
        data.append(row)

    # Add 标准图 columns
    for i in range(max_standards):
        for row in data:
            row[f"标准{i+1}"] = ""

    # Write DataFrame
    df = pd.DataFrame(data)
    excel_path = "国标版重做字体187.xlsx"
    df.to_excel(excel_path, index=False)

    # Insert images using openpyxl
    wb = load_workbook(excel_path)
    ws = wb.active

    for idx, (simsun_path, gb18030_path, std_paths, std_names) in enumerate(zip(simsun_paths, gb18030_paths, standard_paths_list, standards_names_list), start=2):
        # Insert simsun image in "中易" (col C)
        if os.path.exists(simsun_path):
            img = XLImage(simsun_path)
            img.width = 80
            img.height = 80
            ws.add_image(img, f"C{idx}")
        # Insert gb18030 image in "GB18030" (col D)
        if os.path.exists(gb18030_path):
            img = XLImage(gb18030_path)
            img.width = 80
            img.height = 80
            ws.add_image(img, f"D{idx}")
        # Insert standard images in 标准图1, 标准图2, ...
        for j, std_img_path in enumerate(std_paths):
            col_letter = chr(ord('F') + j)  # "标准1" starts at column F
            if os.path.exists(std_img_path):
                img = XLImage(std_img_path)
                img.width = 80
                img.height = 80
                ws.add_image(img, f"{col_letter}{idx}")
            if j < len(std_names):
                ws[f"{col_letter}{idx}"].value = std_names[j]

    wb.save(excel_path)
    print(f"Excel with images saved to {excel_path}")

if __name__ == '__main__':
    extract187()