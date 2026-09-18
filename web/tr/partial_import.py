import sys
import cv2
import re
import math
import logging
from os import path as osp
from bson import json_util

BASE_DIR = osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__))))
META_DIR = osp.join(BASE_DIR, 'web/tr/meta')

sys.path.append(BASE_DIR)

import helper as hp
from util import uni2sim
from web.tr import reel

# db_work = hp.get_db('tw-work')
# db_prod0 = hp.get_db('tr-readprod0')
db_prod = hp.get_db('tr-readprod')
# db_aux = hp.get_db('tw-aux')

# glyphs = list(db_aux.glyph.find({'code': {'$exists': True}}, {'code': 1, 'unicode': 1}))
# code2unicode = {g.get('code'): g.get('unicode') for g in glyphs}
# vts = list(db_work.variant.find({}, {'v_code': 1, 'uni_txt': 1}))
# vts2uni = {vt.get('v_code') or vt.get('txt'): vt.get('uni_txt') for vt in vts}


def get_buid(name):
    """径山藏页编码转原书编码"""

    def get_output(num):
        if num % 2 == 1:
            return str((num + 1) // 2) + 'a'
        else:
            return str(num // 2) + 'b'

    parts = name.rsplit('_', 1)
    num = int(parts[1])
    num = get_output(num)
    buid = '%s_%s' % (parts[0], num)
    return buid


def get_images_img_path(image_name):
    """ 获取页图的路径"""
    inner_path = '/'.join(image_name.split('_')[:-1])
    img_path = osp.join("/nas/web-static/tw-work/images", inner_path, '%s.jpg' % image_name)
    if not osp.exists(img_path):
        return False
    return img_path


def get_ori_txt_by_txt(txt):
    if 'v' in txt and len(txt) > 1:
        unicode = code2unicode[txt]
        txt = unicode2char(unicode)
    return txt


def unicode2char(unicode):
    unicode = unicode.replace('U+', '').lower()
    unicode = f'\\u{unicode}' if len(unicode) <= 4 else f'\\U000{unicode}'
    return unicode.encode('utf-8').decode('unicode_escape')


def get_all_page_names():
    """获取已经校对的页编码"""
    names = db_work.page.distinct('name', {'name': {'$regex': '^JS_'}})
    list1 = []
    for k in range(1, 227):
        tmp = 'JS_%s_' % k
        page_names = [name for name in names if tmp in name]
        list1.extend(page_names)
    # 加上径山藏目录页
    names_mulu = db_work.page.distinct('name', {'source': {'$in': ['JS-M', 'JS-MENU-XC', 'JS-MENU-XK']}})
    list1.extend(names_mulu)
    return list1


def get_select_cond(reel, name='page_code'):
    """ 获取页数据查询条件"""
    start = hp.align_code(reel['start_page'])
    end = hp.align_code(reel['end_page'])
    cond = {name: {'$gte': start, '$lte': end}}
    return cond


def update_page_txts():
    hp.set_logging('update_page_txts')
    logging.info('update_page_txts')
    uni2std_dict, uni2sim_dict = get_uni2std_uni2_sim()
    tripitaka_uid = 'JS'
    uids = db_prod0.page.distinct('uid', {'tripitaka_uid': tripitaka_uid, 'flag': 1})
    split_lst = [uids[i:i + 1000] for i in range(0, len(uids), 1000)]
    for i, names in enumerate(split_lst):
        logging.info('%s\t%s\t%s' % (i, len(names), len(split_lst)))
        pages = list(db_prod0.page.find({'uid': {'$in': names}}, {'_id': 0, 'uid': 1, 'chars': 1}))
        print(pages[0]['uid'])
        for page in pages:
            for c in page.get('chars'):
                t = c['txt']
                c['ori_txt'] = get_ori_txt_by_txt(t)
                uni_txt = vts2uni.get(t)
                if uni_txt in ['fw', 'ys', 'cy', 'fh', 'rm', 'yy']:
                    c['uni_txt'] = c['ori_txt']
                    c['std_txt'] = c['ori_txt']
                    c['sim_txt'] = c['ori_txt']
                else:
                    if 'v' in t:
                        c['uni_txt'] = uni_txt  # 自造字使用异体字表转换的通字
                    else:
                        c['uni_txt'] = t  # 通字使用原来的txt
                    c['std_txt'] = uni2std_dict[c['uni_txt']]  # 使用专门的xlsx转换表
                    c['sim_txt'] = uni2sim_dict[c['uni_txt']]  # 使用专门的xlsx转换表
            db_prod0.page.update_one({'uid': page['uid']}, {'$set': {'chars': page['chars']}})
            db_prod.page.update_one({'uid': page['uid']}, {'$set': {'chars': page['chars']}})


def update_sutra_reel_uids():
    hp.set_logging('update_sutra_reel_uids')
    logging.info('update_sutra_reel_uids')
    tripitaka_uid = 'JS'
    sutras = list(db_prod0.sutra.find({}, {'uid': 1, 'tripitaka_uid': tripitaka_uid}))
    for sutra in sutras:
        logging.info('%s' % (sutra['uid']))
        reels = list(db_prod0.reel.find({'sutra_uid': sutra['uid']}, {'uid': 1, 'name': 1}))
        # reels = sorted(reels, key=lambda reel: [int(y) for y in reel['uid'].split('_') if y.isdigit()])

        reels = sorted(reels, key=lambda reel: custom_sort_key_read(reel['uid']))
        reel_uids = []
        for reel in reels:
            name = reel['name']
            sim_name = uni2sim.simplify(name)
            if sim_name != name:
                name = '%s|%s' % (name, sim_name)
            reel_uids.append([reel['uid'], name])
        db_prod0.sutra.update_one({'uid': sutra['uid']}, {'$set': {'reel_uids': reel_uids}})


def get_column_txt_list(page, txt_type):
    """从页数据中获取全部列的文本列表"""
    if not page.get('chars'):
        return []

    rows = []
    cols = [c for c in page['columns']]
    for col in cols:
        col_chars = [c for c in page['chars'] if c['char_id'].startswith(f'{col["column_id"]}c')]
        col_txt = ''.join([c.get(txt_type) or '■' for c in col_chars])
        rows.append([col['cid'], col_txt])
    return rows


def get_reel_catalog(elements):
    """获取reel的父子结构数据"""
    reel_catalog = {}
    structured_data = []
    h1_dict = {}
    h2_dict = {}
    h3_dict = {}
    h4_dict = {}
    for item in elements:
        for key, value in item.items():
            entry = {'line_uid': value[1], 'std_txt': value[2], 'sim_txt': value[3]}

            if key == 'H1':
                h1_dict[value[1]] = entry
                structured_data.append(entry)
            elif key == 'H2':
                h2_dict[value[1]] = entry
                if structured_data:
                    if not structured_data[-1].get('children'):
                        structured_data[-1].update({'children': []})
                    structured_data[-1]["children"].append(entry)
            elif key == 'H3':
                h3_dict[value[1]] = entry
                if h2_dict:
                    if not h2_dict[list(h2_dict.keys())[-1]].get('children'):
                        h2_dict[list(h2_dict.keys())[-1]].update({'children': []})
                    h2_dict[list(h2_dict.keys())[-1]]["children"].append(entry)
            elif key == 'H4':
                h4_dict[value[1]] = entry
                if h3_dict:
                    if not h3_dict[list(h3_dict.keys())[-1]].get('children'):
                        h3_dict[list(h3_dict.keys())[-1]].update({'children': []})
                    h3_dict[list(h3_dict.keys())[-1]]["children"].append(entry)
            elif key == 'H5':
                if h4_dict:
                    if not h4_dict[list(h4_dict.keys())[-1]].get('children'):
                        h4_dict[list(h4_dict.keys())[-1]].update({'children': []})
                    h4_dict[list(h4_dict.keys())[-1]]["children"].append(entry)
    return structured_data


def update_page_format():
    hp.set_logging('update_page_format')
    logging.info('update_page_format')
    tripitaka_uid = 'JS'
    uids = db_prod0.reel.distinct('uid', {'tripitaka_uid': tripitaka_uid})
    for uid in uids:
        logging.info('\t%s' % uid)
        reel = db_prod0.reel.find_one({'uid': uid})
        if not reel.get('pages'):
            continue
        page_names = [page['uid'] for page in reel['pages']]
        for fmt in reel.get('format'):
            page_uid = fmt['uid']
            if page_uid not in page_names:
                continue
            fmt.pop('uid', 0)
            fmt.pop('cids', 0)
            fmt.pop('ouid', 0)
            db_prod0.page.update_one({'uid': page_uid}, {'$set': {'format': fmt}})


def import_chars():
    hp.set_logging('import_chars')
    logging.info('import_chars')
    tripitaka_uid = 'JS'
    char_coll = f'char_{tripitaka_uid.lower()}'
    names = db_prod0.page.distinct('ouid', {'tripitaka_uid': tripitaka_uid})
    sorted_lst = sorted(names, key=lambda x: [int(y) for y in x.split('_') if y.isdigit()])
    split_lst = [sorted_lst[i:i + 1000] for i in range(0, len(sorted_lst), 1000)]

    for i, names in enumerate(split_lst):
        logging.info('\t%s\t%s\t%s' % (i, len(names), len(split_lst)))
        pages = list(db_prod0.page.find({'ouid': {'$in': names}}, {'format': 0, 'punc_txt': 0}))
        pages = sorted(pages, key=lambda page: [int(y) for y in page['ouid'].split('_') if y.isdigit()])
        for page in pages:
            rows = []
            cols = [c for c in page['columns']]
            for col in cols:
                col_chars = [c for c in page['chars'] if c['char_id'].startswith(f'{col["column_id"]}c')]
                rows.append([col['cid'], col_chars])
            if not rows:
                continue
            if not page.get('sutra_uids'):
                logging.info('\t%s\t%s' % (page['ouid'], '没有经编码'))
                continue
            # 处理多经同页的情况
            suids = [page['sutra_uids'][0]] * len(rows)
            if len(page['sutra_uids']) == 2:
                reel_uid = page['reel_uids'][1]
                reel = db_prod0.reel.find_one({'uid': reel_uid})
                start_column_cid = reel['start_column_cid']
                indexs = [index for index, row in enumerate(rows) if row[0] == start_column_cid]
                if indexs:
                    start_column_cid_index = indexs[0]
                    rows_1 = rows[:start_column_cid_index]
                    rows_2 = rows[start_column_cid_index:]
                    suids = [page['sutra_uids'][0]] * len(rows_1) + [page['sutra_uids'][1]] * len(rows_2)
            # 导入数据
            chars = []
            for i, row in enumerate(rows):
                for char in row[1]:
                    unicode = get_unicode(char['ori_txt'])
                    is_manual = is_in_supplementary_pua(unicode)
                    if char['ori_txt'] != char['std_txt']:
                        is_deform = True
                    else:
                        is_deform = False
                    chars.append({
                        'suid': suids[i],
                        'sn': char['char_id'],
                        'ot': char['ori_txt'],
                        'ut': char['uni_txt'],
                        'st': char['std_txt'],
                        'mt': char['sim_txt'],
                        'puid': page['uid'],
                        'ouid': f"{page['ouid']}_{char['cid']}",
                        'is_manual': is_manual,
                        'is_deform': is_deform
                    })
            if chars:
                for ch in chars:
                    db_prod0[char_coll].insert_one(ch)
                    db_prod[char_coll].insert_one(ch)


def update_sutra_char_cnt():
    """更新每部经的字数"""
    hp.set_logging('update_sutra_char_cnt')
    logging.info('update_sutra_char_cnt')
    tripitaka_uid = 'JS'
    char_coll = f'char_{tripitaka_uid.lower()}'
    sutra_uids = db_prod0.page.distinct('sutra_uids', {'tripitaka_uid': tripitaka_uid, 'flag': 1})
    sutras = list(db_prod0.sutra.find({'uid': {'$in': sutra_uids}, }, {'uid': 1}))
    for sutra in sutras:
        cnt = db_prod0[char_coll].count_documents({'suid': sutra['uid']})
        db_prod0.sutra.update_one({'uid': sutra['uid']}, {'$set': {'char_cnt': cnt}})
        db_prod.sutra.update_one({'uid': sutra['uid']}, {'$set': {'char_cnt': cnt}})
        logging.info('\t%s\t%s' % (sutra['uid'], cnt))


def get_unicode(char):
    """ 字符转unicode """
    code = ord(char)
    code = "U+{:04X}".format(code)
    return code


def import_char_type():
    """导入字种表"""
    hp.set_logging('import_char_type')
    logging.info('import_char_type')
    pipelines = [
        {'$group': {'_id': '$ot', 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}}
    ]
    tripitaka_uid = 'JS'
    char_coll = f'char_{tripitaka_uid.lower()}'
    group_res = list(db_prod0[char_coll].aggregate(pipelines))
    for item in group_res:
        logging.info('\t%s\t%s' % (item['_id'], item['count']))
        txt = item['_id']
        frequency = item['count']

        uid = get_unicode(txt)
        is_manual = is_in_supplementary_pua(uid)
        char_type = {}
        char_type['tripitaka_uid'] = 'JS'
        char_type['uid'] = uid

        char_type['ori_txt'] = txt
        char = db_prod0[char_coll].find_one({'ot': txt})
        char_type['std_txt'] = char['st']
        char_type['uni_txt'] = char['ut']
        char_type['sim_txt'] = char['mt']
        char_type['frequency'] = frequency
        char_type['is_manual'] = is_manual
        if char_type['ori_txt'] != char_type['std_txt']:
            is_deform = True
        else:
            is_deform = False
        char_type['is_deform'] = is_deform
        db_prod0.char_type.insert_one(char_type)
        db_prod.char_type.insert_one(char_type)


def set_coll_seg_ids(coll='char_js', size=10000 * 10, overwrite=True):
    """设置collection的seg_ids，以便查询优化"""
    hp.set_logging('set_coll_seg_ids')
    logging.info('set_coll_seg_ids')
    key = f'{coll}_seg_ids'
    conf = db_prod0.sys_conf.find_one({'key': key}, {'_id': 1})
    if conf and not overwrite:
        return
    # 计算总数
    stats = db_prod0.command('collstats', coll)
    total = stats['count']
    if total < size:
        return
    # 分段计算seg_ids
    seg_ids = {}
    page_count = math.ceil(total / size)
    for i in range(1, page_count):
        logging.info('%s/%s' % (i, page_count))
        doc = list(db_prod0[coll].find({}, {'_id': 1}).skip(i * size - 1).limit(1))
        seg_ids[str(i * size)] = doc[0]['_id']
    data = {'key': key, 'value': seg_ids}
    db_prod0.sys_conf.update_one({'key': key}, {'$set': data}, upsert=True)
    db_prod.sys_conf.update_one({'key': key}, {'$set': data}, upsert=True)


def set_group_char_result(tripitaka_uid='JS', txt_type='ot'):
    """设置字图统计的结果（仅无查询条件时），以便查询优化"""

    key = f'group_char_result_{tripitaka_uid.lower()}_{txt_type}'
    print(key)
    # 计算统计结果
    pipelines = [
        {'$group': {'_id': '$%s' % txt_type, 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}}
    ]
    char_coll = f'char_{tripitaka_uid.lower()}'
    group_res = list(db_prod0[char_coll].aggregate(pipelines))
    res = [{'txt': i['_id'], 'count': i['count']} for i in group_res]
    data = {'key': key, 'value': {'group_res': res}}
    db_prod0.sys_conf.update_one({'key': key}, {'$set': data}, upsert=True)
    db_prod.sys_conf.update_one({'key': key}, {'$set': data}, upsert=True)


def get_uni2std_uni2_sim():
    import pandas as pd

    filename = '径山藏通字转正字&简体字-20250314.xlsx'
    data = pd.read_excel(osp.join(META_DIR, filename))
    uni2std_dict = {}
    uni2sim_dict = {}
    for index, row in data.iterrows():
        uni_txt = row['通字']
        std_txt = row['转换正字']
        sim_txt = row['转换简体字']
        uni2std_dict[uni_txt] = std_txt
        uni2sim_dict[uni_txt] = sim_txt
    return uni2std_dict, uni2sim_dict


def update_pages_imgages():
    """更新page文中图"""
    hp.set_logging('update_pages_imgages')
    logging.info('update_pages_imgages')
    page_names = db_work.image.distinct('page_name', {'type': '文中图'})

    pages = db_prod0.page.find({'ouid': {'$in': page_names}})
    for page in pages:
        ouid = page['ouid']
        imgs = list(db_work.image.find({'page_name': ouid}))
        images = []

        for img in imgs:
            image = {}
            image['cid'] = img['cid']
            img_name = '%s_%s' % (page['ouid'], img['cid'])
            img_path = get_images_img_path(img_name)
            cv2_img = cv2.imread(img_path)
            height, width = cv2_img.shape[:2]
            image['width'] = width
            image['height'] = height
            image['after_which_char'] = img['after_which_char']
            image['is_inline'] = False
            images.append(image)

        # 按 cid 升序排序
        images = sorted(images, key=lambda x: int(x['cid']))
        r0 = db_prod0.page.update_one({'_id': page['_id']}, {'$set': {'images': images}})
        r = db_prod.page.update_one({'_id': page['_id']}, {'$set': {'images': images}})
        logging.info(' %s\t%s\t%s' % (ouid, r0.matched_count, r.matched_count))


def update_reels_imgages():
    """更新reel文中图"""
    hp.set_logging('update_reels_imgages')
    logging.info('update_reels_imgages')
    page_names = db_work.image.distinct('page_name', {'type': '文中图'})
    pages = list(db_prod0.page.find({'ouid': {'$in': page_names}}))
    page2imgs = {p['ouid']: p.get('images') for p in pages}
    uids = []
    for page in pages:
        reel_uids = page.get('reel_uids')
        uids.extend(reel_uids)
    uids = list(set(uids))
    for i, uid in enumerate(uids):
        reel = db_prod0.reel.find_one({'uid': uid})
        for page in reel.get('pages'):
            imgs = page2imgs.get(page['ouid'])
            if imgs:
                page['images'] = imgs
        r0 = db_prod0.reel.update_one({'_id': reel['_id']}, {'$set': {'pages': reel['pages']}})
        r = db_prod.reel.update_one({'_id': reel['_id']}, {'$set': {'pages': reel['pages']}})
        logging.info('%s\t%s\t%s\t%s' % (i, uid, r0.matched_count, r.matched_count))


def is_in_supplementary_pua(code_point):
    # 将输入转换为整数
    if isinstance(code_point, str):
        # 去除前后空格和可能的'U+'前缀，并统一为大写
        code_point = code_point.strip().upper()
        if code_point.startswith("U+"):
            code_point = code_point[2:]
        try:
            num = int(code_point, 16)  # 按16进制解析
        except ValueError:
            return False  # 非法字符（如非16进制符号）
    else:
        num = int(code_point)  # 直接转为整数

    # 检查范围：F0000 ≤ num ≤ FFFFF
    return 0xF0000 <= num <= 0xFFFFF


def get_reel_ouid(name):
    # 1. 拆分字符串
    part1, part2 = name.split('_')

    # 2. 提取前缀字母（如 "JS"）
    prefix = ""
    for char in part1:
        if char.isalpha():
            prefix += char
        else:
            break

    # 3. 处理数字部分（去前导零）
    num_part1 = part1[len(prefix):]  # 提取数字部分（如 "0001"）
    num1 = str(int(num_part1))  # 转为整数再转字符串（"1"）
    num2 = str(int(part2))  # 处理第二部分（"051" → "51"）

    # 4. 组合结果
    result = f"{prefix}_{num1}_{num2}"

    return result


def group_data(data):
    """分组函数，返回需要处理的分组及其原始索引"""
    result = {}
    for idx, item in enumerate(data):
        if 'H' in item[0]:
            key = (item[0], item[1])
            if key not in result:
                result[key] = {"items": [], "indices": []}
            result[key]["items"].append(item)
            result[key]["indices"].append(idx)
    return {k: v for k, v in result.items() if len(v["items"]) >= 2}


def is_adjacent(group, value_map):
    """检查分组是否连续相邻"""
    items = group["items"]
    for i in range(len(items) - 1):
        current_end = items[i][3]
        next_start = items[i + 1][2]
        if (current_end not in value_map or
                next_start not in value_map or
                value_map[next_start] != value_map[current_end] + 1):
            return False
    return True


def merge_group(group):
    """合并连续的分组"""
    items = group["items"]
    return [items[0][0], items[0][1], items[0][2], items[-1][3]]


def merge_chars_fm(original_data, cids):
    """处理原始数据，返回新数据（保持绝对顺序）"""
    # 获取需要处理的分组及其原始索引
    groups_to_process = group_data(original_data)

    # 创建新数据列表（初始为None用于标记位置）
    new_data = [None] * len(original_data)

    # 首先填充所有不需要处理的元素
    for idx, item in enumerate(original_data):
        if not any(idx in group["indices"] for group in groups_to_process.values()):
            new_data[idx] = item

    # 处理每个分组
    for group in groups_to_process.values():
        col_cid = group["items"][0][1]
        # 查找id为16对应的列表
        list1 = None
        for item in cids:
            if item[0] == col_cid:
                list1 = item[1]
                break
        # 创建值到索引的映射字典
        value_to_index = {v: i for i, v in enumerate(list1)}
        if is_adjacent(group, value_to_index):
            # 可合并的情况：在第一个元素的位置放入合并结果
            merged = merge_group(group)
            new_data[group["indices"][0]] = merged
            # 将其他位置标记为待删除
            for i in group["indices"][1:]:
                new_data[i] = "deleted"
        else:
            # 不可合并的情况：原样放回
            for item, idx in zip(group["items"], group["indices"]):
                new_data[idx] = item

    # 移除标记为删除的元素
    return [item for item in new_data if item != "deleted"]


def update_sutra_catalog():
    """更新sutra表的卷目录"""
    hp.set_logging('update_sutra_catalog')
    logging.info('update_sutra_catalog')
    db_test = hp.get_db('tr-readlytest')
    tripitaka_uid = 'JS'
    sutras = list(db_test.sutra.find({'tripitaka_uid': tripitaka_uid}))

    for sutra in sutras:
        logging.info('\t%s' % sutra['uid'])
        sutra_catalog = []
        for reel_uid in sutra['reel_uids']:

            elements = []
            reel = db_test.reel.find_one({'uid': reel_uid[0]})

            p_dict = {}
            if not reel.get('pages'):  # ['JS1724_002z1', '图像'] 没有pages
                continue
            for page in reel.get('pages'):
                p = db_test.page.find_one({'uid': page['uid']})
                page['std_txt0'] = get_column_txt_list(p, 'std_txt')
                page['sim_txt0'] = get_column_txt_list(p, 'sim_txt')
                p_dict[page['uid']] = p

            page_dic = {p['uid']: p for p in reel['pages']}
            for i, fm in enumerate(reel['format']):
                # 整理页的格式标注，把列和字的标题进行合并
                page = page_dic.get(fm['uid'])
                if not page:
                    continue
                page_fm = []
                fm_dict = {}
                for col in fm.get('columns', []):
                    if col[0] in ['H1', 'H2', 'H3', 'H4', 'H5']:
                        fm_dict[col[1]] = [col[0], col[1], [], 'columns']

                """处理字数据"""
                original_chars_fm = fm.get('chars', [])
                if original_chars_fm:
                    original_chars_fm = merge_chars_fm(original_chars_fm, fm.get('cids', []))

                for ch in original_chars_fm:
                    if ch[0] in ['H1', 'H2', 'H3', 'H4', 'H5']:
                        fm_dict[ch[1]] = [ch[0], ch[1], [ch[2], ch[3]], 'chars']
                if not fm_dict:
                    continue
                p1 = p_dict[page['uid']]
                valid_cids = [col['cid'] for col in p1.get('columns', [])]
                if reel.get('start_page_ouid') == page['ouid'] and reel.get('start_column_cid'):

                    index = valid_cids.index(reel.get('start_column_cid'))  # 找到元素的索引
                    valid_cids = valid_cids[index:]  # 获取后面的元素

                elif reel.get('end_page_ouid') == page['ouid'] and reel.get('end_column_cid'):

                    index = valid_cids.index(reel.get('end_column_cid'))  # 找到元素的索引
                    valid_cids = valid_cids[:index + 1]  # 获取前面的元素

                for column_cid in valid_cids:
                    if column_cid in fm_dict.keys():
                        page_fm.append(fm_dict[column_cid])

                for col in page_fm:
                    if col[3] == 'columns':
                        if col[0] in ['H1', 'H2', 'H3', 'H4', 'H5']:
                            page = page_dic.get(fm['uid'])
                            if not page:
                                continue

                            h_index = [i for i, std_txt in enumerate(page.get('std_txt0', [])) if std_txt[0] == col[1]]
                            if h_index:
                                i = h_index[0]
                                sim_txt = page['sim_txt0'][i][1]
                                std_txt = page['std_txt0'][i][1]
                                line_uid = '%s@%s' % (fm['uid'], col[1])
                                elements.append({col[0]: [col[1], line_uid, std_txt, sim_txt]})
                    elif col[3] == 'chars':
                        if col[0] in ['H1', 'H2', 'H3', 'H4', 'H5']:
                            page = page_dic.get(fm['uid'])
                            if not page:
                                continue
                            start_char_cid = col[2][0]
                            end_char_cid = col[2][1]
                            char_cids = [c['cid'] for c in p1.get('chars', [])]
                            char_std_txts = [c['std_txt'] for c in p1.get('chars', [])]
                            char_sim_txts = [c['sim_txt'] for c in p1.get('chars', [])]
                            start_index = char_cids.index(start_char_cid)  # 找到元素的索引
                            end_index = char_cids.index(end_char_cid)  # 找到元素的索引
                            sim_txt = char_sim_txts[start_index:end_index + 1]
                            std_txt = char_std_txts[start_index:end_index + 1]
                            sim_txt = ''.join(sim_txt)
                            std_txt = ''.join(std_txt)
                            line_uid = '%s@%s' % (fm['uid'], col[1])
                            elements.append({col[0]: [col[1], line_uid, std_txt, sim_txt]})

            reel_catalog = get_reel_catalog(elements)
            if reel_catalog:
                for reel_catalog1 in reel_catalog:
                    reel_catalog1['reel_uid'] = reel['uid']
                    sutra_catalog.append(reel_catalog1)

        if sutra_catalog:
            sutra_catalog = remove_elements_recursive(sutra_catalog)
            sutra_catalog = clean_catalog_texts(sutra_catalog)
            db_test.sutra.update_one({'uid': sutra['uid']}, {'$set': {'catalog': sutra_catalog}})

        # if sutra_catalog:
        #     sutra_catalog = remove_elements_recursive(sutra_catalog)
        #     db_prod0.sutra.update_one({'uid': sutra['uid']}, {'$set': {'catalog': sutra_catalog}})
        #     db_prod.sutra.update_one({'uid': sutra['uid']}, {'$set': {'catalog': sutra_catalog}})
        # else:
        #     db_prod0.sutra.update_one({'uid': sutra['uid']}, {'$set': {'catalog': []}})
        #     db_prod.sutra.update_one({'uid': sutra['uid']}, {'$set': {'catalog': []}})

def clean_catalog_texts(data_list):
    """Recursively remove unwanted characters from sim_txt and std_txt in sutra_catalog."""
    import re
    # Define unwanted characters as a regex pattern
    pattern = re.compile(r'[─■□△○●〇]')  # Keep only word chars, whitespace, and Chinese characters
    def clean_text(txt):
        if not isinstance(txt, str):
            return txt
        return pattern.sub('', txt)

    def clean_item(item):
        if 'sim_txt' in item:
            item['sim_txt'] = clean_text(item['sim_txt'])
        if 'std_txt' in item:
            item['std_txt'] = clean_text(item['std_txt'])
        if 'children' in item:
            for child in item['children']:
                clean_item(child)
        return item

    return [clean_item(item) for item in data_list]

def remove_elements_recursive(data_list):
    # 定义需要过滤的关键字列表
    keywords = ['音释',
                '校讹',
                '挍讹',
                '较讹',
                '𣏤讹',
                '咅释',
                '音释',
                '音𥼶',
                '释音',
                '𥼶音',
                '音切',
                '音译',
                '音义',
                ]

    # 递归过滤函数
    def filter_item(item):
        # 获取 sim_txt 的最后两个字符
        sim_txt = item.get('sim_txt', '')
        last_two_chars = sim_txt[-2:] if len(sim_txt) >= 2 else ''

        # 如果当前元素的 sim_txt 的最后两个字符等于关键字，则移除
        if last_two_chars in keywords:
            return None

        # 如果当前元素有 children，递归处理 children
        if 'children' in item:
            item['children'] = [child for child in item['children'] if filter_item(child) is not None]
            # 如果 children 被清空，移除 children 键
            if not item['children']:
                del item['children']

        return item

    # 过滤主列表
    filtered_list = [item for item in data_list if filter_item(item) is not None]
    return filtered_list


def update_reel_fm():
    """更新reel的格式标注"""
    hp.set_logging('update_reel_fm')
    tripitaka_uid = 'JS'

    uids = db_prod0.reel.distinct('uid', {'tripitaka_uid': tripitaka_uid})
    for i, uid in enumerate(uids):
        reel_code = get_reel_ouid(uid)
        reel = db_work.reel.find_one({'reel_code': reel_code}, {'name': 1, 'format': 1})
        format = reel.get('format', [])
        for fm in format:
            fm['uid'] = get_buid(fm['name'])
            fm['ouid'] = fm['name']
            fm.pop('name', 0)
        r0 = db_prod0.reel.update_one({'uid': uid}, {'$set': {'format': format}})
        r = db_prod.reel.update_one({'uid': uid}, {'$set': {'format': format}})
        logging.info('%s\t%s\t%s\t%s' % (i, uid, r0.matched_count, r.matched_count))


def update_reel_pages():
    reel.update_reel_pages()


def set_group_char_result_all():
    print('set_group_char_result_all')
    set_group_char_result(txt_type='ot')  # 17set_group_char_result
    set_group_char_result(txt_type='ut')
    set_group_char_result(txt_type='st')
    set_group_char_result(txt_type='mt')


def set_page_flag():
    """找出差异的页数据，进行更新，并且进行flag标记"""
    hp.set_logging('set_page_flag')
    print('set_page_flag')
    tripitaka_uid = 'JS'
    names = db_prod0.page.distinct('ouid', {'tripitaka_uid': tripitaka_uid})
    sorted_lst = sorted(names, key=lambda x: [int(y) for y in x.split('_') if y.isdigit()])
    print(sorted_lst[0], sorted_lst[-1])
    split_lst = [sorted_lst[i:i + 1000] for i in range(0, len(sorted_lst), 1000)]
    for i, names in enumerate(split_lst):
        logging.info('%s\t%s\t%s' % (i, len(names), len(split_lst)))
        fields = ['name', 'width', 'height', 'blocks', 'columns', 'chars', 'layout', 'punc_txt', 'reel_uids',
                  'sutra_uids']

        pages0 = list(db_prod0.page.find({'ouid': {'$in': names}}, {'blocks': 1, 'columns': 1, 'chars': 1, 'ouid': 1}))

        name2page = {p['ouid']: p for p in pages0}

        pages = list(db_work.page.find({'name': {'$in': names}}, {'_id': 0, **{f: 1 for f in fields}}))
        pages = sorted(pages, key=lambda page: [int(y) for y in page['name'].split('_') if y.isdigit()])
        for p in pages:
            page = {}
            name = p['name']
            page['ouid'] = name
            page['uid'] = get_buid(name)
            page['layout'] = p['layout']
            image = {'width': p['width'], 'height': p['height']}
            page['image'] = image
            # 检查、设置列和子列
            for col in p.get('columns', []):
                # 设置子列数据
                sub_columns = col.get('sub_columns', [])
                for i, sc in enumerate(sub_columns):
                    sub_columns[i] = {k: sc[k] for k in ['x', 'y', 'w', 'h', 'sub_no', 'char_cids'] if sc.get(k)}

            for k in ['blocks', 'columns', 'chars']:
                p[k] = [c for c in p[k] if not c.get('deleted')]
                for i, box in enumerate(p[k]):
                    info = {f: round(box.get(f), 1) for f in ['x', 'y', 'w', 'h']}
                    info.update({f: box[f] for f in [
                        'block_id', 'char_id', 'column_id', 'txt', 'cid', 'char_cids', 'sub_columns', 'is_center'] if
                                 box.get(f)})
                    p[k][i] = info

            if p.get('chars'):
                for c in p['chars']:
                    if c.get('deleted'):
                        continue
            page.update(p)
            page.pop('name', 0)
            page.pop('width', 0)
            page.pop('height', 0)
            page['tripitaka_uid'] = tripitaka_uid
            page['img_name'] = '%s_%s' % (name, hp.md5_encode(name))
            page['ouid2'] = hp.align_code(page['ouid'])
            page['reel_uids'] = []
            page['sutra_uids'] = []

            for reel_uid in p.get('reel_uids', []):
                parts = reel_uid.split('_')
                uid = f'{parts[0]}{int(parts[1]):04d}_{int(parts[2]):03d}'
                page['reel_uids'].append(uid)

            for sutra_uid in p.get('sutra_uids', []):
                parts = sutra_uid.split('_')
                uid = f'{parts[0]}{int(parts[1]):04d}'
                page['sutra_uids'].append(uid)
            page0 = name2page[page['ouid']]
            chars0 = page0.get('chars', [])
            for ch in chars0:
                for field in ["ori_txt", "uni_txt", "std_txt", "sim_txt"]:
                    ch.pop(field, 0)
            if page.get('chars') != chars0 or page.get('columns') != page0['columns'] or page.get('blocks') != page0[
                'blocks']:
                page['flag'] = 1
                db_prod0.page.update_one({'ouid': page['ouid']}, {'$set': page})
                logging.info('\t%s' % (page['ouid']))


def custom_sort_key_read(s):
    """
    针对实际数据格式的自定义排序key：
    格式：JS数字[字母]_数字[后缀]
    1. 首先按主要数字部分排序
    2. x后缀排在基础版本之前，z后缀排在基础版本之后
    """
    # 提取主要部分：JS后面的数字和可选的字母，以及下划线后的数字
    main_match = re.search(r'JS(\d+)([a-z]?)_(\d+)', s)
    if main_match:
        main_num = int(main_match.group(1))  # 0001, 0002 等
        main_letter = main_match.group(2)  # a, b 等字母（可能为空）
        sub_num = int(main_match.group(3))  # 001, 0011 等

        # 字母转换为数字用于排序（a=1, b=2, 无字母=0）
        letter_priority = ord(main_letter) - ord('a') + 1 if main_letter else 0
    else:
        main_num = 0
        letter_priority = 0
        sub_num = 0

    # 检查后缀类型
    if 'x' in s and re.search(r'x\d+$', s):  # x后缀
        suffix_match = re.search(r'x(\d+)$', s)
        suffix_num = int(suffix_match.group(1)) if suffix_match else 0
        priority = 1  # x后缀最高优先级
        suffix_type = 'x'
    elif 'z' in s and re.search(r'z\d+$', s):  # z后缀
        suffix_match = re.search(r'z(\d+)$', s)
        suffix_num = int(suffix_match.group(1)) if suffix_match else 0
        priority = 3  # z后缀较低优先级
        suffix_type = 'z'
    else:  # 无后缀
        priority = 2  # 无后缀中等优先级
        suffix_type = ''
        suffix_num = 0

    return (main_num, letter_priority, sub_num, priority, suffix_type, suffix_num)


def process():
    """局部更新"""
    set_page_flag()  # 1 找出差异的页数据，进行更新，并且进行flag标记
    update_page_txts()  # 2设置page中chars的ori_txt 、uni_txt、std_txt、sim_txt
    update_pages_imgages()  # 3更新page文中图
    update_reel_fm()  # 4更新格式标注
    update_page_format()  # 5更新page表format
    update_reel_pages()  # 6执行 web\tr\reel.py update_reel_pages
    update_sutra_reel_uids()  # 7更新sutra表的reel_uids
    update_sutra_catalog()  # 8更新sutra表的卷目录

    import_chars()  # 9导入字数据
    set_coll_seg_ids()  # 10设置字表的的seg_ids
    import_char_type()  # 11导入字种表
    set_group_char_result_all()  # 12set_group_char_result
    update_sutra_char_cnt()  # 13更新经的字数


def main(func='update_sutra_catalog', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
