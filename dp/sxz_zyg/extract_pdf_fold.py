"""
脚本用途: 从思溪藏PDF提取扣名，例如“大藏经天字第1册 19”
环境变量:
    PDF_ROOT: 思溪藏PDF路径，第一级子文件夹为函(001~548)，不设置则自动读 sx_pdf.txt
    OUT_PATH: 输出目录，下有扣名图片文件夹，不设置则不能OCR
    OCR_API_KEY: 百度OCR的API_KEY，只在需要OCR时才需要设置
    OCR_SECRET_KEY: 百度OCR的SECRET_KEY，只在需要OCR时才需要设置
"""
import re
import pymupdf as pdf
import numpy as np
import cv2
from random import randint
from os import path, remove
from datetime import datetime
from pymongo import UpdateOne

import sys
sys.path.insert(0, path.dirname(path.dirname(path.abspath(__file__))))

from base.base_func import scan_pdf_files, get_scan_info, get_name_img
from base.base_func import auto_mkdir
from base.parse_text import parse_name, split_name, clean_text, re_digit
from base.img_func import stack_images
from base.baidu_ocr import request

rnd = randint(100, 999)
re_georgian = re.compile(r'[\u1000-\u1eff]')  # 461等函的乱码
re_fill_vol = re.compile(r'第([^\d第册]*)册$')

_bids = ''''''.strip()  # 将 mode=2 的打印结果填入，mode=1 补充OCR
re_ocr = _bids.split('\n') if _bids else []
re_pid = [re.sub(r'_\d+$', '', b) for b in re_ocr]


def extract_pdf(db, pdf_file, han, mode, only_pid=''):
    """从PDF提取扣名"""
    pdf_name, vol_pdf, info = get_scan_info(pdf_file, han, db)
    info.update(buffer=[], batch=1 if re_ocr else 60, only_pid=only_pid)

    if only_pid and f'{han}_{vol_pdf}_' not in only_pid:
        return
    if mode == 0:  # 从PDF提取文本
        return _parse_from_pdf_text(info, db, han, vol_pdf, pdf_file, info.get('only_pid'))
    if mode == 4:  # 重新解析OCR文本
        return _update_ocr_words(info, db, han, vol_pdf, info.get('only_pid'))

    for pi in range(100):
        pid = f'{han}_{vol_pdf}_{pi}'  # 页ID
        if (re_pid and pid not in re_pid) or (info.get('only_pid') or pid) != pid:
            continue
        page = db.sx_pdf_page.find_one(dict(pid=pid))
        if page is None:
            break
        info.update(dict(pid=pid, pi=pi, end=page['end'], mode=mode))

        files = [(i, get_name_img(han, vol_pdf, pi, i)) for i in range(10)]
        if mode == 1:  # OCR提取文本
            [_add_ocr_buffer(info, f, i) for i, f in files if f]
        else:
            info['buffer'].extend([(f'{pid}_{i}', page['end'])  # 扣id、是否末页
                                   for i, f in files if f])
    if mode == 1:
        _add_ocr_buffer(info, '', -1)  # end buffer
    else:
        folds = {b: dict(end=e, pdf_name=info['pdf_name'], text_status=0)
                 for b, e in info['buffer']}
        _apply_ocr(db, han, vol_pdf, folds, mode == 2, info.get('only_pid'))


def apply_texts(db, han, vol_pdf, fold_ids, test=True, only_pid=''):
    """择优选取识别结果，提取并保存扣名信息到扣表"""
    folds = {b: dict(text_status=0) for b in fold_ids}
    _apply_ocr(db, han, vol_pdf, folds, test, only_pid)


