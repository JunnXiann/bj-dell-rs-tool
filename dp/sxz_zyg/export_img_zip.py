import os
import shutil
import zipfile
from glob2 import glob


def compress_images(out_path, prefix='joint', folder='joint_add', han='1-548'):
    han0, size, zf, zfn = 0, 0, None, ''
    from_han, to_han = map(int, han.split('-'))
    for han in range(from_han, to_han + 1):
        if not zf:
            han0 = han
            zfn = os.path.join(out_path, 'zip', f'{prefix}-{han}.zip')
            zf = zipfile.ZipFile(zfn, 'w', compression=zipfile.ZIP_DEFLATED)
        files = sorted(glob(os.path.join(out_path, folder, str(han), '**', '*.jpg')))
        for i, fn in enumerate(files):
            size += os.path.getsize(fn)
            zf.write(fn, fn.split(folder)[-1][1:])
        mb = size // (1024 * 1024)
        han = min(han, 548)
        print(f'{han0}\t{han}\t{mb} M')
        if mb > 2 * 1024 or han == 548:
            zf.close()
            zf = None
            size = 0
            shutil.move(zfn, os.path.join(out_path, 'zip', f'{prefix}-{han0}-{han}.zip'))


def main(brief=0, han='1-548'):
    out_path = os.environ['OUT_PATH']
    compress_images(out_path, 'joint' if brief else 'SX', 'joint_add' if brief else 'SX', han)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
