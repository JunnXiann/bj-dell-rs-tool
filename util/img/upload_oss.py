import os
import sys
import logging
import os.path as osp

sys.path.append(osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__)))))

import helper as hp
from util.oss import Oss

db_work = hp.get_db('tw-work')


def upload2oss():
    # 准备参数
    hp.set_logging('upload2oss.log')
    cfg = hp.prop(hp.load_config(), 'oss')
    assert cfg
    oss = Oss(cfg['url'], cfg['key_id'], cfg['key_secret'])
    assert oss.is_readable()
    # 进行上传
    err_times = 0
    root = '/data/static/img'
    # colls = ['char2', 'char5', 'char3', 'char4']
    colls = ['char2']
    for coll in colls:
        cond = {}
        if coll == 'char2':
            cond = {'img.sts': None}
        chars = list(db_work[coll].find(cond, {'name': 1, '_id': 0}))
        names = [p['name'] for p in chars]
        for i, name in enumerate(names):
            logging.info('[%s/%s]%s' % (i, len(names), name))
            suffix = hp.md5_encode(name)
            oss_fn = osp.join('chars', *name.split('_')[:3], '%s_%s.jpg' % (name, suffix))
            local_fn = osp.join(root, oss_fn)
            if not osp.exists(local_fn):
                continue
            try:
                r = oss.upload_file(oss_fn, local_fn)
                if r and r.status == 200:
                    db_work[coll].update_one({'name': name}, {'$set': {'img.sts': 2}})
                else:
                    db_work[coll].update_one({'name': name}, {'$set': {'img.sts': -1}})
            except Exception as e:
                logging.error(e)
                err_times += 1
                if err_times > 10:
                    return


def copy_object(n=0):
    """ 从一个存储桶拷贝至另一个存储桶"""
    # 准备参数
    hp.set_logging('copy_object')
    cfg = hp.prop(hp.load_config(), 'oss')
    assert cfg
    oss = Oss(cfg['url'], cfg['key_id'], cfg['key_secret'])

    # 进行拷贝
    cond = {'name': {'$regex': '^(?!(JS|GL))'}, 'img_status': 0}
    pages = list(db_work.page.find(cond, {'name': 1, '_id': 0}))
    names = [p['name'] for p in pages]
    for i, name in enumerate(names):
        logging.info('[%s/%s]%s' % (i, len(names), name))
        suffix = hp.md5_encode(name)
        filepath = osp.join('pages', *name.split('_')[:-1], '%s_%s.jpg' % (name, suffix))
        try:
            r = oss.bucket.copy_object('tripitaka-img', filepath, filepath)
            if r and r.status == 200:
                db_work.page.update_one({'name': name}, {'$set': {'img_status': 2}})
        except Exception as e:
            logging.error(e)


def multi_copy_object(n=3):
    """ 多进程上传"""
    cmd = 'nohup python3 %s/data/build_data.py --func=copy_object --n=%s &'
    for i in range(n):
        cmd_i = cmd % (hp.BASE_DIR, i + 1)
        os.system(cmd_i)


def main(func='', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
