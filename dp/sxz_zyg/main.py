import re
from os import path
from glob2 import glob
from random import randint
import pymupdf as pdf
import numpy as np
import cv2 as cv
import sys
sys.path.insert(0, path.dirname(path.dirname(path.abspath(__file__))))

from base.base_func import scan_pdf_files, get_scan_info, auto_mkdir, no_file
from base.img_func import create_img
from gen_fold_img import extract_embed_images, gen_img, gen_page_img
from export_join_img import merge_joint

rnd = randint(100, 999)
_cache = {'n': 0}


def export_images(db, han, vol_pdf, pdf_file, info):
    """
    导出pdf中的贴图
    :param db: 数据库链接
    :param han: 含号
    :param vol_pdf: 册号
    :param pdf_file: pdf路径
    :param info: {
        pdf_name：不带后缀的pdf名称
        db: 数据库链接
        han: 涵号
        vol_pdf：册号
        pdf_file：pdf名称
        out_path：输出路径
        }
    :return:
    """
    def add_img(fn, t):
        return no_file(fn) and (new_f[t].append(fn) or fn)
    # 根据含号、pdf册号、宽度大于0为条件从数据看查找对应的扣信息：pid页编码 idx扣序号 embed_mean内嵌扣图色值 fold_mean裁切扣图色值 fold_id扣id
    folds = list(db.sx_fold.find(dict(han=han, vol_pdf=vol_pdf, w={'$gt': 0}), dict(
        pid=1, idx=1, embed_mean=1, fold_mean=1, fold_id=1)))
    # todo 需要再次分析
    sub_page = {re.search(r'册第(.+)页\.', f).group(1): f
                for f in glob(pdf_file.replace('册.pdf', '册第*页.pdf'))}
    new_f = [], [], [] # 并分别用来存储嵌入扣图、裁切扣图、其他(生成的白色扣图)
    with pdf.open(pdf_file) as doc:
        # 遍历每页pdf
        for pi in range(doc.page_count):
            info.update(dict(pid=f'{han}_{vol_pdf}_{pi}', pi=pi))
            if sub_page.get(f'{pi + 1}'):
                with pdf.open(sub_page[f'{pi + 1}']) as s_doc:
                    _export_page_images(db, info, s_doc[0], folds, add_img)
            else:
                _export_page_images(db, info, doc[pi], folds, add_img)
    if new_f[0] or new_f[1]:
        _cache['n'] += len(new_f[0]) + len(new_f[1]) + len(new_f[2])
        print(f"{han}/{info['pdf_name']} {len(folds)} folds, {len(new_f[0])} new embed,"
              f" {len(new_f[1])} new crop, {len(new_f[2])} empty")


def _export_page_images(db, info, page, folds, add_img):
    """
    导出扣图
    :param db:
    :param info:
    {
        pdf_name：不带后缀的pdf名称
        db: 数据库链接
        han: 涵号
        vol_pdf：册号
        pdf_file：pdf名称
        out_path：输出路径
        }
    :param page: pdf对应的页
    :param folds: 扣图信息 pid页编码 idx扣序号 embed_mean内嵌扣图色值 fold_mean裁切扣图色值 fold_id扣id
    :param add_img:
    :return:
    """
    folds = [f for f in folds if f['pid'] == info['pid']]
    # 需要抽取的扣图
    f_embed = [f['idx'] for f in folds if f.get('embed_mean')]
    # 需要裁切的扣图
    f_crop = [f['idx'] for f in folds if not f.get('embed_mean') and f.get('fold_mean')]

    # 得到扣图id与文件路径 tmp/SX/涵号_册号/SX_扣号.jpg
    files = {f['idx']: path.join(info['out_path'], 'SX', *f['fold_id'].split('_')[:2],
                                 f"SX_{f['fold_id']}.jpg") for f in folds}
    # 创建扣图目录
    [auto_mkdir(f) for f in files.values()]
    if [1 for i in f_embed if no_file(files[i])]:
        extract_embed_images(page, lambda i: i in f_embed and add_img(files[i], 0))
    if [1 for i in f_crop if no_file(files[i])]:
        # 裁切扣图
        img_file = gen_page_img(info, page)
        img = cv.imread(img_file, cv.IMREAD_COLOR)
        img = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
        h, w = img.shape

        p = db.sx_pdf_page.find_one({'pid': info['pid']}, dict(dim=1, width=1, height=1))
        dim, h0 = p['dim'], p['height']
        sc = h / h0  # dim是在120DPI计算的
        # todo xs tp bt 对应的值不准确造成经文列切破，具体原因见对应注释
        xs, tp, bt, yc, hc = (dim[f] for f in ['xs', 'tp', 'bt', 'yc', 'hc'])
        # 剪切扣图
        gen_img(img, xs, tp, bt, yc, hc, lambda m, i: i in f_crop and add_img(
            files[i], 1) and cv.imwrite(files[i], m, [cv.IMWRITE_JPEG_QUALITY, 100]), sc=sc)
    for idx in list(set(f['idx'] for f in folds) - set(f_embed) - set(f_crop)):
        # 不能裁切和抽取得到的扣图直接添加对应白色扣图
        add_img(files[idx], 2) and cv.imwrite(files[idx], create_img(300, 800))


