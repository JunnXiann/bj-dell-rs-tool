import os
import re
import sys

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print(f'root_dir:{root_dir}')
sys.path.append(root_dir)

import helper as hlp
# from util.punc import call_gj_ai_punc_v1

PUNC_STR = '。？！，、；：“”‘’「」『』﹃﹄﹁﹂（）《》〈〉［］〔〕【】()——……－～'
CHAR_FMT_TITLE = ['H1', 'H2', 'H3', 'H4', 'H5']


def get_reel_column_list(reel, cut_txt=True):
    """获取卷相关的行数据
    注：reel需要包含需要pages和format字段
    返回值数据结构:
    [
        {
            'page_name': 'xxxx',
            'col_cid': 1,  # 行的唯一id
            'char_cids': [[1, 5], 7],  # 该行包含的字cid，连续cid可以合并，例如[1,5]表示从1到5
            'col_txt': "大般若波羅蜜多經卷第一",  # 校对文本的单行内容
            'col_format': "J",
            'char_format': [],  # 单行有多个字格式时：[["N", 1, 14], ] 含义: format, start_cid, end_cid
        },
        ...
    ]
    cut_txt：是否根据起止字段截取文本：start_volume、start_page、start_block、start_column、end_volume、end_page、end_block、end_column
    """
    col_list = []
    pages = reel.get('pages') or []
    name2format = {p['name']: p for p in reel.get('format') or []}
    start_page = '%s_%s' % (reel.get('start_volume'), reel.get('start_page'))
    end_page = '%s_%s' % (reel.get('end_volume'), reel.get('end_page'))

    for page in pages:
        page_name = page.get('name')
        if not page.get('cids'):
            continue

        page_format = name2format.get(page_name) or {}
        col_cid2col_format = {cid: fmt for fmt, cid in page_format.get('columns') or []}
        valid = page_name != start_page  # 当前行是否有效（起始页默认从无效开始）
        for idx, cid in enumerate(page['cids']):
            col_cid = cid[0]
            col_format = col_cid2col_format.get(col_cid) or 'T'  # 缺省为正文
            # 检查有效性
            add_current = False
            if page_name == start_page:  # 起始页去掉前面多余的文字
                # 默认从无效行开始，计算从哪里开始为有效
                if not reel.get('start_column') and (not reel.get('start_block') or reel.get('start_block') == 1):
                    valid = True
                elif reel.get('start_column'):
                    if reel['start_column'] == col_cid:
                        valid = True
            elif page_name == end_page:  # 终止页去掉后面多余的文字
                # 默认从有效行开始，计算从哪里开始为无效
                if reel.get('end_column'):
                    if reel['end_column'] == col_cid:
                        valid = False
                        add_current = True

            if not cut_txt or valid or add_current:
                col = dict()
                col['page_name'] = page_name
                col['col_txt'] = page['txt'][idx]
                col['col_cid'] = col_cid
                col['col_format'] = col_format
                col['char_cids'] = cid[1]  # 此处不聚合数字[1,2,3,4]不改为[[1,4]]
                col['char_format'] = []
                for ch_fmt in page_format.get('chars') or []:  # 字格式
                    if ch_fmt[1] == col['col_cid']:
                        col['char_format'].append([ch_fmt[0], ch_fmt[2], ch_fmt[3]])
                col_list.append(col)

    return col_list


def get_char_type_info(char_cids, char_format, col_txt):
    """
    char_cids: 单行的字cids, 例如[1,2,3,4]
    char_format: 单行的字格式, 例如[["N", 1, 1, 14], ["N", 1, 17, 34]]
    col_txt: 行格式文本, 'xxxx'

    返回示例：[{'char': '控', 'type': 'L'}, {'char': '苦', 'type': 'N'}]
    """
    char_type_info = ['L'] * len(char_cids)  # 初始化为未标注 L

    for fmt in char_format:
        fmt_type, start_cid, end_cid = fmt
        start_idx = char_cids.index(start_cid)
        end_idx = char_cids.index(end_cid)
        for i in range(start_idx, end_idx + 1):
            char_type_info[i] = fmt_type

    result = []
    for i, ch in enumerate(col_txt):
        result.append({'char': ch, 'type': char_type_info[i], 'bd_logs': {}})

    return result