def _apply_ocr(db, han, vol_pdf, folds, test, only_pid):
    """择优选取识别结果，提取并保存扣名信息到扣表"""
    exclude_pid = ['171_3_7', '362_3_6', '387_4_6', '431_4_6', '449_2_14', '533_1_7',
                   '548_6_', '399_4_0', '544_3_', '548_6_',  # 禁用缺册号的页面
                   '477_5_20', '383_10_6', '384_6_7', '386_9_5', '428_1_8',
                   '446_7_14', '494_7_4']  # 无扣号超过5扣的末页，PDF无法提取扣号，禁用
    # 从PDF文本提取可用项，限文本全或有准确扣序的
    p_cond = {'han': han, 'vol_pdf': vol_pdf, '$or': [
        {'word_n': 10}, {'end5': True}, {'org_text': {'$ne': None}}]}
    if only_pid:
        p_cond['pid'] = only_pid
    for r in db.sx_pdf_page.find(p_cond):
        words = _str_to_words(r['words'], r['vol_pdf'])
        if words and (r.get('fix_reason') or not [1 for s in exclude_pid if s in r['pid']]):
            if r.get('end5') and words[0][2] and len(words[0]) < 4:  # 末页仅五扣且有扣号
                _add_idx_for_end5(r, words, words)
                r['words'] = _words_to_str(words)
            if len(words[0]) > 3:  # 有扣序号和扣名
                r['ids'], t = [f"{r['pid']}_{a[3]}" for a in words], 'exact'
            else:  # 10扣文本
                r['ids'], t = [f"{r['pid']}_{i}" for i in range(10)], 'pdf'
            _pick_folds(folds, r, f"{t}{r['word_n']}")

    # 得到ocr记录
    for r in db.sx_ocr.find(dict(han=han, vol_pdf=vol_pdf, text={'$ne': None})):
        bid = r.get('bid')
        if r.get('idx', -1) >= 0 and bid in folds:  # 单扣
            obj, src = folds[bid], 'ocr1'
            text1 = r['parse'] and r['text'] or '?'
            score = _get_score(r['parse'], src, r, text1)
            if score > obj.get('_score', 0):
                if r.get('org_text') and r.get('fix_reason'):
                    obj.update(dict(text_status=1, fix_reason=r['fix_reason'],
                                    org_text=r['org_text']))
                    src = 'fix'
                obj.update(dict(text=text1, src=src, _score=score, ocr_n=r['ocr_n']))
        elif r.get('id_n'):  # 批量识别
            _pick_folds(folds, r)

    if test:  # 检查缺漏实验
        no_res = [p for p in folds if not folds[p].get('text')]
        no_txt = [p for p in folds if folds[p].get('text') == '?']
        if no_res or no_txt:
            print(f"{han}/{vol_pdf} {len(folds)} folds, "
                  f"{len(no_res)} no result, {len(no_txt)} unknown text"
                  f"{': ' + ', '.join(no_txt[:2]) if no_txt else ''}")
        for bid, r in folds.items():
            if r.get('text') == '?':
                re_ocr.append(bid)
    else:  # 汇总文本
        items, changed = list(folds.items()), 0
        for _, r in items:
            r.pop('_score', 0)
        nc = [{'fix_reason': None}, {'text_status': 0}, {'text': '?'}]
        while items:
            arr = [UpdateOne({'bid': bid, '$or': nc, 'deleted': None}, {'$set': r})
                   for bid, r in items[:20]]
            del items[:20]
            changed += db.sx_fold.bulk_write(arr).modified_count

        has_txt = [1 for p in folds if len(folds[p].get('text', '')) > 1]
        if changed or len(has_txt) != len(folds) or vol_pdf == 1 and han % 10 == 0:
            print(f"{han}/{vol_pdf} {len(folds)} folds, {changed} updated, "
                  f"{'all' if len(has_txt) == len(folds) else len(has_txt)} have text")


def _get_score(parse, src, r=None, text=''):
    add = 0
    ps = text and (parse_name(text, 0)[0] or [0])[0]
    if ps:  # (kc, vol_fold, no)
        add += (2 if ps[2] else 0) + (1 if ps[1] else 0)

    if src and src.startswith('exact'):
        return 9 + add
    if src.startswith('fix'):
        return 10 + add
    if re.match('ocr', src) and r and r.get('org_text'):
        r['parse'] = 1
        return 10 + add
    if src == 'ocr1':
        return {0: 2, 1: 8, 2: 7}.get(parse, 6) + add
    if src:  # ocr<n>, pdf<n>
        return {0: 1, 1: 5, 2: 4}.get(parse, 3) + add
    return 0  # unset


