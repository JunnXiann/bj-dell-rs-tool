import json
from os import path as osp
import os
from util.uni2std import is_family
from util.uni2std import normalize as vt_normalize
from .diff_ import CSequenceMatcher


def get_pos(txt, is_txt, n, most=True):
    """ 获取第n个字的位置
        most为False表示返回地n个字的位置
        most为True表示返回n+1个字之前的位置
    """
    cnt = 0  # 命中次数
    for i, t in enumerate(txt):
        if is_txt(t):
            cnt += 1
        if not most and cnt == n:
            return i
        if most and cnt == n + 1:
            return i - 1

    return len(txt)


def get_txt(txt, is_txt, length, start=0, most=True):
    """ 获取符合条件的文本断落，类似于txt[start:end]"""
    if not is_txt:
        return ''
    pos = get_pos(txt[start:], is_txt, length, most)
    return txt[start:start + pos + 1]


def check_head_segments_duplicated(segments, base_key='base', cmp_key='cmp'):
    """检查前3个segment是否含重文，如含，则进行重置"""
    if len(segments) < 3:
        return segments

    # 检查第一个同文与之后的异文是否为重文
    pos = 0 if segments[0]['is_same'] else 1
    curr, after = segments[pos], segments[pos + 1]
    idx = after[cmp_key].rfind(curr[cmp_key])
    if idx != -1:  # 找到重文
        same_txt = curr[cmp_key]
        # 先将这两个segment的base和cmp拆分为三段，异同关系依次是False,True,False
        base_list = ['', same_txt, after[base_key]]
        cmp_list = [curr[cmp_key] + after[cmp_key][:idx], same_txt, after[cmp_key][idx + len(same_txt):]]
        # 然后再整合到整个的segments中
        if pos > 0:  # 如果pos > 0，则与之前的segment合并
            pre = segments[pos - 1]
            pre.update({cmp_key: pre[cmp_key] + cmp_list[0]})
        else:  # 否则，在前面添加一个segment
            segments.insert(0, {'is_same': False, base_key: base_list[0], cmp_key: cmp_list[0]})
        curr.update({cmp_key: cmp_list[1]})
        after.update({cmp_key: cmp_list[2]})
    return segments

def fuzzy_find(haystack, needle):
    """
    类似于str.find，但只允许单个字符的不连续mismatch（不允许连续mismatch，数量不限）。
    返回第一个匹配的起始索引，未找到返回-1。
    """
    n, m = len(haystack), len(needle)
    if m == 0 or m > n:
        return -1
    if m == 1:
        idx = haystack.find(needle)
        if idx == -1:
            # print(f"Fuzzy finding '{needle}' in '{haystack}'")
            return -2  # Special marker for single char not found
        return idx
    if m < 4:
        # For short needles (2 or 3), require exact match (no fuzzy tolerance).
        return haystack.find(needle)  # returns -1 if not found
    for i in range(n - m + 1):
        window = haystack[i:i + m]
        j = 0
        while j < m:
            if window[j] != needle[j]:
                # Check if this is a block of mismatches
                k = j
                while k < m and window[k] != needle[k]:
                    k += 1
                if k - j > 1:
                    break  # Block of mismatches, not allowed
                j = k  # Skip the mismatched char
            else:
                j += 1
        else:
            # All mismatches are isolated single characters
            return i
    return -1

def get_segments_by_csm(base, cmp, base_key='base', cmp_key='cmp', normalize=True, reset_same=None):
    """
    使用CSequenceMatcher对base和cmp进行比对，返回segments列表。
    支持单字同族(is_family)和自定义reset_same校准is_same。
    """
    segments = []
    cs = CSequenceMatcher(None, base, cmp, autojunk=False)
    for tag, i1, i2, j1, j2 in cs.get_opcodes():
        _base, _cmp = base[i1:i2], cmp[j1:j2]
        seg = {'is_same': tag == 'equal', base_key: _base, cmp_key: _cmp}
        # 校准is_same
        if not seg['is_same'] and normalize and len(_base) == 1 and len(_cmp) == 1:
            seg['is_same'] = is_family(_base, _cmp)
        if not seg['is_same'] and reset_same:
            seg['is_same'] = reset_same(_base, _cmp)
        segments.append(seg)
    return segments

