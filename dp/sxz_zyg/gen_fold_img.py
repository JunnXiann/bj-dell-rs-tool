"""
脚本用途: 从思溪藏PDF提取扣名图片
环境变量:
    PDF_ROOT: 思溪藏PDF路径，第一级子文件夹为函(001~548)，必须设置以便读取页图
    OUT_PATH: 输出目录，将有扣名图片文件夹，必须设置以便输出扣名图片
"""
import re
from os import path
from glob2 import glob
from random import randint
import pymupdf as pdf
import numpy as np
import cv2 as cv
from PIL import Image, ImageChops
from pymongo import UpdateOne

import sys
sys.path.insert(0, path.dirname(path.dirname(path.abspath(__file__))))

from base.base_func import scan_pdf_files, get_scan_info
from base.base_func import get_name_img, auto_mkdir, no_file
from base.calc_dim import calc_dim
from base.img_func import stack_images, resize_image

rnd = randint(100, 999)
_result = {}
_names_bottom = ['官字第01册', '表字第08册', '从字第03册', '子字第02册']


def generate_images(db, pdf_file, han, mode, only_pid=''):
    pdf_name, vol_pdf, info = get_scan_info(pdf_file, han, db)
    if only_pid and f'{han}_{vol_pdf}_' not in only_pid:
        return
    if mode in [4, 5, 6]:  # 存储图片信息
        return _update_images_info(db, info, han, vol_pdf, -1, mode, only_pid)
    sub_page = {re.search(r'册第(.+)页\.', f).group(1): f  # 单页PDF替换相应页
                for f in glob(pdf_file.replace('册.pdf', '册第*页.pdf'))}

    with pdf.open(pdf_file) as doc:
        if mode == 0:
            print(f'{han}/{pdf_name} {doc.page_count} pages')
        for pi in range(doc.page_count):
            info.update(dict(pi=pi, pid=f'{han}_{vol_pdf}_{pi}',
                             end=pi + 1 == doc.page_count))
            if only_pid and only_pid != info['pid']:
                continue
            sub_file = sub_page.get(f'{pi + 1}')
            if sub_file:  # 用更清晰的页面
                with pdf.open(sub_file) as s_doc:
                    _gen_from_pdf_page(info, s_doc[0], mode)
            else:
                _gen_from_pdf_page(info, doc[pi], mode)


def _update_images_info(db, info, han, vol_pdf, pi, mode, only_pid=''):
    folder = {4: 'name', 5: 'embed', 6: 'fold'}[mode]
    mean_f = folder + '_mean'
    items, pi_s = [], '' if pi < 0 else f'_{pi}'

    only_pid = only_pid + '_'
    for fn in glob(path.join(info['out_path'], folder,
                             f'{han}/{vol_pdf}/{han}_{vol_pdf}{pi_s}_*.jpg')):
        bid = path.basename(fn).split('.')[0]
        if re.match(r'^\d+_\d+_\d+_\d+$', bid) and (not only_pid or only_pid in bid):
            im = cv.imread(fn, cv.IMREAD_GRAYSCALE)
            if im is None:
                im = cv.imread(fn, cv.IMREAD_COLOR)
                if im is None:
                    _result['error'] = _result.get('error', 0) + 1
                    continue
                im = cv.cvtColor(im, cv.COLOR_BGR2GRAY)
                cv.imwrite(fn, im, [cv.IMWRITE_JPEG_QUALITY, 100])
            h, w = im.shape
            m = round(np.mean(im) * 100) if im is not None else 1
            d = {mean_f: m}
            if folder == 'embed':
                d.update(dict(embed_w=int(w), embed_h=int(h)))
            items.append((bid, d))

    count, modified = len(items), 0
    while items:
        arr = [UpdateOne({'bid': bid}, {'$set': d}) for bid, d in items[:50]]
        del items[:50]
        modified += db.sx_fold.bulk_write(arr).modified_count

    if count:
        print(f"{han}/{info['pdf_name']}{pi_s} {count} {folder} images, {modified} updated")
        _result['count'] = _result.get('count', 0) + count


