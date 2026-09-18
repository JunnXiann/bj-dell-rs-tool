import shutil
from os import path
import numpy as np
import cv2 as cv
import sys
sys.path.insert(0, path.dirname(path.dirname(path.abspath(__file__))))

from base.base_func import scan_pdf_files, get_scan_info, auto_mkdir, no_file


def export_org_img(db, pdf_file, han=0):
    pdf_name, vol, info = get_scan_info(pdf_file, han, db)
    vol_info = db.sx_volume.find_one(dict(han=han, vol_ok=vol))
    rs = db.sx_fold.find(dict(han=han, vol_ok=vol, deleted=None, fold_id={'$ne': None}),
                         sort=[('fold_no', 1)])
    nums = []
    empty_file = path.join(info['out_path'], 'fold', 'empty.jpg')
    dst_file = path.join(info['out_path'], 'SX', str(han), str(vol), 'SX_%s.jpg')
    auto_mkdir(dst_file)
    for r in rs:
        if not r.get('fold_mean') and r['fold_no'] > vol_info['max_no']:
            continue
        nums.append(r['fold_no'])
        if no_file(dst_file % r['fold_id']):
            mid_p = '/'.join(r['bid'].split('_')[:2])
            src_file1 = path.join(info['out_path'], 'embed', mid_p, r['bid'] + '.jpg')
            src_file2 = path.join(info['out_path'], 'fold', mid_p, r['bid'] + '.jpg')
            src_file = src_file1 if path.exists(src_file1) else src_file2 if path.exists(
                src_file2) else not r.get('fold_mean') and empty_file
            shutil.copy(src_file, dst_file % r['fold_id'])

            im = cv.imread(dst_file % r['fold_id'], cv.IMREAD_GRAYSCALE)
            h, w = map(int, im.shape)
            m = round(np.mean(im) * 100)
            db.sx_fold.update_one(dict(_id=r['_id']), {'$set': dict(w=w, h=h, mean=m)})

    if nums != list(range(1, vol_info['max_no'] + 1)):
        print(han, vol, vol_info['max_no'], len(nums), nums)


def main(db_name='sx_pdf', only_name='', only_han=''):
    scan_pdf_files(lambda file, han, db: export_org_img(db, file, han),
                   db_name, '', only_name, only_han)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
