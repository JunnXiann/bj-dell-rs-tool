import numpy as np
import cv2 as cv


def calc_dim(edges, w, h, sy):
    """
    生成裁切扣图需要的坐标信息
    todo HoughLinesP霍夫曼变换算法检测直线可能不准确，造成经文切破
    :param edges:
    :param w:
    :param h:
    :param sy:
    :return:
    """
    # 水平或竖线检测，步长为1像素、1度，线段长度至少30
    lines = cv.HoughLinesP(edges, 1, np.pi / 180, 100, minLineLength=30, maxLineGap=1)
    assert lines is not None, 'no hough line'
    lines = [s[0] for s in lines if s[0][0] == s[0][2] or s[0][1] == s[0][3]]
    # 页面中间水平线
    cen_lines = {i: [s, 0] for i, s in enumerate(lines)
                 if s[1] == s[3] and abs(s[1] - h / 2) < 50 * sy and s[2] - s[0] > 100 * sy}
    # 搜集顶部、底部、中间的横竖线
    marks = {}
    for i, (x1, y1, x2, y2) in enumerate(lines):
        pos, valid = '', False
        if y1 < 100 * sy or y2 > h - 100 * sy:  # 顶部和底部的竖线
            pos = 'top' if y1 < 100 * sy else 'bottom'
            t = x2 - x1, y1 - y2, x1 - w / 2
            valid = x1 == x2 and t[1] > 50 * sy and abs(t[2]) > 20 * sy
        elif i in cen_lines:  # 中间横线
            pos = 'mid-hor'
            valid = y1 == y2 and x2 - x1 > 100 * sy
            cen_lines[i][1] = valid
        elif y2 > h / 2 - 180 * sy and y1 < h / 2 + 180 * sy:  # 中间短竖线
            pos = 'mid-vert'
            valid = x2 == x1 and y1 - y2 > 40 * sy
        if valid:
            marks[pos] = marks.get(pos, []) + [(x1, y1, x2, y2)]

    # 计算分隔线的位置
    xs = _check_xs(marks, w, sy)  # 竖线X
    yc = np.mean([s[0][1] for s in cen_lines.values() if s[1]])  # 中间横线Y
    # todo tp为空列表造成上下空白高度不一致
    tp = [s[1] for s in marks.get('top', [])]  # 顶部竖线的Y-max
    # todo bt为空列表造成上下空白高度不一致
    bt = [s[3] for s in marks.get('bottom', [])]  # 底部竖线的Y-min
    c1 = [yc - s[3] for s in marks.get('mid-vert', []) if yc - s[3] > 60 * sy]  # 中间竖线的上高
    c2 = [s[1] - yc for s in marks.get('mid-vert', []) if s[1] - yc > 60 * sy]  # 中间竖线的下高
    tp = tp and np.max(tp) or 74 * sy
    bt = bt and np.min(bt) or h - 74 * sy
    ph = min(yc - tp, bt - yc) - 60 * sy  # 统一正反面高度
    tp, bt = yc - ph, yc + ph
    hc = np.mean(c1 + c2) + 20 * sy if c1 or c2 else 100 * sy  # 中间间隔半高
    # xs代表纵向分割线横坐标 tp代表上方横向分割线下方最下端纵坐标 bt代表下方横向分割线下方最下端纵坐标
    # yc代表pdf页图中间线 hc代表中间线到上下方横向分割线的高度
    return xs, round(tp), round(bt), np.round(yc), round(hc)


def _check_xs(marks, w, sy):
    # 竖线分隔线的x坐标
    xs = marks.get('top', []) + marks.get('bottom', []) + marks.get('mid-vert', [])
    xs = sorted([s[0] for s in xs])
    for i, x in enumerate(xs):  # 合并紧挨的竖线
        if i and x - xs[i - 1] < 30 * sy:
            xs[i] = (xs[i - 1] + x) / 2
            xs[i - 1] = 0
    xs, x_gap = [round(x) for x in xs if x] or [round(314 * sy)], round(1078 * sy)
    # 竖线间距
    gap = sorted(x - xs[i - 1] for i, x in enumerate(xs) if i) or [x_gap]
    if gap and abs(gap[0] - x_gap) < 100 * sy:
        x_gap = np.round(np.mean([x for x in gap if abs(x - gap[0]) < 20 * sy]))
    elif gap and gap[0] > x_gap * 1.8:
        x_gap = round(gap[0] / round(gap[0] / x_gap))
    # 补充最左分隔线
    while xs[0] - 50 * sy > x_gap:
        xs.insert(0, xs[0] - x_gap)
    # 补充中间分隔线
    i = 1
    while i < len(xs):
        gap = (xs[i] - xs[i - 1]) / x_gap
        i += 1
        while gap > 1.8:
            xs.insert(i - 1, xs[i - 2] + x_gap)
            gap, i = (xs[i] - xs[i - 1]) / x_gap, i + 1
    # 补充最右分隔线
    while len(xs) < 6:
        xs.append(xs[-1] + x_gap)
    assert len(xs) == 6 and xs[-1] < w - 20 * sy, str(xs)
    return xs
