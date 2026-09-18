import json
import base64
from os import environ
from urllib.request import urlopen
from urllib.request import Request
from urllib.parse import urlencode

ACC_OCR_URL = 'https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic'  # OCR高精度
STD_OCR_URL = 'https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic'  # OCR标准版
TOKEN_URL = 'https://aip.baidubce.com/oauth/2.0/token'
_cache = {}


def fetch_token():
    """获取百度云访问令牌"""
    params = {'grant_type': 'client_credentials',
              'client_id': environ['OCR_API_KEY'],
              'client_secret': environ['OCR_SECRET_KEY']}
    post_data = urlencode(params).encode('utf-8')
    req = Request(TOKEN_URL, post_data)
    try:
        f = urlopen(req, timeout=10)
        result_str = f.read().decode()
        result = json.loads(result_str)
        if 'access_token' in result.keys() and 'scope' in result.keys():
            if 'brain_all_scope' not in result['scope'].split(' '):
                print('please ensure has check the ability')
                return
            return result['access_token']
        else:
            print('please overwrite the correct API_KEY and SECRET_KEY')
    except (OSError, ValueError) as err:
        print('fetch_token', err)


def request(data=None, acc=False, img_file=''):
    """访问百度OCR接口
    :param data, API内容对象
    :param acc, 使用通用OCR高精度版(True)、通用OCR标准版(False)
    :param img_file, 图片文件名，代替 data 参数
    :return 含有 words_result 的字典对象
    """
    if img_file:
        with open(img_file, 'rb') as f:
            content = f.read()
        data = urlencode({'image': base64.b64encode(content)})

    token = _cache['token'] = _cache.get('token') or fetch_token() or ''
    url = (ACC_OCR_URL if acc else STD_OCR_URL) + '?access_token=' + token
    req = Request(url, data.encode('utf-8'))
    try:
        f = urlopen(req, timeout=15)
        result_str = f.read().decode()
        result = json.loads(result_str)
        if result.get('error_code'):
            if result['error_code'] in [17, 18, 19]:
                raise RuntimeError(result['error_msg'])
        return result
    except (OSError, ValueError) as err:
        err = (img_file and img_file.split('/')[-1] or '') + str(err)
        print(err)
        return {'error_msg': err}