def _fix_text_361(text, han):
    """361~393函将函号排入扣名就忽略"""
    if han > 360:
        text = re.sub(f' *{han}$', '', text)
    return text


def _pick_folds(folds, r, src=''):
    """从多扣文本识别结果提取并保存扣名信息到扣表"""
    src = src or f"ocr{r['id_n']}"
    words = _str_to_words(r['words'], r['vol_pdf'])  # (kc, vol_fold, no, idx?, text?)[]
    texts = [w[4] for w in words] if words and len(words[0]) > 4 \
        else split_name(r['text'], r['parse'])
    t = len(words) == len(r['ids']) and r['parse'] or 0
    for i, bid in enumerate(r['ids']):
        text1 = _fix_text_361(texts[i], r['han']) if t and texts else '?'
        if re.match(re_digit, text1):  # 扣名全是数字，页面上仅扣号未压板
            assert not src.startswith('ocr')
            continue  # 自动采用OCR结果（因有3页半页压板，故不在整页文本处检查）
        score = _get_score(t, src, r, text1)
        obj = folds.get(bid, {})
        if obj and score > obj.get('_score', 0):
            if r.get('org_text') and r.get('fix_reason'):
                obj.update(dict(text_status=1, fix_reason=r['fix_reason'], org_text=r['org_text']))
                src = f"fix{r['word_n']}"
            obj.update(dict(text=text1, ocr_n=r.get('ocr_n'), _score=score,
                            src=src or f"ocr{r['id_n']}"))


def _add_ocr_buffer(info, img_file, idx):
    def ocr_batch(arr):
        if info['batch'] == 1:
            n_ = sum(_batch_ocr(info, f, [b]) for _, f, b in arr)
        elif len(arr) > 1:
            m_ = stack_images([m[0] for m in arr])
            cv2.imwrite(tmp_file, m_)
            n_ = _batch_ocr(info, tmp_file, [r[2] for r in arr])
            remove(tmp_file)
            if not n_ and len(arr) <= 10:
                n_ = sum(_batch_ocr(info, f, [b]) for _, f, b in arr)
        else:
            n_ = _batch_ocr(info, arr[0][1], [arr[0][2]])
        return n_

    # 将当前扣名图片加入待OCR的队列
    buf, bid = info['buffer'], img_file and info['pid'] + f'_{idx}'
    if img_file and (not re_ocr or bid in re_ocr):
        im = cv2.imread(img_file, cv2.IMREAD_GRAYSCALE)
        if np.mean(im) < 254.8:  # 空图不OCR
            buf.append((im, img_file, bid + f"_{int(info['end'])}"))

    # 在结束或累积到量时合并一次OCR
    if buf and (not img_file or len(buf) >= info['batch']):
        tmp_file = path.join(info['out_path'], 'tmp', f'_{rnd}.jpg')
        auto_mkdir(tmp_file)
        n = ocr_batch(buf)  # 合并一次OCR
        if 10 < n < len(buf):
            info['batch'] = 10
            while buf:
                n += ocr_batch(buf[:10])
                del buf[:10]
        buf.clear()


def _batch_ocr(info, img_file, ids):
    """对一个或多个扣名图的合图进行OCR"""
    db, han, vol_pdf = [info[f] for f in ['db', 'han', 'vol_pdf']]
    return call_ocr(db, img_file, han, vol_pdf, ids)


