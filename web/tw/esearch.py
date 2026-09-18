import re
import sys
from os import path
from elasticsearch import Elasticsearch

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

import helper as hp
from util.diff import diff
from util.punc import get_punc_str, trim_cbeta_whitespace


def get_hosts():
    config = hp.load_config() or {}
    return [config and config.get('esearch') or dict(host='es')]


def find(query, size=None, index='cbeta-ik'):
    try:
        body = {'query': query}
        if size:
            body['size'] = size
        es = Elasticsearch(hosts=get_hosts())
        r = es.search(index=index, body=body)
        return r['hits']['hits']
    except Exception as e:
        print("[%s]%s." % (e.__class__.__name__, str(e)))


def find_page(volume_id, sn, index='cbeta-ik'):
    query = {'bool': {'must': [
        {'term': {'volume_id.keyword': volume_id}},
        {'term': {'sn': sn}},
    ]}}
    r = find(query, 1, index)
    return r[0]['_source'] if r else None


def find_txt(txt, sutra_id='', size=None, index='cbeta-ik'):
    query = {'match': {'txt': txt}}
    if sutra_id:
        query = {'bool': {'must': [
            {'match': {'txt': txt}},
            {'terms': {'sutra_id.keyword': sutra_id.split(',')}},
        ]}}

    return find(query, size, index)


def find_reel_txt(reel_code, index='jsz-ik-reel'):
    """
    从ES获取整卷文本
    """
    query = {
        "term": {
            "page_ids.keyword": reel_code
        }
    }
    r = find(query, size=1, index=index)
    return r[0] if r and r[0].get('_source') else None


def check_segments_v1(segments):
    # 检查左边
    limit = min(8, int(len(segments) / 2))
    left = {'pos': 0, 'fulfilled': True}
    left_segs = sorted(segments[:limit], key=lambda x: abs(x['len_diff']), reverse=True)
    if abs(left_segs[0]['len_diff']) > 10:  # 异文长度差异大于10
        left = {'pos': left_segs[0]['no'], 'fulfilled': left_segs[0]['len_diff'] < 0}
    # 检查右边
    right = {'pos': 0, 'fulfilled': True}
    right_segs = sorted(segments[-limit:], key=lambda x: abs(x['len_diff']), reverse=True)
    if abs(right_segs[0]['len_diff']) > 10:  # 异文长度差异大于10
        right = {'pos': right_segs[0]['no'], 'fulfilled': right_segs[0]['len_diff'] < 0}

    match_txt = ''.join([s['cmp0'] for s in segments[left['pos']:right['pos'] + 1]])
    return left, right, match_txt


def check_segments_v2(segments):
    txt = ''.join([s['base'] for s in segments])
    limit = min(20, int(len(txt) / 2))
    # 检查左边
    left_segs, start = [], 0
    for seg in segments:
        if abs(seg['len_diff']) < 3:  # 寻找连续「len_diff<3」的seg
            left_segs.append(seg)
            if len(''.join([s['base'] for s in left_segs])) > limit:
                start = left_segs[0]['no']
                break
        else:
            left_segs = []
    miss_txt = ''.join([s['base0'] for s in segments[:start]])
    fulfilled = len(''.join([s['base'] for s in segments[:start]])) < limit
    left = {'pos': start, 'miss_txt': miss_txt, 'fulfilled': fulfilled}
    # 检查右边
    right_segs, end = [], len(segments) - 1
    for seg in segments[::-1]:
        if abs(seg['len_diff']) < 3:
            right_segs.append(seg)
            if len(''.join([s['base'] for s in right_segs])) > limit:
                end = right_segs[0]['no'] + 1
                break
        else:
            right_segs = []
    miss_txt = ''.join([s['base0'] for s in segments[end:]])
    fulfilled = len(''.join([s['base'] for s in segments[end:]])) < limit
    right = {'pos': end, 'miss_txt': miss_txt, 'fulfilled': fulfilled}

    match_txt = ''.join([s['cmp0'] for s in segments[start:end]])
    return left, right, match_txt


