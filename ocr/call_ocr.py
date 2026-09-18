import sys
import math
import logging
import requests
import os.path as osp
from bson import json_util
from datetime import datetime

sys.path.append(osp.dirname(osp.dirname(osp.abspath(__file__))))

import helper as hp
from ocr import util


def call_ocr_process(url, body):
    """ 发起http请求，批量进行单字识别"""
    headers = {'User-Agent': 'Chrome/71.0.3578.98 Safari/537.36'}
    r = requests.post(url=url, headers=headers, data=body)
    r.raise_for_status()
    return json_util.loads(r.text)


def batch_pages_box():
    """ 批量切分页图"""
    hp.set_logging('batch_pages_box')

    db = hp.get_db('')  # 需根据实际情况修改
    cond = {}  # 需根据实际情况修改

    pages = list(db.page.find(cond, {'name': 1}))
    for page in pages:
        page_name = page['name']
        page_path = hp.get_page_img_path(page_name)
        if not page_path:
            logging.warning('没有找到图片:%s' % page_name)
            continue
        try:
            url = 'http://rushi520:9010/v2/ocr/page/box'
            body = {'file_path': page_path, 'h_num': 2}
            response = call_ocr_process(url, body) or {}
            if response.get('status'):
                db.page.update_one({'_id': page['_id']}, {'$set': response.get('page')})
                logging.info('识别成功:%s' % page_name)
            else:
                logging.error('识别失败:%s' % page_name)
        except Exception as err:
            logging.error('识别异常:%s, %s' % (page_name, err))


def batch_chars_ocr(
        port='8900',  # 8900是v1端口，9010是v2端口
        ocr_version='v1',  # api url的版本
        ocr_engine='GJTZ_v1.0',  # ocr引擎代码
        char_coll='char4',  # 字图数据的char表名
        char_source='JSYZ_v2',  # 字图数据的char数据分类
):
    """ 批量识别字图数据"""
    hp.set_logging('batch_chars_ocr')

    db = hp.get_db('')  # 需根据实际情况修改
    size = 1000
    cond = {'source': char_source}
    item_count = db[char_coll].count_documents(cond)
    char_count = math.ceil(item_count / size)
    for i in range(char_count):
        chars = list(db[char_coll].find(cond, {'name': 1, 'txt': 1}).sort('_id', 1).skip(i * size).limit(size))
        # 1.获取字图路径
        char_files, error_files = [], []
        for ch in chars:
            img_path = hp.get_char_img_path(ch['name'])
            if img_path:
                char_files.append(img_path)
            else:
                error_files.append(ch['name'])
        if error_files:
            logging.warning('没有找到图片:%s' % ','.join(error_files))
        if not char_files:
            continue
        logging.info('[%s]%s/%s processing %s chars' % (hp.get_date_time(), i + 1, char_count, len(char_files)))
        # 2.对字图进行ocr
        char_files_str = json_util.dumps(char_files)
        body = dict(char_files=char_files_str, char_ocr_model=ocr_engine)
        url = 'http://rushi520:%s/%s/ocr/batch_chars' % (port, ocr_version)
        ocr_res_list = call_ocr_process(url, body=body) or []
        # 3.存放结果
        name2txt = {c['name']: c['txt'] for c in chars}
        for res in ocr_res_list:
            field = 'ocr_res.%s' % ocr_engine.replace('.', '_')
            char_name = osp.basename(res['img_path']).rsplit('_', 1)[0]
            db[char_coll].update_one({**cond, 'name': char_name}, {'$set': {field: {
                'cc': res['cc'], 'alternatives': res['alternatives'], 'ocr_txt': res['ocr_txt'],
                'equal': name2txt.get(char_name) == res['ocr_txt']}}})


