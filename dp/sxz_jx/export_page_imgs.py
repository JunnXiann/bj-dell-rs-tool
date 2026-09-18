# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import shutil
from os import path

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))


def export_imgs():
    print('export_imgs')
    names = [
        "SX_479_10_60",
        "SX_479_10_59",
        "SX_469_1_125",
        "SX_449_10_53",
        "SX_390_9_32",
        "SX_309_1_121",
        "SX_305_8_14",
        "SX_305_8_13",
        "SX_298_7_20",
        "SX_296_4_53",
        "SX_293_6_52",
        "SX_291_4_35",
        "SX_290_7_82",
        "SX_290_7_81",
        "SX_290_5_45",
        "SX_279_6_72",
        "SX_279_6_71",
        "SX_266_7_55",
        "SX_263_6_92",
        "SX_261_4_25",
        "SX_218_12_12",
        "SX_218_4_92",
        "SX_215_8_12",
        "SX_215_8_11",
        "SX_215_7_32",
        "SX_214_6_45",
        "SX_209_7_60",
        "SX_209_7_59",
        "SX_208_10_75",
        "SX_206_7_5",
        "SX_184_2_92",
        "SX_184_2_91",
        "SX_164_6_63",
        "SX_155_2_104",
        "SX_155_2_103",
        "SX_121_8_65",
        "SX_119_6_114",
        "SX_119_5_91",
        "SX_119_4_74",
        "SX_119_4_73",
        "SX_109_3_53",
        "SX_108_3_54",
        "SX_82_4_45",
        "SX_69_6_5"
    ]
    save_path = '/home/tjx/data'
    os.makedirs(save_path, exist_ok=True)
    for name in names:
        img_path = get_page_img_path(name)
        print(img_path)
        shutil.copy(img_path, path.join(save_path, '%s.jpg' % name))


def get_page_img_path(page_name):
    """ 获取页图的路径"""
    inner_path = '/'.join(page_name.split('_')[:-1])
    img_path = path.join("/nas/data/T/big", inner_path, '%s.jpg' % page_name)
    if not path.exists(img_path):
        return False
    return img_path


if __name__ == '__main__':
    export_imgs()