def check_segments_v3(segments):
    txt = ''.join([s['base'] for s in segments])
    limit = min(10, int(len(txt) / 2))
    same_segs = [s for s in segments if s['is_same'] and len(s['base']) > limit]
    # 检查左边
    start = 0
    if same_segs:
        start = same_segs[0]['no']
        if start > 0:
            for seg in segments[start - 1::-1]:
                if abs(seg['len_diff']) < 3:
                    start = seg['no']
                else:
                    break
    if start >= 2 and abs(segments[start - 1]['len_diff']) <= 10 and \
            segments[start - 2]['is_same'] and len(segments[start - 2]['base']) >= 3:
        start -= 2
    miss_txt = ''.join([s['base0'] for s in segments[:start]])
    fulfilled = len(''.join([s['base'] for s in segments[:start]])) < limit
    left = {'pos': start, 'miss_txt': miss_txt, 'fulfilled': fulfilled}
    # 检查右边
    end = len(segments) - 1
    if same_segs:
        end = same_segs[-1]['no'] + 1
        if end < len(segments) - 1:
            for seg in segments[end:]:
                if abs(seg['len_diff']) < 3:
                    end = seg['no'] + 1
                else:
                    break
    if end <= len(segments) - 3 and abs(segments[end + 1]['len_diff']) <= 10 and \
            segments[end + 2]['is_same'] and len(segments[end + 2]['base']) >= 3:
        end += 2
    miss_txt = ''.join([s['base0'] for s in segments[end:]])
    fulfilled = len(''.join([s['base'] for s in segments[end:]])) < limit
    right = {'pos': end, 'miss_txt': miss_txt, 'fulfilled': fulfilled}
    segments = segments[start:end]
    match_txt = ''.join([s['cmp0'] for s in segments])
    return left, right, match_txt, segments


def filter_cbeta(txt):
    # txt = txt.replace('\n', '¶')
    txt = re.sub(r'[\-\.\{\},0-9a-zA-Z_\-#Ω￥%&*◎\f\t\v ]+', '', txt)
    txt = re.sub(r'\[[+-@*\(\)\/\u2E80-\U0002FFFF]+\]', '※', txt)  # 组字式
    txt = trim_cbeta_whitespace(txt)
    return txt


def find_match(txt, sutra_id='', reverse=True, index='cbeta-ik'):
    """从es文中找出与txt匹配的文本"""
    items = find_txt(txt, sutra_id, 10, index)
    if not items:
        return {}

    punc_str = get_punc_str(True)

    matches = []
    for item in items:
        page = item['_source']
        cbeta_txt = filter_cbeta(page['txt'])
        segments = diff(txt, cbeta_txt, lambda x: x != '\n', lambda x: x not in punc_str, True, True)
        r1 = len(''.join([s['base'] for s in segments if s.get('is_same') or (
                len(s['base']) == 1 and len(s['cmp']) == 1)])) / len(txt)
        r2 = len(''.join([s['base'] for s in segments if s.get('is_same')])) / len(txt)
        matches.append({'pages': [page], 'segments': segments, 'ratio': [r1, r2]})
    matches.sort(key=lambda x: x['ratio'], reverse=True)

    # 1.检查结果
    match = matches[0]
    if match['ratio'][1] < 0.3:
        return {}
    left, right, match['match_txt'], match['segments'] = check_segments_v3(match['segments'])
    if (left['fulfilled'] and right['fulfilled']) or not reverse:
        return match

    # 2.检查前一页
    page = match['pages'][0]
    cbeta_txt = page['txt']
    if not left['fulfilled']:
        pre_page = find_page(page['volume_id'], page['sn'] - 1, index)
        if pre_page and pre_page['txt']:
            cbeta_txt = filter_cbeta(pre_page['txt']) + cbeta_txt
            segments = diff(txt, cbeta_txt, lambda x: x != '\n', lambda x: x not in punc_str, True, True)
            left, right, match['match_txt'], match['segments'] = check_segments_v3(segments)
            match.update({'pages': [pre_page] + match['pages']})
            if (left['fulfilled'] and right['fulfilled']) or not reverse:
                return match
    # 3.检查后一页
    if not right['fulfilled']:
        next_page = find_page(page['volume_id'], page['sn'] + 1, index)
        if next_page and next_page['txt']:
            cbeta_txt = cbeta_txt + filter_cbeta(next_page['txt'])
            segments = diff(txt, cbeta_txt, lambda x: x != '\n', lambda x: x not in punc_str, True, True)
            left, right, match['match_txt'], match['segments'] = check_segments_v3(segments)
            match.update({'pages': match['pages'] + [next_page]})
            if (left['fulfilled'] and right['fulfilled']) or not reverse:
                return match

    # 4.自由查找前后未命中文本
    if not left['fulfilled']:
        match1 = find_match(left['miss_txt'], '', False, index)
        if match1:
            match['match_txt'] = match1['match_txt'] + match['match_txt']
            match['pages'] = match1['pages'] + match['pages']
    if not right['fulfilled']:
        match2 = find_match(right['miss_txt'], '', False, index)
        if match2:
            match['match_txt'] = match['match_txt'] + match2['match_txt']
            match['pages'] = match['pages'] + match2['pages']
    segments = diff(txt, match['match_txt'], lambda x: x != '\n', lambda x: x not in punc_str, True, True)
    left, right, match['match_txt'], match['segments'] = check_segments_v3(segments)
    return match