def call_ocr(db, img_file, han, vol_pdf, ids):
    """调用OCR
    :param db, 数据库对象
    :param img_file, 扣名图片文件名
    :param han, 函号
    :param vol_pdf, 册号
    :param ids, bid_end[] 末尾为1是末页，0是其它页
    """
    ids = [ids] if isinstance(ids, str) else ids
    pi, idx, end = map(int, ids[0].split('_')[2:]) if len(ids) == 1 else (0, 0, 0)
    if not img_file:
        return 0
    r = db.sx_ocr.find_one(dict(han=han, vol_pdf=vol_pdf,
                                pi=pi, idx=idx)) if len(ids) == 1 else None
    if r:
        return r['word_n']

    res = request(img_file=img_file)
    ocr_n = (db.sx_ocr.find_one({}, {'ocr_n': 1},
                                sort=[('ocr_n', -1)]) or {}).get('ocr_n', 0) + 1
    d, n = dict(ocr_n=ocr_n, time=datetime.now()), 0

    if res and 'words_result' in res:
        text = _concat_ocr_words(res)
        ids, n = _parse_ocr_text(d, end, han, ids, idx, pi, text, vol_pdf)
        print(f"#{ocr_n} ocr: {n} texts for {len(ids)} folds ({ids[0]})")
    elif res and res.get('error_msg'):
        d.update(dict(file=path.basename(img_file), error=res['error_msg'] + ','.join(ids)))

    db.sx_ocr.insert_one(d)
    return n


def _parse_ocr_text(d, end, han, ids, idx, pi, text, vol_pdf):
    words, t = parse_name(text)
    n = len(words)
    d.update(dict(text=text, word_n=n, words=_words_to_str(words),
                  parse=t, han=han, vol_pdf=vol_pdf))
    if len(ids) == 1:
        d.update(dict(pi=pi, idx=idx, bid=f'{han}_{vol_pdf}_{pi}_{idx}', end=end))
    else:
        end = list(set(s.endswith('_1') for s in ids))
        end = end[0] if len(end) == 1 else None
        ids = ['_'.join(s.split('_')[:4]) for s in ids]
        d.update(dict(id_n=len(ids), ids=ids, end=end))
    return ids, n


def _concat_ocr_words(result):
    text, w_n = '', 0
    for i, r in enumerate(result['words_result']):
        sp, s = ' ', r['words']
        if i:
            if '册' in s or '字第' in s:
                w_n += 1
                if w_n and w_n % 5 == 0:
                    sp = '\n'
            text += sp
        text += s
    return text


def _update_ocr_words(info, db, han, vol_pdf, only_pid):
    changed, only_i = 0, int(only_pid.split('_')[-1]) if only_pid else -1
    for r in db.sx_ocr.find(dict(han=han, vol_pdf=vol_pdf, text={'$ne': None})):
        if only_i < 0 or only_i == r.get('idx', only_i):
            text = r['text']
            if f'{han}_{vol_pdf}' in ['90_3', '173_8', '173_9']:
                text = re.sub(r'第\s*\d+\s*册', f'第{vol_pdf}册', text)
            if r.get('bid') and 'idx' in r:
                text = _fix_text_361(text, han)
            words, t = parse_name(text)
            n, word_str = len(words), _words_to_str(words)
            if word_str != r.get('words'):
                u = db.sx_ocr.update_one({'_id': r['_id']}, {'$set': dict(
                    word_n=n, words=word_str, parse=t, text=text)})
                changed += u.modified_count
    if changed:
        print(f"{han}/{info['pdf_name']} {changed} changed")


