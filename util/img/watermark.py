import os
import os.path as osp
from PIL import Image, ImageDraw, ImageFont


def create_wartermark_vertical(text='如是我聞', font_size=40, opacity=0.3, show=False):
    image = Image.new("RGBA", (font_size + 1, (font_size + 6) * len(text)))
    draw = ImageDraw.Draw(image)

    y_offset = 0
    fill = (170, 170, 170, int(255 * opacity))
    font = ImageFont.truetype("FZXZTK", font_size)  # 方正小篆体_GBK
    for char in text:
        draw.text((0, y_offset), char, fill=fill, font=font)
        y_offset += font_size + 5

    image.save(osp.join(osp.dirname(osp.abspath(__file__)), 'rushi-v.png'))
    show and image.show()


def create_wartermark_horizontal(text='如是我聞', font_size=40, opacity=0.3, show=False):
    image = Image.new("RGBA", ((font_size + 1) * len(text), font_size + 1))
    draw = ImageDraw.Draw(image)

    fill = (170, 170, 170, int(255 * opacity))
    font = ImageFont.truetype("FZXZTK", font_size)  # 方正小篆体_GBK
    draw.text((0, 0), text, fill=fill, font=font)

    image.save(osp.join(osp.dirname(osp.abspath(__file__)), 'rushi-h.png'))
    show and image.show()


def add_watermark(img_file='', result_file=''):
    """ 调用linux convert命令添加水印（推荐）"""
    mark = osp.join(osp.dirname(osp.abspath(__file__)), 'rushi-v.png')  # 指定水印图片
    script = 'convert %s %s -gravity center -composite %s' % (img_file, mark, result_file)
    os.makedirs(osp.dirname(result_file), exist_ok=True)
    os.system(script)


def add_watermark2(img_file, result_file, show=False):
    """ 调用PIL添加水印"""
    image = Image.open(img_file)
    w1, h1 = image.size
    watermark_path = osp.join(osp.dirname(osp.abspath(__file__)), 'rushi.png')
    watermark_image = Image.open(watermark_path)
    w2, h2 = watermark_image.size

    position = (int((w1 - w2) / 2), int((h1 - h2) / 2))
    image.paste(watermark_image, position, watermark_image)

    image.save(result_file)
    show and image.show()


def main():
    pass


if __name__ == '__main__':
    main()
