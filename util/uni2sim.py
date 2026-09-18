from os import path as osp

cache = {}


def _load_uni2sim():
    if cache:
        return
    print('loading uni2sim...')
    with open(osp.join(osp.dirname(osp.abspath(__file__)), 'meta/uni2sim.txt'), 'r') as f:
        lines = [ln.strip() for ln in f.readlines() if ln.strip() and not ln.startswith('#')]
    cache['uni2sim'] = {ln.split(':')[0]: ln.split(':')[1] for ln in lines}


def get_simtxt(ch, default='', only_one=True):
    """ 获取所属简体正字"""
    if ord(ch) < 255:
        return default
    _load_uni2sim()
    stds = cache['uni2sim'].get(ch)
    if not stds:
        return default
    if only_one:
        std_list = stds.split('&')
        if ch in std_list:  # ch为正字时，优先返回自己
            return ch
        else:
            return std_list[0]
    return stds


def get_simtype(ch):
    """ 获取文字类型"""
    std = get_simtxt(ch, '', False)
    if not std:  # 未找到
        return -1
    if len(std) == 1:
        if std == ch:
            return 0  # 纯正字
        else:
            return 1  # 狭义异体字
    else:
        if ch in std:
            return 2  # 广义异体字兼正字
        else:
            return 3  # 纯广义异体字


def is_family(a, b):
    """ 检查a和b是否在一个家族"""
    if not a or not b or len(a) > 1 or len(b) > 1:
        return
    _load_uni2sim()
    a_std, b_std = get_simtxt(a), get_simtxt(b)
    if not a_std or not b_std:
        return False
    com = set(a_std.split('&')).intersection(set(b_std.split('&')))
    return bool(com)


def simplify(txt):
    """ 将文档中的异体字转换为简体正字"""
    _load_uni2sim()
    return ''.join([get_simtxt(ch, ch, True) for ch in txt])


def main():
    print(get_simtxt('體'))
    print(get_simtype('㢧'))
    print(simplify('煗-简'))


if __name__ == '__main__':
    main()
