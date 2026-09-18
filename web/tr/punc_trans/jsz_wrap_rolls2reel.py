import os
import re
import sys

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(root_dir)

import helper as hp

hp.set_logging('jsz_wrap_rolls2reel', False)


def jsz_wrap_rolls2reel():
    "TECH 001 User Story2：对齐文本和匹配信息导出和同步校对平台"
    db_work = hp.get_db('tw-work')
    db_dev = hp.get_db('rushi-dev')
    # 1 获取全部的卷号
    reel_codes = db_dev.jsz_wrap_rolls.distinct('卷号')
    # 2 通过卷号遍历查询
    for i, reel_code in enumerate(reel_codes):
        fresh_doc = db_dev.jsz_wrap_rolls.find_one({'卷号': reel_code})
        # 3 优先级最高的同步4个字段
        match_ratio1, bd_source1, cmp_txt1 = get_content(fresh_doc)
        cmp_txt1 = filter_cmp_txt(cmp_txt1)

        # 4 匹配信息
        # 循环类型，只要有内容就update下 reel.bd_source_match_info
        bd_source_match_info = {}
        source_match_info = fresh_doc.get('source_match_info')
        if source_match_info:
            for source, match_infos in source_match_info.items():
                bd_source_match_info[source] = {}
                for field in ['all_reel', '3_reel', '1_reel']:
                    if match_infos.get(field):
                        match_ratio = match_infos[field]['match_info2']['match_rate']
                        cmp_text2 = match_infos[field]['cmp_text2']
                        bd_source_match_info[source]['match_ratio'] = match_ratio
                        cmp_text2 = filter_cmp_txt(cmp_text2)
                        bd_source_match_info[source]['cmp_txt'] = cmp_text2
                        break

        if bd_source1 == 'HLAI':
            bd_source_match_info['HLAI'] = {}
            bd_source_match_info['HLAI']['cmp_txt'] = cmp_txt1
            bd_source_match_info['HLAI']['match_ratio'] = match_ratio1

        # 5 更新生产平台reel
        update = {'match_ratio': match_ratio1, 'bd_source': bd_source1, 'bd_txt': cmp_txt1,
                  'bd_source_match_info': bd_source_match_info, 'flag': 617}

        r = db_work.reel.update_one({'reel_code': reel_code}, {'$set': update, '$unset': {'cmp_txt': 1}})



def filter_cmp_txt(cmp_txt):
    """
    预处理 cmp_txt，去除或替换干扰字符（如带圈数字 ③、④ 等）

    Args:
        cmp_txt (str): 待处理的文本

    Returns:
        str: 处理后的干净文本
    """
    if not isinstance(cmp_txt, str):
        return cmp_txt  # 如果不是字符串，直接返回（或可以抛异常）

    # 1. 去除带圈数字（如 ①、②、③...）
    cmp_txt = remove_circled_numbers(cmp_txt)

    # 2. 去除其他可能的干扰符号（如 [p59] 这样的标记）
    cmp_txt = re.sub(r'\[p\d+\]', '', cmp_txt)  # 移除 [p59] 之类的页码

    # 3. 替换¶为换行符
    cmp_txt = cmp_txt.replace('¶', '\n')

    return cmp_txt


def remove_circled_numbers(text):
    """移除文本中的带圈数字（Unicode 范围）"""
    # 匹配 ①-⑳ (U+2460-U+2473) 和 ㉑-㉟ (U+3251-U+325F)
    circled_numbers_pattern = re.compile(
        r"[\u2460-\u2473\u3251-\u325F]"
    )
    return circled_numbers_pattern.sub("", text)


def get_content(fresh_doc):
    # 优先级最高的多同步4个字段
    # match_radio= > reel.match_ratio
    # source= > reel.bd_source
    # content => reel.bd_txt
    # cmp_txt => reel.cmp_txt

    rushi_content = fresh_doc.get("标点内容", "") if fresh_doc else ""
    huali_content = fresh_doc.get("华鲤打标内容", "") if fresh_doc else ""
    wl_punc_content = fresh_doc.get("wl_punc_content", "") if fresh_doc else ""
    xz_punc_content = fresh_doc.get("xz_punc_content", "") if fresh_doc else ""
    fgz_punc_content = fresh_doc.get("fgz_punc_content", "") if fresh_doc else ""
    cbeta_punc_content = fresh_doc.get("cbeta_punc_content", "") if fresh_doc else ""

    content_type = "rushi"
    content = rushi_content

    if len(xz_punc_content) > 2:
        content_type = "xz"
        content = xz_punc_content
    elif len(wl_punc_content) > 2:
        content_type = "wl"
        content = wl_punc_content
    elif len(fgz_punc_content) > 2:
        content_type = "fgz"
        content = fgz_punc_content
    elif len(cbeta_punc_content) > 2:
        content_type = "cbeta"
        content = cbeta_punc_content
    # 华鲤AI打标做最后的兜底
    elif len(huali_content) > 2:
        content_type = "HLAI"
        content = huali_content

    source = content_type
    bd_source = source.upper()  # 转换为大写
    bd_txt = content
    source_match_info = fresh_doc.get('source_match_info', {})
    if not source_match_info:
        source_match_info = {}

    cmp_txt, match_ratio = get_cmp_txt(source_match_info, bd_source)  # 从source_match_info获取cmp_txt、match_rate
    if bd_source == 'HLAI':
        match_ratio = 1
        cmp_txt = bd_txt
    return match_ratio, bd_source, cmp_txt


