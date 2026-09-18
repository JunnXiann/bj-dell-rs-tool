import shutil
from os import path, remove
import numpy as np
import cv2 as cv
import sys
sys.path.insert(0, path.dirname(path.dirname(path.abspath(__file__))))

from base.base_func import scan_pdf_files, get_scan_info, auto_mkdir, no_file
from base.img_func import create_img, resize_image


def export_join_img(db, han, vol, info, fold_id, reset, overwrite, force):
    """生成版心列加宽扣图"""
    img_path = path.join(info['out_path'], 'SX', str(han), str(vol), f'SX_{han}_{vol}_%d.jpg')
    joint_bak = path.join(info['out_path'], 'joint_bak', str(han), str(vol))

    c_id = {'fold_id': fold_id} if fold_id else {}
    c_w = {'add_w': None} if not reset and not overwrite else {}
    # 从数据库查找对应含、对应册、宽度不为null的扣记录
    rs = list(db.sx_fold.find(dict(han=han, vol_ok=vol, w={'$ne': None}, **c_id, **c_w), dict(
        fold_id=1, fold_no=1, w=1, h=1, mean=1, add_w=1, y=1), sort=[('fold_no', 1)]))

    for i, r in enumerate(rs):
        t = merge_joint(img_path % r['fold_no'], img_path % (r['fold_no'] - 1),
                        joint_bak, 'reset' if reset else force, fold_id or overwrite, r.get('y'))
        save_merge_info(db, r, t)


def copy_join_img(db, info, org_root=''):
    """导出版心列加宽扣图表、原始扣图"""
    rs = list(db.sx_fold.find(dict(add_w={'$ne': None}),
                              sort=[('han', 1), ('vol_ok', 1), ('fold_no', 1)]))
    ids, n, han, vol = set(), 0, 0, 0
    for i, r in enumerate(rs):
        db.sx_fold_joint.update_one({'fold_id': r['fold_id']}, {'$set': {
            f: r[f] for f in ['han', 'idx', 'pid', 'pdf_name', 'fold_id', 'fold_no', 'vol_ok',
                              'w', 'h', 'add_w', 'y']}}, upsert=True)
        ids.add(r['fold_id'])
        ids.add(f"{r['han']}_{r['vol_ok']}_{r['fold_no'] + 1}")
    for fold_id in list(ids):
        han, vol, no = fold_id.split('_')
        src_file = path.join(info['out_path'], f'SX/{han}/{vol}/SX_{fold_id}.jpg')
        bak_file = path.join(info['out_path'], f'joint_bak/{han}/{vol}/SX_{fold_id}.jpg')
        dst_file = path.join(org_root, f'{han}/{vol}/SX_{fold_id}.jpg')
        if len(org_root) > 1 and no_file(dst_file):
            auto_mkdir(dst_file)
            shutil.copy(bak_file if path.exists(bak_file) else src_file, dst_file)
            n += 1
            if n % 100 == 0:
                print(n, han, vol)
    print(han, vol, n or len(ids))


def update_join_img(db, han, vol, info, fold_id, y=0):
    """更新版心列加宽扣图的上下错位距离"""
    img_path = path.join(info['out_path'], f'SX/{han}/{vol}/SX_{han}_{vol}_%d.jpg')
    joint_bak = path.join(info['out_path'], f'joint_bak/{han}/{vol}')
    rs = list(db.sx_fold.find(dict(add_w={'$ne': None}, han=han, vol_ok=vol,
                                   fold_id=fold_id or {'$ne': None}), dict(
        fold_id=1, fold_no=1, han=1, vol_ok=1, w=1, h=1, mean=1, add_w=1),
                              sort=[('han', 1), ('vol_ok', 1), ('fold_no', 1)]))
    for i, r in enumerate(rs):
        t = merge_joint(img_path % r['fold_no'], img_path % (r['fold_no'] - 1),
                        joint_bak, False, True, y)
        save_merge_info(db, r, t)


