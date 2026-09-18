import os
import json
from pathlib import Path
import pycdlib
import zipfile, tarfile, py7zr, rarfile
from concurrent.futures import ThreadPoolExecutor, as_completed

SOURCE_PATH = Path("E:/")
# 待拷贝文件信息
OUTPUT_FILE = "file_list.json"
# 扫描文件缓存，多次运行时或者有增量文件时可用，避免重复扫描
CACHE_FILE = "scan_progress.json"  
MAX_WORKERS = 16

TARGET_EXTS = {'.txt', '.csv', '.json', '.doc', '.docx', '.pdf', '.xml', '.tsv', '.rtf', '.odt', '.epub', '.uvz', '.pdg',
               '.html', '.sqlite', '.sqlite3', '.db', '.db3', '.sql', '.mdf', '.bak',
               '.pdb', '.bson', '.dump', '.rdb', '.zip', '.gz', '.rar', '.7z', '.tar', '.iso'}
TEXT_EXTS = TARGET_EXTS - {'.zip', '.gz', '.rar', '.7z', '.tar', '.iso'}

def archive_contains_texts(path: Path) -> bool:
    """压缩包内文本文件数量占比>=0.5时，判断为“文本文件压缩包”
    """
    ext = path.suffix.lower()
    try:
        if ext == '.zip':
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
        elif ext == '.tar':
            with tarfile.open(path) as tf:
                names = tf.getnames()
        elif ext == '.7z':
            with py7zr.SevenZipFile(path, 'r') as zf:
                names = zf.getnames()
        elif ext == '.rar':
            with rarfile.RarFile(path) as rf:
                names = rf.namelist()
        elif ext == '.gz':
            return path.with_suffix('').suffix.lower() in TEXT_EXTS
        elif ext == '.iso':
            iso = pycdlib.PyCdlib()
            iso.open(str(path))
            names = []

            def walk_iso(directory='/'):
                children = []
                iso_children = []
                iso_children = iso.list_children(iso_path=directory)
                for child in iso_children:
                    name = child.file_identifier().decode('utf-8').replace(';;1', '')
                    if name in ('.', '..'):
                        continue
                    full_path = os.path.join(directory, name)
                    if child.is_dir():
                        children.extend(walk_iso(full_path))
                    else:
                        full_path = full_path.replace(';1', '')
                        children.append(full_path)
                return children

            names = walk_iso('/')
            iso.close()
        else:
            return False
        if not names:
            return False
        count = sum(1 for n in names if Path(n).suffix.lower() in TEXT_EXTS)
        return count / len(names) >= 0.5
    except:
        return False

def process_file(path: Path):
    ext = path.suffix.lower()
    if ext not in TARGET_EXTS:
        return None
    if ext in {'.zip', '.gz', '.rar', '.7z', '.tar', '.iso'}:
        if not archive_contains_texts(path):
            return None
    try:
        size = path.stat().st_size
        return {"path": str(path), "size": size}
    except:
        return None

def scan_all_files():
    processed = set()
    if Path(CACHE_FILE).exists():
        processed = set(json.loads(Path(CACHE_FILE).read_text()))
    
    all_paths = []
    for dirpath, _, filenames in os.walk(SOURCE_PATH):
        for name in filenames:
            full = str(Path(dirpath) / name)
            if full not in processed:
                all_paths.append(Path(full))
                processed.add(full)

    print(f"待处理文件数：{len(all_paths)}")

    valid_files = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_file, path): path for path in all_paths}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result:
                valid_files.append(result)
            if i % 100 == 0:
                print(f"已处理 {i} / {len(futures)}")

    total_size = sum(f["size"] for f in valid_files)
    total_tb = total_size / 1024**4

    print(f"\n 扫描完成，符合条件文件数：{len(valid_files)}")
    print(f"总空间占用：{total_size / 1024**3:.2f} GB ({total_tb:.2f} TB)")

    output_data = {
        "total_size": total_size,
        "total_tb": round(total_tb, 4),
        "files": valid_files
    }

    Path(OUTPUT_FILE).write_text(json.dumps(output_data, indent=2))
    Path(CACHE_FILE).write_text(json.dumps(list(processed)))

if __name__ == "__main__":
    scan_all_files()
