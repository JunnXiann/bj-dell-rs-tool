from os import path
from pymongo import UpdateOne

import sys
sys.path.insert(0, path.dirname(path.dirname(path.abspath(__file__))))

from base.base_func import with_db, make_page_no

_data = {}
fields = ['vol_fold', 'fold_no', 'vol_pdf', 'vol_ok', 'pi', 'bid', 'pid', 'end',
          'order', 'pdf_name', 'empty', 'fold_id']


def verify_volumes(db, only_han=0):
    """按“函号_扣名册号_扣号”依次验证"""
    def check_retry(vs, ret):
        if ret == 'retry':
            vs, start_i = {}, vs['start_i']
            for j in range(start_i, i + 1):
                vs = check_retry(vs, rs[j]['bid'] in f_map and _verify_r(
                    db, j, rs[j], han, vs, all_vols, f_map))
            ret = vs
        return ret or vs

    for han in range(only_han or 1, only_han + 1 if only_han else 549):
        all_vols, vols = {}, {}
        rs = list(db.sx_fold_check.find({'han': han}, {f: 1 for f in fields},
                                        sort=[('vol_fold', 1), ('fold_no', 1)]))
        deleted = [r['bid'] for r in db.sx_fold.find({'bid': {
            '$in': [s['bid'] for s in rs]}, 'deleted': {'$ne': None}}, {'bid': 1})]
        f_map = {r['bid']: r for r in rs if r['bid'] not in deleted}
        for i, r in enumerate(rs):
            r['vol_ok'] = r.get('vol_ok') or r['vol_fold']
            vols = check_retry(vols, r['bid'] in f_map and _verify_r(
                db, i, r, han, vols, all_vols, f_map))
        _save_vols(db, vols)


def _verify_r(db, ri, r, han, vols, all_vols, f_map):
    v1, no, vol_pdf, v2, pi, bid, pid, end, empty, order = [r.get(f) for f in [
        'vol_fold', 'fold_no', 'vol_pdf', 'vol_ok', 'pi', 'bid', 'pid', 'end', 'empty', 'order']]

    is_front = all_vols.get(v2, {}).get('max_no', 0) == 0  # 还没到非空扣
    if v2 not in all_vols:  # 先占位，以便能记录首页空扣
        all_vols[v2] = dict(vol_fold=v1, vol_pdf=vol_pdf, folds={}, diff_vols=[],
                            start_i=ri, min_no=no)  # 起始扣号，允许空扣

    if empty:  # 空扣，经统计无论是否有跨册扣，末页上的扣都是扣名册号对应的末页扣
        k = ('front' if is_front else 'end' if end else 'mid') + '_empty'
        all_vols[v2][k] = all_vols[v2].get(k, []) + [
            f'{bid}({no})' + ('e' if end else '')]
        # return vols  空扣也要输出就不跳出

    if is_front:  # 另起一册
        _save_vols(db, vols)
        vols = all_vols[v2]
        vols.update(dict(max_no=0, page_n=0, start_empty=0, fold_n=0,
                         pdf_name=r['pdf_name'], vol_ok=v2, han=han, cur_f={}, pid=''))
        if v1 != vol_pdf or v2 != vol_pdf:
            print(r['pdf_name'], vol_pdf, v1, v2)
    elif vols.get('end_empty') and not empty:
        vols['mid_empty'] = vols.get('mid_empty', []) + vols.pop('end_empty')

    assert vols['min_no'] <= no < 300, [bid, no]
    if not empty:
        if 'start_empty' not in vols:  # 已到非空扣
            s_no = min(make_page_no(han, vol_pdf, pi, i_, order) for i_ in range(10))
            vols['start_empty'] = no - s_no
        vols['max_no'] = no
        vols['fold_n'] += 1
    if vols['pid'] != pid:
        vols['pid'] = pid
        vols['page_n'] += 1
    if vols.get('cur_f'):  # 不是第一扣
        last = vols['cur_f']
        t = last['is_next_continuous'] = last['fold_no'] + 1 == no
        if not t:
            if last['fold_no'] == no and _end_duplicated(db, han, f_map.get(last['bid']), r, f_map):
                all_vols.pop(v2)
                return 'retry'
            vols['break_nums'] = vols.get('break_nums', []) + [f"{last['fold_no']}→{no}"]
            vols['lack_n'] = vols.get('lack_n', 0) + max(0, abs(no - last['fold_no']) - 1)

    v_no = vols['cur_f'] = vols['folds'][no] = vols['folds'].get(no) or dict(
        fold_no=no, vol_fold=v1, vol_ok=v2, vol_pdf=vol_pdf, bid=bid, end=end, empty=empty)

    t = v_no['is_duplicated'] = v_no['fold_no'] != no
    if t:
        vols['duplicated_n'] = vols.get('duplicated_n', 0) + 1
        vols['duplicated_nums'] = vols.get('duplicated_nums', set()) | {no}
    if v2 != v_no['vol_pdf']:  # 记录跨册的扣
        vols['diff_vols'].append(bid + ('e' if end else ''))
        vols['diff_vol_pid'] = pid
    return vols


def _find_page_sum(pid, f_map, allow_empty=True):
    """查找末页的册号集合和扣号个数"""
    vols, count = set(), 0
    for i in range(10):
        f = f_map.get(f'{pid}_{i}')
        if f and (allow_empty or not f['empty']):
            count += 1
            vols.add(f['vol_fold'])
    return vols, count