def gen_page_img(info, page):
    """
    抽取pdf页图
    :param info:
    :param page:
    :return: pdf页图
    """
    file = path.join(info['out_path'], f"page/{info['han']}/{info['vol_pdf']}/{info['pid']}.jpg")
    if no_file(file) and auto_mkdir(file):
        # cmd = 'convert -density 120 "%s[%s]" %s' % (info['pdf_file'], info['pi'], file)
        # os.system(cmd)
        pix = page.get_pixmap(dpi=120)  # 创建页面内容的光栅图像
        pix.save(file, jpg_quality=100)
    return file


def _gen_from_pdf_page(info, page, mode):
    # 从info字典中提取相关字段
    db, han, vol_pdf, pi, pid, end = [info[f] for f in [
        'db', 'han', 'vol_pdf', 'pi', 'pid', 'end']]

    if mode == 2:  # 导出内嵌扣图
        # 提取页面中的内嵌图像
        nums, whole = _extract_embed_images(page, han, vol_pdf, pi,
                                            path.join(info['out_path'], 'embed'))
        if nums or whole:
            # 更新数据库中的sx_pdf_page记录，设置内嵌图像数量和是否为完整图像
            db.sx_pdf_page.update_one(dict(pid=pid), {'$set': dict(
                embed_n=len(nums), whole_img=whole == 1)})
        # 更新图像信息
        return _update_images_info(db, info, han, vol_pdf, pi, mode + 3)

    # 查询数据库中是否存在该页面的维度信息
    exist_p = db.sx_pdf_page.find_one(dict(pid=pid, dim={'$ne': None}), dict(dim=1))
    if mode == 0 and exist_p:
        # 如果模式为0且已存在维度信息，则直接返回
        return

    # 生成页面图像文件
    img_file = gen_page_img(info, page)
    # 读取图像
    im = cv.imread(img_file, cv.IMREAD_COLOR)
    # 转换为灰度图像
    gray = cv.cvtColor(im, cv.COLOR_BGR2GRAY)
    # 获取图像的高度和宽度
    h, w = gray.shape
    # 计算缩放因子
    sy = h / 6000  # 最初以6000宽高为参考度量

    if mode == 0 or exist_p is None:
        edges = cv.Canny(gray, 50, 200)  # 边缘检测

        # xs: 竖线X, tp: 顶部Y, bt: 底部Y, yc: 中间横线Y, hc: 中间间隔半高
        xs, tp, bt, yc, hc = calc_dim(edges, w, h, sy)
        dim = dict(xs=list(map(int, xs)), tp=int(tp), bt=int(bt),
                   yc=int(yc), hc=int(hc))
        db.sx_pdf_page.update_one(dict(pid=pid), {'$set': dict(
            dim=dim, width=pix.width, height=pix.height)})
        exist_p = {'dim': dim}
    if mode > 0:
        dim, n = exist_p['dim'], 0
        xs, tp, bt, yc, hc = (dim[f] for f in ['xs', 'tp', 'bt', 'yc', 'hc'])
        if mode == 1:  # 生成扣名图片
            bt_name = end and info['pdf_name'] in _names_bottom
            _, n = _gen_name_img(gray, han, vol_pdf, pi, xs, yc, hc, bt, h, sy, bt_name)
            if bt_name and n:
                db.sx_pdf_page.update_one(dict(pid=pid), {'$set': dict(order='底')})

        elif mode == 3:  # 3-裁切扣图
            _, n = _gen_page_img(gray, han, vol_pdf, pi, xs, tp, bt, yc, hc,
                                 path.join(info['out_path'], 'fold'))
        if n:
            _update_images_info(db, info, han, vol_pdf, pi, mode + 3)


