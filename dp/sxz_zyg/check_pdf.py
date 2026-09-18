import re
from os import path, environ
from glob2 import glob
import pymupdf as pdf


def check_pdf(pdf_root=''):
    files = sorted(glob(path.join(pdf_root or environ['PDF_ROOT'], '**', '*.pdf')))
    files = [s for s in files if re.search(r'/\d{3}/.字第\d+册\.pdf', s.replace('\\', '/'))]
    fn, pn, err_n = 0, 0, 0
    for pdf_file in files:
        sub_page = {re.search(r'册第(.+)页\.', f).group(1): f
                    for f in glob(pdf_file.replace('册.pdf', '册第*页.pdf'))}
        try:
            with pdf.open(pdf_file) as doc:
                fn += 1
                for pi in range(doc.page_count):
                    pn += 1
                    if sub_page.get(f'{pi + 1}'):
                        try:
                            with pdf.open(sub_page[f'{pi + 1}']) as s_doc:
                                fn += 1
                        except (RuntimeError, OSError) as e:
                            err_n += 1
                            print(path.basename(pdf_file), pi, str(e))
        except (RuntimeError, OSError) as e:
            err_n += 1
            print('/'.join(pdf_file.split('/')[-2:]), str(e))
    print(f"{fn} pdf, {err_n} invalid pdf, {pn} pages, {'ok' if pn == 45994 else 'fail'}")


if __name__ == '__main__':
    import fire

    fire.Fire(check_pdf)