def repair_mid_repeats(segments, base_key='base', cmp_key='cmp',
                       min_len_diff=50):
    """Repair mid-document repetitive-paragraph misalignments.
    Look for pattern: diff (large len_diff), small equal, diff (similar large len_diff).
    Merge the three segments and re-diff the combined window to get a better segmentation.
    """

    i = 0
    while i <= len(segments) - 3:
        a, b, c = segments[i], segments[i+1], segments[i+2]
        if (not a.get('is_same') and b.get('is_same') and not c.get('is_same')):
            lendiff_a = len(a.get(base_key, '')) - len(a.get(cmp_key, ''))
            if abs(lendiff_a) >= min_len_diff:
                idx = fuzzy_find(a[base_key], b[base_key])
                if idx == -2:
                    if i + 3 < len(segments):
                        d = segments[i + 3]
                        merged_cmp = b[cmp_key] + c[cmp_key] + d[cmp_key]
                        merged_base = a[base_key] + b[base_key] + c[base_key]
                        idx2 = fuzzy_find(merged_base, merged_cmp)
                        idx = 0 if idx2 != -1 else -1
                    else:
                        idx = -1
                if idx != -1:
                    same_txt = b[base_key] # 若
                    base_list = [a[base_key][:idx], # 為緣所生諸受
                                 a[base_key][idx:idx + len(same_txt)], # 若
                                 a[base_key][idx + len(same_txt):] + b[base_key] + c[base_key]] # 作有量無量不作有量無量於眼界若作廣狹不作廣狹於色....
                    cmp_list = [a[cmp_key][:idx], # 法處
                                b[base_key], # 若
                                c[cmp_key]] # 

                    #Re-diff
                    same_txt_rediff = get_segments_by_csm(base_list[1], cmp_list[1], base_key, cmp_key)
                    leftover_rediff = get_segments_by_csm(base_list[2], cmp_list[2], base_key, cmp_key)

                    #Rebuild segments
                    new_segs = []
                    if base_list[0]:
                        new_segs.append({base_key: base_list[0], cmp_key: cmp_list[0], 'is_same': False})

                    for _, seg in enumerate(same_txt_rediff):
                        new_segs.append(seg)

                    for _, seg in enumerate(leftover_rediff):
                        new_segs.append(seg)

                    for j, seg in enumerate(new_segs):
                        pre = j and new_segs[j - 1]
                        if not pre:
                            continue
                        if pre['is_same'] == seg['is_same']:
                            seg[base_key] = pre[base_key] + seg[base_key]
                            seg[cmp_key] = pre[cmp_key] + seg[cmp_key]
                            pre['merged'] = True
                    result_segs = [s for s in new_segs if s.get('merged') is not True]

                    #Replace segments
                    segments = segments[:i] + result_segs + segments[i+3:]
                    #Restart from previous segment
                    i = max(i - 1, 0)
                    continue
        i += 1
    return segments

