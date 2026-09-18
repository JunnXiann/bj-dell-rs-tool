import os
from datetime import datetime,timezone
import logging
import sys
from datetime import datetime,timezone, timedelta
import re
import pymongo
import os


root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)

from util.punc import transfer_punc_for_stats
from util.punc_lib.best_match_two_txt import BestMatchTwoTxt
import helper as hp

cur_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
hp.set_logging('find_best_match_text-'+str(cur_time),False)


IS_BASE_TEXT = lambda x:x not in '\n[]JS_0123456789'

PARAGRAGH_NUM = 50 # 段落判断阈值

best_matcher = BestMatchTwoTxt()


# 校对平台正式环境
check_online_read_client = hp.connect_db_max('check-read-online','mongodb-',True)
check_online_read_db = check_online_read_client["tripitaka-product"]
reel_bd_collection = check_online_read_db["reel_bd"]
sutra_sources_collection = check_online_read_db["sutra_source"]


# 预处理 source 的文本
def process_source_text(text: str) -> str:
    """
    1. 过滤所有注释行（以#开头，含全角#）
    2. 删除所有空行（包括处理后的空字符串）
    3. 删除所有空格（半角/全角/行首尾）
    4. TODO 替代带圈字
    5. TODO 去掉干扰[p23]类型标题
    6. 非空行用¶连接，无空行分隔
    """

    # 1. 按行分割，过滤注释行（支持全角#）
    lines = [
        line for line in text.split('\n')
        if not line.lstrip('\r').startswith('#')  # 兼容 Windows 换行，忽略注释
    ]

    # 2. 处理每一行：删除所有空格，过滤空行
    processed = []
    for line in lines:
        # 去除所有空格（半角\u0020、全角\u3000）+ 首尾换行符
        stripped = re.sub(r'[\u0020\u3000\r]', '', line.strip('\n'))
        if stripped:  # 仅保留非空行
            # 去掉一些字符
            stripped = stripped.replace('【', '').replace('】', '').replace('◎', '')
            processed.append(stripped)

    # 3. 用¶连接所有非空行
    return '¶'.join(processed)


def merge_contents(contents):
    """
    将(卷号, 内容)列表拼接成大文本
    :param contents: (卷号, 内容)列表
    :return: 拼接后的大文本
    """
    return "".join([content + "\n" for _, content, _ in contents])

def get_source_reel_uids_by_sutra_uid(sutra_uid):
    results = reel_bd_collection.find({"sutra_uid":sutra_uid}).sort("reel_no")
 
    reel_uids = [result["reel_uid"] for result in results]
    return reel_uids


def get_source_contents_by_juanhaos(juanhaos):
    results = reel_bd_collection.find({"reel_uid":{"$in":juanhaos}}).sort("reel_no")
 
    source_contents = [(result["reel_uid"], result["txt"], result["reel_no"]) for result in results]
    return source_contents


def get_source_reel_big_text(source, sutra_uid, reel_nos):
    """
    获取数据源的经卷内容大文本
    :param collection: MongoDB 集合对象
    :param sutra_uid: 源经号
    :param: reel_nos: 页码
    :return: 排序后的列表
    """

    logging.info(f"get_source_reel_big_text start > source:{source}, sutra_uid:{sutra_uid}, reel_nos:{reel_nos}")

    # 构建查询条件（强制reel_no为数字类型，非数字的可能是序和跋）
    query = {
        "sutra_uid": sutra_uid,
        "source": source,
        "reel_no": {"$type": "number"} 
    }
    if reel_nos:  # 仅当数组非空时添加reel_no条件
        query["reel_no"] = {"$in": reel_nos}

    # 查询并按reel_no升序排列
    cursor = reel_bd_collection.find(
        query,
        projection={"source": 1, "txt": 1, "sutra_uid": 1, "reel_uid": 1, "_id": 0}
    ).sort("reel_no", pymongo.ASCENDING) 
    cursor = list(cursor)

    logging.info(f"get_source_reel_big_text end > source:{source}, sutra_uid:{sutra_uid}, reel_nos:{reel_nos},len:{len(cursor)}")

    return '\n'.join([item['txt'] for item in cursor]) if cursor else ''


def get_rs_sutra_uid(sutra_uid,source):
    """
    获取经号对应的rs_sutra_uid，兼容 sutra_uid 为字符串或数组的情况
    """
    query = {
        "source_type": source,
        "$or": [
            {"sutra_uid": sutra_uid},             # 字符串匹配
            {"sutra_uid": {"$in": [sutra_uid]}}   # 数组包含
        ]
    }

    result = sutra_sources_collection.find_one(query, {"rushi_sutra_uid": 1, "_id": 0})
    logging.info(f"get_rs_sutra_uid: {sutra_uid} {source}, result: {result}")
    return result.get("rushi_sutra_uid") if result else None