def get_merged_yinshi_list(reel_column_list, include_center=False, format_type='E'):
    """
    返回格式:
    [
        {
            'page_name': 'xxx', 'col_format': 'E', 'col_txts': 'xxxxxx', 'col_cid': 2,
            'char_type_info': [{'char': '般', 'type': 'L'}, {'char': '梵', 'type': 'N'}]
        },
        ...
    ]
    include_center: 是否包含版心列
    format_type: 'E'或'C', 取合并并且附带char_type_info的音释或者校讹
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
                if current_group[-1]['col_format'] == format_type:
                    char_type_info = []
                    for item in current_group:
                        char_type_info.extend(item['char_type_info'])
                    result.append(
                        {
                            'page_name': current_group[0]['page_name'],
                            # 使用第一行的col_cid
                            'col_cid': current_group[0]['col_cid'],
                            'col_format': current_group[0]['col_format'],
                            'col_txts': col_txts,
                            'char_type_info': char_type_info,
                            # 首行的字格式，用于判断是否为字格式标题开头
                            # 例如：“音释”+音释内容 JS_1_13#JS_1_255_19
                            'char_format': current_group[0].get('char_format', []),
                            'col_start_cid': current_group[0]['char_cids'][0],
                        }
                    )
                else:
                    result.append(
                        {
                            'page_name': current_group[0]['page_name'],
                            # 使用第一行的col_cid
                            'col_cid': current_group[0]['col_cid'],
                            'col_format': current_group[0]['col_format'],
                            'col_txts': col_txts,
                        }
                    )
                current_group = [col]
    # 最后一组
    if current_group:
        col_txts = [item['col_txt'] for item in current_group]
        if current_group[-1]['col_format'] == format_type:
            char_type_info = []
            for item in current_group:
                char_type_info.extend(item['char_type_info'])
            result.append(
                {
                    'page_name': current_group[0]['page_name'],
                    'col_cid': current_group[0]['col_cid'],  # 使用第一行的col_cid
                    'col_format': current_group[0]['col_format'],
                    'col_txts': col_txts,
                    'char_type_info': char_type_info,
                    'char_format': current_group[0].get('char_format', []),
                    'col_start_cid': current_group[0]['char_cids'][0],
                }
            )
        else:
            result.append(
                {
                    'page_name': current_group[0]['page_name'],
                    'col_cid': current_group[0]['col_cid'],  # 使用第一行的col_cid
                    'col_format': current_group[0]['col_format'],
                    'col_txts': col_txts,
                }
            )

    merged_yinshi_list = []
    for col in result:
        if col['col_format'] == format_type:
            col['col_txts'] = ''.join(col['col_txts'])
            merged_yinshi_list.append(col)

    return merged_yinshi_list


def insert_newlines(char_type_info):
    new_txt = ''
    for i in range(len(char_type_info)):
        new_txt += char_type_info[i]['char']
        # 如果当前是 N，下一位是 L，则插入换行符
        if char_type_info[i]['type'] == 'N':
            if i + 1 < len(char_type_info) and char_type_info[i + 1]['type'] == 'L':
                new_txt += '\n'
    return new_txt


def yinshi_re_deal(text):
    # 先处理“二切” 规则2. “，XX、XX二切。”
    def erqie_replacer(match):
        first = match.group(2) if match.group(2) else ''
        second = match.group(3) if match.group(3) else ''
        qie_char = match.group(4)  # 保留原文中的“切”字形
        return f'，{first}、{second}二{qie_char}。'

    erqie_pattern = r'([。.，,]?)(..)[、,]?(..)二([切切切𭃄])[，,。.]?'
    text = re.sub(erqie_pattern, erqie_replacer, text)

    # 再处理单个“切”，但排除“二切” 规则1. “，XX切。”
    def qie_replacer(match):
        full_match = match.group(0)
        chars = match.group(2) if match.group(2) else ''
        qie_char = match.group(3)  # 保留原文中的“切”字形
        # 排除“二切”
        if re.search(rf'二[切切切𭃄]', full_match):
            return full_match  # 不处理
        return f'，{chars}{qie_char}。'

    qie_pattern = r'([，,]?)(..)?([切切切𭃄])[，,。.]?'
    text = re.sub(qie_pattern, qie_replacer, text)

    # 3. “，XX反。”
    def fan_replacer(match):
        chars = match.group(2) if match.group(2) else ''
        return f'，{chars}反。'

    fan_pattern = r'([，,]?)(..)反[，,。.]?'
    text = re.sub(fan_pattern, fan_replacer, text)

    # 4. “曰：”
    text = re.sub(r'曰[：:，,]?', '曰：', text)

    # 5. “从X，X声也。”
    def cong_replacer(match):
        x = match.group(1)
        y = match.group(2)
        sheng_char = match.group(3)
        return f'从{x}，{y}{sheng_char}也。'

    # 匹配“从”后跟一个汉字（可根据需要调整），后面不是“，X声也。”
    text = re.sub(r'从[，,。.]?(.)[，,。.]?(.)([聲𮋻声𤛗𡔜])也[，,。.]?', cong_replacer, text)

    # 6. “也。”
    text = re.sub(r'也[，,。.]?', '也。', text)

    # 11. 常见书名加书名号：《尔雅》《广雅》《字林》《说文》《仓颉篇》《玉篇》《声类》《通俗文》
    book_titles = [
        '尔雅',
        '尔疋',
        '爾雅',
        '爾疋',
        '廣雅',
        '字林',
        '説文',
        '說文',
        '倉頡篇',
        '玉篇',
        '聲類',
        '通俗文',
    ]
    pattern = r'(?<!《)(' + '|'.join(book_titles) + r')(?!》)'
    text = re.sub(pattern, r'《\1》', text)

    return text


def yinshi_format_deal(char_type_info):
    """
    规则来源：https://rushi-ai.feishu.cn/docx/KJZzd7aAZo5T2fxNMPVcC5xCnMc
    规则7、8、9、10
    """
    if not char_type_info:
        return ''

    format_bd_txt = ''
    for i in range(len(char_type_info)):
        format_bd_txt += char_type_info[i]['char']

        # 如果当前是 N，下一位是 L
        if char_type_info[i]['type'] == 'N':
            if i + 1 < len(char_type_info) and char_type_info[i + 1]['type'] != 'N':
                # 规则7: 小字句尾加句号
                # 规则10: 每个“大字：小字”单独成段
                # 小字与字格式标题 之间也需要'。\n'
                format_bd_txt += '。）\n'  # 音释一行的末尾
            elif i + 1 == len(char_type_info):  # 整个音释的末尾
                format_bd_txt += '。）'

        # 如果当前是 L，下一位是 N
        if char_type_info[i]['type'] == 'L':
            if i + 1 < len(char_type_info) and char_type_info[i + 1]['type'] == 'N':
                # 规则9: 小字加括号
                format_bd_txt += '（'

    # 规则8: 小字完全匹配大字, 在小字后加逗号  例如：“欻尔：欻，许勿切。欻尔，犹卒然也。”  命中小字“欻尔”加“，”
    dazi_list = []
    _tmp = ''
    for char_info in char_type_info:
        if char_info['type'] == 'L':
            _tmp += char_info['char']
        # 大字被字格式标题隔断，例如JS_141_3#JS_24_25b_17
        elif char_info['type'] in CHAR_FMT_TITLE:
            continue
        else:
            if _tmp:
                dazi_list.append(_tmp)
                _tmp = ''

    def replacer(match):
        replacer.count += 1
        if replacer.count == 1:
            return match.group(0)
        else:
            return f'{match.group(1)}，{match.group(2)}'

    # 大字命中加“，”
    dazi_hit_list = []
    yinshi_cols = format_bd_txt.split('\n')
    len_diff = 0
    # 音释以小字开头时，yinshi_cols行数比大字多一行
    if len(dazi_list) < len(yinshi_cols):
        len_diff = 1
        dazi_hit_list.append(yinshi_cols[0])
    if len(dazi_list) > len(yinshi_cols):
        print(dazi_list)
        print(yinshi_cols)
    for i, dazi in enumerate(dazi_list):
        replacer.count = 0
        pattern = rf'({dazi})([^，。！？：；]*)'
        result = re.sub(pattern, replacer, yinshi_cols[i + len_diff])
        dazi_hit_list.append(result)

    # 合并回format_bd_txt
    format_bd_txt = '\n'.join(dazi_hit_list)
    return format_bd_txt


def emendation_re_deal(text):
    """
    校讹规则来源：https://rushi-ai.feishu.cn/docx/PReBdMarPov9Q7xwhsAcFc86n8e
    若出现在句首，则不加标点
    """

    # 先处理“今從” 规则5. “，今從”
    def jincong_replacer(match):
        prefix = match.group(1)
        cong_char = match.group(2)
        if prefix == '':  # 句首
            return f'今{cong_char}'
        return f'{prefix}，今{cong_char}'

    # 捕获：前缀可以为空或任意字符（非换行）
    jincong_pattern = r'(^|.?)今([從从従徔𫢴])'
    text = re.sub(jincong_pattern, jincong_replacer, text)

    # 处理单独 '從'（但避免重复匹配已经处理过的 '今從'）
    def cong_replacer(match):
        prefix = match.group(1)
        cong_char = match.group(2)
        if prefix == '':  # 句首
            return f'{cong_char}'
        return f'{prefix}，{cong_char}'

    text = re.sub(r'(^|.?)((?<!今)[從从従徔𫢴])', cong_replacer, text)

    # 规则4: “，依”
    def yi_replacer(match):
        prefix = match.group(1)
        if prefix == '':
            return '依'
        return f'{prefix}，依'

    text = re.sub(r'(^|.?)依', yi_replacer, text)

    # 规则6: “，宋南藏作Y”“，南宋藏作Y”“，X藏作Y。”
    def zang_replacer(match):
        full_match = match.group(0)
        prefix = match.group(1)
        content = match.group(2)
        if prefix == '':
            return f'{content}。'

        if '宋南藏' in full_match or '南宋藏' in full_match:
            return f'，{prefix}{content}。'

        return f'{prefix}，{content}。'

    text = re.sub(r'(^|.?)(([^，。,．、\s]藏作[^，。,\s]))[，,。.]?', zang_replacer, text)

    # 规则8: “，X。”
    def yidang_replacer(match):
        prefix = match.group(1)
        content = match.group(2)
        if prefix == '':
            return f'疑當作{content}。'
        return f'{prefix}，疑當作{content}。'

    text = re.sub(r'(^|.?)疑當作(.+?)[，,。.]?', yidang_replacer, text)

    return text


def emendation_format_deal(char_type_info):
    """
    规则来源：https://rushi-ai.feishu.cn/docx/KJZzd7aAZo5T2fxNMPVcC5xCnMc
    校讹规则1、2、3、9、10
    """
    if not char_type_info:
        return ''

    format_bd_txt = ''
    for i in range(len(char_type_info)):
        format_bd_txt += char_type_info[i]['char']

        # 如果当前是 N，下一位是 L
        if char_type_info[i]['type'] == 'N':
            if i + 1 < len(char_type_info) and char_type_info[i + 1]['type'] != 'N':
                # 规则2: 小字句尾加句号
                # 规则3: 每个“大字：小字”单独成段
                format_bd_txt += '。）\n'  # 音释一行的末尾
            elif i + 1 == len(char_type_info):  # 整个音释的末尾
                format_bd_txt += '。）'

        # 如果当前是 L，下一位是 N
        if char_type_info[i]['type'] == 'L':
            if i + 1 < len(char_type_info) and char_type_info[i + 1]['type'] == 'N':
                # 规则1: 小字加括号
                format_bd_txt += '（'

    return format_bd_txt


def insert_linebreak(text, n):
    """
    在排除标点后的第 n 个字符后插入换行符\n
    """
    count = 0
    result = []
    inserted = False  # 标志位，控制只插入一次

    for ch in text:
        result.append(ch)
        if not inserted and count == n:
            result.append('\n')
            inserted = True
        if ch not in '，。！？；：「」『』、《》〈〉（）【】——…·':
            count += 1
    return ''.join(result)


def get_rule_bd(reel, format_type):
    """
    获取一卷内音释或校讹标点文本字典
    format_type: 'E'、'C'分别代表音释、校讹
    返回格式：
    {
        'JS_1_23_19': [{'txt': 'xxx'}],
        'JS_1_24_4': [{'txt': 'xxx'}]
    }
    """
    reel_column_list = get_reel_column_list(reel)
    for col in reel_column_list:
        if col['col_format'] == format_type:
            char_cids, char_format, col_txt = col['char_cids'], col['char_format'], col['col_txt']
            col['char_type_info'] = get_char_type_info(char_cids, char_format, col_txt)

    # merged_yinshi_list中的元素，包含char_type_info字段，用于标记每个字的格式以及字后跟随的标点
    merged_yinshi_list = get_merged_yinshi_list(reel_column_list, include_center=False, format_type=format_type)

    for merged_yinshi in merged_yinshi_list:
        char_type_info = merged_yinshi['char_type_info']
        col_txts = merged_yinshi['col_txts']  # 未标点的音释字符串

        # # 古籍酷ai标点
        # # 在N和L之间插入\n
        # new_txt = insert_newlines(char_type_info)
        # ai_bd_txt = call_gj_ai_punc_v1(new_txt)
        # for i, char in enumerate(ai_bd_txt):
        #     if char in PUNC_STR:
        #         front_bd_txt = ai_bd_txt[:i]
        #         _no_punc_txt = re.sub(r'[\s%s]' % PUNC_STR, '', front_bd_txt)
        #         index = len(_no_punc_txt) - 1
        #         char_type_info[index]['bd_logs']['ai'] = char
        # print(merged_yinshi['page_name'])
        if format_type == 'E':
            # 规则标点1,2,3,4,5,6
            re_bd_txt = yinshi_re_deal(col_txts)
        elif format_type == 'C':
            re_bd_txt = emendation_re_deal(col_txts)

        for i, char in enumerate(re_bd_txt):
            if char in PUNC_STR:
                front_bd_txt = re_bd_txt[:i]
                _no_punc_txt = re.sub(r'[\s%s]' % PUNC_STR, '', front_bd_txt)
                index = len(_no_punc_txt) - 1
                char_type_info[index]['bd_logs']['re_rule'] = char

        if format_type == 'E':
            # 规则7,8,9,10
            format_bd_txt = yinshi_format_deal(char_type_info)
        elif format_type == 'C':
            format_bd_txt = emendation_format_deal(char_type_info)

        for i, char in enumerate(format_bd_txt):
            if char in (PUNC_STR + '\n'):
                front_bd_txt = format_bd_txt[:i]
                _no_punc_txt = re.sub(r'[\s%s]' % (PUNC_STR + '\n'), '', front_bd_txt)
                index = len(_no_punc_txt) - 1
                if char in ['\n', '）']:  # '。）\n' 此时迁移标点需叠加
                    if char_type_info[index]['bd_logs'].get('format_rule'):
                        char_type_info[index]['bd_logs']['format_rule'] += char
                else:
                    char_type_info[index]['bd_logs']['format_rule'] = char

    # 合并各规则标点 优先级：格式标点>re标点>ai标点
    reel_yinshi_dict = {}
    for yinshi in merged_yinshi_list:
        yinshi_bd_txt = ''
        for char_info in yinshi['char_type_info']:
            yinshi_bd_txt += char_info['char']
            bd_logs = char_info['bd_logs']
            if bd_logs.get('format_rule'):
                yinshi_bd_txt += bd_logs.get('format_rule')
                continue
            elif bd_logs.get('re_rule'):
                yinshi_bd_txt += bd_logs.get('re_rule')
                continue
            # elif bd_logs.get('ai'):
            #     yinshi_bd_txt += bd_logs.get('ai')

        # 由于标点合并，不在emendation_re_deal处理，在这边处理比较简单
        if format_type == 'C':
            # 规则7: 行后的第一个字加引号、作后的第一个字加引号
            yinshi_bd_txt = re.sub(r'(行)([，。（）]?)([^\s，。,．、])', r'\1\2“\3”', yinshi_bd_txt)
            yinshi_bd_txt = re.sub(r'(作)([，。（）]?)([^\s，。,．、])', r'\1\2“\3”', yinshi_bd_txt)

        # 字格式标题后面加\n 例如：“音释”+音释内容 在同一行
        for char_fmt in yinshi['char_format']:
            if char_fmt[0] in CHAR_FMT_TITLE:
                insert_idx = char_fmt[2] - yinshi['col_start_cid']
                yinshi_bd_txt = insert_linebreak(yinshi_bd_txt, insert_idx)

        col_cid = yinshi['page_name'] + '_' + str(yinshi['col_cid'])
        reel_yinshi_dict[col_cid] = [{'txt': yinshi_bd_txt}]

    return reel_yinshi_dict


if __name__ == '__main__':
    tw_client = hlp.connect_db_max('tw-product', 'mongodb-', True)
    # 选择数据库
    tw_db = tw_client['tripitaka-product']
    # tw_db = tw_client["tripitaka-dev"]
    # 查询径山藏的卷
    cond = {'sutra_code': {'$regex': 'JS_'}}
    # cond = {"reel_code" : {"$in": ["JS_445_2", "JS_445_3"]}}
    # reels = list(tw_db.reel.find(cond, {'reel_code': 1}))

    reel = tw_db.reel.find_one({'reel_code': 'JS_1669_89'})
    # reel = tw_db.reel.find_one({'reel_code': 'JS_1092_7'})
    # reel = tw_db.reel.find_one({"reel_code": "JS_141_3"})
    # reel = tw_db.reel.find_one({'reel_code': 'JS_1_13'})  # 测试音释+音释内容
    # print(get_reel_yinshi_bd(reel))

    # print(get_rule_bd(reel, "E"))
    print(get_rule_bd(reel, 'C'))

    # text = '控苦貢切制也\n蠢蠢尺允切擾動也\n拯音字林整尔雅救也\n蓬蒲蒙蒲梦二切\n紛糾糾舉有切紛糾繚戾也玄奘奘在黨切玄奘法師名訛謬訛吾禾切舛也謬靡幼切誤也翹𬡅堯切舉也賾士革切深也泫胡犬切露光也軌躅軌古委切車轍也躅直六切跡也綜綜作弄切括古活切謂綜制包括也黔黎黔其廉切黎鄰溪切皆黑也謂黑𩠐之眾𢉙也齠齔齠田聊切齔初覲切始毀齒也足岳足將豫切益也謂以輕塵益山岳之高也'
    # print(yinshi_re_deal(text))

    # char_type_info = [{'char': '控', 'type': 'L', 'bd_logs': {}}, {'char': '苦', 'type': 'N', 'bd_logs': {}}, {'char': '貢', 'type': 'N', 'bd_logs': {}}, {'char': '切', 'type': 'N', 'bd_logs': {}}, {'char': '制', 'type': 'N', 'bd_logs': {}}, {'char': '也', 'type': 'N', 'bd_logs': {}}, {'char': '蠢', 'type': 'L', 'bd_logs': {}}, {'char': '蠢', 'type': 'L', 'bd_logs': {}}, {'char': '尺', 'type': 'N', 'bd_logs': {}}, {'char': '允', 'type': 'N', 'bd_logs': {}}, {'char': '切', 'type': 'N', 'bd_logs': {}}, {'char': '擾', 'type': 'N', 'bd_logs': {}}, {'char': '動', 'type': 'N', 'bd_logs': {}}, {'char': '也', 'type': 'N', 'bd_logs': {}}, {'char': '拯', 'type': 'L', 'bd_logs': {}}, {'char': '音', 'type': 'N', 'bd_logs': {}}, {'char': '整', 'type': 'N', 'bd_logs': {}}, {'char': '救', 'type': 'N', 'bd_logs': {}}, {'char': '也', 'type': 'N', 'bd_logs': {}}, {'char': '紛', 'type': 'L', 'bd_logs': {}}, {'char': '糾', 'type': 'L', 'bd_logs': {}}, {'char': '糾', 'type': 'N', 'bd_logs': {}}, {'char': '舉', 'type': 'N', 'bd_logs': {}}, {'char': '有', 'type': 'N', 'bd_logs': {}}, {'char': '切', 'type': 'N', 'bd_logs': {}}, {'char': '紛', 'type': 'N', 'bd_logs': {}}, {'char': '糾', 'type': 'N', 'bd_logs': {}}, {'char': '繚', 'type': 'N', 'bd_logs': {}}, {'char': '戾', 'type': 'N', 'bd_logs': {}}, {'char': '也', 'type': 'N', 'bd_logs': {}}]
    # print(yinshi_format_deal(char_type_info))

    # text = '依行今從一藏作二从依三疑當作大今从從行'
    # print(emendation_re_deal(text))