def diff(base, cmp, is_base=None, is_cmp=None, restore=True, normalize=True,
         base_key='base', cmp_key='cmp', reset_same=None):
    """ 文本比对
        is_base, is_cmp 用于过滤掉不需要比较的字符
        restore 表示是否将base和cmp还原为原始文本
    """
    base0, cmp0 = base, cmp
    if is_base:
        base = ''.join([t for t in base if is_base(t)])
    if is_cmp:
        cmp = ''.join([t for t in cmp if is_cmp(t)])
    if normalize:
        base = vt_normalize(base)
        cmp = vt_normalize(cmp)
    # 根据diff获取segments
    segments = []
    cs = CSequenceMatcher(None, base, cmp, autojunk=False)
    for tag, i1, i2, j1, j2 in cs.get_opcodes():
        _base, _cmp = base[i1:i2], cmp[j1:j2]
        seg = {'is_same': tag == 'equal', base_key: _base, cmp_key: _cmp}
        # 校准is_same
        if not seg['is_same'] and normalize and len(_base) == 1 and len(_cmp) == 1:
            seg['is_same'] = is_family(_base, _cmp)
        if not seg['is_same'] and reset_same:
            seg['is_same'] = reset_same(_base, _cmp)
        segments.append(seg)
    # 合并连续的同文或异文
    for i, seg in enumerate(segments):
        pre = i and segments[i - 1]
        if not pre:
            continue
        if pre['is_same'] == seg['is_same']:
            seg[base_key] = pre[base_key] + seg[base_key]
            seg[cmp_key] = pre[cmp_key] + seg[cmp_key]
            pre['merged'] = True
    segments = [s for s in segments if s.get('merged') is not True]

    # 检查并重置重文
    segments = check_head_segments_duplicated(segments, base_key, cmp_key)
    segments = repair_mid_repeats(segments, base_key=base_key, cmp_key=cmp_key)

    # 设置其余字段
    s_b, s_c = 0, 0
    for i, seg in enumerate(segments):
        # 设置no和len_diff
        seg.update({'no': i, 'len_diff': len(seg[base_key]) - len(seg[cmp_key]),
                    'range': [s_b, s_b + len(seg[base_key])]})
        # 设置base0、cmp0
        if restore and is_base:
            _base0 = get_txt(base0, is_base, len(seg[base_key]), s_b)
            seg[f'{base_key}0'] = _base0
            s_b += len(_base0)
        if restore and is_cmp:
            _cmp0 = get_txt(cmp0, is_cmp, len(seg[cmp_key]), s_c)
            seg[f'{cmp_key}0'] = _cmp0
            s_c += len(_cmp0)

    return segments


def repair_mid_repeats_v2(segments, base, cmp, base_key='base', cmp_key='cmp', min_len_diff=50):
    """
    Repair mid-document repetitive-paragraph misalignments for diff_v2 segments.
    Preserves and updates i1, i2, j1, j2 for each segment.
    """
    i = 0
    while i <= len(segments) - 3:
        a, b, c = segments[i], segments[i+1], segments[i+2]
        if (not a.get('is_same') and b.get('is_same') and not c.get('is_same')):
            lendiff_a = len(a.get(base_key, '')) - len(a.get(cmp_key, ''))
            if abs(lendiff_a) >= min_len_diff:
                idx = fuzzy_find(a[base_key], b[base_key])
                if idx == -2:
                    if i + 3 < len(segments):
                        d = segments[i + 3]
                        merged_cmp = b[cmp_key] + c[cmp_key] + d[cmp_key]
                        merged_base = a[base_key] + b[base_key] + c[base_key]
                        idx2 = fuzzy_find(merged_base, merged_cmp)
                        idx = idx2 if idx2 != -1 else -1 # 21/1/2026 changed from idx = 0 if idx2 != -1 else -1
                    else:
                        idx = -1
                if idx != -1:
                    old_tail = segments[i+3:]
                    old_end_i2 = segments[i+2]['i2']
                    old_end_j2 = segments[i+2]['j2']

                    same_txt = b[base_key]
                    # Calculate split positions in base and cmp
                    a_i1, _, a_j1, _ = a['i1'], a['i2'], a['j1'], a['j2']
                    base_list = [a[base_key][:idx], a[base_key][idx:idx + len(same_txt)], a[base_key][idx + len(same_txt):] + b[base_key] + c[base_key]]
                    cmp_list = [a[cmp_key], b[base_key], c[cmp_key]] # 22/1/2026 cmp_list = [a[cmp_key][:idx], b[base_key], c[cmp_key]]

                    same_txt_rediff = get_segments_by_csm(base_list[1], cmp_list[1], base_key, cmp_key)
                    leftover_rediff = get_segments_by_csm(base_list[2], cmp_list[2], base_key, cmp_key)

                    base_start = a_i1
                    cmp_start = a_j1

                    new_segs = []
                    # Rebuild segments with updated indices
                    if base_list[0]:
                        new_segs.append({
                            base_key: base_list[0],
                            cmp_key: cmp_list[0],
                            'is_same': False,
                            'i1': base_start,
                            'i2': base_start + len(base_list[0]),
                            'j1': cmp_start,
                            'j2': cmp_start + len(cmp_list[0]),
                        })
                        base_start += len(base_list[0])
                        cmp_start += len(cmp_list[0])

                    for seg in same_txt_rediff:
                        seg.update({
                            'i1': base_start,
                            'i2': base_start + len(seg[base_key]),
                            'j1': cmp_start,
                            'j2': cmp_start + len(seg[cmp_key]),
                        })
                        new_segs.append(seg)
                        base_start += len(seg[base_key])
                        cmp_start += len(seg[cmp_key])

                    for seg in leftover_rediff:
                        seg.update({
                            'i1': base_start,
                            'i2': base_start + len(seg[base_key]),
                            'j1': cmp_start,
                            'j2': cmp_start + len(seg[cmp_key]),
                        })
                        new_segs.append(seg)
                        base_start += len(seg[base_key])
                        cmp_start += len(seg[cmp_key])

                    # Merge consecutive segments with the same is_same status
                    result_segs = []
                    for seg in new_segs:
                        if result_segs and result_segs[-1]['is_same'] == seg['is_same']:
                            result_segs[-1][base_key] += seg[base_key]
                            result_segs[-1]['i2'] = seg['i2']
                            result_segs[-1][cmp_key] += seg[cmp_key]
                            result_segs[-1]['j2'] = seg['j2']
                        else:
                            result_segs.append(seg)

                    # Replace segments
                    segments = segments[:i] + result_segs + old_tail

                    new_end_i2 = result_segs[-1]['i2']
                    new_end_j2 = result_segs[-1]['j2']
                    delta_i = new_end_i2 - old_end_i2
                    delta_j = new_end_j2 - old_end_j2

                    if delta_i != 0 or delta_j != 0:
                        for seg in segments[i + len(result_segs):]:
                            seg['i1'] += delta_i
                            seg['i2'] += delta_i
                            seg['j1'] += delta_j
                            seg['j2'] += delta_j

                    i = max(i - 1, 0)
                    continue
        i += 1
    return segments