def extract_embed_images(page, get_filename, print_save=False):
    """
    抽取扣图
    :param page: pdf页
    :param get_filename: 获取扣图文件名称的函数
    :param print_save:
    :return:
    """
    embed_n, whole_img = 0, 0
    # todo page.get_images()数量大于10是可能会得到错误扣图，比一个bbox里面有多个扣图
    for m in page.get_images():
        # xref为图在pdf中的引用编号 im_name为图名称
        xref, w, h, im_name = m[0], m[2], m[3], m[7]
        if w * 3.5 > h > w * 2 and w > 260:  # 是扣图
            # 根据嵌入扣图名称得到图像左上角和右下角坐标(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
            bbox = page.get_image_bbox(im_name)
            # 左上角纵坐标小于pdf页高的一半，说明在pdf页的上半部分
            up = bbox.y0 < page.rect.height / 2
            # 通过嵌入扣图的横坐标位置得到图的序号(从左到右)
            x = (bbox.x0 + bbox.x1) * 2.5 / page.rect.width
            # 得到扣图在pdf页中的序号，对应文档中的左序
            idx = int(x) + (0 if up else 5)
            f = get_filename(idx)
            if not f:
                # 扣图已经存在
                continue

            # page.parent为pdf pix为pdf中扣图像素映射
            pix, cmyk = pdf.Pixmap(page.parent, xref), ''
            if auto_mkdir(f) and no_file(f):
                try:
                    pix.save(f, jpg_quality=100)
                    _result['fold'] = _result.get('fold', 0) + 1
                    # 扣图缩放
                    resize_image(f, 1000, 1400)
                except (pdf.mupdf.FzErrorBase, ValueError):
                    img = Image.frombytes('L', (pix.width, pix.height), pix.samples)
                    # 将图像中像素翻转
                    img = ImageChops.invert(img)
                    try:
                        img.save(f, jpg_quality=100)
                        resize_image(f, 1000, 1400)
                        # CMYK用户印刷的颜色，青色（Cyan）、品红色（Magenta）、黄色（Yellow）和黑色（Key，通常简写为K）
                        cmyk = 'CMYK'
                        _result[cmyk] = _result.get(cmyk, 0) + 1
                    except pdf.mupdf.FzErrorBase as e:
                        _result['error'] = _result.get('error', 0) + 1
                        cmyk = 'error ' + str(e)
                if print_save:
                    print(path.basename(f), w, h, cmyk)
                embed_n += 1
        elif w > 2000 and abs(w - h) < 500:
            _result['whole_img'] = _result.get('whole_img', 0) + 1
            whole_img += 1
        elif h > w * 4:
            _result['long_img'] = _result.get('long_img', 0) + 1
        else:
            _result['other_img'] = _result.get('other_img', 0) + 1

    return embed_n, whole_img


def _extract_embed_images(page, han, vol_pdf, pi, out_path):
    def get_filename(idx):
        nums.append(idx)
        return path.join(out_path, f'{han}/{vol_pdf}/{han}_{vol_pdf}_{pi}_{idx}.jpg')

    nums = []
    embed_n, whole_img = extract_embed_images(page, get_filename, True)
    nums.sort()
    return nums, whole_img


def _gen_name_img(page_img, han, vol_pdf, pi, xs, yc, hc, bt, h, sy, bt_name):
    sp1, sp2, sp3 = 100 * sy, 4 * sy, 8 * sy
    images, means, new_n = [], [], 0

    for y1, y2 in [(yc - hc - sp2, yc - sp3),
                   (bt + 60 * sy, h) if bt_name else (yc + sp3, yc + hc + sp2)]:
        for i, x1 in enumerate(xs[:-1]):
            x2 = xs[i + 1]
            x1, y1, x2, y2 = map(int, [x1 + sp1, y1, x2 - sp1, y2])
            im = page_img[y1: y2, x1: x2]
            images.append(cv.flip(im, -1) if y2 > yc and not bt_name else im)

    # 按从左到右、先上面五扣再下面五扣的顺序，输出扣名图片，空图除外
    img_file = get_name_img(han, vol_pdf, pi, '%d', False)
    for i, im in enumerate(images):
        m = np.mean(im)
        means.append(round(m * 100))
        if m >= 254.8:
            _result['empty'] = _result.get('empty', 0) + 1
        elif no_file(img_file % i):
            auto_mkdir(img_file)
            cv.imwrite(img_file % i, im)
            new_n += 1

    # 输出此页的扣名合并图片
    img_file = get_name_img(han, vol_pdf, pi, -1, False)
    if no_file(img_file):
        h0 = round(sum(p.shape[0] for p in images) / len(images))  # 平均高度
        images = [m if h0 == m.shape[0] or not m.shape[0] else cv.resize(
            m, None, fx=h0 / m.shape[0], fy=h0 / m.shape[0]) for m in images]
        _images_trim_left_right(images)

        img1 = np.concatenate(images[:5], axis=1)
        img2 = np.concatenate(list(images[5:]), axis=1)
        if img1 is not None or img2 is not None:
            auto_mkdir(img_file)
            cv.imwrite(img_file, stack_images([img1, img2]))

    return means, new_n