def get_cmp_txt(source_match_info, bd_source):
    # 从source_match_info获取cmp_txt、match_rate
    # 确定好类型后，从source_match_info中找对应的匹配率，比如类型是 source = FGZ
    match_info = source_match_info.get(bd_source, {})
    # 优先级是  all_reel 、 3_reel 、 1_reel (从前到后判断，有key就结束)
    # 假设有all_reel,
    # 取 source_match_info.FGZ.all_reel.cmp_text2 => reel.bd_source_match_info.FGZ.cmp_txt
    # 取 source_match_info.FGZ.all_reel.match_info2.match_rate => reel.bd_source_match_info.FGZ.match_ratio
    # 如果没有all_reel，则判断3_reel,如果没有则1_reel
    # 注意：HLAI的匹配率是 1
    match_ratio = 0
    cmp_txt = None
    for field in ['all_reel', '3_reel', '1_reel']:
        if match_info.get(field):
            match_ratio = match_info[field]['match_info2']['match_rate']
            cmp_txt = match_info[field]['cmp_text2']
            break
    return cmp_txt, match_ratio


def hlai2reel_bd():
    """
    Story6: 华鲤AI数据导入reel_bd
    """
    db_work = hp.get_db('tw-work')
    db_dev = hp.get_db('rushi-dev')
    # 1 获取全部的卷号
    reel_codes = db_dev.jsz_wrap_rolls.distinct('卷号')
    # 2 通过卷号遍历查询
    for reel_code in reel_codes:
        fresh_doc = db_dev.jsz_wrap_rolls.find_one({'卷号': reel_code})
        #  3筛选出 len(jsz_wrap_rolls.华鲤打标内容) > 2的部分：
        huali_content = fresh_doc.get("华鲤打标内容", "") if fresh_doc else ""
        if len(huali_content) > 2:
            bd_source = "HLAI"
            txt = huali_content
        else:
            continue
        # 4 HLAI的 经号和卷号 跟 径山藏的 经号卷号命名规则一致
        reel_no = fresh_doc['序号']
        sutra_uid = fresh_doc['经号'].replace('JS', 'HLAI')
        reel_uid = fresh_doc['卷号'].replace('JS', 'HLAI')
        # 5 reel_bd插入HLAI的数据
        reel_bd = {'rs_sutra_uid': None, 'sutra_uid': sutra_uid, 'reel_uid': reel_uid, 'reel_no': reel_no, 'txt': txt,
                   'source': bd_source}
        db_work.reel_bd.insert_one(reel_bd)


def hlai2sutra_source():
    """按照JSZ的数据，给HLAI来一份"""
    db_work = hp.get_db('tw-work')
    sutra_sources = list(db_work.sutra_source.find({'source_type': 'JSZ'}, {'_id': 0}))
    for sutra_sourc in sutra_sources:
        if isinstance(sutra_sourc['sutra_uid'], list):
            sutra_uid = [s.replace('JS', 'HLAI') for s in sutra_sourc['sutra_uid']]
        else:
            sutra_uid = sutra_sourc['sutra_uid'].replace('JS', 'HLAI')
        sutra_sourc['sutra_uid'] = sutra_uid
        sutra_sourc['source_type'] = 'HLAI'
        db_work.sutra_source.insert_one(sutra_sourc)


def process():
    jsz_wrap_rolls2reel()  # 对齐文本和匹配信息导出和同步校对平台
    hlai2reel_bd()  # Story6: 华鲤AI数据导入reel_bd
    hlai2sutra_source()  # Story6: 华鲤AI数据导入sutra_sources
    pass


def main(func='process', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