def _end_duplicated(db, han, last, now, f_map):
    # 重复的两扣来自两册末页，一册末页前5扣的扣名册号为本册、后5扣是另一册，而另一册末页仅5扣（册号与文件册号相同）
    if last:
        v1, n1 = _find_page_sum(last['pid'], f_map, False)  # 前者页面的非空扣的扣名册号、扣数
        v2, n2 = _find_page_sum(now['pid'], f_map, False)  # 后者页面的非空扣的扣名册号、扣数
        if len(v1) == 1 and len(v2) == 2:  # 后者跨册则对调，以便用下面逻辑
            v1, n1, v2, n2, last, now = v2, n2, v1, n1, now, last
        if len(v1) == 2 and len(v2) == 1 and n2 < 6 and v1 - v2 == {last['vol_pdf']}:
            folds = [f_map.get(f"{last['pid']}_{i}") for i in range(10)]
            folds = [f for f in folds if f and f['vol_fold'] == now['vol_fold']]  # 末5扣是另册
            valid = sorted([f['fold_no'] for f in folds if not f['empty']])  # 末5扣的非空扣号
            empty_n = len([f['fold_no'] for f in folds if f['empty']])
            empty_n = '及%d个空扣' % empty_n if empty_n else ''
            assert last['end'] and now['end']
            reason = f" 末页5扣{valid[0]}~{valid[-1]}{empty_n}与{now['pdf_name']}末页仅有的5扣重复"
            reason = '%03d/%s' % (han, last['pdf_name']) + reason
            print(last['bid'], reason)
            for r in folds:
                f_map.pop(r['bid'])
            db.sx_fold.update_many({'bid': {'$in': [r['bid'] for r in folds]}, 'deleted': None},
                                   {'$set': {'deleted': reason}})
            return True
        else:
            print(last['pid'], last['fold_no'], now['pid'], now['fold_no'])


def _save_vols(db, d):
    if not d.get('fold_n'):
        return
    folds = d.pop('folds', [])
    changed = _output_folds(db, list(folds.values()), d)
    d['diff_vol_n'] = len(d['diff_vols'])
    if 'duplicated_nums' in d:
        d['duplicated_nums'] = ','.join(map(str, list(d['duplicated_nums'])))
    d['empty_n'] = len(sum([d.get(k + '_empty', []) for k in ['front', 'mid', 'end']], []))
    for k, v in list(d.items()):
        if isinstance(v, list):
            if not v:
                d.pop(k)
            elif isinstance(v[0], str):
                s0 = '_' in v[0] and v[0].rsplit('_', 1)[0]
                if s0 and 1 < len(v) == len([1 for s in v if s.rsplit('_', 1)[0] == s0]):
                    d[k] = f'{len(v)}: {s0}_' + ','.join(s.rsplit('_', 1)[1] for s in v)
                else:
                    d[k] = (f'{len(v)}: ' if len(v) > 1 else '') + ','.join(v)
    for f in ['start_i', 'cur_f', 'pid']:
        d.pop(f)

    db.sx_volume.update_one(dict(han=d['han'], vol_fold=d['vol_fold']),
                            {'$set': d}, upsert=True)
    print(f"{d['han']},{d['pdf_name']},{d['fold_n']},{d['empty_n']},{changed}")
    d.clear()


def _output_folds(db, folds, v):
    """向 sx_fold 输出汇总检查后的字段
        扣名册号 vol_fold （从扣名 text 提取的册号）
        最终册号 vol_ok
        扣号 fold_no（从扣名 text 提取的扣号）
        原始扣号 org_fold_no （从原始扣名 org_text 提取的扣号，无法提取则为0）
        扣名编号 fold_id（由 han、vol_ok、fold_no 组成）
    之前已有：
        函号 han、文件册号 vol_pdf
        扣名 text、原始扣名 org_text
        修改原因 fix_reason，用于 org_text 与 text 不同的原因
        扣名状态 text_status = 0|1|2，分别是没有修改、人工校对、根据扣号连续修改
    """
    changed, ids = 0, []
    rs = {r['bid']: r for r in db.sx_fold.find({'bid': {'$in': [f['bid'] for f in folds]}},
                                               {f: 1 for f in fields})}
    for r in folds:
        exist, n = rs[r['bid']], 0
        r['fold_id'] = f"{v['han']}_{v['vol_ok']}_{r['fold_no']}"
        for f in ['vol_fold', 'vol_ok', 'fold_no', 'fold_id']:
            old, now = exist.get(f), r.get(f) or v[f]
            if old != now:
                n += 1  # 可加断点查看将改变情况
        if n:
            ids.append(r['bid'])
    folds = [f for f in folds if f['bid'] in ids]
    while folds:
        arr = [UpdateOne({'bid': f['bid']}, {'$set': dict(
            vol_fold=v['vol_fold'], vol_ok=v['vol_ok'],
            fold_no=f['fold_no'], fold_id=f['fold_id'])})
               for f in folds[:20]]
        del folds[:20]
        changed += db.sx_fold.bulk_write(arr).modified_count
    return changed


def main(db_name='sx_pdf', only_han=0):
    with_db(db_name, lambda db: verify_volumes(db, only_han))


if __name__ == '__main__':
    import fire

    fire.Fire(main)
