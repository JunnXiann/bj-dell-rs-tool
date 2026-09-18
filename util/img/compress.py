import os
import sys
import imghdr
import logging
import subprocess
import os.path as osp
from PIL import Image


def compress_image(img_file='', result_file='', add_watermark=False):
    """ 调用linux convert命令进行图片压缩（推荐）
    :param img_file: 待压缩的图片文件路径
    :param result_file: 压缩结果文件路径
    :param add_watermark: 是否自动在生成的小图上加水印
    """
    if not osp.exists(img_file):
        raise OSError('file %s not exist' % img_file)
    script = 'convert %s -resize 1200x -quality 75' % img_file
    if add_watermark:
        mark = osp.join(osp.dirname(osp.abspath(__file__)), 'rushi-v.png')  # 指定水印图片
        script += ' %s -gravity center -composite' % mark
    result_file = result_file.split('.')[0] + '.jpg'
    os.makedirs(osp.dirname(result_file), exist_ok=True)
    script += ' %s' % result_file
    os.system(script)


def compress_image2(img_file='', result_file='', add_watermark=False, compress_img=False):
    """ 调用PIL进行图片压缩
    :param img_file: 待压缩的图片文件路径
    :param result_file: 压缩结果文件路径
    :param add_watermark: 是否自动在生成的小图上加水印
    :param compress_img: 是否压缩图片
    """
    # 检查图片
    if not osp.exists(img_file):
        raise OSError('file %s not exist' % img_file)
    im = Image.open(img_file)
    if not im:
        raise OSError('fail to open image %s' % img_file)
    if imghdr.what(img_file) != 'jpeg':
        im = im.convert('L')
    # 调整比例
    w2, h2 = w, h = im.size
    img_small = im
    if w > 1200 or h > 1200:
        if w2 > 1200:
            w2, h2 = 1200, int(1200 * h2 / w2)
        if h2 > 1200:
            w2, h2 = int(1200 * w2 / h2), 1200
        img_small = im.resize((w2, h2))
    # 添加水印
    if add_watermark:
        mark = Image.open(osp.join(osp.dirname(osp.abspath(__file__)), 'rushi-v.png'))  # 指定水印图片
        w3, h3 = mark.size
        position = (int((w2 - w3) / 2), int((h2 - h3) / 2))  # 居中
        img_small.paste(mark, position, mark)
    # 保存小图
    os.makedirs(osp.dirname(result_file), exist_ok=True)
    img_small.save(result_file.split('.')[0] + '.jpg')
    # 图片压缩
    if compress_img:
        try:
            s = ['cjpeg', '-optimize', '-progressive', result_file, '>', result_file]
            subprocess.call(s)
        except Exception as e:
            logging.error(str(e))


def main():
    pass


if __name__ == '__main__':
    main()
