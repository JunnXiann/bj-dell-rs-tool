import os
import re
import sys
import json
import time
import logging
import requests
from os import path

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

import helper as hlp
from helper import BASE_DIR
from util.uni2std import is_family
from util.diff import get_txt, diff
from util.ai.deepseek import DeepseekManager
from util.ai.qwen import QwenManager
from util.ai.doubao import DoubaoManager

# 标点符号
PUNC_STR = '。？！，、；：“”‘’「」『』﹃﹄﹁﹂（）《》〈〉［］〔〕【】()——……－～．'
PH_PUNC_STR = '。？！，、；：“”‘’﹃﹄﹁﹂《》〈〉［］【】()——……－～．'
START_PUNC = '“‘「『﹃﹁（《〈［〔【('
END_PUNC = '”’」』﹄﹂）》〉］〕】)'

# 中文汉字（https://www.qqxiuzi.cn/zh/hanzi-unicode-bianma.php）
ZH_STR = '[\u3400-\uFAD9\U00020000-\U0003134A]'
UN_ZH_STR = '[^\u3400-\uFAD9\U00020000-\U0003134A]'
ZH_PUNC_STR = '[\u2000-\uFF5E\U00020000-\U0003134A]'
UN_ZH_PUNC_STR = '[^\u2000-\uFF5E\U00020000-\U0003134A]'


def get_punc_str(include_newline=True):
    punc_str = PUNC_STR
    if include_newline:
        punc_str += '\n¶'
    return punc_str


def get_PH_punc_str(include_newline=True):
    punc_str = PH_PUNC_STR
    if include_newline:
        punc_str += '\n¶'
    return punc_str


def is_punc(t, include_newline=True):
    punc_str = get_punc_str(include_newline)
    return t in punc_str


def has_punc(txt, include_newline=True):
    punc_str = get_punc_str(include_newline)
    for t in txt:
        if t in punc_str:
            return True
    return False


def trim_punc(txt, include_newline=True):
    punc_str = get_punc_str(include_newline)
    return re.sub('[%s]+' % punc_str, '', txt)


def trim_PH_punc(txt, include_newline=True):
    punc_str = get_PH_punc_str(include_newline)
    return re.sub('[%s]+' % punc_str, '', txt)


def trim_punc_and_pagecode(txt, include_newline=True):
    txt = re.sub(r'\[.*?\]', '', txt)
    return trim_punc(txt, include_newline)


def trim_cbeta_whitespace(cbeta_txt):
    txt = re.sub(r'[ \u3000]', '', cbeta_txt)
    return txt


def get_punc_cnt(txt, include_newline=True):
    punc_str = get_punc_str(include_newline)
    return len([t for t in txt if t in punc_str])


def stat_punc_cnt(txt, include_newline=True):
    punc_str = get_punc_str(include_newline)
    punc2cnt = {}
    for punc in punc_str:
        punc2cnt[punc] = txt.count(punc)
    return punc2cnt


def get_punc_type(txt):
    """ 获取标点类型 """
    stat = stat_punc_cnt(txt)
    punc_keys = '。？！，、；：“”‘’「」『』'
    punc_cnt = sum([v for k, v in stat.items() if k in punc_keys])
    key_cnt = len([k for k, v in stat.items() if k in punc_keys and v > 3])
    limit = int(len(txt) * 0.05)
    if punc_cnt > limit:
        if key_cnt > 3:
            return '标点'
        if stat.get('。') > limit:
            return '句读'
    return '无'


def get_right_start_punc(txt):
    """获取文本末尾的起始标点"""
    for i, t in enumerate(txt[::-1]):
        if t not in START_PUNC:
            pos = len(txt) - i
            return txt[:pos], txt[pos:], pos
    return txt, '', len(txt)


def get_right_end_punc(txt):
    """获取文本末尾的结束标点"""
    for i, t in enumerate(txt[::-1]):
        if t not in END_PUNC:
            pos = len(txt) - i
            return txt[:pos], txt[pos:], pos
    return txt, '', len(txt)


def get_left_start_punc(txt):
    """获取文本起始的开始标点"""
    for i, t in enumerate(txt):
        if t not in START_PUNC:
            return txt[:i], txt[i:], i
    return '', txt, -1


def get_left_end_punc(txt):
    """获取文本起始的结束标点"""
    for i, t in enumerate(txt):
        if t not in END_PUNC:
            return txt[:i], txt[i:], i
    return '', txt, -1


