# -*- coding: utf-8 -*-
"""
@File    : find_same_fold_content.py
@Time    : 2025/5/27 15:29
@Author  : zhujiantao
@Version : 1.0
@Desc    : 根据扣图识别出来的ocr内容查找内容相同的扣图,扣图内容由数据库导出，扣图ocr内容样例数据在SX目录下，最终生成result.json
"""

import json
import os
import hashlib
from concurrent.futures import ProcessPoolExecutor
from tqdm import tqdm


def calculate_file_hash(file_path):
    """Calculate the SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read and update hash in chunks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return file_path, sha256_hash.hexdigest()


def find_duplicate_files(directory, max_workers):
    """Find duplicate txt files based on their content using multiple processes."""
    # Dictionary to store file hashes and their corresponding file names
    file_hashes = {}

    # List to store file paths
    file_paths = [os.path.join(root, file)
                  for root, _, files in os.walk(directory)
                  for file in files if file.endswith(".txt")]

    # Use ProcessPoolExecutor to calculate file hashes in parallel
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Wrap the results with tqdm to show a progress bar
        results = tqdm(executor.map(calculate_file_hash, file_paths), total=len(file_paths))

        # Populate the file_hashes dictionary
        for file_path, file_hash in results:
            print(file_path)
            if file_hash in file_hashes:
                file_hashes[file_hash].append(file_path)
            else:
                file_hashes[file_hash] = [file_path]

    # Filter out files with unique content
    duplicates = {hash: files for hash, files in file_hashes.items() if len(files) > 1}

    return duplicates


if __name__ == "__main__":
    # Specify the directory containing the .txt files
    directory_path = "../SX"

    # Specify the maximum number of processes
    max_workers = 40

    # Find duplicate files
    duplicates = find_duplicate_files(directory_path, max_workers)

    # Print the results
    for file_hash, files in duplicates.items():
        print(f"Files with hash {file_hash}:")
        for file in files:
            print(f" - {file}")
        print()

    with open("result.json", "w") as f:
        f.write(json.dumps(duplicates))
