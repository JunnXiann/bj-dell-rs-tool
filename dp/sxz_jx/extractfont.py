import sys
import os
from typing import List, Dict, Any
import pandas as pd
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
import fire

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import helper as hp

db_aux = hp.get_db('tw-aux')

def extractfont(
    output: str = '国标版重做字体187.xlsx',
    remark_regex: str = '重做字体'
) -> None:
    '''
    Extracts font information from the database, generates an Excel file with images.

    Args:
        output: Output Excel file path.
        remark_regex: Regex for remark field in DB query.
    '''
    cursor = db_aux.gbhan.find({'remark': {'$regex': remark_regex}})
    data: List[Dict[str, Any]] = []
    simsun_paths: List[str] = []
    gb18030_paths: List[str] = []
    standard_paths_list: List[List[str]] = []
    standards_names_list: List[List[str]] = []
    max_standards: int = 0

    for doc in cursor:
        unicode: str = doc.get('unicode')
        gb18030: str = doc.get('gb18030')
        txt: str = doc.get('txt')
        pdf_name: str = doc.get('pdf_name')
        page_num: int = doc.get('page_num')
        standards: List[str] = doc.get('standards', [])
        remark: str = doc.get('remark', '')

        simsun_path = os.path.join('/nas/web-static/tw-aux/fonts/simsun/', f'{unicode}.jpg')
        gb18030_path = os.path.join('/nas/web-static/tw-aux/fonts/gb18030/', f'{unicode}.jpg')
        standard_paths = [
            os.path.join('/nas/web-static/tw-aux/unicode', pdf_name, str(page_num), f'{unicode}_{s}.jpg')
            for s in standards
        ]
        max_standards = max(max_standards, len(standard_paths))

        simsun_paths.append(simsun_path)
        gb18030_paths.append(gb18030_path)
        standard_paths_list.append(standard_paths)
        standards_names_list.append(standards)

        row: Dict[str, Any] = {
            '编码': unicode,
            'txt': txt,
            '中易': 'simsun',
            'GB18030': gb18030 if gb18030 else '',
            '备注': remark,
        }
        data.append(row)
    # Add 标准图 columns
    for i in range(max_standards):
        for row in data:
            row[f'标准{i+1}'] = ''

    df = pd.DataFrame(data)
    excel_path = output
    df.to_excel(excel_path, index=False)

    wb = load_workbook(excel_path)
    ws = wb.active

    for idx, (simsun_path, gb18030_path, std_paths, std_names) in enumerate(
        zip(simsun_paths, gb18030_paths, standard_paths_list, standards_names_list), start=2
    ):
        # Insert simsun image in '中易' (col C)
        if os.path.exists(simsun_path):
            img = XLImage(simsun_path)
            img.width = 80
            img.height = 80
            ws.add_image(img, f'C{idx}')

        # Insert gb18030 image in 'GB18030' (col D)
        if os.path.exists(gb18030_path):
            img = XLImage(gb18030_path)
            img.width = 80
            img.height = 80
            ws.add_image(img, f'D{idx}')

        # Insert standard images in '标准1', '标准2', ... (cols E, F, G, ...)
        for j, std_img_path in enumerate(std_paths):
            col_letter = chr(ord('F') + j)
            if os.path.exists(std_img_path):
                img = XLImage(std_img_path)
                img.width = 80
                img.height = 80
                ws.add_image(img, f'{col_letter}{idx}')
            if j < len(std_names):
                ws[f'{col_letter}{idx}'].value = std_names[j]

    wb.save(excel_path)
    print(f'Excel with images saved to {excel_path}')

if __name__ == '__main__':
    fire.Fire(extractfont)