def split_punc(txt, direction='left', punc_type='start'):
    """从txt中截取前面或后面连续的起始或终止标点"""
    if direction == 'left':
        if punc_type == 'start':
            return get_left_start_punc(txt)
        elif punc_type == 'end':
            return get_left_end_punc(txt)
    elif direction == 'right':
        if punc_type == 'start':
            return get_right_start_punc(txt)
        elif punc_type == 'end':
            return get_right_end_punc(txt)


def slice_txt(txt, is_txt):
    """ 将txt拆分为连续的文字或标点"""
    slices = []
    flag, start, end = None, 0, 0
    for i, t in enumerate(txt):
        if flag is None:
            flag = is_txt(t)
            continue
        _flag = is_txt(t)
        if _flag != flag:
            slices.append([txt[start:end + 1], flag])
            start = end = i
            flag = _flag
        else:
            end += 1
    if txt[start:end + 1]:
        slices.append([txt[start:end + 1], flag])
    return [s[0] for s in slices]


def transfer_cmp_punc_to_base(segments, is_base, is_cmp, most=False):
    """ 将cmp中的标点等标记转换至base，记录在base1中"""

    def transfer_in_order():
        items, start = [], 0
        slices = slice_txt(seg['cmp0'], is_cmp)
        for s in slices:
            if not is_cmp(s[0]):  # 标点段，直接加入
                items.append(s)
            else:  # 文本段，查找base0的文本加入
                txt = get_txt(seg['base0'], is_base, len(s), start, most)
                items.append(txt)
                start += len(txt)
        if start < len(seg['base0']):
            items.append(seg['base0'][start:])
        punc_txt = ''.join(items)
        # 移动开始标点从行末至下行首
        punc_txt = re.sub(r'([%s]+)([\n¶]+)' % START_PUNC, r'\2\1', punc_txt)
        # 移动其余标点从本行首至上行末
        other_punc = '。？！，、；：——……－～' + END_PUNC
        punc_txt = re.sub(r'([\n¶]+)([%s]+)' % other_punc, r'\2\1', punc_txt)

        return punc_txt

    def transfer_same_seg():
        return transfer_in_order()

    def transfer_diff_seg():
        if seg['len_diff'] == 0:
            return transfer_in_order()
        if seg['len_diff'] > 2:
            return seg['base0']
        slices = slice_txt(seg['cmp0'], is_punc)
        if len(slices) > 3:
            return seg['base0']

        if len(slices) == 3 and has_punc(slices[1]):  # 中间为标点
            left, right = slices[0], slices[2]
            left2 = get_txt(seg['base0'], is_base, len(left), 0)
            right2 = get_txt(seg['base0'], is_base, len(right), len(left2))
            if left == right2 or is_family(left, right2) or right == left2 or is_family(right, left2):
                return seg['base0'] + slices[1]

        return transfer_in_order()

    def get_start_punc_from_end(txt):
        """从txt尾巴上获取连续的开始标点"""
        ret = []
        for t in txt[::-1]:
            if t in START_PUNC:
                ret.append(t)
            else:
                return ''.join(ret[::-1])

    def get_end_punc_from_start(txt):
        """从txt开始获取连续的结束标点"""
        ret = []
        for t in txt:
            if t in END_PUNC:
                ret.append(t)
            else:
                return ''.join(ret)

    length = len(segments)
    for i, seg in enumerate(segments):
        if not has_punc(seg['cmp0']):
            seg['base1'] = seg['base0']
            continue
        if not seg['base']:
            if i == 0:  # 获取cmp0尾巴的开始标点
                punc = get_start_punc_from_end(seg['cmp0'])
                seg['base1'] = punc + seg['base0']
            elif i == length - 1:  # 获取cmp0开始的结束标点
                punc = get_end_punc_from_start(seg['cmp0'])
                seg['base1'] = seg['base0'] + punc
            else:
                seg['base1'] = seg['base0']
            continue

        if seg['is_same']:
            seg['base1'] = transfer_same_seg()
        else:
            seg['base1'] = transfer_diff_seg()


def not_newline(x):
    return x not in '¶\n'


def not_punc(x):
    punc_str = get_punc_str(True)
    return x not in punc_str

def not_newline_and_pagecode(x, state={'in_code': False}):
    if x == '[':
        state['in_code'] = True
        return False
    if x == ']':
        state['in_code'] = False
        return False
    if state['in_code']:
        return False
    return not_newline(x)

