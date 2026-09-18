import time
import fitz
import os
import re
import csv
import numpy as np
import pandas as pd
from PIL import Image
from typing import Dict, Any, Tuple, List, Optional

def log_message(msg: str, log_path: str = "process_log.txt"):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def load_page_info(csv_path: str):
    """
    Loads the page info CSV and returns a dict:
    {(pdf_name, pi): {'whole_img': bool, 'dim': dict}}
    """
    df = pd.read_csv(csv_path, converters={'dim': eval})
    page_info = {}

    for _, row in df.iterrows():
        key = (row['pdf_name'], row['pi'])
        page_info[key] = {
            'whole_img': bool(row['whole_img']),
            'dim': row['dim']
        }

    return page_info

def orientation_label(angle: float) -> str:
    a = abs(angle)
    if a < 1:
        return "正"
    elif a < 2:
        return "微倾"
    elif a >= 179:
        return "反转"
    elif a > 178:
        return "反转+微倾"
    else:
        return "倾斜"

def scale_bbox(bbox: Any, scale: float = 1.0) -> Any:
    """Return a scaled fitz.Rect bbox."""
    return fitz.Rect(bbox.x0 * scale, bbox.y0 * scale, bbox.x1 * scale, bbox.y1 * scale)

def collect_image_areas(pdf_path: str, scale: float = 1.0):
    doc = fitz.open(pdf_path)
    area_dict = {}
    all_areas = []
    bbox_dict = {}

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        for img in page.get_images(full=True):
            name = img[7]
            bbox = page.get_image_bbox(name)
            bbox = scale_bbox(bbox, scale)
            area = (bbox.x1 - bbox.x0) * (bbox.y1 - bbox.y0)
            area_dict[(page_num, name)] = area
            bbox_dict[(page_num, name)] = bbox
            all_areas.append(area)

    return area_dict, all_areas, bbox_dict

def sort_images_by_position(bbox_dict: Dict[Tuple[int, str], Any], page_num: int) -> Dict[str, int]:
    """Sort images by position to match the sequential ordering (0,1,2,3...9)"""
    page_images = [(name, bbox) for (pnum, name), bbox in bbox_dict.items() if pnum == page_num]
    
    if not page_images:
        return {}
    
    # Get actual min and max y coordinates of all images
    min_y = min(bbox.y0 for _, bbox in page_images)
    max_y = max(bbox.y1 for _, bbox in page_images)
    page_mid_y = (min_y + max_y) / 2
    
    # Separate upper and lower half images based on their center point
    upper_images = []
    lower_images = []
    
    for name, bbox in page_images:
        bbox_center_y = (bbox.y0 + bbox.y1) / 2
        if bbox_center_y < page_mid_y:
            upper_images.append((name, bbox))
        else:
            lower_images.append((name, bbox))
    
    # Sort by x-coordinate (left to right)
    upper_images.sort(key=lambda x: x[1].x0)
    lower_images.sort(key=lambda x: x[1].x0)
    
    # Create position mapping
    position_map = {}
    current_pos = 0
    
    # Upper row images (0, 1, 2, 3, 4)
    for name, bbox in upper_images:
        position_map[name] = current_pos
        current_pos += 1
    
    # Lower row images (5, 6, 7, 8, 9)
    for name, bbox in lower_images:
        position_map[name] = current_pos
        current_pos += 1
    
    return position_map

def assign_grid_indices(
    bbox_dict: Dict[Tuple[int, str], Any],
    dim: Dict[str, Any],
    page_num: int,
    pdf_base: str = ""
) -> Dict[str, int]:
    xs = dim['xs']
    yc = dim['yc']
    tp = dim['tp']
    bt = dim['bt']
    cell_map = {}
    index_map = {}

    for (pnum, name), bbox in bbox_dict.items():
        if pnum != page_num:
            continue

        cx = (bbox.x0 + bbox.x1) / 2
        cy = (bbox.y0 + bbox.y1) / 2
        area = (bbox.x1 - bbox.x0) * (bbox.y1 - bbox.y0)
        col = None
        for i in range(5):
            if xs[i] <= cx < xs[i+1]:
                col = i
                break

        if col is None:
            log_message(f"[WARN] PDF={pdf_base}, Page={page_num}, Image {name} at cx={cx:.2f} does not fit in any column, skipping.")
            continue

        row = 0 if cy <= yc else 1
        key = (row, col)

        if key not in cell_map or area > cell_map[key][1]:
            cell_map[key] = (name, area)


    for (row, col), (name, _) in cell_map.items():
        idx = row * 5 + col
        index_map[name] = idx

    return index_map

