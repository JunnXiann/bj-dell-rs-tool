from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re
import sys

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print(f'root_dir:{root_dir}')
sys.path.append(root_dir)

from util.punc_lib.yinshi_deal import get_reel_column_list, get_rule_bd
import helper as hp


def get_reel_all_pages(reel):
    """
    reel: 卷对象（来自校对平台数据库） 注：校对平台和阅藏平台的reel数据结构不一样，这里适用校对平台的reel数据结构
    reel_all_pages示例:
        {
            # 页码(page_name)作为唯一id, 快速索引到行数据
            'JS_1_8': [
                    {
                        'col_cid': 1,  # 行的唯一id
                        'char_cids': [1,2,3,4],  # 该行包含的字cid
                        'col_txt': "大般若波羅蜜多經卷第一",  # 校对文本的单行内容
                        'col_format': "J",
                        'char_format': [],  # 单行有多个字格式时：[["N", 1, 1, 14], ["N", 1, 17, 34]] 含义: format, column_cid, start_cid, end_cid
                    },
                    ...
            ],
            'JS_1_9': [...],
        }
    """
    reel_all_pages = {}
    pages = reel.get('pages') or []
    for page in pages:
        page_name = page.get('name')
        single_reel_page = []
        if not page.get('cids'):  # 跳过错误数据(page里没cids是错误数据)
            continue

        for index, cid in enumerate(page['cids']):
            single_page_col = {}
            single_page_col['col_cid'] = cid[0]
            single_page_col['char_cids'] = cid[1]
            single_page_col['col_txt'] = page['txt'][index]
            single_page_col['col_format'] = 'T'  # 默认为正文，没有format则全部为正文
            single_page_col['char_format'] = []
            if reel.get('format'):
                for format in reel['format']:
                    if format['name'] == page_name:
                        for col_fmt in format['columns']:
                            if col_fmt[1] == single_page_col['col_cid']:
                                single_page_col['col_format'] = col_fmt[0]
                                break
                        for char_fmt in format.get('chars', []):
                            if char_fmt[1] == single_page_col['col_cid']:
                                single_page_col['char_format'].append(char_fmt)
                        break

            single_reel_page.append(single_page_col)
        reel_all_pages[page_name] = single_reel_page

    return reel_all_pages


def merge_by_format(reel_column_list, include_center=False):
    """
    拼接col_format相同且连续的行，返回每组的page_name、col_format和拼接后的col_txts。
    返回相同format的连续行（所有格式）
    返回格式:
    [
        {'page_name': 'xxx', 'col_format': 'E', 'col_txts': ['xxx'], 'col_cid': 2},
        ...
    ]
    include_center: 是否包含版心列
    """
    if not reel_column_list:
        return []
    result = []
    current_group = []
    for col in reel_column_list:
        if col.get('col_format') == 'G' and not include_center:
            continue
        if not current_group:
            current_group.append(col)
        else:
            # 判断col_format是否与上一行相同且连续
            if col['col_format'] == current_group[-1]['col_format']:
                current_group.append(col)
            else:
                # 拼接当前组
                col_txts = [item['col_txt'] for item in current_group]
                result.append(
                    {
                        'page_name': current_group[0]['page_name'],
                        'col_cid': current_group[0]['col_cid'],  # 使用第一行的col_cid
                        'col_format': current_group[0]['col_format'],
                        'col_txts': col_txts,
                    }
                )
                current_group = [col]
    # 最后一组
    if current_group:
        col_txts = [item['col_txt'] for item in current_group]
        result.append(
            {
                'page_name': current_group[0]['page_name'],
                'col_cid': current_group[0]['col_cid'],
                'col_format': current_group[0]['col_format'],
                'col_txts': col_txts,
            }
        )
    return result


def concat_col_txt_by_format(reel_all_columns, format):
    """
    reel_all_columns数据结构:
    [
        {'page_name','col_cid', 'char_cids', 'col_txt', 'col_format', 'char_format'}
        , ...
    ]
    format: 拼接的连续格式,如“E”、“K”分别代表音释、牌记

    返回相同format的连续行（特定格式）
    same_format_col_txts数据格式: [{'page_name', 'content'}, ...]
    """
    same_format_col_txts = []

    if reel_all_columns:
        current_group = []
        for col in reel_all_columns:
            if col.get('col_format') == format:
                current_group.append(col)
            else:
                if current_group:
                    content = ''.join([item['col_txt'] for item in current_group])
                    same_format_col_txts.append(
                        {
                            'page_name': current_group[0]['page_name'],
                            'col_cid': current_group[0]['col_cid'],
                            'content': content,
                        }
                    )
                    current_group = []
        # 最后一组
        if current_group:
            content = ''.join([item['col_txt'] for item in current_group])
            same_format_col_txts.append(
                {'page_name': current_group[0]['page_name'], 'col_cid': current_group[0]['col_cid'], 'content': content}
            )

    return same_format_col_txts


