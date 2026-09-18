import re
import sys
import pymongo
from glob2 import glob
from pymongo.errors import PyMongoError
from os import path, makedirs, environ, stat

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

import helper as hp


def no_file(f):
    """
    文件不存在返回true
    :param f:
    :return:
    """
    return not path.exists(f) or stat(f).st_size == 0


def auto_mkdir(filename, is_dir=False, print_fail=True):
    """自动创建文件夹"""
    filename = filename if is_dir else path.dirname(filename)
    try:
        if not path.exists(filename):
            makedirs(filename)
        return True
    except OSError as e:
        if print_fail:
            print(filename, e)


def prop(obj, key: str, default=None):
    """ 从字典或数组对象中按点号分隔的多级键名获取值
    :param obj, dict or list
    :param key, 按点号分隔的多级键名
    :param default 没有值时的默认返回值
     """
    p = {} if obj is None else obj
    for s in key.split('.'):
        s = int(s) if re.match(r'^\d+$', s) else s
        if isinstance(p, list):  # s: int, index
            p = p[s] if len(p) > s > -1 else None
        else:
            p = p.get(s) if isinstance(p, dict) else None

    if p is None and default is not None:  # 不存在键值时添加中间路径的字典对象
        key = key.split('.')
        while key:
            s = key.pop(0)
            s = int(s) if re.match(r'^\d+$', s) else s
            if not isinstance(obj, dict):
                break
            obj[s] = obj.get(s, {} if key else default)
            obj = obj[s]
    return default if p is None else p


def _get_client(db_name):
    return pymongo.MongoClient(db_name == 'rushi-dev' and environ.get('DB_URI') or 'localhost',
                               timeoutMS=5000, socketTimeoutMS=8000)


def with_db(db_name, scanner):
    try:
        with _get_client(db_name) as client:
            db = client[db_name]
            scanner(db)
    except KeyboardInterrupt:
        pass


def get_pdf_names():
    with open(path.join(path.dirname(path.abspath(__file__)), 'sx_pdf.txt')) as f:
        files = f.read().split('\n')
    return files


def scan_pdf_files(scanner, db_id, src_path='', only_name='', only_han=''):
    """
    扫描所有pdf
    :param scanner: 扫描函数
    :param db_id: 数据库id
    :param src_path: pdf路径
    :param only_name: 限定的pdf名称，可以为tuple或者字符串
    :param only_han: 限定的含路径
    :return:
    """
    # 如果src_path用@开头则在环境变量中获取pdf路径
    src_path = environ.get(src_path[1:]) if src_path.startswith('@') else src_path
    if src_path and path.exists(src_path):
        files = sorted(glob(path.join(src_path, '**', '*.pdf')))
        files = [s for s in files if re.search(r'/\d{3}/.字第\d+册\.pdf', s.replace('\\', '/'))]
    else:
        # 从入参src_path找不到pdf路径时，从base/sx_pdf.txt中获取所有pdf路径
        files = get_pdf_names()

    hans = []
    # 获取限定含列表
    only_han = list(only_han) if isinstance(only_han, (tuple, list)) else str(
        only_han).split(',') if only_han else []
    for range_s in only_han:
        # 将分解出的所有含号放到一个列表中
        if '-' in str(range_s):
            from_han, to_han = [int(s) if s else 0 for s in range_s.split('-')]
            for han in range(from_han or 1, (to_han or 548) + 1):
                hans.append(han)
        elif re.match(r'^\d+$', str(range_s)):
            hans.append(int(range_s))
    # pdf文件名
    names = list(only_name) if isinstance(only_name, tuple) else only_name and only_name.split(',')

    db = hp.get_db(db_id)
    for pdf_file in files:
        # 遍历含路径下所有pdf
        try:
            # 根据pdf路径得到含号
            han = int(re.search(r'(\d{3})[/\\].字第\d+册', pdf_file).group(1))
            if (not hans or han in hans) and (
                    not names or [s for s in names if s in path.basename(pdf_file)]):
                if scanner(pdf_file, han, db) is False:
                    break
        except PyMongoError as e:
            print(han, path.basename(pdf_file), e)
        except KeyboardInterrupt:
            break



def get_scan_info(pdf_file, han, db=None):
    """
    用于获取不带后缀的pdf名称、含号、及字典{
    pdf_name：不带后缀的pdf名称
    db: 数据库链接
    han: 涵号
    vol_pdf：册号
    pdf_file：pdf名称
    out_path：输出路径
    }
    :param pdf_file: str
    :param han: 涵号
    :param db: 数据库链接
    :return: 不带后缀的pdf名称、册号、
    """
    pdf_name = path.basename(pdf_file).split('.')[0]  # PDF文件名
    vol_pdf = int(re.search(r'第(\d+)册', pdf_name).group(1))  # 册号
    info = dict(pdf_name=pdf_name, db=db, han=han, vol_pdf=vol_pdf, pdf_file=pdf_file,
                out_path=environ.get('OUT_PATH', '.tmp'))
    return pdf_name, vol_pdf, info


def find_pdf_info(db, han, vol_pdf):
    return db.pdf.find_one(dict(han=han, vol_pdf=vol_pdf))


def get_name_img(han, vol_pdf, pi, idx=-1, check_exists=True):
    fn = path.join(environ.get('OUT_PATH', ''),
                   'name10' if idx == -1 else 'name',
                   f'{han}/{vol_pdf}/{han}_{vol_pdf}_{pi}_{idx}.jpg').replace('_-1', '')
    return (not check_exists or path.exists(fn)) and fn


def make_page_no(han, vol_pdf, pi, i, order):
    """计算每十扣一页的指定页(pi或pid)内指定扣序号(i)的扣号"""
    if isinstance(pi, str):  # han_vol_pi
        pi = int(pi.split('_')[-1])
    assert pi >= 0 and 0 <= i < 10
    start_no = 0
    if (han == 90 or han == 149) and vol_pdf == 1 and pi > 0:
        pi -= 1  # 位字第01册、四字第01册 前两页相同，忽略第一页

    if order == '右':
        no = 10 - i if i < 5 else i - 4
    elif order == '底':
        no = 5 - i if i < 5 else 15 - i
    else:  # 左
        no = 5 - i if i < 5 else i + 1
    return no + pi * 10 + start_no