def extract_image_transformations(
    pdf_path: str,
    page_info: Optional[Dict[Tuple[str, int], Dict[str, Any]]] = None,
    use_grid: bool = True,
    scale: float = 1.0
) -> Dict[int, List[Dict[str, Any]]]:
    doc = fitz.open(pdf_path)
    skewed = {}
    bbox_dict = {}
    pdf_base = os.path.splitext(os.path.basename(pdf_path))[0]
    
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        for img in page.get_images(full=True):
            name = img[7]
            bbox = page.get_image_bbox(name)
            bbox = scale_bbox(bbox, scale)
            bbox_dict[(page_num, name)] = bbox
    
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        content_streams = page.get_contents()

        if content_streams:
            stream_data = b"".join([doc.xref_stream(xref) for xref in content_streams])
            stream_text = stream_data.decode("latin1", errors="ignore")
            pattern = r"([-\d\. ]+)\s+cm\s*/(Im\d+)\s+Do"
            matches = re.findall(pattern, stream_text)
            
            # Use grid-based mapping
            info_key = (pdf_base, page_num)
            if use_grid and page_info and info_key in page_info:
                dim = page_info[info_key]['dim']
                position_map = assign_grid_indices(bbox_dict, dim, page_num, pdf_base=pdf_base)
            else:
                position_map = sort_images_by_position(bbox_dict, page_num)
            
            for matrix_str, im_name in matches:
                matrix = [float(x) for x in matrix_str.strip().split()]
                a, b, c, d, e, f = matrix
                angle = np.degrees(np.arctan2(b, a))
                label = orientation_label(angle)
                position = position_map.get(im_name, 0)  # Default to 0 if not found
                
                if page_num not in skewed:
                    skewed[page_num] = []
                skewed[page_num].append({
                    "image": im_name, 
                    "angle": angle, 
                    "label": label, 
                    "position": position
                })
    
    return skewed

def label_outliers(
    area_dict: Dict[Tuple[int, str], float],
    all_areas: List[float],
    threshold: float = 0.5
) -> Tuple[Dict[Tuple[int, str], Tuple[float, str]], float]:
    median_area = np.median(all_areas) if all_areas else 0
    outlier_dict = {}

    for key, area in area_dict.items():
        ratio = area / median_area if median_area else 0
        outlier = ""
        if ratio < threshold or ratio > 1/threshold:
            outlier = "异常"
        outlier_dict[key] = (area, outlier)

    return outlier_dict, median_area

def write_csv(rows: List[List[Any]], csv_path: str):
    with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['bid', 'pdf', 'page', 'image', 'degree', 'label', 'area', 'outlier'])
        for row in rows:
            writer.writerow(row)

def extract_volume_number(filename: str) -> Optional[int]:
    match = re.search(r'(\d+)册\.pdf$', filename)
    if match:
        return int(match.group(1))
    return None

def extract_image_number(im_name: str) -> Optional[int]:
    match = re.match(r'Im(\d+)', im_name)
    if match:
        return int(match.group(1))
    return None

def process_pdf(
    pdf_path: str,
    subdir: str,
    filename: str,
    threshold: float = 0.5,
    page_info: Optional[Dict[Tuple[str, int], Dict[str, Any]]] = None,
    use_grid: bool = True,
    scale: float = 1.0
) -> List[List[Any]]:
    dir = int(subdir)
    vol = extract_volume_number(filename)
    area_dict, all_areas, bbox_dict = collect_image_areas(pdf_path, scale=scale)

    if not all_areas:
        return []
    
    outlier_dict, median_area = label_outliers(area_dict, all_areas, threshold)
    skewed = extract_image_transformations(pdf_path, page_info, use_grid, scale=scale)
    rows = []
    pdf_base = os.path.splitext(filename)[0]

    for pagenum, images in skewed.items():
        info_key = (pdf_base, pagenum)

        if page_info:
            if info_key not in page_info:
                log_message(f"[WARN] info_key {info_key} not found in page_info, skipping page.")
                continue
            if page_info[info_key]['whole_img']:
                continue  # skip this page

        for img in images:
            key = (pagenum, img['image'])
            area, outlier = outlier_dict.get(key, (0, ""))
            bid = f"{dir}_{vol}_{pagenum}_{img['position']}"
            rows.append([
                bid,
                f"{subdir}/{filename}",
                pagenum,
                img['image'],
                f"{img['angle']:.2f}",
                img['label'],
                f"{area:.2f}",
                outlier,
            ])

    return rows

def transformation_matrix_extractor(
    source_folder: str,
    threshold: float = 0.5,
    csv_path: str = 'bids-0915.csv',
    max_files: Optional[int] = None,
    page_info_csv: Optional[str] = None,
    log_every: int = 100,
    use_grid: bool = True,
    scale: float = 1.0
) -> None:
    all_rows = []
    file_count =  0
    start_time = time.time()
    page_info = load_page_info(page_info_csv) if page_info_csv else None

    for dirpath, _, filenames in os.walk(source_folder):
        subdir = os.path.relpath(dirpath, source_folder)
        for filename in filenames:
            if filename.lower().endswith(".pdf"):
                pdf_path = os.path.join(dirpath, filename)
                # print(f"Processing {pdf_path}")
                rows = process_pdf(pdf_path, subdir, filename, threshold, page_info, use_grid, scale=scale)
                all_rows.extend(rows)
                file_count += 1
                if file_count % log_every == 0:
                    elapsed = time.time() - start_time
                    print(f"[INFO] Processed {file_count} PDFs in {elapsed:.1f}s")
                if max_files is not None and file_count >= max_files:
                    return
                
    write_csv(all_rows, csv_path)

if __name__ == "__main__":
    transformation_matrix_extractor(
        "../../../nas/data/T/原始藏经资料/07思溪藏SX/思溪藏_扬州古籍_PDF", 
        threshold=0.5, 
        max_files=None,
        page_info_csv="sx_pdf_page.csv",
        use_grid=True,
        scale=1.666
    )