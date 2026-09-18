"""
cbeta数据下载使用步骤：
 1. 初始化目录（需要CBReader本地数据中的catalog.txt）
 2. 下载CBETA经文(zip)
 3. 解压CBETA经文(zip->juan 多个卷txt文件)
 4. 合并CBETA经文(juan->jing 多个卷txt文件合成一个经txt)
"""
import re
import os
import csv
import shutil
import sys
import zipfile
import logging
import requests
import os.path as path

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

from util.uni2std import normalize as vt_normalize
import helper as hp

CBETA_ROOT = path.expanduser('~/Develop/cbeta-txt')  # CBETA根目录
# 去掉吕澂、太虚、印顺等人物文集以及南传大藏经
PASS_ZIPS = ['LC', 'TX', 'Y', 'N']


def create_init_dirs():
    """ 创建CBETA目录 """
    if not path.exists(CBETA_ROOT):
        init_dirs = ['meta', 'zip', 'juan', 'jing']
        for d in init_dirs:
            os.makedirs(path.join(CBETA_ROOT, d), exist_ok=True)
        # 把CBReader本地数据文件中的catalog.txt复制到meta目录下
        catalog_fp = path.expanduser('~/Library/CBETA/Bookcase/CBETA/catalog.txt')
        if path.exists(catalog_fp):
            shutil.copy(catalog_fp, path.join(CBETA_ROOT, 'meta'))
        else:
            logging.error('CBReader catalog.txt not found! %s' % catalog_fp)


def get_cb_catalog_list():
    """ 获取CBETA经目"""
    # ['藏经代码', 'CBETA部类', 'T部类', '册号', '经号', '卷数', '经名', '作译者']
    with open(f'{CBETA_ROOT}/meta/catalog.txt', 'r') as f:
        rows = list(csv.reader(f, delimiter=','))
    return rows


def download_zip(cb_no, force=False):
    """ 
    下载指定经号的 CBETA 数据文件（ZIP 格式）
    如果文件已存在且 force=False，则跳过下载
    """
    fp = path.join(CBETA_ROOT, 'zip', '%s.txt.zip' % cb_no)
    if path.exists(fp) and not force:
        return True

    url = 'https://cbdata.dila.edu.tw/stable/download/text/%s.txt.zip' % cb_no
    r = requests.get(url, headers={
        'content-type': 'application/zip', 'accept': 'application/zip',
        'referer': 'https://guji.rushi-ai.net/'
    })
    if r.status_code == 200:
        if 'error' in r.content.decode('utf-8', errors="ignore"):
            logging.error('[e1]%s, %s' % (cb_no, r.content.decode('utf-8')))
            return False
        with open(fp, 'ab') as wf:
            wf.write(r.content)
            return True
    else:
        logging.error('[e2]%s, %s' % (cb_no, r.status_code))
        return False


def unzip_juan(cb_no, force=False):
    """ 解压zip包"""
    root = path.join(CBETA_ROOT, 'juan', cb_no)
    if not force and path.exists(root) and len(os.listdir(root)):
        return

    fn = path.join(CBETA_ROOT, 'zip', '%s.txt.zip' % cb_no)
    if not path.exists(fn):
        if not download_zip(cb_no, force):
            return

    with zipfile.ZipFile(fn, 'r') as z:
        for f in z.namelist():
            z.extract(f, root)


def batch_download_zip(force=False):
    hp.set_logging('batch_download_zip.log')
    catalog_rows = get_cb_catalog_list()
    for r in catalog_rows:
        if r[0].strip() in PASS_ZIPS:  # 跳过不需要的经
            continue
        cb_id = f'{r[0].strip()}{r[4].strip()}'
        logging.info(f'[{cb_id}] downloading...')
        download_zip(cb_id, force)


def batch_unzip(force=False):
    hp.set_logging('batch_unzip.log')
    catalog_rows = get_cb_catalog_list()
    for r in catalog_rows:
        cb_id = f'{r[0].strip()}{r[4].strip()}'
        logging.info(f'[{cb_id}] unzip...')
        unzip_juan(cb_id, force)


