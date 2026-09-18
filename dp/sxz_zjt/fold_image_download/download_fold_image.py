# -*- coding: utf-8 -*-
"""
@File    : download_fold_image.py
@Time    : 2025/5/26 13:04
@Author  : zhujiantao
@Version : 1.0
@Desc    : 下载dell服务器上扣图到本地
"""

import os.path
import subprocess
import multiprocessing

import numpy as np


def scp_file_from_remote(remote_user: str, remote_host: str, remote_file_path: str, local_file_path: str, remote_port=28282):
    """
    使用scp命令将远程服务器上的文件拷贝到本地
    :param remote_port: 远程服务器端口
    :param remote_user: 远程服务器用户名
    :param remote_host: 远程服务器地址
    :param remote_file_path: 远程服务器上文件的路径
    :param local_file_path: 本地保存文件的路径
    """
    command = f"scp -P {remote_port} {remote_user}@{remote_host}:{remote_file_path} {local_file_path}"
    try:
        subprocess.run(command, shell=True, check=True)
        print(f"文件拷贝成功【{remote_file_path}】")
    except subprocess.CalledProcessError as e:
        print(f"文件拷贝失败: {e}")


def copy_from_remote(fold_id_list: list, fold_id_list_order: int, skip_downloaded_flag=True):
    """
    从远程主机拷贝图片
    :param skip_downloaded_flag: 不重复下载标志 true不重复下载 false重复下载
    :param fold_id_list: 扣图id列表 [1_2_3]
    :param fold_id_list_order: 下载目标目录序号
    :return:
    """
    print(f"开始执行第{fold_id_list_order}个进程...")
    remote_user = "zjt"  # 远程服务器用户名
    remote_host = "222.128.59.112"  # 远程服务器IP地址
    local_file_path = "download_fold_image"  # 本地文件路径

    if not os.path.exists(local_file_path):
        os.makedirs(local_file_path)

    exist_fold_id_list = []
    if skip_downloaded_flag is True:
        # 得到已下载的扣图id
        for tmp in os.listdir("download_fold_image"):
            exist_fold_id_list.append(tmp.split(".")[0][3:])

    for fold_id in fold_id_list:

        if fold_id in exist_fold_id_list:
            print(f"跳过{fold_id}")
            continue

        remote_file_path = "/nas/data/T/big/SX"  # 远程文件路径

        han_dir = fold_id.split("_")[0]
        volume_dir = fold_id.split("_")[1]

        filename = f"SX_{fold_id}.jpg"

        remote_file_path = os.path.join(remote_file_path, han_dir, volume_dir, filename)
        print(remote_file_path)

        scp_file_from_remote(remote_user, remote_host, remote_file_path, local_file_path)


def download_fold_image_multiprocessing(fold_id_list: list):
    """
    多进程下载扣图
    :param fold_id_list: 扣图id列表,例如['1_2_3']
    :return:
    """
    # 进程数量
    process_count = 20
    # 将扣图id列表平均分为若干个列表
    chunks = np.array_split(fold_id_list, process_count)
    chunk_list = [chunk.tolist() for chunk in chunks]

    processes = []
    for i in range(0, process_count):
        p = multiprocessing.Process(target=copy_from_remote, args=(chunk_list[i], i))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()
