import re
import os
import sys
import os.path as osp
from rapidfuzz import fuzz
from datetime import datetime

root_dir = osp.dirname(osp.dirname(osp.abspath(__file__)))
sys.path.append(root_dir)

from util.diff import diff
from util.punc import not_newline_and_pagecode, trim_punc, get_punc_str, not_newline, not_punc, split_punc, trim_punc_and_pagecode


def get_stat_info(segments, start, end):
    """ 计算匹配的参数"""

    def is_similar(s):
        # 同文或长度相同且小于3的异文，都可认为是相似文本
        # 这个参数可以避免异体字或错别字带来的干扰
        return s['is_same'] or (s['len_diff'] == 0 and len(s['base']) < 3)

    match_segments = [s for s in segments[start:end] if s.get('match')]
    similar_segments = [s for s in match_segments if is_similar(s)]
    same_segments = [s for s in similar_segments if s['is_same']]

    # 要从segments合并base_txt，以免遗漏文本
    base_init_len = len(''.join([s['base'] for s in segments]))
    base_match_len = len(''.join([s['base'] for s in match_segments]))
    base_similar_len = len(''.join([s['base'] for s in similar_segments]))
    base_same_len = len(''.join([s['base'] for s in same_segments]))
    base_info = {
        'init_length': base_init_len, 'match_length': base_match_len,
        'similar_len': base_similar_len, 'same_length': base_same_len,
        'match_ratio': base_init_len and round(base_match_len / base_init_len, 4) or 0,
        'similar_ratio': base_init_len and round(base_similar_len / base_init_len, 4) or 0,
        'same_ratio': base_init_len and round(base_same_len / base_init_len, 4) or 0,
    }

    # 要从segments[start:end]合并cmp_txt，以免引入噪音
    cmp_init_len = len(''.join([s['cmp'] for s in segments[start:end]]))
    cmp_match_len = len(''.join([s['cmp'] for s in match_segments]))
    cmp_similar_len = len(''.join([s['cmp'] for s in similar_segments]))
    cmp_same_len = len(''.join([s['cmp'] for s in same_segments]))
    cmp_info = {
        'init_length': cmp_init_len, 'match_length': cmp_match_len,
        'similar_len': cmp_similar_len, 'same_length': cmp_same_len,
        'match_ratio': cmp_init_len and round(cmp_match_len / cmp_init_len, 4) or 0,
        'similar_ratio': cmp_init_len and round(cmp_similar_len / cmp_init_len, 4) or 0,
        'same_ratio': cmp_init_len and round(cmp_same_len / cmp_init_len, 4) or 0,
    }

    return {'base': base_info, 'cmp': cmp_info}