def not_punc_and_cbeta_whitespace(x):
    punc_str = get_punc_str(True)
    return x not in punc_str and x not in ' \u3000'


def transfer_punc(base_txt, punc_txt, is_base_txt=None, is_punc_txt=None):
    """ 标点迁移
    @base_txt: 不含标点的基础文本
    @punc_txt: 含标点的文本
    @is_base_txt: 判断是否为基础文本的函数
    @is_punc_txt: 判断是否为标点文本的函数
    """
    if not is_base_txt:
        is_base_txt = not_newline
    if not is_punc_txt:
        is_punc_txt = not_punc

    segments = diff(base_txt, punc_txt, is_base_txt, is_punc_txt)
    transfer_cmp_punc_to_base(segments, is_base_txt, is_punc_txt)
    txt = ''.join([seg['base1'] for seg in segments])
    return txt


def transfer_punc_v2(base_txt, punc_txt, is_base_txt=None, is_punc_txt=None):
    """ 标点迁移,大文本版本
    @base_txt: 不含标点的基础文本
    @punc_txt: 含标点的文本
    @is_base_txt: 判断是否为基础文本的函数
    @is_punc_txt: 判断是否为标点文本的函数
    """
    if not is_base_txt:
        is_base_txt = lambda x: True
    if not is_punc_txt:
        punc_str = get_punc_str(include_newline=True)
        is_punc_txt = lambda x: x not in punc_str

    segments = diff(base_txt, punc_txt, is_base_txt, is_punc_txt)
    transfer_cmp_punc_to_base(segments, is_base_txt, is_punc_txt)
    txt = ''.join([seg['base1'] for seg in segments])
    # 移动开始标点从行末至下行首
    txt = re.sub(r'([%s]+)(\n)' % START_PUNC, r'\2\1', txt)
    # 移动其余标点从本行首至上行末
    other_punc = '。？！，、；：——……－～' + END_PUNC
    txt = re.sub(r'(\n)([%s]+)' % other_punc, r'\2\1', txt)
    return txt


def transfer_punc_for_stats(base_txt, punc_txt, is_base_txt=None, is_punc_txt=None):
    """ 标点迁移,统计差异版本
    @base_txt: 不含标点的基础文本
    @punc_txt: 含标点的文本
    @is_base_txt: 判断是否为基础文本的函数
    @is_punc_txt: 判断是否为标点文本的函数
    """
    if not is_base_txt:
        is_base_txt = lambda x: True
    if not is_punc_txt:
        punc_str = get_punc_str(include_newline=True)
        is_punc_txt = lambda x: x not in punc_str

    segments = diff(base_txt, punc_txt, is_base_txt, is_punc_txt)
    transfer_cmp_punc_to_base(segments, is_base_txt, is_punc_txt)
    txt = ''.join([seg['base1'] for seg in segments])
    # 移动开始标点从行末至下行首
    txt = re.sub(r'([%s]+)(\n)' % START_PUNC, r'\2\1', txt)
    # 移动其余标点从本行首至上行末
    other_punc = '。？！，、；：——……－～' + END_PUNC
    txt = re.sub(r'(\n)([%s]+)' % other_punc, r'\2\1', txt)
    return txt, segments


def transfer_base_symbol_to_cmp(segments, is_base, is_cmp):
    """ 将base中的换行符、页码等标记转换至cmp中"""

    def transfer_in_order():
        items, start = [], 0
        slices = slice_txt(seg['base0'], is_base)
        for s in slices:
            if not is_base(s[0]):
                items.append(s)
            else:
                items.append(get_txt(seg['cmp0'], is_cmp, len(s), start))
                start += len(items[-1])
        return ''.join(items)

    def transfer_same_seg():
        return transfer_in_order()

    def transfer_diff_seg():
        m1 = re.match(r'^([\[\]JS_\d+\n]+).*', seg['base0'])
        if m1:
            return seg['cmp0'] + m1.group(1)
        m2 = re.match(r'.+([\[\]JS_\d+\n]+)$', seg['base0'])
        if m2:
            return m2.group(1) + seg['cmp0']
        return seg['cmp0']

    for seg in segments:
        if seg['base0'] == seg['base']:
            seg['cmp1'] = seg['cmp0']
            continue
        if seg['is_same']:
            seg['cmp1'] = transfer_same_seg()
        else:
            seg['cmp1'] = transfer_diff_seg()


