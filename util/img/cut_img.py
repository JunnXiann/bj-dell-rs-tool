import os
import sys
import logging
import os.path as osp
from PIL import Image, ExifTags

sys.path.append(osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__)))))

import helper as hp


def resize_binary(img, width=1024, height=1024):
    w, h = img.size
    if w > width or h > height:
        if w > width:
            w, h = width, int(width * h / w)
        if h > height:
            w, h = int(height * w / h), height
        img = img.resize((w, h), Image.BICUBIC)
    return img


def check_rotate(img):
    """ 检查旋转"""
    for orientation in ExifTags.TAGS.keys():
        if ExifTags.TAGS[orientation] == 'Orientation':
            break

    exif = dict(img._getexif().items())
    if exif[orientation] == 3:
        img = img.rotate(180, expand=True)
    elif exif[orientation] == 6:
        img = img.rotate(270, expand=True)
    elif exif[orientation] == 8:
        img = img.rotate(90, expand=True)
    return img


def cut_img(img_fn, page, dst_dir):
    """ 根据坐标生成字图"""
    os.makedirs(dst_dir, exist_ok=True)
    img = Image.open(img_fn)
    # img = check_rotate(img)
    iw, ih = img.size
    pw, ph = int(page['width']), int(page['height'])
    print(iw, ih, pw, ph)
    if iw != pw or ih != ph:
        img = img.resize((pw, ph), Image.BICUBIC)
        iw, ih = img.size

    for c in page['chars']:
        txt = c.get('txt') or c.get('ocr_txt')
        if c.get('deleted') or not txt:
            continue
        x, w, y, h = int(c['x']), int(c['w']), int(c['y']), int(c['h'])
        try:
            img_c = img.crop((x, y, min(iw, x + w), min(ih, y + h)))
            img_c = resize_binary(img_c, 64, 64)
            img_c.save(osp.join(dst_dir, '%s_%s.jpg' % (c['char_id'], txt)))
        except Exception as e:
            print(e)


def main():
    pass


if __name__ == '__main__':
    main()
