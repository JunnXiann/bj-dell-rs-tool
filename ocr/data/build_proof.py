import sys
import math
import os.path as osp
from datetime import datetime

sys.path.append(osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__)))))

from ocr.data import config
from ocr.data import util
import helper as hp

db_lab = hp.get_db('tw-lab')
db_work = hp.get_db('tw-work')


def insert_dataset_chars_to_lab(version='0605'):
    """ 将dataset的标注数据插入到lab的char3、char4表"""
    tks = db_lab.tk_data.distinct('tk', {'active': True})
    for i, tk in enumerate(tks):
        print('[%s/%s]%s' % (i + 1, len(tks), tk))
        tk_data = db_lab.tk_data.find_one({'tk': tk}, {'dataset': 1})
        dataset = tk_data.get('dataset') or {}
        dataset = {f: dataset.get(f) for f in ['km_train_data', 'km_test_data', 'cc_train_data', 'cc_test_data']}
        for data_type, names in dataset.items():
            if 'km' in data_type:
                source = 'JSYZ_KM_%s' % version
                coll = 'char3' if 'train' in data_type else 'char4'
            else:
                source = 'JSYZ_CC_%s' % version
                coll = 'char3' if 'train' in data_type else 'char4'
            colls = list(dataset['sources'].keys())
            chars = util.get_work_chars(colls, names, {'_id': 0, 'tasks': 0, 'box_logs': 0, 'txt_logs': 0})
            for char in chars:
                char['txt'] = tk  # txt使用构建标注时候的值
                char['source'] = source
            db_lab[coll].insert_many(chars)


def get_dataset_char_names():
    """ 获取dataset的标注数据字图name """
    char_names = set()
    tk_datas = db_lab.tk_data.find({'active': True}, {'dataset': 1})
    for i, tk_data in enumerate(tk_datas):
        char_names.update(util.merge_dict_data(tk_data.get('dataset')))
    return list(char_names)


def sync_work_char9_by_dataset(source='JS0705'):
    """ 将dataset的标注数据同步到work的char9表"""
    # 获取lab平台标注数据的name
    print('sync_work_char9_by_dataset')
    names = get_dataset_char_names()
    print('lab平台标注数据%s条' % len(names))
    existed_chars = util.get_work_chars('char9', names, {'name': 1, '_id': 0})
    existed_names = [c['name'] for c in existed_chars]
    print('work平台char9表已存在%s条' % len(existed_names))
    # 插入work平台char9表不存在的name
    names = list(set(names) - set(existed_names))
    print('work平台char9表未存在%s条' % len(names))
    chars = util.get_work_chars(config.get_select_colls(), names, {'_id': 0})
    if not chars:
        return
    for ch in chars:
        ch['source'] = source
    cnt = util.insert_work_chars('char9', chars)
    print('work平台char9表新插入%s条' % cnt)


def update_work_char9_source(source='JS0605'):
    """ 设置work的char9表的source"""
    db_work.char9.update_many({}, {'$set': {'source': '已禁用'}})
    char_names = get_dataset_char_names()
    util.update_work_chars('char9', char_names, 'source', source)


def set_work_char9_forbidden_chars():
    """ 设置work的char9表的已禁用的字图"""
    char_names = get_dataset_char_names()  # 最新标注数据字图名
    chars = db_work.char9.find({}, {'name': 1, '_id': 0})  # char9的所有字图名
    char9_names = [char['name'] for char in chars]
    forbidden_names = list(set(char9_names) - set(char_names))
    db_work.char9.update_many({'name': {'$in': forbidden_names}}, {'$set': {'source': '已禁用'}})


def update_work_char9_params(reset=True):
    """ 设置work的char9表的source"""
    # 初始化
    if reset:
        db_work.char9.update_many({}, {'$set': {'tk': '', 'cc_status': 0, 'km_status': 0}})
    # 更新tk
    fields = ['km_train_data', 'km_test_data', 'cc_train_data', 'cc_test_data']
    field2names = {f: [] for f in fields}
    tk_datas = list(db_lab.tk_data.find({'active': True}, {'dataset': 1, 'tk': 1}))
    for i, tk_data in enumerate(tk_datas):
        print('[%s/%s]%s' % (i + 1, len(tk_datas), tk_data['tk']))
        dataset = tk_data.get('dataset') or {}
        char_names = util.merge_dict_data(dataset)
        db_work.char9.update_many({'name': {'$in': list(char_names)}}, {'$set': {'tk': tk_data['tk']}})
        for f in fields:
            field2names[f].extend(dataset.get(f) or [])
    # 更新kmstatus/cc_status
    if field2names.get('km_train_data'):
        cnt = util.update_work_chars('char9', field2names['km_train_data'], 'km_status', 1)
        print('km_status=1：%s条' % cnt)
    if field2names.get('km_test_data'):
        cnt = util.update_work_chars('char9', field2names['km_test_data'], 'km_status', 2)
        print('km_status=2：%s条' % cnt)
    if field2names.get('cc_train_data'):
        cnt = util.update_work_chars('char9', field2names['cc_train_data'], 'cc_status', 1)
        print('cc_status=1：%s条' % cnt)
    if field2names.get('cc_test_data'):
        cnt = util.update_work_chars('char9', field2names['cc_test_data'], 'cc_status', 2)
        print('cc_status=2：%s条' % cnt)


