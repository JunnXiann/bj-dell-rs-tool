import os
import re
import sys
import csv
import json
import logging
from os import path
from glob2 import glob
from datetime import datetime

sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

import helper as hp


def func1():
    pass


def main(func='', **kwargs):
    eval(func)(**kwargs)


if __name__ == '__main__':
    import fire

    fire.Fire(main)