def merge_joint_images(db, han, vol, info, overwrite):
    """
    加宽扣图(拼接版心列) 没有更新add_w及y到数据库
    :param db: 数据库链接
    :param han: 涵号
    :param vol: 册号
    :param info:
    :param overwrite: boolean 是否重新生成
    :return:
    """
    # 检索出存在add_w属性的记录
    folds = list(db.sx_fold.find(dict(han=han, vol_ok=vol, add_w={'$ne': None}), dict(
        fold_no=1, fold_id=1, w=1, h=1, add_w=1, y=1)))
    img_path = path.join(info['out_path'], f'SX/{han}/{vol}/SX_{han}_{vol}_%s.jpg')
    # file_n代表路径下符合规则的扣图数量
    file_n, count = len(glob(img_path % '*')), 0
    if file_n < len(folds):
        return print(f'{han}/{vol} {file_n} != {len(folds)}')

    # 待加宽扣图备份路径
    joint_bak = path.join(info['out_path'], f'joint_bak/{han}/{vol}')
    for f in folds:
        # 拼接上一扣与下一扣
        t = merge_joint(img_path % f['fold_no'], img_path % (f['fold_no'] - 1),
                        joint_bak, False, overwrite, f['y'])
        if t:
            count += 1
    _cache['n'] += count
    return print(f'{han}/{vol} {count} joint images')


def cmp_images(db, han, vol, info, root):
    for fn1 in sorted(glob(path.join(info['out_path'], f'SX/{han}/{vol}/SX_{han}_{vol}_*.jpg'))):
        fold_id = re.search(r'SX_(.+)\.', fn1).group(1)
        fn2 = path.join(root, f'{han}/{vol}', path.basename(fn1))
        try:
            im1, im2 = cv.imread(fn1, -1), cv.imread(fn2, -1)
            if len(im1.shape) != 2:
                im1 = cv.cvtColor(cv.imread(fn1, cv.IMREAD_COLOR), cv.COLOR_BGR2GRAY)
                cv.imwrite(fn1, im1, [cv.IMWRITE_JPEG_QUALITY, 100])
            if len(im2.shape) != 2:
                im2 = cv.cvtColor(cv.imread(fn2, cv.IMREAD_COLOR), cv.COLOR_BGR2GRAY)
            h1, w1, h2, w2 = im1.shape + im2.shape
            if h1 != h2:
                diff = f'h {h1}!={h2}'
            elif w1 != w2:
                diff = f'w {w1}!={w2}'
            else:
                diff = np.sum(cv.subtract(im1, im2) ** 2) / float(h1 * w1)
                diff = int(diff * 10)

            db.sx_fold.update_one({'fold_id': fold_id, 'w': {'$gt': 0}}, {
                '$set': dict(w=w1, h=h1, diff=diff)})
        except (AttributeError, ValueError) as e:
            print(path.basename(fn1), 'file error', str(e))


def main(src_path='@PDF_ROOT', db_id='sx_pdf', only_han='',
         joint=True, overwrite=False, cmp_ocr=''):
    """根据PDF生成全部扣图
    :param src_path: PDF目录，含有001等函的文件夹
    :param db_id: 数据库名，在app.yml中定义
    :param only_han: Union[int, str], 限定函，可用减号或逗号指定区间，例如 100、-100、100-200,202
    :param joint: 是否生成加宽版心列扣图，先用False生成全部扣图，再用True生成加宽扣图
    :param overwrite: 是否重新生成
    :param cmp_ocr: 上次提交OCR的扣图根目录
    """
    def scanner(pdf_file, han, db):
        """
        扫描函数：可以用来加宽扣图、切割或者导出扣图
        :param pdf_file: pdf路径
        :param han: 涵号
        :param db: 数据库链接
        :return:
        """
        pdf_name, vol_pdf, info = get_scan_info(pdf_file, han, db)
        if cmp_ocr:
            cmp_images(db, han, vol_pdf, info, cmp_ocr)
        elif joint:
            merge_joint_images(db, han, vol_pdf, info, overwrite)
        else:
            export_images(db, han, vol_pdf, pdf_file, info)

    scan_pdf_files(scanner, db_id, src_path, only_han, "")
    print(_cache)


if __name__ == '__main__':
    import fire
    fire.Fire(main)