def get_error_tks(gte=0.1, lt=1.01):
    """" 获取OCR测评结果错误率区间[gte, lt)的字种"""
    # 需根据实际情况修改
    rows = util.load_csv('./meta/[JSYZ_CC_0605]字种统计_原字_20230613_1686620756.csv')
    tks = [r[0] for r in rows[1:] if lt > float(r[2]) >= gte]

    rows = util.load_csv('./meta/[JSYZ_KM_0605]字种统计_原字_20230613_1686620672.csv')
    tks.extend([r[0] for r in rows[1:] if lt > float(r[2]) >= gte])
    return list(set(tks))


def set_high_error_tk_all_chars_source(source='JS0605-1'):
    """ 设置高错误率(错误率大于等于0.1)字种所有字数据的分类"""
    char_names = []
    tks = get_error_tks(0.1, 1.01)  # 错误率0.1≤r<1.01
    tk_datas = list(db_lab.tk_data.find({'tk': {'$in': tks}}, {'dataset': 1}))
    for tk_data in tk_datas:
        char_names.extend(util.merge_dict_data(tk_data.get('dataset') or {}))
    util.update_work_chars('char9', char_names, 'source', source)


def set_other_error_chars_source(
        km_engine='JSYZ_KM_0605',  # km引擎
        cc_engine='JSYZ_CC_0605',  # cc引擎
        source='JS0605-2',  # 数据分类
):
    """ 设置除高错误率外的其它字种对应的所有错误字数据的分类"""
    tks = get_error_tks(0.1, 1.01)  # 错误率0.05≤r<0.1，需排除
    cond = {'source': {'$in': [km_engine, cc_engine]}, 'txt': {'$nin': tks}, '$or': [
        {'ocr_res.%s.equal' % km_engine: False}, {'ocr_res.%s.equal' % cc_engine: False}
    ]}
    char_names = set(db_lab.char3.distinct('name', cond))
    char_names.update(db_lab.char4.distinct('name', cond))
    util.update_work_chars('char9', char_names, 'source', source)


def set_middle_error_tk_right_chars_source(
        km_engine='JSYZ_KM_0605',  # km引擎
        cc_engine='JSYZ_CC_0605',  # cc引擎
        source='JS0605-3',  # 数据分类
):
    """ 设置中错误率(0.05≤r<0.1)字种的正确字数据的分类"""
    tks_high_error = get_error_tks(0.1, 1.01)  # 错误率0.1≤r<1.01
    tks = get_error_tks(0.05, 0.1)  # 错误率0.05≤r<0.1
    tks = list(set(tks) - set(tks_high_error))  # 字种出重
    cond = {'source': {'$in': [km_engine, cc_engine]}, 'txt': {'$in': tks}, '$and': [
        {'ocr_res.%s.equal' % km_engine: True}, {'ocr_res.%s.equal' % cc_engine: True}
    ]}
    char_names = set(db_lab.char3.distinct('name', cond))
    char_names.update(db_lab.char4.distinct('name', cond))
    util.update_work_chars('char9', char_names, 'source', source)


def sync_char_back():
    """ 校对数据同步回源表"""
    size = 10000
    cond = {}  # 需根据实际情况修改
    item_cnt = db_work.char9.count_documents(cond)
    group_cnt = math.ceil(item_cnt / size)
    for i in range(group_cnt):
        fields = ['name', 'txt', 'is_vague', 'uncertain', 'remark', 'txt_updated_time', 'txt_logs', 'src_coll']
        chars = list(db_work.char9.find(cond, {f: 1 for f in fields}).sort('_id', 1).skip(i * size).limit(size))
        for ch in chars:
            ch.pop('_id', 0)
            name = ch.pop('name', 0)
            src_coll = ch.pop('src_coll', 0)
            if not src_coll:
                print('%s: src_coll is null.' % name)
                continue
            db_work[src_coll].update_one({'name': name}, {'$set': ch})