def get_source_sutra_uid(rushi_sutra_uid,source):
    """
    获取源经号 sutra_uid
    :param rushi_sutra_uid: 如是经号
    :param source: 来源
    :return: sutra_uid
    """
    result = sutra_sources_collection.find_one({"rushi_sutra_uid": rushi_sutra_uid,"source_type": source}, {"sutra_uid": 1,"assist_sutra_uid": 1, "_id": 0})
    logging.info(f"get_source_sutra_uid: {rushi_sutra_uid} {source}, result: {result}")
    sutra_uid = result.get("sutra_uid") if result else None
    assist_sutra_uid = result.get("assist_sutra_uid") if result else None
    logging.info(f"sutra_uid: {sutra_uid} assist_sutra_uid: {assist_sutra_uid}")

    return sutra_uid, assist_sutra_uid



def cal_diff_rate(input_text,big_cmp_text,jsz_jinghao,sort_no):
    logging.info(f"cal_diff_rate start: {jsz_jinghao} {sort_no}")
    # 文本对齐匹配率
    text1_no_punc, matched_paragraph_no_punc, matched_paragraph, align_match_rate = best_matcher.find_best_match(input_text, big_cmp_text)
    logging.info(f"find_best_match end,transfer_punc_for_stats start : {jsz_jinghao} {sort_no}")

    _,segments = transfer_punc_for_stats(input_text, matched_paragraph,IS_BASE_TEXT)
    # logging.info(f'transfer_punc_for_stats,segments_end')
    logging.info(f"transfer_punc_for_stats end : {jsz_jinghao} {sort_no}")

    # 过滤出 len_diff 不为 0 的数据
    diff_segments = [segment for segment in segments if (segment["len_diff"] != 0 and segment['is_same'] == False)]
    # 分母数量
    denominator = sum(len(segment["base"]) for segment in segments)
    # logging.info(f'jsz_jtransfer_punc_for_stats_end:{jsz_jinghao},diff_segments_len:{len(diff_segments)}')

    # 计算不匹配的分子总数
    misnumerator = sum(len(segment["base"]) for segment in diff_segments if segment["len_diff"] > 2)
    # 计算不匹配度
    if denominator != 0:
        mismatch_rate = misnumerator / denominator
        # 保留两位小数
        mismatch_rate = round(mismatch_rate, 4)
    else:
        mismatch_rate = 0
    match_rate = round(1 - mismatch_rate,4)

    logging.info(f"jsz_jinghao:{jsz_jinghao},sort_no:{sort_no},不匹配分子:{misnumerator},分母：{denominator},nomal_content_length:{len(input_text)} 不匹配度：{mismatch_rate},匹配度: {match_rate}")
    match_info = {
        "match_rate": match_rate,
        "misnumerator": misnumerator,
        "denominator": denominator,
        "minus_numerator": 0,
        "mismatch_rate": mismatch_rate,
        "jsz_content_lenth": len(input_text),
        "align_match_rate": align_match_rate,
    }
    return match_info,matched_paragraph,segments,diff_segments

def punc_rate_stat_by_segment(input_text,big_cmp_text,jsz_jinghao,sort_no):
    '''
    1. 按照diff算法计算匹配度
    2. 2次搜索召回后，再计算匹配度
    '''
    
    match_info,matched_cmp_text,segments,diff_segments = cal_diff_rate(input_text,big_cmp_text,jsz_jinghao,sort_no)
    # 如果有 len_diff 不为 0 的数据，保存到 Excel 文件
    todo_segments = []
    if diff_segments:

        # 对未匹配到的段落做2次查询，防止源数据段落混乱；剩下没匹配到的非段落的小字符串，暂时不做AI标点，防止打混乱，这部分人工处理
        todo_segments = [segment for segment in diff_segments if segment["len_diff"] >= PARAGRAGH_NUM]
        if todo_segments:
            for todo_segment in todo_segments:
                base_content = todo_segment["base"]
                logging.info(f"对齐算法2次搜索开始，sort_no:{sort_no}")
                # 二次查找，从经级别找
                text1_no_punc, matched_paragraph_no_punc, matched_paragraph, match_rate = best_matcher.find_best_match(base_content, big_cmp_text)
                logging.info(f'对齐算法2次搜索segment_content_match_info,sort_no:{sort_no},match_rate:{match_rate},\n,base_content:{base_content}，\n matched_paragraph:{matched_paragraph}')
                if match_rate > 0.7:

                    todo_segment['base1'],_ = transfer_punc_for_stats(base_content, matched_paragraph,IS_BASE_TEXT)
                    todo_segment['cmp'] = matched_paragraph_no_punc
                    todo_segment['cmp0'] = matched_paragraph
                else:
                    logging.info(f"对齐算法2次搜索，sort_no:{sort_no}，match_rate:{match_rate}，2次没有匹配到，不做打标")
  
    else:
        logging.info("sort_no：{sort_no},没有 len_diff 不为 0 的数据。")

    # 这里需要把 todo_segments 更新后的base1，赋值给 segments 里对应项的 base1，然后拼接segments的base1作为最后的标点大文本
    for todo_segment in todo_segments:
        # 查找 segments 中 no 相同的项
        for segment in segments:
            if segment["no"] == todo_segment["no"]:
                # 将 todo_segments 里的 base1 赋值给 segments 里对应项的 base1
                # logging.info(f'jsz_juanhao:{jsz_juanhao},origin_segment:{segment},update_todo_segment:{todo_segment}')
                segment['base1'] = todo_segment['base1']
                segment['cmp'] = todo_segment['cmp']
                segment['cmp0'] = todo_segment['cmp0']
                break

    # 计算2次查找的匹配率
    cmp_text2 = "".join([segment["cmp0"] for segment in segments])
    match_info2,matched_cmp_text2,segments2,diff_segments2 = cal_diff_rate(input_text,cmp_text2,jsz_jinghao,sort_no)

    # 拼接segments的base1作为最后的标点大文本
    origin_new_content = "".join([segment["base1"] for segment in segments2])

    # 释放内存
    del segments
    del todo_segments
    del diff_segments
    del segments2
    del diff_segments2

    return origin_new_content,match_info,match_info2,cmp_text2


