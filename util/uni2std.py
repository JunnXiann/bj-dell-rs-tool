from os import path as osp

cache = {}


def _load_uni2std():
    if cache:
        return
    print('loading uni2std...')
    with open(osp.join(osp.dirname(osp.abspath(__file__)), 'meta/uni2std.txt'), 'r') as f:
        lines = [ln.strip() for ln in f.readlines() if ln.strip() and not ln.startswith('#')]
    cache['uni2std'] = {ln.split(':')[0]: ln.split(':')[1] for ln in lines}
    with open(osp.join(osp.dirname(osp.abspath(__file__)), 'meta/uni2std_my.txt'), 'r') as f:
        lines = [ln.strip() for ln in f.readlines() if ln.strip() and not ln.startswith('#')]
    cache['uni2std_my'] = {ln.split(':')[0]: ln.split(':')[1] for ln in lines}


def get_stdtxt(ch, default='', multi_policy=2):
    """ 获取所属繁体正字"""
    if ord(ch) < 255:
        return default
    _load_uni2std()
    stds = cache['uni2std_my'].get(ch) or cache['uni2std'].get(ch)
    if not stds:
        return default
    std_list = stds.split('&')
    if len(std_list) == 1:
        return std_list[0]

    #  有多个正字时，根据policy返回
    if multi_policy == 0:  # 返回空串
        return ''
    if multi_policy == 1:  # 返回所有
        return std_list
    if multi_policy == 2:  # 选择自己，不做转换
        return ch
    if multi_policy == 3:  # 优先选择自己，否则选择第1个
        if ch in std_list:
            return ch
        else:
            return std_list[0]


def get_stdtype(ch):
    """ 获取文字类型"""
    std = get_stdtxt(ch, '', False)
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
    """ 检查a和b是否在一个正字家族"""
    if not a or not b or len(a) > 1 or len(b) > 1:
        return
    _load_uni2std()
    a_std = get_stdtxt(a, a, 1)
    b_std = get_stdtxt(b, b, 1)
    if not a_std or not b_std:
        return False
    com = set(a_std).intersection(set(b_std))
    return bool(com)


def normalize(txt):
    """ 将文档中的异体字转换为繁体正字"""
    _load_uni2std()
    return ''.join([get_stdtxt(ch, ch, 2) for ch in txt])


def main():
    # print(get_stdtxt('乁'))
    # print(get_stdtype('㢧'))
    print(is_family('及', '乁'))
    # print(normalize('福-煗-简'))


if __name__ == '__main__':
    main()
