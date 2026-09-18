# Usage:
# python3 -m run_tests.py --coverage
# python3 -m run_tests.py -k test_case_name

import os
import sys
import pytest

sys.path.append(os.path.dirname(__file__))

if __name__ == '__main__':
    test_args = sys.argv[1:]

    try:
        test_args.remove('--coverage')
    except ValueError:
        test_args += ['tests']
        # 单独调试某个测试用例或用例集时，可将下行的注释取消，改为相应的测试用例函数名
        # test_args += ['-k test_find_match_case2']
    else:
        test_args = ['--cov=controller', '--cov-report=term', '--cov-report=html',
                     'tests'] + test_args
    errcode = pytest.main(test_args)
    sys.exit(errcode)