def set_tk_ocr_ratio():
    """ 测评后把测评数据导入dataset"""
    rows_cc = util.load_csv('./meta/[JSYZ_CC_0605]字种统计_原字_20230613_1686620756.csv')  # 根据实际情况修改
    rows_km = util.load_csv('./meta/[JSYZ_KM_0605]字种统计_原字_20230613_1686620672.csv')
    cc_ratio_dict = {r[0]: 1 - float(r[2]) for r in rows_cc[1:]}
    km_ratio_dict = {r[0]: 1 - float(r[2]) for r in rows_km[1:]}
    for tk in km_ratio_dict.keys():
        ocr_ratio = {'km': km_ratio_dict.get(tk), 'cc': cc_ratio_dict.get(tk)}
        db_lab.tk_data.update_one({'tk': tk}, {'$set': {'dataset.ocr_ratio': ocr_ratio}})


def sync_char9_with_src_char():
    """ 校对数据双向同步"""
    size = 10000
    cond = {}  # 需根据实际情况修改
    item_cnt = db_work.char9.count_documents(cond)
    group_cnt = math.ceil(item_cnt / size)
    df_time = datetime.strptime('1970-01-01', '%Y-%m-%d')  # 缺省时间
    fields = ['pos', 'column', 'source', 'name', 'txt', 'is_vague', 'is_deform', 'uncertain', 'remark',
              'txt_updated_time', 'txt_logs', 'src_coll']
    for i in range(group_cnt):
        chars_train = list(db_work.char9.find(cond, {f: 1 for f in fields}).sort('_id', 1).skip(i * size).limit(size))
        # 1 遍历char9表
        for char_train in chars_train:
            name, src_coll = char_train['name'], char_train.get('src_coll')
            char_src = db_work[src_coll].find_one({'name': char_train['name']})
            # 2 如果数据为空，更新source为已删除
            if not char_src:
                if 'deleted' not in char_train['source']:
                    db_work.char9.update_one({'name': name}, {'$set': {'source': '%s_deleted' % char_train['source']}})
                continue

            logs_src, logs_train = char_src.get('txt_logs') or [], char_train.get('txt_logs') or []
            new_logs = util.merge_txt_logs(logs_src, logs_train)  # 合并日志
            if new_logs == logs_src and new_logs == logs_train and \
                    char_src.get('pos') == char_train.get('pos') and char_src.get('column') == char_train.get('column'):
                continue
            update_fields = ['txt', 'is_vague', 'is_deform', 'uncertain', 'remark']
            # 3 获取同步的字段
            update_fields = [k for k in update_fields if char_src.get(k) != char_train.get(k)]
            # 4 同步txt和属性
            for update_field in update_fields:
                last_time_train = util.get_last_log_time(logs_train, update_field) or df_time
                last_time_src = util.get_last_log_time(logs_src, update_field) or df_time
                if last_time_src == last_time_train:
                    if not char_src.get(update_field):
                        char_src[update_field] = char_train[update_field]
                    else:
                        char_train[update_field] = char_src[update_field]
                elif last_time_src > last_time_train:
                    char_train[update_field] = char_src[update_field]
                else:
                    char_src[update_field] = char_train[update_field]
            # 5 同步txt_updated_time
            if char_src.get('txt_updated_time') or char_train.get('txt_updated_time'):
                txt_updated_time_src = char_src.get('txt_updated_time') or df_time
                txt_updated_time_train = char_train.get('txt_updated_time') or df_time
                if txt_updated_time_src > txt_updated_time_train:
                    char_train['txt_updated_time'] = txt_updated_time_src
                elif txt_updated_time_src < txt_updated_time_train:
                    char_src['txt_updated_time'] = txt_updated_time_train
            # 6 字框坐标不一致，以源表的字框数据为准
            if char_src.get('pos') != char_train.get('pos') or char_src.get('column') != char_train.get('column'):
                char_train['pos'] = char_src.get('pos')
                char_train['column'] = char_src.get('column')
            # 7 更新数据
            char_train['txt_logs'] = new_logs
            db_work.char9.update_one({'name': name}, {'$set': char_train})
            char_src['txt_logs'] = new_logs
            db_work[src_coll].update_one({'name': name}, {'$set': char_src})


def process():
    pass


def main(func='process', **kwargs):
    eval(func)(**kwargs)
    print('finished.')


if __name__ == '__main__':
    import fire

    fire.Fire(main)