def _parse_from_pdf_text(info, db, han, vol_pdf, pdf_file, only_pid):
    """PDF页面文本解析"""
    fulls = []
    with pdf.open(pdf_file) as doc:
        for pi in range(doc.page_count):
            pid, end = f'{han}_{vol_pdf}_{pi}', pi + 1 == doc.page_count
            if only_pid and only_pid != pid:
                continue

            p = db.sx_pdf_page.find_one(dict(pid=pid), dict(
                dim=1, text=1, words=1, fix_reason=1))
            if p and p.get('fix_reason'):
                w_old = _str_to_words(p['words'], vol_pdf)
                words, t = parse_name(p['text'])
                d = dict(word_n=len(words), words=_words_to_str(words), parse=t)
                if w_old and len(words) == len(w_old) and (len(w_old[0]) > 4 or end):
                    if end and len(words) == 5:
                        _add_idx_for_end5(p, w_old, words)
                        for i, old in enumerate(w_old):
                            words[i] += (old[3], re.sub(r'册[ \d]*$', f'册{words[i][2]}', old[4]))
                        d['end5'] = True
                    assert len(words) == 10 or d.get('end5')
                if len(words) == 10 or d.get('end5'):
                    fulls.append(pi)
                db.sx_pdf_page.update_one(dict(pid=pid), {'$set': d})
                continue

            page = doc.load_page(pi)
            text = org_txt = _exclude_text(clean_text(page.get_text()))
            words, t = parse_name(text)
            words_org, un, org_ws, now_ws = words, {}, '', ''
            if text:  # get_text('dict') 遍历有图像块的页面较慢
                # 设置 PYMUPDF_USE_EXTRA 为0，
                # 在 pymupdf/__init__.py 中跳过 JM_make_image_block 则很快
                t = page.get_text('dict')
                text, words, t = _parse_pdf_dict(t, p and p.get('dim'), han, vol_pdf)

            d = dict(han=han, vol_pdf=vol_pdf, pi=pi, end=end, text=text, word_n=len(words),
                     words=_words_to_str(words), parse=t, pdf_name=info['pdf_name'])
            assert len(words) >= len(words_org)
            if text != org_txt:
                org_ws = '\n'.join(','.join(map(str, s[:3])) for s in words_org)
                now_ws = '\n'.join(','.join(map(str, s[:3])) for s in words)
                d.update(dict(org_text=org_txt, org_words=org_ws,
                              org_word_n=len(words_org)))
            if org_ws == now_ws:
                for f in ['org_words', 'org_word_n']:
                    d.pop(f, 0)
                    un[f] = 1
            if end and len(words) == 5 and len(words[0]) > 4:
                d['end5'] = True
            if org_ws != now_ws or len(words) == 10:
                fulls.append(pi)

            exist_i = [r['idx'] for r in db.sx_fold.find(dict(pid=pid), {'idx': 1})]
            if not exist_i:
                d['order'] = '右' if han == 1 else '左'
                d['kb'] = path.getsize(pdf_file) // 1024
            db.sx_pdf_page.update_one(dict(pid=pid), {'$set': d, '$unset': un}, upsert=True)

            if len(exist_i) != 10:
                db.sx_fold.bulk_write([UpdateOne({'bid': f'{pid}_{i}'}, {'$set': {
                    'pi': pi, 'idx': i, 'pid': pid, 'end': end,
                    **{f: info[f] for f in ['han', 'vol_pdf', 'pdf_name']}}}, upsert=True)
                                        for i in range(10) if i not in exist_i])

        if fulls:
            print(f"{han}/{info['pdf_name']} {doc.page_count} pages, "
                  f"{len(fulls)} get the full text: {','.join(map(str, fulls))}")


def _add_idx_for_end5(p, w_old, words):
    if len(w_old[0]) < 5:
        assert (int(words[0][2]) % 10) in [5, 6]
        a = split_name(p['text'])
        for i, old in enumerate(w_old):
            w_old[i] += (i, a[i])


