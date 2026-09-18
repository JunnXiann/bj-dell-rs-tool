import re
import json
from os import path

cache = {}


def _load_gaiji():
    """ 加载外字"""
    # https://github.com/cbeta-org/cbeta_gaiji
    if 'gaiji' not in cache:
        print('loading gaiji...')
        with open(path.join(path.dirname(path.abspath(__file__)), 'gaiji.json'), 'r') as f:
            gaiji = json.load(f)
        cache['gaiji'] = {v['composition']: v.get('uni_char') for v in gaiji.values() if v.get('composition')}
    return cache['gaiji']


def replace_gaiji(txt):
    """ 替换组字式"""

    def get_char(zzs):
        return gaiji.get(zzs) or zzs

    gaiji = _load_gaiji()
    regex = r'\[[+-@*\(\)\/\u2E80-\U0002FFFF]+\]'  # 组字式正则式
    txt = re.sub(regex, lambda m: get_char(m.group(0)), txt)
    return txt