def diff_v2(base, cmp, is_base=None, is_cmp=None, restore=True, normalize=True, reset_same=None,
            page_size=10000, base_key='base', cmp_key='cmp'):
    """ 分段文本比对"""
    base0, cmp0 = base, cmp
    if is_base:
        base = ''.join([t for t in base if is_base(t)])
    if is_cmp:
        cmp = ''.join([t for t in cmp if is_cmp(t)])
    if normalize:
        base = vt_normalize(base)
        cmp = vt_normalize(cmp)

    # 1. 分段循环比对
    s_b, s_c = 0, 0
    segments, idx = [], 0
    len_b, len_c = len(base), len(cmp)
    
    while s_b < len_b and s_c < len_c:
        _segments = []
        _base, _cmp = base[s_b: s_b + page_size], cmp[s_c: s_c + page_size]
        sc = CSequenceMatcher(None, _base, _cmp, autojunk=False)
        for tag, i1, i2, j1, j2 in sc.get_opcodes():
            seg = {'i1': s_b + i1, 'i2': s_b + i2, 'j1': s_c + j1, 'j2': s_c + j2,
                   'is_same': tag == 'equal', base_key: _base[i1:i2], cmp_key: _cmp[j1:j2]}
            # 校准is_same
            # if not seg['is_same'] and normalize and len(seg[base_key]) == 1 and len(seg[cmp_key]) == 1:
            #     seg['is_same'] = is_family(seg[base_key], seg[cmp_key])
            # if not seg['is_same'] and reset_same:
            #     seg['is_same'] = reset_same(seg[base_key], seg[cmp_key])
            _segments.append(seg)
        # 最后一个seg为异文时，予以弹出，放在下一次循环中处理
        last = _segments[-1]
        if len(_segments) > 1 and not last['is_same'] and last['i2'] < len_b and last['j2'] < len_c:
            _segments.pop()
        # 前大段最后的seg与后大段第一个seg的is_same相同时，予以合并
        first = _segments[0]
        if segments and segments[-1]['is_same'] == first['is_same']:
            segments[-1][base_key] += first[base_key]
            segments[-1]['i2'] = first['i2']
            segments[-1][cmp_key] += first[cmp_key]
            segments[-1]['j2'] = first['j2']
            _segments = _segments[1:]
        segments.extend(_segments)
        # 更新循环参数
        s_b, s_c = segments[-1]['i2'], segments[-1]['j2']
        idx += 1
    # 2. 处理循环溢出
    if s_b < len_b or s_c < len_c:
        seg = {'i1': s_b, 'i2': len_b, 'j1': s_c, 'j2': len_c,
               'is_same': base[s_b:] == cmp[s_c:], base_key: base[s_b:], cmp_key: cmp[s_c:]}
        segments.append(seg)
    # 3. 合并连续的相同性质seg
    for i, seg in enumerate(segments):
        if not i:
            continue
        pre = segments[i - 1]
        if seg['is_same'] == pre['is_same']:
            pre[base_key] += seg[base_key]
            pre['i2'] = seg['i2']
            pre[cmp_key] += seg[cmp_key]
            pre['j2'] = seg['j2']
            seg['deleted'] = True
    segments = [seg for seg in segments if not seg.get('deleted')]
    
    segments = repair_mid_repeats_v2(segments, base, cmp, base_key=base_key, cmp_key=cmp_key)

    # 4. 恢复原文
    if restore and is_base:
        start = 0
        for i, seg in enumerate(segments):
            seg[f'{base_key}0'] = get_txt(base0, is_base, seg['i2'] - seg['i1'], start)
            start += len(seg[f'{base_key}0'])
    if restore and is_cmp:
        start = 0
        for i, seg in enumerate(segments):
            seg[f'{cmp_key}0'] = get_txt(cmp0, is_cmp, seg['j2'] - seg['j1'], start)
            start += len(seg[f'{cmp_key}0'])
    # 5. 补充其他信息
    for i, seg in enumerate(segments):
        seg.update({'no': i + 1, 'range': [seg['i1'], seg['i2']], 'len_diff': len(seg[base_key]) - len(seg[cmp_key])})
        for k in ['i1', 'i2', 'j1', 'j2']:
            seg.pop(k, 0)

    return segments