def gen_img(gray, xs, tp, bt, yc, hc, save_img, sc=1):
    """
    剪切扣图
    :param gray: pdf页图二进制流
    :param xs: 纵向切割线横坐标列表
    :param tp: 上部切割线纵坐标
    :param bt: 下部切割线纵坐标
    :param yc: 页图中间分割线
    :param hc: 业务中间分割线到下部切割线长度
    :param save_img:
    :param sc:
    :return:
    """
    idx = -1
    # 中间分割线纵坐标开始位置tp, 纵坐标结束位置yc-hc; 下方扣纵坐标开始位置yc+hc, 纵坐标结束位置bt
    for y1, y2 in [(tp, yc - hc), (yc + hc, bt)]:
        # 遍历第一个到倒数第二个扣中间分割线
        for i, x1 in enumerate(xs[:-1]):
            # 横坐标结束位置x2位后面横坐标
            x2, idx, up = xs[i + 1], idx + 1, y2 < yc
            x1_, y1_, x2_, y2_ = map(int, [x1 * sc, y1 * sc, x2 * sc, y2 * sc])
            im = gray[y1_: y2_, x1_: x2_]
            # 下面的扣图进行翻转
            im = im if up else cv.flip(im, -1)
            # 保存切割好的图片
            save_img(im, idx)


def _gen_page_img(gray, han, vol_pdf, pi, xs, tp, bt, yc, hc, out_path=''):
    def save_img(im, idx):
        m = np.mean(im)
        means.append(round(m * 100))
        if m >= 254.8:
            _result['empty'] = _result.get('empty', 0) + 1
        elif out_path and no_file(img_file % idx):
            auto_mkdir(img_file)
            cv.imwrite(img_file % idx, im, [cv.IMWRITE_JPEG_QUALITY, 100])

    means, new_n = [], 0
    img_file = path.join(out_path, f'{han}/{vol_pdf}/{han}_{vol_pdf}_{pi}_%d.jpg')
    gen_img(gray, xs, tp, bt, yc, hc, save_img)

    return means, new_n


def _images_trim_left_right(images):
    margin_l, margin_r = 0, 0
    for im in images:
        if np.mean(im) < 254.8:
            ret, thresh = cv.threshold(im, 127, 255, cv.INTER_NEAREST)
            coords = np.column_stack(np.where(thresh < 240))
            coords = np.array(coords, dtype=np.float32)
            h1, w1 = im.shape
            y, x, h, w = cv.boundingRect(coords)
            margin_l = max(margin_l, min(w1 // 3, x - 50))
            margin_r = max(margin_r, min(w1 // 3, w1 - (x + w) - 50))
    for i, im in enumerate(images):
        h, w = im.shape
        images[i] = im[0:h, margin_l: w - margin_r]


def main(src_path='@PDF_ROOT', db_name='sx_pdf', mode=0,
         only_name='', only_pid='', only_han=''):
    """脚本主函数
    :param src_path: PDF目录，含有001等函的文件夹
    :param db_name: 数据库名，如果为 rushi-dev 则使用环境变量 DB_URI 的远程数据库
    :param mode: 0-生成PDF页面上的扣裁切度量信息，1-生成扣名图片，2-导出内嵌扣图，3-裁切扣图
                 4-存储扣名图片信息，5-存储内嵌扣图信息，6-存储扣图信息 (1~3会自动存储图信息)
    :param only_name: 仅转换PDF文件名含有指定文本的文件，逗号分隔多个
    :param only_pid: 仅转换指定页面id的文件，一个页面最多10扣
    :param only_han: Union[int, str], 限定函，可用减号或逗号指定区间，例如 100、-100、100-200,202
    """
    if only_pid:  # 'han_vol_pi'
        only_han = int(str(only_pid).split('_')[0])
    scan_pdf_files(lambda file, han, db: generate_images(db, file, han, mode, only_pid),
                   db_name, src_path, only_name, only_han)
    if _result:
        print(_result)


if __name__ == '__main__':
    import fire
    """
    这个py文件优先于main.py文件运行，主要是更新数据库里面扣图信息
    """
    fire.Fire(main)