# https://pymupdf.readthedocs.io/en/latest/textpage.html
def _parse_pdf_dict(page, dim, han, vol_pdf):
    def is_digits(s1):
        return re.match(re_digit, s1) and int(s1) > 9

    texts, text, words = {}, [], []
    try:
        width, height = page['width'], page['height']
        yc = dim['yc'] * 72 / 120 if dim else height / 2
        for block in page['blocks']:
            spans = []
            for line in block.get('lines', []):  # 文本块的行
                spans.extend(line['spans'])
            for s in spans:
                st = _fix_text_361(_exclude_text(s['text']), han)
                if not st:
                    continue
                x0, y0, x1, y1 = s['bbox']
                x = (x0 + x1) * 2.5 / width  # 横向对应到五格中
                idx = int(x) + (0 if y0 < yc else 5)
                ts = texts[idx] = texts.get(idx, [])
                if st and re_fill_vol.search(st):
                    st = re_fill_vol.sub(f'第{vol_pdf}册', st)
                if ts and is_digits(ts[-1]) and is_digits(st):
                    print(f"{han}/{vol_pdf} ignore {st} due to {ts[-1]}")
                    continue  # 一个扣不允许末尾有两个大于9的数
                elif ts and re_fill_vol.search(ts[0]) and (st == str(vol_pdf) or st in ts[0]):
                    # 将后排入的册号替换到册前占位符(空格或减号), 370-376、441 539 540函
                    ts[0] = re_fill_vol.sub(f'第{vol_pdf}册', ts[0])
                else:
                    ts.append(st)
    except (ValueError, KeyError) as e:
        print(e)

    for idx in sorted(texts.keys()):
        arr = texts[idx]
        if not arr:
            continue
        if re.match(re_digit, arr[0]):
            arr.append(arr.pop(0))
        txt = clean_text(' '.join(arr))
        if f'{han}_{vol_pdf}' in ['90_3', '173_8', '173_9']:  # 位字第03册，全是第2册，应为第3册
            txt = re.sub(r'第\s*\d+\s*册', f'第{vol_pdf}册', txt)
        rs, _ = parse_name(txt, idx)
        if han == 475 and vol_pdf == 1:  # 坟字第01册
            txt = txt.replace('第-册', f'第{vol_pdf}册')
        text.append(txt)
        words.append((rs[0] if rs else ('', '', -1)) + (idx, txt))

    return '\n'.join(text), words, 1


def _exclude_text(text):
    if re_georgian.search(text):
        return ''
    return re.sub('双 ?拼', '', text).strip()


def _words_to_str(words):
    """ (kc, vol_fold, no, idx?, text?)[] 转为多行文本 """
    return '\n'.join(','.join(map(str, w)) for w in words) or None


def _str_to_words(text, vol0):
    if not text:
        return []
    words = [s.split(',') for s in text.split('\n')] if text else []
    try:
        return [tuple(int(s) if 0 < i < 4 and re_digit.match(s) else s
                      for i, s in enumerate(w)) for w in words]
    except ValueError:
        for i, w in enumerate(words):
            if re.match(re_digit, w[1]):
                vol0 = int(w[1]) or vol0
            else:
                words[i][1] = vol0
        return [tuple(int(s) if 0 < i < 4 and re_digit.match(s) else s
                      for i, s in enumerate(w)) for w in words]


def _extract_pages(db, file, han, mode, only_pid):
    ids = str(only_pid).split(',')
    if len(ids) > 1:
        for pid in str(only_pid).split(','):
            extract_pdf(db, file, han, 0, pid)
            extract_pdf(db, file, han, 3, pid)
    else:
        extract_pdf(db, file, han, mode, only_pid)


def main(src_path='@PDF_ROOT', db_name='sx_pdf', mode=2,
         only_name='', only_pid='', only_han=''):
    """脚本主函数
    :param src_path: PDF目录，含有001等函的文件夹
    :param db_name: 数据库名，如果为 rushi-dev 则使用环境变量 DB_URI 的远程数据库
    :param mode: 0-从PDF提取文本，1-OCR提取文本，2-检查缺漏实验, 3-汇总文本, 4-重新解析OCR文本
    :param only_name: 仅转换PDF文件名含有指定文本的文件，逗号分隔多个
    :param only_pid: 仅转换指定页面id的文件，一个页面最多10扣
           如果指定了多个逗号分隔的pid，则同时执行提取文本和汇总文本，用于人工修改页面文本后更新
    :param only_han: Union[int, str], 限定函，可用减号或逗号指定区间，例如 100、-100、100-200,202
    """
    if only_pid and ',' not in str(only_pid):
        only_han = int(str(only_pid).split('_')[0])
    scan_pdf_files(lambda file, han, db: _extract_pages(db, file, han, mode, only_pid),
                   db_name, src_path, only_name, only_han)
    if mode == 2 and re_ocr:
        print(str(sorted(re_ocr)).replace('[', '[\n') + f' # {len(re_ocr)}')


if __name__ == '__main__':
    import fire

    fire.Fire(main)