def check_match(segments):
    """ 检查segments匹配情况
    一、现象分析
    如果两段文本非常匹配，只有少量由于异体字或者个别字的增删改造成的不同，那么diff得到的
    segments呈现的特点是：大量的长同文，少量的短异文。如果两段文本并不匹配，那么diff得
    到的segments呈现的特点是：大量的长异文，少量的短同文。也就是说，长的同文或异文是决定
    是否匹配的关键特征。为便于算法实现，设定：
    1. 长同文/长异文：文本长度/文本差异长度 >= 10
    2. 短同文/短异文：文本长度/文本差异长度 =< 3
    3. 中同文/中异文：3 < 文本长度/文本差异长度 < 10
    二、算法设计
    1. 从前往后遍历，根据关键特征确定当前匹配状态：长同文认为是匹配，长异文认为是不匹配
    2. 短同文/短异文：随当前匹配状态
    3. 中同文：如果当前匹配状态为True，则设置状态为True，否则不做设置
    3. 中异文：如果当前匹配状态为False，则设置状态为False，否则不做设置
    * 针对前几条segment，如果某条segment base长度小于15而cmp不匹配的长度大于30，这条之前都作为不匹配
    """
    # 检查前10条，寻找关键不匹配segment，在此之前都作为不匹配
    limit = 10
    match_indexes = [i for i, s in enumerate(segments[:limit]) if s['is_same'] and len(s['base']) >= 15]
    if match_indexes:
        limit = match_indexes[0]
    last, curr_status = -1, None
    mismatch_indexes = [i for i, s in enumerate(segments[:limit]) if not s['is_same'] and len(s['cmp']) > 30]
    if mismatch_indexes:
        last, curr_status = mismatch_indexes[-1], False
        for seg in segments[0:last]:
            seg['match'] = False

    # 按照算法检查后续的segment
    match_indexes = []
    for i, seg in enumerate(segments):
        if i < last:
            continue
        if seg['is_same']:  # 同文
            if len(seg['base']) >= 10:  # 长同文
                curr_status = seg['match'] = True
            elif len(seg['base']) <= 3:  # 短同文
                seg['match'] = curr_status
            else:  # 中同文
                if curr_status:
                    seg['match'] = True
                else:
                    curr_status = None
        else:  # 异文
            if abs(seg['len_diff']) >= 10:  # 长异文
                seg['match'] = False
                if i != 0:  # 忽略掉第一条长异文
                    curr_status = False
            elif abs(seg['len_diff']) <= 3:  # 短异文
                seg['match'] = curr_status
            else:  # 中异文
                if curr_status is False:
                    seg['match'] = False
                else:
                    curr_status = None
        if seg.get('match'):
            match_indexes.append(i)
    if not match_indexes:
        return segments, 0, 0

    start, end = match_indexes[0], match_indexes[-1] + 1
    # 往前追溯，把start之前match为None的seg都包括进来
    for i, seg in enumerate(segments[:start][::-1]):
        if seg.get('match') is None:
            seg['match'] = True
            start -= 1
        else:
            break
    # 如果start的base为空，则往后移一个
    if segments[start]['base'] == '':
        segments[start]['match'] = False
        start += 1

    # 将segments[start-1]右侧的开始标点移至segments[start]
    if start >= 1:
        pre = segments[start - 1]
        pre['cmp0'], part1, _ = split_punc(pre['cmp0'], 'right', 'start')
        segments[start]['cmp0'] = part1 + segments[start]['cmp0']

    # 将segments[end-1]的开始标点去掉
    if end > 1:
        last = segments[end - 1]
        last['cmp0'], _, _ = split_punc(last['cmp0'], 'right', 'end')

    return segments, start, end


def exact_find_match(txt1, txt2, refind=True):
    """ 从txt2中查找与txt1最匹配的文本，txt2比txt1略长（不超过txt1长度的3倍）
    算法设计思路：
    1. 利用diff函数比较两段文本，得到segments
    2. 检查首尾连续不匹配的segment，返回中间连续匹配的segment
    算法设计关键：
    1. 如果两段文本并不匹配，只有个别字相同，那么diff得到的segments，呈现的特点是：大量的长异文，少量的短同文。
    2. 如果两段文本高度匹配，只有个别字不同，那么diff得到的segments，呈现的特点是：大量的长同文，少量的短异文。
    center_char_cnt：版心列字符的长度。如果txt含版心列，那么在计算匹配率时，需要去掉这个长度
    """
    # 进行diff比对
    segments = diff(txt1, txt2, not_newline, not_newline_and_pagecode)
    # 检查segments匹配情况
    segments, start, end = check_match(segments)
    # 针对长异文进行二次查找
    refind_len = 0
    long_mismatch_segs = [s for s in segments[start:end] if not s.get('match') and abs(s['len_diff']) > 10]
    if refind and len(long_mismatch_segs):
        for seg in long_mismatch_segs:
            if len(seg['base']) < len(seg['cmp']):
                seg['cmp0'] = '■' * len(seg['base'])
            else:
                r = find_best_match(seg['base0'], txt2, False)
                _match_txt, _long_mismatch_segs = trim_punc(r[0]), r[-1]
                if len(_long_mismatch_segs) == 0 and len(_match_txt) - len(seg['base']) < 50:
                    seg['match'] = True
                    seg['cmp0'] = r[0]
                    seg['cmp'] = _match_txt
                    refind_len += len(seg['base'])
                else:
                    seg['match'] = False
                    seg['cmp'] = seg['cmp0'] = '■' * len(seg['base'])

    # 计算返回值
    match_txt = ''.join([s['cmp0'] for s in segments[start:end]])
    stat = get_stat_info(segments, start, end)

    return match_txt, stat, refind_len, segments, start, end, long_mismatch_segs