def rs_ai_punc(txt):
    """ AI标点 """
    import requests

    url = 'https://guji.rushi-ai.net/api/txt/punc'
    hlp.get_config('login_id')
    data = {'txt': txt, 'punc_type': 1, 'login_id': hlp.get_config('rs_ai.login_id'),
            'password': hlp.get_config('rs_ai.password')}
    r = requests.post(url, data=data)
    if r.status_code == 200:
        res = json.loads(r.text)
        if 'data' in res:
            return res['data'].get('txt')
    return ''


def call_gj_ai_punc_v1(txt):
    """ AI断句 """
    for i in range(5):
        print('call_punc', i, len(txt))
        url = 'https://punct.gj.cool/punct/test'
        r = requests.post(url, headers={'content-type': 'application/json'}, json=[{'src': txt}])
        if r.status_code == 200:
            res = json.loads(r.text)[0]['pred_sent']
            # if '句子太長啦' not in res:
            return res
        time.sleep(7 + i)
    return ''


def get_auth_v3():
    url = 'https://gj.cool/ocr_login'
    data = {'apiid': hlp.get_config('gj_cool.apiid'),
            'password': hlp.get_config('gj_cool.password'), 'encrypt': 0}
    r = requests.post(url=url, data=data)
    if r.status_code == 200:
        res = json.loads(r.text)
        if 'access_token' in res:
            with open(path.join(BASE_DIR, 'util/meta/auth.json'), 'w') as f:
                json.dump(res, f)
                return
    raise Exception('获取授权失败')


def get_auth():
    url = 'https://gj.cool/ocr_login'
    data = {'apiid': hlp.get_config('gj_cool.apiid'),
            'password': hlp.get_config('gj_cool.password'), 'encrypt': 0}
    r = requests.post(url=url, data=data)
    if r.status_code == 200:
        res = json.loads(r.text)
        if 'access_token' in res:
            with open(path.join(BASE_DIR, 'util/meta/auth.json'), 'w') as f:
                json.dump(res, f)
                return
    raise Exception('获取授权失败')


def refresh_auth():
    url = 'https://gj.cool/ocr_refresh'
    auth = json.load(open(path.join(BASE_DIR, 'util/auth.json')))
    headers = {'Authorization': 'gjcool %s' % auth['access_token']}
    r = requests.post(url=url, headers=headers)
    if r.status_code == 200:
        res = json.loads(r.text)
        if 'access_token' in res:
            auth['access_token'] = res['access_token']
            with open(path.join(BASE_DIR, 'util/auth.json'), 'w') as f:
                json.dump(auth, f)
                return
    raise Exception('授权刷新失败')


def call_gj_ai_punc_v2(txt, refresh=True):
    """ AI断句 """
    url = 'https://api.jzd.cool:9013/punct_pro'
    auth = json.load(open(path.join(BASE_DIR, 'util/meta/auth.json')))
    headers = {'Authorization': 'gjcool %s' % auth['access_token']}
    r = requests.post(url, headers=headers, data={'src': txt})
    res = json.loads(r.text)
    if r.status_code == 200 and 'text' in res:
        return '\n'.join(res['text'])
    if r.status_code in [401, 422] and refresh:
        get_auth()
        return call_gj_ai_punc_v2(txt, False)
    # print(res)
    return ''


def call_gj_ai_punc_v3(txt, refresh=True):
    """ 
    AI断句 
    小模型打标
    """
    url = 'https://api.jzd.cool:9013/punct_pro'
    # logging.info(f'path:{path.join(BASE_DIR, 'util/meta/auth.json')}')
    auth = json.load(open(path.join(BASE_DIR, 'util/meta/auth.json')))
    # logging.info(f'auth:{auth}')
    headers = {'Authorization': 'gjcool %s' % auth['access_token']}
    r = requests.post(url, headers=headers, data={'src': txt})
    res = json.loads(r.text)

    if r.status_code == 200 and 'text' in res:
        return '\n'.join(res['text'])
    if r.status_code in [401, 422] and refresh:
        logging.info(f'refresh token,res:{res}')
        get_auth_v3()
        return call_gj_ai_punc_v3(txt, True)
    logging.info(f'call_gj_ai_punc_v3_ept:{res}')
    # print(res)
    return ''


def get_last_pos(txt, n=1):
    """ 获取倒数第n个标点的位置"""
    i, pos = 0, None
    for j, t in enumerate(txt[::-1]):
        if t in '。？！':
            i += 1
            pos = len(txt) - j - 1
            if n == i:
                return pos
    return pos


