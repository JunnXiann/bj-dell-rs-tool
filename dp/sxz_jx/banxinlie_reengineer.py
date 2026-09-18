import sys
import os
import pandas as pd
import json
import fitz  # PyMuPDF
from PIL import Image
from typing import List, Dict, Any, Optional

import argparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import helper as hp

db_aux = hp.get_db('tw-aux')

def load_banxinlie() -> List[Dict[str, Any]]:
    with open('banxinlie.json', 'r', encoding='utf-8') as f:
        banxinlie_raw = json.load(f)

    banxinlie = []
    for item in banxinlie_raw:
        fold_id, col_id = item.split('@')
        col_num = int(col_id.split('c')[1])
        direction = 'R' if col_num == 1 else 'L'
        banxinlie.append({'oriname': item, 'fold_id': fold_id[3:], 'col_id': col_id, 'direction': direction})

    return banxinlie

def get_bid_by_fold_id(fold_id: str) -> Optional[str]:
    fold = db_aux.sx_fold.find_one({'fold_id': fold_id}, {'bid': 1})
    return fold['bid'] if fold else None

def get_bids(banxinlie: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    fold_ids = [item['fold_id'] for item in banxinlie]
    folds = db_aux.sx_fold.find({'fold_id': {'$in': fold_ids}}, {'fold_id': 1, 'bid': 1})
    fold_id_to_bid = {fold['fold_id']: fold['bid'] for fold in folds}

    for item in banxinlie:
        item['han'], item['vol'], item['pi'], item['idx'] = fold_id_to_bid.get(item['fold_id']).split('_')

    return banxinlie

def crop(
    ori: str,
    pdf_name: str,
    pdf_path: str,
    pi: int,
    idx: int,
    direction: str,
    page_image_path: str
) -> None:
    
    db_page = db_aux.sx_pdf_page.find_one({'pdf_name': pdf_name, 'pi': pi}, {'dim': 1})

    if not db_page or 'dim' not in db_page:
        print(f"No dim info for {pdf_name} page {pi}")
        return
    
    dim = db_page['dim']
    xs, tp, bt, yc, hc = dim['xs'], dim['tp'], dim['bt'], dim['yc'], dim['hc']

    doc = fitz.open(pdf_path)
    page = doc[pi]
    pix = page.get_pixmap(dpi=120)
    img_path = page_image_path + f'/{pdf_name}_page_{pi}_full.jpg'
    os.makedirs(page_image_path, exist_ok=True)
    pix.save(img_path, jpg_quality=100)

    offset = 25  # expand region by 25 pixels
    if idx < len(xs) - 1:
        y1, y2 = tp, yc - hc
        x1, x2 = xs[idx], xs[idx + 1]
        if direction == 'L':
            x1 = max(x1 - offset, 0)
        elif direction == 'R':
            x2 = min(x2 + offset, pix.width)
        rotate = False
    else:
        region_idx = idx - (len(xs) - 1)
        y1, y2 = yc + hc, bt
        x1, x2 = xs[region_idx], xs[region_idx + 1]
        if direction == 'L':
            x2 = min(x2 + offset, pix.width)
        elif direction == 'R':
            x1 = max(x1 - offset, 0)
        rotate = True
    
    img = Image.open(img_path)
    crop_img = img.crop((x1, y1, x2, y2))
    if rotate:
        crop_img = crop_img.rotate(180)

    add_x = (
        (idx == 0 and direction == 'L') or
        (idx == 4 and direction == 'R') or
        (idx == 5 and direction == 'R') or
        (idx == 9 and direction == 'L')
    )
    x_tag = 'X@' if add_x else ''

    cropped_folder = os.path.join(page_image_path, "cropped")
    os.makedirs(cropped_folder, exist_ok=True)
    crop_img.save(os.path.join(
        cropped_folder,
        # f'{pdf_name}_page_{pi}_idx_{idx}_crop.jpg'
        f'{x_tag}{ori}.jpg'
    ))

    print(f"Cropped region saved: {cropped_folder}/{ori}({pdf_name}_page_{pi}_idx_{idx}).jpg")

def get_page(banxinlie: List[Dict[str, Any]], DIR: str, page_image_path: str) -> None:
    for item in banxinlie:
        ori = item['oriname']
        han = item['han']
        vol = item['vol']
        pi = int(item['pi'])
        idx = int(item['idx'])
        d = item['direction']
        han_dir = os.path.join(DIR, han.zfill(3))
        pdf_files = [f for f in os.listdir(han_dir) if f.endswith('.pdf') and f'第{int(vol):02d}册' in f]

        if not pdf_files:
            print(f"No PDF found for HAN: {han}, VOL: {vol}")
            continue

        pdf_name = pdf_files[0].replace('.pdf', '')
        pdf_path = os.path.join(han_dir, pdf_files[0])
        crop(ori, pdf_name, pdf_path, pi, idx, d, page_image_path)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dir', type=str, required=True, help='PDF root directory')
    parser.add_argument('--out', type=str, required=True, help='Output image directory')
    args = parser.parse_args()

    banxinlie = load_banxinlie()
    banxinlie = get_bids(banxinlie)
    get_page(banxinlie, args.dir, args.out)
