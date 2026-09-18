import re
import os
import sys
import csv
import fitz  # PyMuPDF
import logging
import pymupdf as pdf
from PIL import Image, ImageDraw, ImageChops
from os import path as osp

BASE_DIR = osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__))))
sys.path.append(BASE_DIR)

import helper as hp


def gen_sx_page_images_by_fitz(pdf_name='天字第04册', page_idx=0):
    """从PDF中提取页图"""
    root = '/Volumes/v2/00Inbox/SXZ/sample'
    pdf_path = f'{root}/{pdf_name}.pdf'
    page_image_path = osp.join(root, 'page', f'{pdf_name}_page_{page_idx}_by_fitz.jpg')
    if not osp.exists(page_image_path):
        doc = fitz.open(pdf_path)
        page = doc[page_idx]  # 第1页
        pix = page.get_pixmap(dpi=120)
        pix.save(page_image_path, jpg_quality=100)


def gen_sx_page_images_by_convert(pdf_name='天字第04册', page_idx=0):
    """从PDF中提取页图"""
    root = '/Volumes/v2/00Inbox/SXZ/sample'
    pdf_path = f'{root}/{pdf_name}.pdf'
    page_image_path = osp.join(root, 'page', f'{pdf_name}_page_{page_idx}_by_convert.jpg')
    if not osp.exists(page_image_path):
        cmd = 'magick -density 120 -quality 100 "%s[%s]" %s' % (pdf_path, page_idx, page_image_path)
        os.system(cmd)


def draw_sx_fold_lines(pdf_name='天字第04册', page_idx=0):
    """将dim坐标在页图上画线"""
    root = '/Volumes/v2/00Inbox/SXZ/sample'
    page_image_path = os.path.join(root, 'page', f'{pdf_name}_page_{page_idx}_by_fitz.jpg')
    db = hp.get_db('ax-prod')
    page = db.sx_pdf_page.find_one({'pdf_name': pdf_name, 'pi': {page_idx}}, {'dim': 1})
    dim = page['dim']
    xs, tp, bt, yc, hc = dim['xs'], dim['tp'], dim['bt'], dim['yc'], dim['hc']
    img = Image.open(page_image_path)
    draw = ImageDraw.Draw(img)
    for y1, y2 in [(tp, yc - hc), (yc + hc, bt)]:
        for i, x1 in enumerate(xs[:-1]):
            x2 = xs[i + 1]
            draw.line([(x1, y1), (x2, y1)], fill=(255, 0, 0), width=3)
            draw.line([(x2, y1), (x2, y2)], fill=(255, 0, 0), width=3)
            draw.line([(x2, y2), (x1, y2)], fill=(255, 0, 0), width=3)
            draw.line([(x1, y2), (x1, y1)], fill=(255, 0, 0), width=3)
            img.save(osp.join(root, 'page', f'{pdf_name}_page_1_by_fitz_with_line.jpg'))


def gen_sx_fold_cut_images(pdf_name='天字第04册', page_idx=0):
    """以裁切的方式从PDF中提取抠图"""
    root = '/Volumes/v2/00Inbox/SXZ/sample'
    page_image_path = os.path.join(root, 'page', f'{pdf_name}_page_{page_idx}_by_fitz.jpg')
    img = Image.open(page_image_path)

    db = hp.get_db('ax-prod')
    page = db.sx_pdf_page.find_one({'pdf_name': pdf_name, 'pi': page_idx}, {'dim': 1})
    dim = page['dim']
    xs, tp, bt, yc, hc = dim['xs'], dim['tp'], dim['bt'], dim['yc'], dim['hc']
    idx = 0
    for y1, y2 in [(tp, yc - hc), (yc + hc, bt)]:
        for i, x1 in enumerate(xs[:-1]):
            idx += 1
            x2 = xs[i + 1]
            cropped_img = img.crop((x1, y1, x2, y2))
            if y2 > yc:
                cropped_img = cropped_img.rotate(180)
            cropped_img.save(f"{root}/fold/cut_fold_{idx}.jpg")


def extract_sx_fold_embed_images(pdf_name='天字第04册', page_idx=0):
    """以裁切的方式从PDF中提取抠图"""
    root = '/Volumes/v2/00Inbox/SXZ/sample'
    pdf_path = f'{root}/{pdf_name}.pdf'
    doc = fitz.open(pdf_path)
    page = doc[page_idx]  # 第几页
    images = page.get_images(full=True)
    for idx, m in enumerate(images):
        xref, w, h, im_name = m[0], m[2], m[3], m[7]
        bbox = page.get_image_bbox(im_name)
        print(xref, im_name, bbox)
        up = bbox[-1] < int(page.rect.height / 2)
        pix = fitz.Pixmap(doc, xref)
        if up:
            matrix = fitz.Matrix(-1, -1)
            pix = fitz.Pixmap(pix, pix.width, pix.height, matrix)
        # 若是 CMYK 或透明图，转换为 RGB
        if pix.n > 4:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        img_path = f"{root}/fold/{pdf_name}_extract_fold_{idx + 1}.jpg"
        try:
            pix.save(img_path, jpg_quality=100)
        except (pdf.mupdf.FzErrorBase, ValueError):
            img = Image.frombytes('L', (pix.width, pix.height), pix.samples)
            img = ImageChops.invert(img)
            try:
                img.save(img_path, jpg_quality=100)
            except pdf.mupdf.FzErrorBase as e:
                print('error ' + str(e))


def cut_sx_fold_embed_images_by_bbox(pdf_name='天字第04册', page_idx=0):
    """以裁切的方式从PDF中提取抠图"""
    root = '/Volumes/v2/00Inbox/SXZ/sample'
    pdf_path = f'{root}/{pdf_name}.pdf'
    page_image_path = os.path.join(root, 'page', f'{pdf_name}_page_{page_idx}_by_fitz.jpg')
    img = Image.open(page_image_path)
    dpi = 120
    scale = dpi / 72
    doc = fitz.open(pdf_path)
    page = doc[0]  # 第1页
    images = page.get_images(full=True)
    for idx, m in enumerate(images):
        xref, w, h, im_name = m[0], m[2], m[3], m[7]
        bbox = page.get_image_bbox(im_name)
        print(xref, im_name, bbox)
        up = bbox[-1] < int(page.rect.height / 2)
        pixel_bbox = [int(coord * scale) for coord in bbox]
        cropped_img = img.crop(pixel_bbox)
        if not up:
            cropped_img = cropped_img.rotate(180)
        cropped_img.save(f"{root}/fold/{pdf_name}_cut_fold_by_bbox_{idx + 1}.jpg")


def process():
    pdf_name, page_idx = '车字第02册', 2
    # gen_sx_page_images_by_fitz(pdf_name, page_idx)
    # extract_sx_fold_embed_images(pdf_name, page_idx)
    cut_sx_fold_embed_images_by_bbox(pdf_name, page_idx)


def main(func='process', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