def gj_ai_punc(txt, version='v2'):
    """ 古籍库AI标点 """

    def trim_txt(_txt):
        return re.sub(r'[。？！，、；：]+', '', _txt).strip()

    txt = trim_txt(txt)
    times, size = 3, 4990
    segs, is_last, idx = [], False, 1
    logging.info('ai_punc, txt length %s.' % len(txt))
    while txt:
        is_last = len(txt) <= size
        txt1 = txt[:size]
        for i in range(times):
            logging.info('#%s, #%s: seg length %s.' % (idx, i, len(txt1)))
            txt2 = eval('call_punc_%s' % version)(txt1)
            if txt2:
                if not is_last:
                    txt3 = txt2[:get_last_pos(txt2) + 1]
                    segs.append(txt3)
                    txt = txt[len(trim_txt(txt3)):]
                else:
                    segs.append(txt2)
                break
            if i == times - 1:
                logging.error('failed, tried %s times.' % times)
                return ''
        idx += 1
        if is_last:
            break
    return ''.join(segs)


def stat_bd_bydir(sutra_dir, file_name=None):
    """ 检查除了句号之外的标点  按目录"""

    if not path.exists(sutra_dir):
        logging.error(f'file not exists:{sutra_dir}')
        return {}, 0
    stat = {}
    txt_length = 0
    punc_str = '。？！，、；：「」『』'
    for fn in os.listdir(sutra_dir):
        if not fn.endswith('.txt') or (file_name and fn != file_name):
            continue
        with open(f'{sutra_dir}/{fn}', 'r') as f:
            lines = [ln for ln in f.readlines() if not ln.startswith('#')]
            txt = ''.join(lines)
            for p in punc_str:
                cnt = txt.count(p)
                stat[p] = stat.get(p, 0) + cnt
            txt2 = re.sub(r'[\s%s]' % punc_str, '', txt)
            txt_length += len(txt2)
    return stat, txt_length


def stat_bd_details_bydir(sutra_dir, file_name=None):
    bd_stat, txt_length = stat_bd_bydir(sutra_dir, file_name=None)
    bd_cnt1 = sum([v for k, v in bd_stat.items()])
    bd_ratio = txt_length and round(bd_cnt1 / txt_length, 4) or ''
    bd_cnt2 = sum([v for k, v in bd_stat.items() if k not in '。：'])
    if bd_cnt2 > 10:
        has_modern_bd = 'Y'
    else:
        has_modern_bd = 'N'

    return has_modern_bd, bd_ratio


def stat_bd_byfile(file_path):
    """ 检查除了句号之外的标点  按文件"""

    if not path.exists(file_path):
        logging.error(f'file not exists:{file_path}')
        return {}, 0
    stat = {}
    txt_length = 0
    punc_str = '。？！，、；：「」『』'

    with open(f'{file_path}', 'r') as f:
        lines = [ln for ln in f.readlines() if not ln.startswith('#')]
        txt = ''.join(lines)
        for p in punc_str:
            cnt = txt.count(p)
            stat[p] = stat.get(p, 0) + cnt
        txt2 = re.sub(r'[\s%s]' % punc_str, '', txt)
        txt_length += len(txt2)
    return stat, txt_length


def stat_bd_details_byfile(file_path):
    bd_stat, txt_length = stat_bd_byfile(file_path)
    bd_cnt1 = sum([v for k, v in bd_stat.items()])
    bd_ratio = txt_length and round(bd_cnt1 / txt_length, 4) or ''
    bd_cnt2 = sum([v for k, v in bd_stat.items() if k not in '。：'])
    if bd_cnt2 > 10:
        has_modern_bd = 'Y'
    else:
        has_modern_bd = 'N'

    return has_modern_bd, bd_ratio


async def big_model_punc(model_name, text, jsz_juanhao=''):
    """ 大模型打标 """
    if model_name not in ['deepseek', 'qwen', 'doubao']:
        return text

    if model_name == 'deepseek':
        deepseek = DeepseekManager()
        return deepseek.add_punctuation(text, jsz_juanhao)
    elif model_name == 'qwen':
        qwen = QwenManager()
        return await qwen.add_punctuation_with_chunks(text, jsz_juanhao)
    elif model_name == 'doubao':
        doubao = DoubaoManager()
        return await doubao.add_punctuation_with_chunks(text, jsz_juanhao)
    return text
