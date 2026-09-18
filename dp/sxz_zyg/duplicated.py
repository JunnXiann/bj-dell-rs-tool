from os import path

import sys
sys.path.insert(0, path.dirname(path.dirname(path.abspath(__file__))))

from base.base_func import with_db


def check_same_fold(db, only_han=0):
    """对扣号相同的扣检查扣图是否相同"""
    cond = dict(han=only_han, should_no={'$gt': 0})
    if not only_han:
        cond.pop('han')
    # 找到扣名相同的扣编号
    fold_ids = [r['_id'] for r in db.sx_fold_check.aggregate([{'$match': cond}, {'$group': {
        '_id': '$fold_id', 'n': {'$sum': 1}}}])]
    folds = {r['_id']: r['ids'] for r in db.sx_fold_check.aggregate([
        {'$match': {'fold_id': {'$in': fold_ids}}},
        {'$group': {'_id': '$fold_id', 'n': {'$sum': 1}, 'ids': {'$addToSet': '$bid'}}},
        {'$match': {'n': {'$gt': 1}}}])}

    for fid, ids in folds.items():
        rs = [r for r in db.sx_fold.find({'bid': {'$in': ids}, 'deleted': None}, {
            'fold_mean': 1, 'end': 1, 'bid': 1})]
        means = [r.get('fold_mean') for r in rs]
        if ids[0].rsplit('_', 1)[0] == ids[1].rsplit('_', 1)[0]:  # 同页
            print(f"{fid},{rs[0]['bid']},{rs[1]['bid']},{abs(means[0] - means[1])}")


def main(db_name='sx_pdf', func='', only_han=0):
    with_db(db_name, lambda db: check_same_fold(db, int(only_han)))


if __name__ == '__main__':
    import fire

    fire.Fire(main)
