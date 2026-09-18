import numpy as np
import cv2


def create_img(w, h):
    im = np.zeros((h, w), np.uint8)
    im.fill(255)
    return im


def stack_images(images):
    def resize(m_):
        fy = w / m_.shape[1] if m_.shape[1] else 1
        return m_ if w == m_.shape[1] else cv2.resize(m_, None, fx=fy, fy=fy)

    h, w = images[0].shape
    return np.vstack(tuple(resize(m) for m in images)) if len(images) > 1 else images[0]


def resize_image(filename, max_w, max_h, im=None):
    """
    当抽取的扣图宽或者高大于阈值时重新设置大小
    :param filename: 扣图名称
    :param max_w: 最大宽度阈值
    :param max_h: 最大高度阈值
    :param im: 扣图二进制流
    :return:
    """
    im = cv2.imread(filename, -1) if im is None else im
    h, w = im.shape[:2]
    if w > max_w or h > max_h:
        # 得到最小缩放比
        s = min(max_w / w, max_h / h)
        im = cv2.resize(im, None, fx=s, fy=s)
    cv2.imwrite(filename, im, [cv2.IMWRITE_JPEG_QUALITY, 100])
