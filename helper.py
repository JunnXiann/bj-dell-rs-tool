import re
import ast
import hashlib
import re
import pymongo
import logging
from os import path
from yaml import load as load_yml, SafeLoader
from datetime import datetime, timedelta, timezone

BASE_DIR = path.dirname(path.abspath(__file__))


def load_config():
    if path.exists(path.join(BASE_DIR, 'app.yml')):
        with open(path.join(BASE_DIR, 'app.yml'), encoding='utf-8') as f:
            return load_yml(f, Loader=SafeLoader) or {}


def get_config(key, default=None):
    return prop(load_config(), key, default)


def connect_db(db_id, prefix='mongodb-', only_client=False):
    """ 连接数据库"""
    config = load_config()
    conf = config.get(f'{prefix}{db_id}')
    auth = conf.get('auth') or conf.get('name')
    host = conf.get('host') or '127.0.0.1'
    port = conf.get('port', 27017)
    if conf.get('user'):
        uri = f'mongodb://{conf["user"]}:{conf["password"]}@{host}:{port}/{auth}'
    else:
        uri = f'mongodb://{host}:{port}/{auth}'
    client = pymongo.MongoClient(
        uri, connectTimeoutMS=2000, serverSelectionTimeoutMS=2000,
        maxPoolSize=10, waitQueueTimeoutMS=5000, connect=False
    )
    if only_client:
        return client
    return client[conf['name']]


def connect_db_max(db_id, prefix='mongodb-', only_client=False):
    """ 连接数据库  加强版"""
    config = load_config()
    conf = config.get(f'{prefix}{db_id}')
    auth = conf.get('auth') or conf.get('name')
    host = conf.get('host') or '127.0.0.1'
    port = conf.get('port', 27017)
    if conf.get('user'):
        uri = f'mongodb://{conf["user"]}:{conf["password"]}@{host}:{port}/{auth}'
    else:
        uri = f'mongodb://{host}:{port}/{auth}'
    # client = pymongo.MongoClient(
    #     uri, connectTimeoutMS=300000, serverSelectionTimeoutMS=300000,socketTimeoutMS=600000,
    #     maxPoolSize=100, waitQueueTimeoutMS=300000
    # )
    client = pymongo.MongoClient(
        uri,
        connectTimeoutMS=3000000,  # 连接建立超时保持300秒
        serverSelectionTimeoutMS=3000000,  # 服务器选择保持300秒
        socketTimeoutMS=None,  # 关键修改：禁用操作超时
        maxPoolSize=150,  # 连接池扩容至150
        waitQueueTimeoutMS=3000000,
        retryWrites=True,  # 启用写入重试
        retryReads=True  # 启用读取重试
    )
    if only_client:
        return client
    return client[conf['name']]


def get_db(db_id):
    return connect_db(db_id)


def set_logging(filename='', use_suffix=True, log_file=''):
    if use_suffix:
        dt = datetime.now().strftime('%Y%m%d-%H%M%S')
        filename = f'{filename}-{dt}'
    if not log_file and filename:
        log_file = path.join(BASE_DIR, f'log/{filename}.log')

    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s]%(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',  # 仅显示月日小时和分钟秒
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )


def prop(obj, key, default=None):
    """ 获取dict、list和object的嵌套属性
    :param obj: dict、list或object
    :param key: 嵌套属性的字符串表示，如:
        'a.b'或'a.[0]'或'a.{k:v}'或'a.{k:v, k1:v1}'或'a.{k:v}[0]'或'a.{k:v}[0].c'
        如果要对数组取某个元素，可以用'[n]'取第n个元素、或者用'{k:v}'进行条件过滤
    :param default: 如果属性不存在，返回的默认值
    """
    try:
        for k in key.split('.'):
            if isinstance(obj, dict):
                obj = obj.get(k)
            elif isinstance(obj, list):
                m = re.match(r'^(\{.*})?(\[\d+])?$', k)
                if not m:
                    return None
                if m.group(1):  # 如果是条件过滤
                    cond = ast.literal_eval(m.group(1))
                    obj = [i for i in obj if all(i.get(k) == v for k, v in cond.items())]
                if m.group(2):  # 如果有索引
                    idx = int(m.group(2)[1:-1])
                    if 0 <= idx < len(obj):
                        obj = obj[idx]
            elif obj and isinstance(obj, object):
                obj = getattr(obj, k)
            else:
                obj = None
                break
    except Exception as e:
        obj = None

    return default if obj is None else obj


def pos(items, item, default=-1):
    """ 获取数组中某个元素的索引位置"""
    if item in items:
        return items.index(item)
    return default


def merge_nums(num_list):
    """合并连续的数字列表"""
    ret = [num_list[0]]
    if len(num_list) == 1:
        return ret
    for n in num_list[1:]:
        if isinstance(ret[-1], list):  # list
            if n - ret[-1][-1] == 1:  # 连续的数字
                ret[-1] = [ret[-1][0], n]
            else:
                ret.append(n)
        else:  # int
            if n - ret[-1] == 1:  # 连续的数字
                ret[-1] = [ret[-1], n]
            else:
                ret.append(n)
    return ret


