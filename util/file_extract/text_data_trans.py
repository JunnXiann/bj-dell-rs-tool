"""
注意：
DEST_PATH、MAX_SIZE_BYTES、MAX_WORKERS 需要根据实际情况调整。
该脚本重复执行，每次拷贝的限额是MAX_SIZE_BYTES，从copy_state.json的copied_index开始拷贝。
"""

import json
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

FILE_LIST = "file_list.json"
STATE_FILE = "copy_state.json"
DEST_PATH = Path("D:/test_copy")
MAX_SIZE_BYTES = 14 * 1024 ** 4  # 每轮最大拷贝容量，目前是4TB
MAX_WORKERS = 8

lock = Lock()
copied_size = 0  # 全局已拷贝量（从 state 恢复）
session_copied_size = 0  # 本轮实际拷贝量

def load_state():
    if Path(STATE_FILE).exists():
        return json.loads(Path(STATE_FILE).read_text())
    return {"copied_index": 0, "copied_size": 0}

def save_state(state):
    Path(STATE_FILE).write_text(json.dumps(state, indent=2))

def copy_file(item):
    src = Path(item["path"])
    rel_path = src.relative_to(Path(src.drive + "/"))
    dest = DEST_PATH / rel_path
    try:
        if dest.exists():
            print(f"[跳过已存在] {dest}")
            return item["size"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return item["size"]
    except Exception as e:
        print(f"[失败] {src}: {e}")
        return 0

def main():
    global copied_size, session_copied_size

    files = json.loads(Path(FILE_LIST).read_text())
    state = load_state()
    copied_index = state["copied_index"]
    copied_size = state["copied_size"]
    session_copied_size = 0

    print(f"从第 {copied_index} 个文件开始复制...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []

        for i in range(copied_index, len(files["files"])):
            item = files["files"][i]

            if "RECYCLE.BIN" in item["path"]:
                print(f"[跳过] {item['path']}")
                continue

            with lock:
                if session_copied_size + item["size"] > MAX_SIZE_BYTES:
                    print("本轮容量上限达到，停止任务提交")
                    break
                session_copied_size += item["size"]

            future = executor.submit(copy_file, item)
            futures.append((future, i))

        for future, index in futures:
            copied = future.result()

            if copied == 0:
                with lock:
                    session_copied_size -= files["files"][index]["size"]
            else:
                copied_size += copied

            state["copied_index"] = index + 1
            state["copied_size"] = copied_size
            save_state(state)
            print(f"已复制 {index + 1} 个文件，累计总大小 {copied_size / 1024**4:.2f} TB，"
                  f"本轮共复制 {session_copied_size / 1024**4:.2f} TB")

    print("本轮拷贝完成")

if __name__ == "__main__":
    main()