def combine_ranges_by_merge(ranges):
    ranges = sorted(ranges, key=lambda x: x[0])
    res = [ranges[0]]
    for r in ranges[1:]:
        pre = res[-1]
        if r[0] <= pre[1]:
            pre[1] = max(pre[1], r[1])
        else:
            res.append(r)
    return res


def combine_ranges_by_split(ranges):
    ranges.sort(key=lambda x: x[0])
    res = [ranges[0]]
    for r in ranges[1:]:
        pre = res[-1]
        if r[0] <= pre[1]:
            pre[1] = r[0]
        res.append(r)
    return res


def reset_segments(segments, diff_ranges):
    keys = [k for k, v in segments[0].items() if isinstance(v, str)]
    assert len(keys) == 2
    # 先拆分
    segs, idx = [], 0
    for s, e in diff_ranges:
        finished = False  # 当前(s, e)是否已处理完
        while idx < len(segments) and not finished:
            seg = segments[idx]
            _s, _e = seg['range']
            if _s <= s:
                if _e <= s:  # (_s, _e)在(s, e)的左边
                    segs.append(seg)
                    idx += 1
                elif s < _e <= e:  # (_s, _e)左交于(s, e)
                    if _s < s:
                        sub1 = {k: (v[0: s - _s] if isinstance(v, str) else v) for k, v in seg.items()}
                        sub1['range'] = [_s, s]
                        segs.append(sub1)
                    sub2 = {k: (v[s - _s:] if isinstance(v, str) else v) for k, v in seg.items()}
                    sub2.update({'range': [s, _e], 'is_same': False})
                    segs.append(sub2)
                    finished = _e == e
                    idx += 1
                    s = _e
                elif e < _e:  # (_s, _e)包围(s, e)
                    if _s < s:
                        sub1 = {k: (v[0: s - _s] if isinstance(v, str) else v) for k, v in seg.items()}
                        sub1['range'] = [_s, s]
                        segs.append(sub1)
                    sub2 = {k: (v[s - _s: e - _s] if isinstance(v, str) else v) for k, v in seg.items()}
                    sub2.update({'range': [s, e], 'is_same': False})
                    segs.append(sub2)
                    segments[idx] = {k: (v[e - _s: _e - _s] if isinstance(v, str) else v) for k, v in seg.items()}
                    segments[idx]['range'] = [e, _e]
                    finished = True
            elif s < _s:
                if _e <= e:  # (s, e)包围(_s, _e)
                    seg['is_diff'] = True
                    segs.append(seg)
                    finished = _e == e
                    s = _e
                    idx += 1
                elif e < _e:  # (_s, _e)右交于(s, e)
                    sub1 = {k: (v[0: e - _s] if isinstance(v, str) else v) for k, v in seg.items()}
                    sub1.update({'range': [_s, e], 'is_same': False})
                    segs.append(sub1)
                    segments[idx] = {k: (v[e - _s:] if isinstance(v, str) else v) for k, v in seg.items()}
                    segments[idx]['range'] = [e, _e]
                    finished = True
    segs.extend(segments[idx:])
    # 再合并
    ret = [segs[0]]
    k1, k2 = keys[0], keys[1]
    for seg in segs[1:]:
        pre = ret[-1]
        if pre.get('is_same') == seg.get('is_same'):
            pre[k1] = pre[k1] + seg[k1]
            pre[k2] = pre[k2] + seg[k2]
            pre['range'] = [pre['range'][0], seg['range'][1]]
        else:
            ret.append(seg)
    last = diff_ranges[-1]
    re_ranges = [seg['range'] for seg in ret if not seg.get('is_same')]
    if last[0] == last[1] and len(re_ranges) < len(diff_ranges):
        ret.append({k1: '', k2: '', 'range': last, 'is_same': False})
        re_ranges.append(last)

    assert diff_ranges == re_ranges
    return ret


