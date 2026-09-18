import os
import json
from PIL import Image
import fitz
import sys
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import helper as hp

db_aux = hp.get_db('tw-aux')

with open('/home/tjx/rs-tool/dp/sxz_jx/slanted.json', 'r', encoding='utf-8') as f:
    slanted_data = json.load(f)

def get_degree_from_db(fold_id):
    result = db_aux.sx_fold.find_one({'fold_id': fold_id}, {'degree': 1})
    if result and 'degree' in result:
        return result['degree']
    else:
        return None

def normalize_degree(degree: float) -> float:
    # If degree is near 180 or -180, remove the upside-down part
    if abs(degree) > 170:
        if degree > 0:
            return degree - 180
        else:
            return degree + 180
    return degree

def rotate_image(image_path: str, degree: float, output_path: str) -> None:
    degree = normalize_degree(degree)
    with Image.open(image_path) as img:
        orig_w, orig_h = img.size
        if img.mode == 'L':
            fill = 255
        else:
            fill = (255, 255, 255)
        rotated_img = img.rotate(degree, expand=True, fillcolor=fill)
        rot_w, rot_h = rotated_img.size

        # Crop only top and bottom to match original height, keep full width
        top = (rot_h - orig_h) // 2
        bottom = top + orig_h
        cropped_img = rotated_img.crop((0, top, rot_w, bottom))
        cropped_img.save(output_path)
        
if __name__ == "__main__":
    for fold_id in slanted_data:
        degree = get_degree_from_db(fold_id.strip('SX_'))
        rotate_image(f'/home/tjx/data/{fold_id}.jpg', degree, f'/home/tjx/data/deskewed/{fold_id}.jpg')