def merge_rows_with_charfmt(reel_all_columns, col_format):
    """
    返回大段的音释内容，合并char_cids，连续的char_format合并
    例如，校对平台 JS_1_46卷 JS_1_963页 5~8行的音释合并结果如下:
    [{'page_name': 'JS_1_963', 'col_cid': 5, 'char_cids': [46, 47, 48, ... , 119, 120, 121],
    'col_txt': '苾芻苾薄密切芻楚俱切.......衆生謂用佛道成就衆生也埵音朶', 'col_format': 'E',
    'char_format': [['N', 5, 48, 99], ['N', 6, 102, 121]]}]
    """
    merged = []
    i = 0
    while i < len(reel_all_columns):
        row = reel_all_columns[i]
        if row['col_format'] != col_format:
            i += 1
            continue

        # 初始化合并行
        merged_row = {
            'page_name': row['page_name'],
            'col_cid': row['col_cid'],
            'char_cids': list(row['char_cids']),
            'col_txt': row['col_txt'],
            'col_format': row['col_format'],
            'char_format': [fmt.copy() for fmt in row['char_format']],
        }

        j = i + 1
        while j < len(reel_all_columns) and reel_all_columns[j]['col_format'] == 'E':
            next_row = reel_all_columns[j]
            # 合并 char_cids
            merged_row['char_cids'].extend(next_row['char_cids'])
            # 合并 col_txt
            merged_row['col_txt'] += next_row['col_txt']

            # 合并 char_format
            if merged_row['char_format'] and next_row['char_format']:
                last_fmt = merged_row['char_format'][-1]
                next_fmt = next_row['char_format'][0]
                # 判断格式类型相同且编号连续
                if last_fmt[0] == next_fmt[0] and last_fmt[3] + 1 == next_fmt[2]:
                    # 合并格式区间
                    merged_row['char_format'][-1][3] = next_fmt[3]
                    # 拼接 next_row 剩余的格式
                    merged_row['char_format'].extend([fmt.copy() for fmt in next_row['char_format'][1:]])
                else:
                    merged_row['char_format'].extend([fmt.copy() for fmt in next_row['char_format']])
            else:
                merged_row['char_format'].extend([fmt.copy() for fmt in next_row['char_format']])

            j += 1

        merged.append(merged_row)
        i = j
    return merged


def set_reel_bd_pre_data(reel_code, tw_db, tr_db):
    """
    校对平台reel表设置bd_pre_data值，包含yinshi、colophon(牌记)
    """
    reel_doc = tw_db.reel.find_one({'reel_code': reel_code})

    reel_all_columns = get_reel_column_list(reel_doc)
    merged_column_list = merge_by_format(reel_all_columns, False)

    # 音释 "E"  音释规则处理（AI打标已弃用）
    reel_yinshi_dict = get_rule_bd(reel_doc, 'E')

    # 行格式 校讹 "C"
    reel_emendation_dict = get_rule_bd(reel_doc, 'C')

    # 卷所属的牌记
    colophon_col_txts = [col for col in merged_column_list if col['col_format'] == 'K']
    bd_colophon = dict()
    for col_txt in colophon_col_txts:
        page_name = col_txt['page_name']
        pubnote = tr_db.pubnote.find_one({'img_name': {'$regex': f'^{re.escape(page_name)}'}}, {'pub_note': 1})
        if pubnote:
            key = col_txt['page_name'] + '_' + str(col_txt['col_cid'])
            bd_colophon[key] = [{'txt': pubnote.get('pub_note')}]

    # 校对平台数据库reel表设置bd_pre_data.yinshi和bd_pre_data.colophon
    tw_db.reel.update_one(
        {'reel_code': reel_code},
        {
            '$set': {
                'bd_pre_data': {
                    'yinshi': reel_yinshi_dict,
                    'colophon': bd_colophon,
                    'emendation': reel_emendation_dict,
                }
            }
        },
    )
    print('reel_code:', reel_code, 'done')


if __name__ == '__main__':
    tw_client = hp.connect_db_max('tw-product', 'mongodb-', True)
    # 选择数据库
    tw_db = tw_client['tripitaka-product']
    # tw_db = tw_client["tripitaka-dev"]
    # 查询径山藏的卷
    cond = {'sutra_code': {'$regex': 'JS_'}}
    # cond = {"reel_code" : {"$in": ["JS_445_2", "JS_445_3"]}}
    reels = list(tw_db.reel.find(cond, {'reel_code': 1}))

    tr_client = hp.connect_db_max('tr-readprod', 'mongodb-', True)
    # 选择数据库
    tr_db = tr_client['tripitaka-reader-prod']

    # 单独测试
    # set_reel_bd_pre_data('JS_1669_89', tw_db, tr_db)

    reel_codes = [reel['reel_code'] for reel in reels]
    # # 方便查看哪个卷报错
    # # for reel_code in reel_codes:
    # #     set_reel_bd_pre_data(reel_code, tw_db, tr_db)

    max_workers = os.cpu_count() * 2
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(set_reel_bd_pre_data, rc, tw_db, tr_db) for rc in reel_codes]
        for future in as_completed(futures):
            future.result()