def check_segments(key2segments, base_key):
    # check size
    sizes = set([len(segments) for _, segments in key2segments.items()])
    assert len(sizes) == 1, sizes
    # check detail
    size = list(sizes)[0]
    keys = list(key2segments.keys())
    ini_key, other_keys = keys[0], keys[1:]
    for i in range(size):
        seg = key2segments[ini_key][i]
        for key in other_keys:
            _seg = key2segments[key][i]
            if seg['range'] != _seg['range']:
                print('[range]%s, %s' % (seg, _seg))
            if seg[base_key] != _seg[base_key]:
                print('[base]%s, %s' % (seg, _seg))


def merge_segments(key2segments):
    sizes = set([len(segments) for _, segments in key2segments.items()])
    assert len(sizes) == 1
    size = list(sizes)[0]
    segments = []
    keys = list(key2segments.keys())
    ini_key, other_keys = keys[0], keys[1:]
    for i in range(size):
        seg = key2segments[ini_key][i]
        for key in other_keys:
            _seg = key2segments[key][i]
            seg[key] = _seg[key]
        seg['no'] = i + 1
        seg.pop('len_diff', 0)
        segments.append(seg)
    return segments


def diff_many(key2txt, base_key):
    # 逐个比对
    range_list = []
    key2segments = {}
    base_txt = key2txt.get(base_key)
    keys = [k for k in key2txt.keys() if k != base_key]
    for k in keys:
        src_txt = key2txt.get(k)
        segments = diff_v2(base_txt, src_txt, base_key=base_key, cmp_key=k)
        key2segments[k] = segments
        range_list.extend([[s['range'][0], s['range'][1]] for s in segments if not s.get('is_same')])
    # 重置segments
    ranges = combine_ranges_by_merge(range_list)
    key2resegments = {}
    for k in keys:
        segments = key2segments.get(k)
        key2resegments[k] = reset_segments(segments, ranges)
    # 检查segments
    check_segments(key2resegments, base_key=base_key)
    # 合并segments
    segments = merge_segments(key2resegments)

    log = {'ranges': ranges, 'key2segments': key2segments, 'key2resegments': key2resegments}
    return segments, log