def merge_juan2jing(cb_no, normalize=False, force=False):
    """ 
    合并CBETA卷文 
    将某个经号的所有卷文件合并为一个完整的经文文件
    """
    out_fp = path.join(CBETA_ROOT, 'jing', '%s.txt' % cb_no)
    if not force and path.exists(out_fp):
        return

    # 查找txt文件
    root = path.join(CBETA_ROOT, 'juan', cb_no)
    files = [fn for fn in os.listdir(root) if re.match(r'^%s_\d+\.txt$' % cb_no, fn)]
    files.sort()
    # 逐个合并
    lines = []
    for fn in files:
        with open(path.join(root, fn), 'r') as rf:
            rows = [ln.strip() for ln in rf.readlines() if
                    ln.strip() and not ln.startswith('#') and not ln.startswith('No')]
            lines.extend(rows)
    # 写入经文本
    txt = '※※'.join(lines)
    txt = re.sub(r'\s', '', txt)  # 去掉空格
    if normalize:
        txt = vt_normalize(txt)
    with open(out_fp, 'w') as f:
        f.write(txt.replace('※※', '\n'))


def batch_merge_juan2jing(normalize=False, force=False):
    """ 
    合并CBETA卷文 
    将某个经号的所有卷文件合并为一个完整的经文文件
    """
    hp.set_logging('batch_unzip.log')
    catalog_rows = get_cb_catalog_list()
    for r in catalog_rows:
        cb_id = f'{r[0].strip()}{r[4].strip()}'
        merge_juan2jing(cb_id, normalize, force)


def get_cb_catalog_dict():
    """ 获取CBETA经目"""
    rows = get_cb_catalog_list()
    return {f'{r[0].strip()}{r[4].strip()}': r for r in rows}

def get_cb_catalog_sutra_uids():
    """
    获取CBETA经号列表
    row格式：['藏经代码', 'CBETA部类', 'T部类', '册号', '经号', '卷数', '经名', '作译者']
    """
    rows = get_cb_catalog_list()
    return [f'{r[0].strip()}{r[4].strip()}' for r in rows]

def check_cb_reel_txt_count():
    """统计juan目录下不含 'toc' 的 .txt 文件数量"""
    root = path.join(CBETA_ROOT, 'juan')
    if not path.exists(root):
        return 0

    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            name_lower = fn.lower()
            if name_lower.endswith('.txt') and ('toc' not in name_lower):
                total += 1
    return total

def format_cb_no(cb_no):
    """ 将catalog的编码转换为CBETA api的编码"""
    if re.match(r'^[AB]\d{3}$', cb_no):
        cb_no = 'J%s' % cb_no
    return cb_no


def find_cb_meta(js_title):
    """ 查找对应CBETA经目
    js_meta: 径山藏经目[[js_no, title], ...]
    """
    catalog = get_cb_catalog_dict()
    title = js_title.split('，')[0].strip()  # 如果有中文逗号，则仅取逗号前的部分
    cb = catalog.get(title)
    if cb:
        return [format_cb_no(cb[4].strip()), cb[6].strip(), cb[7].strip()]  # 经号、经名、作译者
    cb2 = catalog.get(vt_normalize(title))
    if cb2:
        return [format_cb_no(cb2[4].strip()), cb2[6].strip(), cb2[7].strip()]


def batch_find_cb_meta(js_meta_list):
    """ 查找对应CBETA经目
    js_meta: 径山藏经目[[js_no, title], ...]
    """
    # 获取CBETA经目
    catalog = get_cb_catalog_dict()

    # 根据径山藏的信息，查找对应CBETA经目
    cb_meta_list = []
    for i, (js_no, title) in enumerate(js_meta_list):
        row = [js_no, title]
        title1 = title.split('，')[0].strip()
        cb = catalog.get(title1)
        cb2 = catalog.get(vt_normalize(title1))
        if cb:
            row.extend(['Y1', format_cb_no(cb[4].strip()), cb[6].strip(), cb[7].strip()])  # 经号、经名、作译者
        elif cb2:
            row.extend(['Y2', format_cb_no(cb2[4].strip()), cb2[6].strip(), cb2[7].strip()])
        else:
            row.extend(['N', '', '', ''])
        print('\t'.join(row))
        cb_meta_list.append(row)

    return cb_meta_list


def get_cbeta_txt_v2(cb_no):
    """ 获取CBETA经文
        param: cb_no为api或网站使用的经号
    """
    cb_no = format_cb_no(cb_no)
    fn = path.join(CBETA_ROOT, 'jing', '%s.txt' % cb_no)
    if not path.exists(fn):
        download_zip(cb_no)
        unzip_juan(cb_no)
        merge_juan2jing(cb_no)
    with open(fn, 'r') as f:
        return f.read()