def batch_js_pages_ocr(
        main_engine='JSYZ_v6.0',
        sub_engine='JSYZ_v9.0'
):
    """ 径山藏原字双引擎批量识别页图"""
    hp.set_logging('batch_pages_ocr')

    db = hp.get_db('')  # 需根据实际情况修改
    cond = {'name': ''}  # 需根据实际情况修改
    pages = list(db.page.find(cond, {'name': 1, 'blocks': 1, 'columns': 1, 'chars': 1, '_id': 0}))
    for page in pages:
        page_name = page['name']
        page_path = hp.get_page_img_path(page_name)
        if not page_path:
            logging.warning('没有找到图片:%s' % page_name)
            continue
        try:
            # 准备参数
            p = {f: [] for f in ['blocks', 'columns', 'chars']}
            for f in ['blocks', 'columns', 'chars']:
                for box in page.get(f, []):
                    if box.get('deleted'):
                        continue
                    info = {f: round(box.get(f), 1) for f in ['x', 'y', 'w', 'h']}
                    info.update({f: box[f] for f in ['block_no', 'column_no', 'char_no', 'cid'] if box.get(f)})
                    p[f].append(info)
            page_str = json_util.dumps(p)
            # 主引擎识别
            url = 'http://rushi520:9010/v2/ocr/page/ocr'
            body = {'file_path': page_path, 'h_num': 2, 'page': page_str, 'ocr': True, 'char_recog_model': main_engine}
            main_response = call_ocr_process(url, body) or {}
            if not main_response.get('status'):
                logging.error('识别失败:%s' % page_name)
                continue
            # 辅引擎识别
            body['char_recog_model'] = sub_engine
            sub_response = call_ocr_process(url, body) or {}
            if not sub_response.get('status'):
                logging.error('识别失败:%s' % page_name)
                continue
            main_chars = hp.prop(main_response, 'page.chars', [])
            sub_chars = hp.prop(sub_response, 'page.chars', [])
            main_res_dict = {c['cid']: c for c in main_chars}
            sub_res_dict = {c['cid']: c for c in sub_chars}
            for c in page['chars']:
                if c.get('deleted'):
                    continue
                main_res = main_res_dict.get(c['cid'])
                sub_res = sub_res_dict.get(c['cid'])
                alternatives = util.merge_ocr_res(main_res['alternatives'], sub_res['alternatives'])
                c.update({
                    'ocr_txt': main_res['ocr_txt'], 'cc': main_res['cc'], 'alternatives': alternatives,
                    'ocr_col': sub_res['ocr_col'], 'lc': sub_res['cc']
                })
            db.page.update_one({'_id': page['_id']}, {'$set': {'chars': page['chars']}})
            logging.info('识别成功:%s' % page_name)
        except Exception as err:
            logging.error('识别异常:%s, %s' % (page_name, err))


def batch_js_chars_ocr(
        main_engine='JSYZ_v9.0',  # 主引擎
        sub_engine='JSYZ_v8.0',  # 辅引擎
        char_coll='char4',  # 字图数据的char表名
        char_source='JSYZ_v9',  # 字图数据的char数据分类
):
    """ 径山藏原字双引擎批量识别字图 """
    hp.set_logging('batch_js_chars_ocr')

    size = 1000
    db = hp.get_db('')  # 需根据实际情况修改
    cond = {'source': char_source}  # 可根据实际情况修改
    item_count = db[char_coll].count_documents(cond)
    char_count = math.ceil(item_count / size)
    for i in range(char_count):
        chars = list(db[char_coll].find(cond, {'name': 1, 'txt': 1}).sort('_id', 1).skip(i * size).limit(size))
        # 1.获取字图路径
        char_files, error_files = [], []
        for ch in chars:
            img_path = hp.get_char_img_path(ch['name'])
            if img_path:
                char_files.append(img_path)
            else:
                error_files.append(ch['name'])
        if error_files:
            logging.error('没有找到图片:%s' % ','.join(error_files))
        if not char_files:
            continue
        logging.info('[%s]%s/%s processing %s chars' % (hp.get_date_time(), i + 1, char_count, len(char_files)))
        # 2.双引擎对字图进行ocr
        char_files_str = json_util.dumps(char_files)
        body = dict(char_files=char_files_str, char_ocr_model=main_engine)
        url = 'http://rushi520:9010/v2/ocr/batch_chars'
        main_res_list = call_ocr_process(url, body=body) or []
        body['char_ocr_model'] = sub_engine
        sub_res_list = call_ocr_process(url, body=body) or []
        sub_res_dict = {osp.basename(sub_res['img_path']).rsplit('_', 1)[0]: sub_res for sub_res in sub_res_list}
        # 3.遍历结果集，合并结果，保存数据
        for main_res in main_res_list:
            char_name = osp.basename(main_res['img_path']).rsplit('_', 1)[0]
            sub_res = sub_res_dict.get(char_name) or {}
            alternatives = util.merge_ocr_res(main_res['alternatives'], sub_res['alternatives'])
            db[char_coll].update_one({**cond, 'name': char_name}, {'$set': {
                'ocr_txt': main_res['ocr_txt'], 'cc': int(main_res['cc'] * 1000), 'alternatives': alternatives,
                'ocr_col': sub_res['ocr_txt'], 'lc': int(sub_res['cc'] * 1000)
            }})


def main(func='case1', **kwargs):
    eval(func)(**kwargs)
    print('finished.')


if __name__ == '__main__':
    import fire

    fire.Fire(main)
