import re

re_rule1 = re.compile(r'[大人].?[经轻]\s?([^字第册\d\s]+)?\s?字*[第弟]?'
                      r'[\u4e00-\u9fa5]?\s*([^第弟册\s-]+?)[\s-]*册\s*(\d[ \d]*)')
re_rule2 = re.compile(r'(\d+)\s*[大人].?[经轻](.)?字*[第弟]?'
                      r'[\u4e00-\u9fa5]?\s*(\d+)\s*册')
re_rule3 = re.compile(r'[\u4e00-\u9fa5_-]*[第弟](\d+)册\s*(\d[ \d]*)')
re_rule4 = re.compile(r'[大人].?[经轻]\s?([^字第册\d\s]+)?\s?字*[第弟]?'
                      r'[\u4e00-\u9fa5]?\s*([^第弟册\s-]+?)[\s-]*册')
re_rules = [re_rule1, re_rule2, re_rule3, re_rule4]
re_clean = re.compile(r'[\x01-\x06\u0001-\u0006]')
re_space = re.compile(r'[\x0f-\x1f]')
re_digit = re.compile(r'^\d+$')


def clean_text(text):
    """清除不可见异常字符"""
    text = re_space.sub(' ', text or '')
    return re_clean.sub('', text).strip()


def parse_name(text, idx=-1):
    """解析扣名文本
    :param text, 要解析的文本
    :param idx, 如果为单扣文本则>=0
    :return (kc, vol_fold, no)[], parse_type
        千字文kc可能为''，扣号no为正整数或0(无扣号)
    """
    text = re_clean.sub('', text or '')
    items = re_rule1.findall(text)  # 规则1：千?、册、扣
    t = 1 if items else 0
    if not items and text:
        a3 = re_rule3.findall(text)  # - 规则3：册、扣，用于OCR中千字文乱字时能提取册号和扣号
        a2 = not a3 and re_rule2.findall(text)  # 规则2：扣、千?、册，支持OCR中扣号串到前面
        a4 = not a3 and re_rule4.findall(text)  # 规则4：无扣号，千?、册，支持原扣名不含扣号
        if a3:  # 千字文为空
            t = 3
            for r in a3:
                vol_fold, no = r[:2]
                items.append(('', vol_fold, no))
        elif len(a2) == 1 and idx >= 0:  # 仅单扣OCR、末尾无扣号才识别是否串位
            t = 2
            no, kc, vol_fold = a2[0][:3]
            items.append((kc, vol_fold, no, idx))
        elif a4:  # 实在没有扣号，就识别扣名基本文本
            t = 4
            for r in a4:
                kc, vol_fold = r[:3]
                items.append((kc, vol_fold, 0))
    return items, t


def split_name(text, t=0):
    """拆分文本到各扣，t 来自 parse_name"""
    text = re_clean.sub('', text or '')
    re_c = re_rules[t - 1] if 0 < t < 1 + len(re_rules) else None
    ret, m = [], None
    while text:
        if ret or re_c is None:
            for re_c in re_rules:  # 后续动态规则识别
                m = re_c.search(text)
                if m:
                    break
        else:  # 第一个子文本按之前的规则号(t>0)识别
            m = re_c.search(text)

        s = m and m.group()  # 匹配到的文本
        end_i = s and text.index(s) + len(s)
        if s:
            ret.append(re.sub(r'\n', '', text[:end_i]).strip())  # 匹配到的、前面文字也算在子文本中
        text = s and text[end_i:]  # 后续文本用于下一个子文本的提取
    return ret