def get_source_sorted_contents(source, source_jinghao, reel_nos, one_2_multy_params):
    """
    根据经号从指定集合中获取按卷号排序的(卷号, 内容)列表
    :param jinghao: 经号
    :return: 排序后的(卷号, 内容)列表
    """
    # 判断是否为数组
    if isinstance(source_jinghao, list):
        logging.info(f"source_jinghao is list,source_jinghao:{source_jinghao}")
        source_jinghao = ','.join(source_jinghao)
    # 单个字符串，转成数组
    if one_2_multy_params and len(one_2_multy_params) > 1 and isinstance(one_2_multy_params, str):
        one_2_multy_params = [one_2_multy_params]

    logging.info(f"get_source_sorted_contents start,source:{source},source_jinghao:{source_jinghao},one_2_multy_params:{one_2_multy_params},reel_nos:{reel_nos}")

    source_big_txt = ''
    if one_2_multy_params == None or one_2_multy_params == '' or len(one_2_multy_params) == 0:
        source_big_txt = get_source_reel_big_text(source, source_jinghao, reel_nos)
    else:
        source_contents = []
        # 1对多
        # {"X0273_010,X0273_001-009,X0275_001,X0274,X0275_001-010"}
        # 按序拼接所有的
        for part in one_2_multy_params:
            logging.info(f"part:{part},source:{source},source_jinghao:{source_jinghao}")
            # 异常数据处理
            if part == '-':
                continue
            source_juanhaos = []
            part = part.strip()
            if '-' in part:
                # 处理连续范围X0273_001-009,T1435_060-061
                prefix, range_part = part.split('_')
                start_end = range_part.split('-')
                if len(start_end) == 2:
                    start = int(start_end[0])
                    end = int(start_end[1])
                    for num in range(start, end+1):
                        source_juanhaos.append(f"{prefix}_{num:03d}")
            else:
                # 处理单个标识（经号或卷号）
                if '_' in part:  # 卷号（如 X0273_010）
                    source_juanhaos.append(part)
                else:  # 经号（如 X0274）
                    # 获取该经号下的所有卷号并按序号排序
                    jing_juanhaos = get_source_reel_uids_by_sutra_uid(part)
                    source_juanhaos.extend(jing_juanhaos)
            
            logging.info(f'part:{part},source_juanhaos:{source_juanhaos}')
            # 每个循环都要请求，不然顺序会不一致
            source_content = get_source_contents_by_juanhaos(source_juanhaos)
            if source_content:
                source_contents.extend(source_content)
    
        # logging.info(f'source_contents:{source_contents}')
        # 将 source 这边的内容按照卷号排序拼接起来成 1 个大的内容
        source_big_txt = merge_contents(source_contents)

    # 预处理source文本，去掉换行符，空格等
    source_big_pre_deal_txt = process_source_text(source_big_txt)

    logging.info(f"source_big_pre_deal_txt 处理完成,source_jinghao:{source_jinghao}")

    return source_big_pre_deal_txt


def get_match_info(jinghao, sort_no,origin_text,source_text=""):
    """
    计算两个文本的匹配信息
    """
    logging.info(f'get_match_info start,jinghao:{jinghao},sort_no:{sort_no}')

    # diff算法匹配率
    return punc_rate_stat_by_segment(origin_text,source_text,jinghao,sort_no)