def fuzzy_find_match(txt1, txt2, max_steps=10000, long_cut=True):
    """ 在大文本txt2范围内粗略查找小文本txt1，找到最匹配的文本段
    算法设计思路：
    1. 将txt2以step为步长进行分段，每段segment长度window_size。
    2. 遍历各段，从中找到最大匹配率的segment。
    算法设计关键：
    1. 设置step和window_size，必须保证目标文本在某个segment中，而不会被切断
    long_cut：如果txt1超长，则将切断后查找txt2，找到结果后，再在txt2中直接按切断后的长度进行补充
    注：返回segment的长度为txt1的size倍
    """
    # 清除标点，以免干扰
    _txt1, _txt2 = trim_punc(txt1), trim_punc(txt2)

    # 限制_txt1的长度，避免过长导致性能问题
    limit, _txt1_ = 10000, _txt1
    if long_cut and len(_txt1) > limit:
        _txt1_ = _txt1[:limit]

    # 设置step和window_size
    ratio = 0.5 if (len(_txt1_) < 5000) else 1
    step_len = int(len(_txt1_) * ratio) or 1
    # window_size > len(_txt1) + step，才可以保证不遗漏
    window_size = len(_txt1_) + step_len + 10
    steps = min(len(_txt2) // step_len, max_steps)

    # 遍历查找
    best_segment, best_score, best_start = '', 0, 0
    for i in range(0, steps):
        segment = _txt2[i * step_len:i * step_len + window_size]
        gap = window_size - len(segment)
        if gap > 0:
            # 补齐长度，以便ratio更准确，否则从JS_1_82页文本中查找SX_1_4_57页文本会失败
            segment += '■' * gap
        # partial_ratio更符合要求但是性能太慢，因此用ratio
        # score = fuzz.partial_ratio(_txt1, segment)
        score = fuzz.ratio(_txt1_, segment)
        if score > best_score:
            best_segment, best_score, best_start = segment, score, i * step_len
            if gap > 0:
                best_segment = segment.rstrip('■')

    # 如果被截断，则直接还原
    if long_cut and len(_txt1) > limit:
        end = best_start + len(best_segment)
        best_segment += _txt2[end:end + len(_txt1) - limit]

    # 还原至未清除标点前的文本
    punc_str = get_punc_str(True)
    start = best_start  # 从best_start开始找起，直到找到best_start个非标点的文字作为起点
    cnt = len(trim_punc(txt2[:best_start]))  # 当前非标点文字的数量
    for i, s in enumerate(txt2[best_start:]):
        if s not in punc_str:
            cnt += 1
        if cnt == best_start:  # 找到best_start个非标点文字，结束
            start = best_start + i + 1
            break
    end = start  # 从start开始算起，找到len(best_segment)个非标点文字作为结束
    cnt = len(trim_punc(txt2[:start]))  # 当前非标点文字的数量
    for i, s in enumerate(txt2[start:]):
        if s not in punc_str:
            cnt += 1
        if cnt == best_start + len(best_segment):  # 找到best_start + len(best_segment)个非标点文字，结束
            end = start + i + 1
            break
    match_segment = txt2[start:end]
    # assert trim_punc(match_segment) == best_segment

    return match_segment, best_score, start


def find_best_match(txt1, txt2, refinded=True):
    """ 从txt2中找到与txt1最匹配的文本"""
    if not txt2:
        return '', {'base': {'match_ratio': 0}}, False, []

    fuzzy_txt = txt2
    # txt2的长度 > txt1的2倍时，先进行模糊查找
    if len(txt2) > len(txt1) * 2:
        fuzzy_txt, score, start = fuzzy_find_match(txt1, txt2)
    # 精确查找匹配的文本段
    # exact_find_match会回调find_best_match
    # 要用到find_best_match返回值的match_txt, long_mismatch_segs
    ret = exact_find_match(txt1, fuzzy_txt, refinded)

    return ret


def main():
    txt1 = open(osp.join(root_dir, 'tests/data/大般若经第四卷-JS_1_5卷文本.txt'), 'r').read()
    # txt1 = open(osp.join(root_dir, 'tests/data/大般若经第四卷-SX_1_4_57页文本.txt'), 'r').read()
    # txt1 = open(osp.join(root_dir, 'tests/data/大般若经第四卷-JS_1_82页文本.txt'), 'r').read()
    # txt1 = open(osp.join(root_dir, 'tests/data/大般若经第四卷-JS_1_5卷文本人工颠倒.txt'), 'r').read()
    txt2 = open(osp.join(root_dir, 'tests/data/大般若经-T0220(前10卷).txt'), 'r').read()
    print(f'[{datetime.now()}]txt1长度: {len(txt1)}, txt2长度: {len(txt2)}')
    ret = find_best_match(txt1, txt2)
    print(f'[{datetime.now()}]匹配率: {ret[1]}')


if __name__ == "__main__":
    main()