def get_cbeta_txt_v1(cb_no, newline='\n'):
    """ 获取CBETA经文 """
    m = re.match(r'^([A-Z]{1,2})(\d+[a-z]?)$', cb_no)
    if not m:
        return ''
    tripitaka_id = m.group(1)
    sutra_dir = path.join(CBETA_ROOT, 'cbeta-text', tripitaka_id, cb_no)
    if not path.exists(sutra_dir):
        return ''

    txt_lines = []
    files = [f for f in os.listdir(sutra_dir) if f.endswith('.txt')]
    files.sort()
    for fn in files:
        with open(path.join(sutra_dir, fn), 'r') as f:
            lines = [ln.strip() for ln in f.readlines() if ln.strip() and not ln.startswith('#')]
            txt_lines.extend(lines)
    txt = newline.join(txt_lines)
    return txt


def convert_cbeta_updated_catalog_to_normal_catalog():
    """将cbeta日常更新的 updated_catalog.txt 转换为 catalog.txt 经典格式。

    输入行规则：
    - 每行以形如 `X67n1302` 或 `J40nB485` 的编号开头：
        - `X`/`J` 为藏经代码（tripitaka_code）
        - `67`/`40` 为册号（volume_no，可有前导 0）
        - `n` 为分隔符
        - `1302`/`B485` 为经号（sutra_no，可能以字母开头或包含字母后缀）
    - 之后为：经名 + `(N卷)` 或 `（N卷）` + `【作译者】`，其中卷数或作译者可能缺失。

    输出列：
    tripitaka_code, '', '', volume_no, sutra_no, reel_count, title, author
    """
    updated_txt_path = path.join(CBETA_ROOT, 'meta/updated_catalog.txt')
    out_txt_path = path.join(CBETA_ROOT, 'meta/catalog.txt')

    if not path.exists(updated_txt_path):
        logging.error('updated_catalog.txt not found: %s' % updated_txt_path)
        return False

    # 形如: X67n1302 或 J40nB485
    code_parse_re = re.compile(r'^([A-Z])(\d+)n(.+)$')
    vol_re = re.compile(r'[（(]\s*(\d+)\s*卷\s*[)）]')
    author_re = re.compile(r'【(.*?)】')

    total = 0
    written = 0
    skipped = 0

    rows = []
    with open(updated_txt_path, 'r', encoding='utf-8') as rf:
        for raw_line in rf:
            total += 1
            line = raw_line.strip()
            if not line:
                skipped += 1
                continue

            parts = line.split()
            if not parts:
                skipped += 1
                continue

            code = parts[0].strip()
            m_code = code_parse_re.match(code)
            if not m_code:
                # 非 <字母><数字>n<经号> 的首字段，跳过
                skipped += 1
                continue

            tripitaka_code = m_code.group(1)
            volume_no = m_code.group(2)  # 册号，保持原样（包含可能的前导0）
            sutra_no = m_code.group(3)  # 经号，允许以字母开头或包含字母

            # 余下文本：标题(卷数)【作者】
            rest_start_idx = line.find(code) + len(code)
            rest_text = line[rest_start_idx:].strip()

            # 作者
            author_match = author_re.search(rest_text)
            author = author_match.group(1).strip() if author_match else ''

            # 卷数
            vol_match = vol_re.search(rest_text)
            reel_count = vol_match.group(1) if vol_match else ''

            # 标题：优先取至卷数括号前，否则取至作者前，否则整个剩余文本
            title_end_idx = None
            if vol_match:
                title_end_idx = vol_match.start()
            elif author_match:
                title_end_idx = author_match.start()
            title = rest_text[:title_end_idx].strip() if title_end_idx is not None else rest_text.strip()

            # 去除标题末尾可能残留的标点和空白
            title = title.rstrip('（(【 ')  # 简单清理

            # 目标行：藏经编码, 部类细分(空), 部类(空), 册数, 经号后面部分, 卷数, 经名, 作译者
            row = [tripitaka_code, '', '', volume_no, sutra_no, reel_count, title, author]
            rows.append(row)
            written += 1

    # 写入新目录txt
    os.makedirs(path.join(CBETA_ROOT, 'meta'), exist_ok=True)
    with open(out_txt_path, 'w', encoding='utf-8', newline='') as wf:
        writer = csv.writer(wf, delimiter=',')
        for r in rows:
            writer.writerow(r)

    logging.info(
        'convert_cbeta_updated_catalog_to_normal_catalog done. total=%d, written=%d, skipped=%d -> %s'
        % (total, written, skipped, out_txt_path)
    )
    return True


def process():
    create_init_dirs()  # 创建CBETA目录
    # cb_no = 'T0001'
    # download_zip(cb_no)
    # unzip_juan(cb_no)
    # merge_juan2jing(cb_no)
    batch_download_zip(force=False)
    batch_unzip(force=False)
    # batch_merge_juan2jing(normalize=False, force=False)
    # print(get_cb_catalog_sutra_uids())


def main(func='process', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