'''
最佳匹配文本查找逻辑：
原文经号跟来源经号做匹配
1. 一对一
1)按1卷、3卷、全经的逻辑依次去算匹配率，满足了就返回

2：一对多
1）按顺序拼接好经文后，计算匹配率

'''
def find_best_match_text(source,jinghao,sort_no,origin_text):
    logging.info(f"find_best_match_text start，source：{source}, jinghao:{jinghao},'sort_no:{sort_no},origin_text:{origin_text}")
    rs_sutra_uid = get_rs_sutra_uid(jinghao,'JSZ')

    MATCH_RATE_LIMIT = 0.98  # 匹配率阈值，超过则不再搜索
    result = {'code':0, 'msg':'','result':{'source': source, 'match_ratio': 0, 'cmp_text':''}}
    if not source or not jinghao or not sort_no or not origin_text:
        result['code'] = 401
        result['msg'] = 'param error'
        return result

    while(True):

        one_2_multy_params = None

        source_sutra_uid,assist_sutra_uid = get_source_sutra_uid(rs_sutra_uid, source)
        logging.info(f"find_best_match_text rs_sutra_uid:{rs_sutra_uid},source_sutra_uid：{source_sutra_uid},assist_sutra_uid:{assist_sutra_uid},jinghao:{jinghao}")

        if source_sutra_uid == None:
            logging.info(f"find_best_match_text source:{source} ,rs_sutra_uid:{rs_sutra_uid},source_sutra_uid not found,return")
            result['code'] = 404
            result['msg'] = 'source_sutra_uid not found'
            break

        # 辅助经号有就是1对多    
        if assist_sutra_uid and len(assist_sutra_uid) > 0:
            one_2_multy_params = assist_sutra_uid

        # 处理一对多情况
        if one_2_multy_params:
            logging.info(f'db_find_multy,source:{source},jinghao:{jinghao},one_2_multy_params:{one_2_multy_params}')
            source_text = get_source_sorted_contents(source, source_sutra_uid, [], one_2_multy_params)
            if len(source_text) == 0:
                logging.info(f'source:{source},jinghao:{jinghao},source_sutra_uid:{source_sutra_uid}，one_2_multy_params:{one_2_multy_params}，source_text为空，不做处理')
                result['code'] = 404
                result['msg'] = 'source_text not found'
                break

            origin_new_content, match_info, match_info2, cmp_text2 = get_match_info(source_sutra_uid, sort_no, origin_text,source_text )
        else:
            reel_configs = [
                ('1_reel', [sort_no]),
                ('3_reel', [sort_no-1, sort_no, sort_no+1]),
                ('all_reel', [])
            ]

            logging.info(f'source:{source},reel_configs:{reel_configs}')

            # 遍历卷配置生成匹配项
            for reel_type, reel_nos in reel_configs:
                logging.info(f"reel_configs,source:{source},reel_type:{reel_type},reel_nos:{reel_nos},one_2_multy_params:{one_2_multy_params}")
                
                source_text = get_source_sorted_contents(source, source_sutra_uid, reel_nos, one_2_multy_params)
                if len(source_text) == 0:
                    logging.info(f'source:{source},jinghao:{jinghao},source_sutra_uid:{source_sutra_uid}，source_text为空，不做处理')
                    continue

                origin_new_content, match_info, match_info2, cmp_text2 = get_match_info(source_sutra_uid, sort_no, origin_text,source_text )
                result['result']['match_ratio'] = match_info2['match_rate']
                result['result']['cmp_text'] = cmp_text2
                # 如果匹配率达标，则终止
                if match_info2['match_rate'] >= MATCH_RATE_LIMIT:
                    tmp = match_info2['match_rate']
                    logging.info(f'source_sutra_uid:{source_sutra_uid},reel_type:{reel_type},current_match_rate:{tmp} >= MATCH_RATE_LIMIT:{MATCH_RATE_LIMIT}，终止匹配')
                    break
        break

    logging.info(f"find_best_match_text jinghao:{jinghao},sort_no:{sort_no}")

    return result


if __name__ == "__main__":
    logging.info('\n\n main start')
    source = 'CBETA'  # 来源
    sutra_uid = 'JS_2024'
    sort_no = 3

    sutra_uid = 'JS_1118'  # 经号
    sort_no = 8  # 卷号
    
    origin_text = best_matcher.read_text_file(f'web/tr/punc_trans/test_datas/{sutra_uid}_{sort_no}.txt')

    logging.info(f'source:{source},sutra_uid:{sutra_uid},sort_no:{sort_no},\n origin_text:\n{origin_text}')
    result = find_best_match_text(source,sutra_uid,sort_no,origin_text)
    logging.info(f'result:{result}')
    logging.info('main end \n\n')