def expand_nums(num_list):
    """展开合并后的nums"""
    ret = []
    for n in num_list:
        if isinstance(n, list):  # list
            ret.extend(list(range(n[0], n[1] + 1)))
        else:  # int
            ret.append(n)
    return ret


def md5_encode(img_name):
    salt = get_config('img.hash_salt', '')
    md5 = hashlib.md5()
    md5.update((img_name + salt).encode('utf-8'))
    return md5.hexdigest()


def align_code(code):
    """对齐编码"""
    # 把带code中的_替换为0填充、补齐4位，如GL_1_1_1转换为GL000100010001
    return ''.join([n.zfill(4) for n in code.split('_')]).lstrip('0')

def align_reel_code(code):
    """
    For codes like SX1110_001x1, SX1110_001, SX1110_001z1:
    - Sort x-suffix first, then no suffix, then z-suffix last.
    """
    parts = code.split('_')
    if len(parts) < 2:
        return code
    prefix = parts[0]
    last = parts[1]
    # Extract numeric and suffix
    m = re.match(r'(\d+)([a-zA-Z].*)?$', last)
    if m:
        num, suf = m.groups()
        key = [prefix, num]
        # Custom sort: x < (none/other) < z
        if suf and suf.startswith('x'):
            key.append('-1')
        elif suf and suf.startswith('z'):
            key.append('1')
        elif suf:
            key.append('0' + suf)
        else:
            key.append('0')
        return ''.join(key)
    return code

def get_unicode(char):
    """ 字符转unicode """
    code = char.encode('unicode_escape').decode('utf-8')
    code = 'U+%s' % (code.upper().replace(r'\U', '').lstrip('0'))
    return code


def get_unicode2(char):
    """ 字符转unicode """
    return f'\\u{ord(char):04x}'


def unicode2char(unicode):
    unicode = unicode.replace('U+', '').lower()
    unicode = f'\\u{unicode}' if len(unicode) <= 4 else f'\\U000{unicode}'
    return unicode.encode('utf-8').decode('unicode_escape')


def get_date_time(date_time=None, fmt=None):
    """格式化date_time字符串，time2str"""
    time = date_time if date_time else datetime.now()
    if isinstance(time, str):
        try:
            time = str2time(datetime)
        except ValueError:
            return time

    time_zone = timezone(timedelta(hours=8))
    return time.astimezone(time_zone).strftime(fmt or '%Y-%m-%d %H:%M:%S')


def str2time(str_time, fmt=None):
    if not fmt:
        fmt = '%Y-%m-%d'
        s1 = str_time.split(' ')
        if len(s1) > 1:
            s2 = s1[1].split(':')
            fmt += ' ' + ':'.join(['%H', '%M', '%S'][:len(s2)])
    return str_time and datetime.strptime(str_time, fmt)


def get_page_img_path(page_name):
    """ 获取页图的路径"""
    inner_path = '/'.join(page_name.split('_')[:-1])
    img_path = path.join("/nas/data/T/big", inner_path, '%s.jpg' % page_name)
    if not path.exists(img_path):
        return False
    return img_path


def get_char_img_path(char_name):
    """ 获取字图的路径"""
    md5 = md5_encode(char_name)
    inner_path = '/'.join(char_name.split('_')[:-1])
    char_name = '%s_%s.%s' % (char_name, md5, 'jpg')
    img_path = path.join("/data/tw-imgs/img/chars/", inner_path, char_name)
    if not path.exists(img_path):
        return False
    return img_path


def convert_reel_code(code: str) -> str:
    """ JS_1_1转JS0001_001
        JS_1100a_1转JS1100a_001
    """
    parts = code.split("_")
    if len(parts) != 3:
        return code  # 不符合格式时返回原始值
    prefix, sutra_no, reel_no = parts

    # 提取 sutra_no 中的数字和后缀字母
    m = re.match(r"(\d+)([a-zA-Z]*)", sutra_no)
    if not m:
        return code
    num_part, letter_part = m.groups()
    sutra_no_fmt = f"{int(num_part):04d}{letter_part}"  # 数字部分补4位

    try:
        int(reel_no)
        tr_reel_code = f'{prefix}{sutra_no_fmt}_{int(reel_no):03d}'
    except ValueError:
        tr_reel_code = f'{prefix}{sutra_no_fmt}_{reel_no}'

    return tr_reel_code


def merge_nums(num_list):
    """合并连续的数字列表"""
    ret = [num_list[0]]
    if len(num_list) == 1:
        return ret
    for n in num_list[1:]:
        if isinstance(ret[-1], list):  # list
            if n - ret[-1][-1] == 1:  # 连续的数字
                ret[-1] = [ret[-1][0], n]
            else:
                ret.append(n)
        else:  # int
            if n - ret[-1] == 1:  # 连续的数字
                ret[-1] = [ret[-1], n]
            else:
                ret.append(n)
    return ret


def expand_nums(num_list):
    """展开合并后的nums"""
    ret = []
    for n in num_list:
        if isinstance(n, list):  # list
            ret.extend(list(range(n[0], n[1] + 1)))
        else:  # int
            ret.append(n)
    return ret