def save_merge_info(db, r, t):
    """保存或重置版心列加宽信息"""
    if isinstance(t, tuple):
        y, add_w, add_w0, w, h = t
        print(r['fold_id'], y, add_w, w, h)
        if y == 'reset':
            db.sx_fold.update_one(dict(_id=r['_id']), {
                '$set': dict(w=w, h=h), '$unset': dict(add_w=1, add_w0=1, y=1)})
        else:
            db.sx_fold.update_one(dict(_id=r['_id']), {'$set': dict(
                w=w, h=h, add_w=add_w, add_w0=add_w0, y=y)})


def merge_joint(fn_left, fn_rt, bak_path, force, overwrite=True, y=None):
    """
    :param fn_left 左扣（下扣）原始扣图文件名
    :param fn_rt 右扣（上扣）原始扣图文件名
    :param bak_path 备份目录
    :param force 是否强制输出版心列加宽图，为 reset 则重置版心列
    :param overwrite 是否重新生成版心列加宽图
    :param y 可指定右图下移与左图对齐的Y位移量（相对于原始扣图高度）
    :return None 或 (移动距离、加图宽度、新宽、新高)
    """

    def reset_db_img():
        # 删除加宽后的扣图，将备份左扣图移动到左扣图
        if _reset_img(bak_file, fn_left):
            im_ = cv.imread(fn_left, cv.IMREAD_GRAYSCALE)
            h_, w_ = im_.shape
            return 'reset', 0, 0, w_, h_
    # 扣图备份路径，备份下扣(左扣)
    bak_file = path.join(bak_path, path.basename(fn_left))
    if not overwrite and not no_file(bak_file):
        # 不重新生成版心列加宽图或者备份文件存在，则不执行加宽动作
        return  # exists
    if force == 'reset':
        _reset_img(bak_file, fn_left)
        return
    im1 = cv.imread(bak_file if not no_file(bak_file) else fn_left, cv.IMREAD_GRAYSCALE)
    # todo _0.什么作用
    im2 = cv.imread(fn_rt, cv.IMREAD_GRAYSCALE) if '_0.' not in fn_rt else None
    if im1 is None or im2 is None or np.mean(im1) > 254.9 or np.mean(im2) > 254.9:
        # 不存在左扣或者又扣，或者左扣右扣为纯白色扣图则不加宽
        return
    # 调整右图，让两图高度相同
    h, w, h2, w2 = im1.shape + im2.shape
    # 将右扣调整为与左扣一样高，右扣宽度等比变动
    im2 = im2 if h2 == h else cv.resize(im2, (round(h * w2 / h2), h))
    # 边缘检测，宽缩小到300以免横线抖动或断开过大
    th1, th2, kernel, fx = 20, 200, 5, 300 / w
    im3, im4 = cv.resize(im1, None, fx=fx, fy=fx), cv.resize(im2, None, fx=fx, fy=fx)
    edge_l, edge_r = cv.Canny(im3, th1, th2, kernel), cv.Canny(im4, th1, th2, kernel)
    # 去掉下图右侧、上图左侧的空白
    # im3 im4代表左右扣疑似版心列图二进制流 edge_l, edge_r代表边缘框图二进制流
    im3, im4, edge_l, edge_r, mean1, mean2, sp1, sp2, sp_changed = _remove_space(
        im1, im2, edge_l, edge_r, fx)
    # 检测是否有版心列文本、上下错位
    if y is None:
        # todo 判断版心列及上下错位像素数量有问题
        y = _has_joint(edge_l, edge_r, force)
        if y is None:
            return reset_db_img()  # no
        y = round(y / fx)
        if abs(y) > 20:
            # todo 20个像素内容忽略？
            y = 0
    # 检查左图右侧是否接近空白（连续4列每列≤10像素）
    x1 = x2 = 0
    for x1 in range(10):
        for n in range(4):
            if mean1[x1 + n] > 10:
                break
        else:  # 右侧是否接近空白
            break
    if x1 < 5 or sum(mean1[:3]) < 15:
        return reset_db_img()
    # 检查右图左侧是否接近空白（连续4列每列≤10像素）
    for x2 in range(15):
        for n in range(5):
            if mean2[x2 + n] > 10:
                break
        else:  # 正常字列
            break
    if x2 < 5 or sum(mean2[:3]) < 15:
        return reset_db_img()
    # todo 这里是查找需要拼接的版心列宽度
    # 查找版心列加宽上限，排除正常字列（连续5列每列>100像素）
    for x2 in range(15):
        for n in range(5):
            if mean2[x2 + n] < 100:
                break
        else:  # 正常字列
            break
    if x2 < 5:
        return reset_db_img()
    # 将上图版心列加到下图右边
    x = w2 * x2 // 300
    im5 = im4[:, :x] if y == 0 else im4[-y:, :x] if y < 0 else im4[:-y, :x]
    h3, add_w = im5.shape
    # 下扣加宽
    im = np.concatenate([im3, create_img(add_w, h)], axis=1)
    # 将缺少的版心列贴进来
    if y < 0:
        im[0:h3, -add_w:] = im5
    else:
        im[y:, -add_w:] = im5
    h, w = im.shape
    yc = w2 * 20 // 300
    cv.rectangle(im, (w - add_w, 0), (w, yc), (220, 220, 220), 1)
    cv.line(im, (w - add_w // 2, yc), (w - add_w // 2, yc + y), (180, 180, 180), 1)
    cv.line(im, (w - add_w, h), (w - add_w, h - yc // 2), (220, 220, 220), 1)

    # 备份和更新左图
    add_file = bak_file.replace('_bak', '_add')
    auto_mkdir(add_file)
    auto_mkdir(bak_file)
    if no_file(bak_file):
        if not cv.imwrite(bak_file, im1, [cv.IMWRITE_JPEG_QUALITY, 100]):
            raise OSError(bak_file + ' save fail')
    resize_image(add_file, 324, 800, im)
    if not cv.imwrite(fn_left + '.jpg', im, [cv.IMWRITE_JPEG_QUALITY, 100]):
        raise OSError(fn_left + ' save fail')
    shutil.move(fn_left + '.jpg', fn_left)

    return y, add_w, x2, w, h  # 上下移动距离、加图宽度、x2怎么描述、新宽、新高


def _reset_img(bak_file, fn_left):
    """
    删除加宽后的扣图，将备份扣图替换为左扣图
    :param bak_file: 下扣（左扣）备份文件
    :param fn_left: 下扣（左扣）
    :return: 备份左扣图存在情况下返回true
    """
    try:
        # 删除已加宽的扣图文件
        remove(bak_file.replace('_bak', '_add'))
    except OSError:
        pass
    if not no_file(bak_file):
        # 备份文件存在情况下将左扣替换为备份的扣图
        print('reset', path.basename(fn_left))
        shutil.move(bak_file, fn_left)
        return True


def _has_joint(edge_left, edge_rt, force):
    """对下图右侧、上图左侧的轮廓图，检测有匹配的版心列文本及错位距离
    :param edge_left 左扣（下扣）轮廓图，已缩小到宽300
    :param edge_rt 右扣（上扣）轮廓图，两图等高
    :param force 是否强制输出版心列加宽图
    :return 右图下移与左图对齐的Y位移量（相对于轮廓图高度），None表示没有版心列
    """
    h, w, h2, w2 = edge_rt.shape + edge_left.shape
    assert h == h2
    s, sc = w / 300, 1e3 / w * 300
    c1 = sc * np.mean(edge_rt[:, 0:10]) / h  # 上图左侧10像素的色值
    c2 = sc * np.mean(edge_left[:, -10:-1]) / h  # 下图右侧10像素的色值
    # todo 这个地方判断是否有版心列有问题，例如出现残笔、10列像素内黑色笔画占比太小，也会错过版心列
    if not force and (c1 < 1 or c2 < 1):  # 轮廓太少
        return
    # 如果有长横线，就按线对齐
    yl, yr = _find_hor_y(edge_left, edge_rt, w, h)
    if yl and yr:
        return yl - yr
    # todo 这个地方判断是否有版心列有问题，例如出现残笔、10列像素内黑色笔画占比太大，也会错过版心列
    if not force and (c1 > 50 or c2 > 50):  # 轮廓太多，很可能是正常字列
        return

    # todo 这个地方有问题，如果两个像素凑巧一样，但是本来应该在不同位置，则会出错
    # 比较接缝处最小像素差值的位移量
    diff = 1e7, 0  # 最小像素差值、位移量
    max_dy = 20 * h // 1393
    # ds= [0, 1, -1, 2, -2, 3, -3, 4, -4 ...]
    ds = [0] + sum([[d, -d] for d in range(1, max_dy)], [])  # 位移尝试序列
    ml, mr = edge_left[:, -1], edge_rt[:, 0]  # 左图末列、右图首列
    for y in ds:  # 左图不动，右图下移y (y>0表示右图下移)
        d = np.sum(ml - mr if y == 0 else ml[:y] - mr[-y:] if y < 0 else ml[y:] - mr[:-y])
        if diff[0] > abs(d):
            diff = abs(d), y
    return diff[1]  # Y位移量，>0表示右图下移与左图对齐


def _remove_space(im_left, im_rt, edge_l, edge_r, fx):
    """去掉下图右侧、上图左侧的空白
    :param im_left 左扣（下扣）原始扣图
    :param im_left 右扣（上扣）原始扣图，与左扣图等高
    :param edge_l 左扣（下扣）轮廓图，已缩小到宽300
    :param edge_r 右扣（上扣）轮廓图，两图等高
    :param fx 原始扣图到轮廓图的放缩比例
    """
    h, w = im_left.shape
    # 得到左右扣图上面黑色横线纵坐标
    t1, t2 = _find_hor_in(edge_l, edge_r, round(w * fx), round(h * 0.05 * fx), round(h * 0.2 * fx))
    # 得到左右扣图下面黑色横线纵坐标
    b1, b2 = _find_hor_in(edge_l, edge_r, round(w * fx), round(h * 0.8 * fx), round(h * 0.95 * fx))
    # 分别用来存储大于6行像素的行数
    mean1, mean2 = [], []

    # todo yl=t1 yr=b1 todo 分别代表左扣图上下黑色横向纵坐标 需要再分析
    i1, i1_old, yl, yr = 0, 0, t1 + 1, b1 or round(h * fx)
    for i in range(100):
        # 遍历左扣图右侧100横向像素
        m = np.mean(edge_l[yl:yr, -i - 1])
        if m != 0 and i:
            # 检测到非纯黑色像素列 边缘框图中0位黑色 255为白色 白色代表边缘
            i1_old = i
            break
    for i in range(100):
        m = np.sum(edge_l[yl:yr, -i - 1]) // 255
        if m > 6:  # 倒数第i列超过6行有像素
            i1 = i1 or i + 1
        if i < 20:
            mean1.append(m)
        elif i1:
            break
    i1 = max(0, i1 - 1)
    if i1:
        rm_w1 = round(i1 / fx)
        # 左边包含边缘框的边缘框二进制流edge_l及对应的图二进制流im_left
        im_left, edge_l = im_left[:, :-rm_w1], edge_l[:, :-i1]

    i2, i2_old, yl, yr = 0, 0, t2 + 1, b2 or round(h * fx)
    for i in range(100):
        m = np.mean(edge_r[yl:yr, i])
        if m != 0 and i:
            i2 = i
            break
    for i in range(100):
        m = np.sum(edge_r[yl:yr, i]) // 255
        if m > 6:  # 第i列超过6行有像素
            i2 = i2 or i + 1
        if i < 20:
            mean2.append(m)
        elif i2:
            break
    i2 = max(0, i2 - 1)
    if i2:
        rm_w2 = round(i2 / fx)
        im_rt, edge_r = im_rt[:, rm_w2:], edge_r[:, i2:]
    # todo i1 != i1_old表示什么
    return (im_left, im_rt, edge_l, edge_r, mean1, mean2,
            i1, i2, i1 != i1_old or i2 != i2_old)


def _find_hor_y(edge_left, edge_rt, w, h):
    """查找长横线位置
    :param edge_left 左扣（下扣）轮廓图
    :param edge_rt 右扣（上扣）轮廓图，两图等高
    :param w 左扣轮廓图的宽度
    :param h 左扣轮廓图的高度
    :return 左扣、右扣的长横线坐标Y，相对于轮廓图高度
    """
    # 上面黑色横线纵坐标 todo 0.05 0.2固定参数可能导致错过黑色横线
    yl, yr = _find_hor_in(edge_left, edge_rt, w, int(h * 0.05), int(h * 0.2))
    if not yl or not yl:
        # 上面黑色横线找不到纵坐标，则找下面黑色横线纵坐标
        yl, yr = _find_hor_in(edge_left, edge_rt, w, int(h * 0.8), int(h * 0.95))
    return yl, yr


def _find_hor_in(edge_left, edge_rt, w, y_min, y_max):
    """在Y区间内查找轮廓图中的长横线坐标
    :param edge_left 左扣（下扣）轮廓图
    :param edge_rt 右扣（上扣）轮廓图，两图等高
    :param w 左扣轮廓图的宽度
    :param y_min 轮廓图Y区间的起始Y
    :param y_max 轮廓图Y区间的结束Y
    :return 长横线坐标Y，相对于轮廓图高度
    """
    yl, yr, ys1, ys2 = 0, 0, [], []
    for y in range(y_min, y_max):
        # 遍历 轮廓图Y区间的起始Y 到 y_max 轮廓图Y区间的结束Y 区间y坐标
        if edge_left[y, -3] == 255:  # 下图右侧 edge_left[y, -3]为纯白色，即边缘轮廓像素
            y_ = y
            ys1.append(y)
            for x1 in range(3, int(w / 10)):
                # 遍历 -3 到 -w/10区间内的横坐标
                if edge_left[y_, -x1] != 255:
                    if edge_left[y_ + 1, -x1] == 255:
                        y_ += 1
                    elif edge_left[y_ - 1, -x1] == 255:
                        y_ -= 1
                    elif edge_left[y_ + 2, -x1] == 255 and edge_left[y_ + 1, 1 - x1] == 255:
                        y_ += 2
                    elif edge_left[y_ - 2, -x1] == 255 and edge_left[y_ - 1, 1 - x1] == 255:
                        y_ -= 2
                    else:
                        break
                ys1.append(y_)
            else:  # 有长横线
                yl = _calc_line_y(ys1)
                break
    for y in range(y_min, y_max):
        if edge_rt[y, 2] == 255:  # 上图左侧
            y_ = y
            ys2.append(y)
            for x2 in range(2, int(w / 10)):
                if edge_rt[y_, x2] != 255:
                    if edge_rt[y_ + 1, x2] == 255:
                        y_ += 1
                    elif edge_rt[y_ - 1, x2] == 255:
                        y_ -= 1
                    elif edge_rt[y_ + 2, x2] == 255 and edge_rt[y_ + 1, x2 - 1] == 255:
                        y_ += 2
                    elif edge_rt[y_ - 2, x2] == 255 and edge_rt[y_ - 1, x2 - 1] == 255:
                        y_ -= 2
                    else:
                        break
                ys2.append(y_)
            else:  # 有长横线
                yr = _calc_line_y(ys2)
                break
    return yl, yr


def _calc_line_y(ys):
    """
    得到黑色横线纵坐标
    :param ys:
    :return:
    """
    yn = {}
    for y_ in ys:
        yn[y_] = yn.get(y_, 0) + 1
    yn = sorted(list(yn.items()), key=lambda m: m[1], reverse=True)
    if len(yn) > 1 and yn[0][1] > len(ys) * 0.25 and yn[0][1] > yn[1][1] * 1.5:
        yl = yn[0][0]
    else:
        yl = round(sum(ys) / len(ys))
    return yl


def main(db_name='sx_pdf', only_name='', only_han='', fold_id='',
         reset=False, overwrite=False, force=False, update_y=None):
    def scanner(pdf_file, han, db):
        pdf_name, vol, info = get_scan_info(pdf_file, han, db)
        if fold_id and not fold_id.startswith(f'{han}_{vol}_'):
            return
        if isinstance(update_y, int):
            update_join_img(db, han, vol, info, fold_id, update_y)
        else:
            export_join_img(db, han, vol, info, fold_id, reset, overwrite, force)

    if fold_id:
        only_han = fold_id.split('_')[0]
    overwrite = fold_id or isinstance(update_y, int) or overwrite
    scan_pdf_files(scanner, db_name, '', only_name, only_han)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
