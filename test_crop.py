import cv2
import numpy as np
import json
import gc
import os
from os import path
from datetime import datetime
from bson import ObjectId
import helper as hp

def generate_scroll_boxes(small_image_path, json_data, output_json_path=None):
    print(f"\n--- Starting Processing for: {small_image_path} ---")

    # Get original dimensions for mapping
    large_width = json_data.get("width")
    large_height = json_data.get("height")
    
    if not large_width or not large_height:
        print("Error: JSON must contain both 'width' and 'height' fields.")
        return

    existing_boxes = json_data.get("images", [])
    
    # 2. Determine Starting Coordinates (Right-to-Left)
    if existing_boxes:
        start_box = existing_boxes[0] 
        starting_x_large = start_box["x"]
        global_y = start_box["y"]
        global_h = start_box["h"]
        cid_counter = max([box["cid"] for box in existing_boxes]) + 1
    else:
        starting_x_large = float('inf') 
        global_y = 0            # Fallback
        global_h = large_height # Fallback
        cid_counter = 1

    # 3. Load SMALL Image into OpenCV
    print("Loading small image into RAM...")
    img_small = cv2.imread(small_image_path, 0)
    
    if img_small is None:
        print(f"Error: Could not load image {small_image_path}.")
        return

    small_height, small_width = img_small.shape
    
    # Calculate mapping ratios
    scale_x = large_width / small_width
    scale_y = large_height / small_height
    print(f"Scale Ratios -> X: {scale_x:.4f}, Y: {scale_y:.4f}")

    # ==========================================
    # 4. Find the Top and Bottom Black Border Lines
    # ==========================================
    print("Locating the horizontal black border lines...")
    
    _, ink_mask = cv2.threshold(img_small, 120, 255, cv2.THRESH_BINARY_INV)
    
    kernel_width = max(10, int(small_width * 0.05)) 
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1))
    lines_only = cv2.morphologyEx(ink_mask, cv2.MORPH_OPEN, horizontal_kernel)
    
    horizontal_projection = np.sum(lines_only, axis=1)
    peak_threshold = np.max(horizontal_projection) * 0.3
    line_y_coords = np.where(horizontal_projection > peak_threshold)[0]
    
    if len(line_y_coords) >= 2:
        small_top_line_y = line_y_coords[0]
        small_bottom_line_y = line_y_coords[-1]
    else:
        print("Warning: Could not clearly detect both black border lines. Using fallbacks.")
        small_top_line_y = int(small_height * 0.1)
        small_bottom_line_y = int(small_height * 0.9)

    # Calculate large scale for fallbacks later
    large_top_line_y = small_top_line_y * scale_y
    large_bottom_line_y = small_bottom_line_y * scale_y

    # --- THE FIX: STRICT MASKING ---
    # We step 3 pixels strictly inside the black lines so the table is 100% ignored.
    safe_top_small = small_top_line_y + 3
    safe_bottom_small = small_bottom_line_y - 3

    # Create the text_mask for Section 5 and Section 6
    _, text_mask = cv2.threshold(img_small, 180, 255, cv2.THRESH_BINARY_INV)
    
    # Erase everything outside our strict safe zone
    text_mask[0:safe_top_small, :] = 0
    text_mask[safe_bottom_small:small_height, :] = 0

    safe_zone = text_mask[safe_top_small:safe_bottom_small, :]
    
    # ==========================================
    # 5. Extract the Seams from the Safe Zone
    # ==========================================
    print("Finding the 5-column leaves in the safe zone...")
    
    # Use a small vertical kernel to clean up horizontal noise/dirt.
    paper_height = safe_bottom_small - safe_top_small
    kernel_h = max(2, int(paper_height * 0.02))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_h))
    
    clean_margin = cv2.morphologyEx(safe_zone, cv2.MORPH_OPEN, vertical_kernel)

    # Project vertically to find the seams
    vertical_projection = np.sum(clean_margin, axis=0)
    
    # We can use a lower threshold now because there is no text to cause false peaks
    peak_threshold = np.max(vertical_projection) * 0.3
    line_x_coords_small = np.where(vertical_projection > peak_threshold)[0]
    
    # Group pixels into single seam coordinates (Buffer is ~0.3% of image width)
    clean_small_x_coords = []
    min_gap = max(5, int(small_width * 0.003)) 
    for x in line_x_coords_small:
        if not clean_small_x_coords or x - clean_small_x_coords[-1] > min_gap: 
            clean_small_x_coords.append(float(x))

    # Map the detected seams back to the massive database scale
    clean_large_x_coords = [x * scale_x for x in clean_small_x_coords]
    clean_large_x_coords.sort(reverse=True)
    
    valid_lines_large = [x for x in clean_large_x_coords if x <= starting_x_large]
    print(f"BINGO! Detected {len(valid_lines_large)} major seams.")

    # 6. Group Major Lines into 25-Column Cores, then pad to 27 Columns
    # 6 major lines => 5 intervals => 25 text columns core
    major_lines_per_box = 6
    major_step = 5  # move by 5 intervals / 25 text columns each box

    new_boxes = []

    print("Calculating padded boxes from major divider lines...")

    # Isolate tall vertical lines so they don't ruin the horizontal projection
    v_kernel_size = max(15, int(small_height * 0.015)) 
    v_kernel_erase = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_size))
    
    # Detect vertical lines in the mask
    vertical_artifacts = cv2.morphologyEx(text_mask, cv2.MORPH_OPEN, v_kernel_erase)
    
    # Subtract them, leaving primarily just the text characters
    text_mask_no_lines = cv2.subtract(text_mask, vertical_artifacts)

    for i in range(0, len(valid_lines_large) - major_lines_per_box + 1, major_step):
        chunk = valid_lines_large[i:i + major_lines_per_box]
        if len(chunk) < major_lines_per_box:
            break

        core_right_edge = chunk[0]
        core_left_edge = chunk[-1]
        core_width = core_right_edge - core_left_edge

        if core_width <= 0:
            print(f"  -> Warning: invalid core width for box {cid_counter}. Skipping.")
            continue

        average_column_width = core_width / 25.0

        expanded_right_edge = min(float(large_width), core_right_edge + average_column_width)
        expanded_left_edge = max(0.0, core_left_edge - average_column_width)

        box_x = round(expanded_left_edge, 1)
        box_w = round(expanded_right_edge - expanded_left_edge, 1)

        if box_w <= 0:
            print(f"  -> Warning: invalid expanded width for box {cid_counter}. Skipping.")
            continue

        # --- LOCAL BOUNDING LOGIC FOR Y-COORDINATES ---
        small_left = int(expanded_left_edge / scale_x)
        small_right = int(expanded_right_edge / scale_x)

        small_left = max(0, small_left)
        small_right = min(small_width, small_right)

        # CHANGE HERE: Use the mask with vertical lines subtracted!
        box_slice = text_mask_no_lines[:, small_left:small_right]

        if box_slice.size == 0:
            # Fallback if empty: Snap to the black lines
            local_box_y = round(large_top_line_y, 1)
            local_box_h = round(large_bottom_line_y - large_top_line_y, 1)
        else:
            horizontal_projection = np.sum(box_slice, axis=1)

            if np.max(horizontal_projection) > 0:
                row_y_coords = np.where(horizontal_projection > np.max(horizontal_projection) * 0.05)[0]
            else:
                row_y_coords = []

            if len(row_y_coords) > 0:
                # 1. Find the exact highest and lowest text pixels for THIS specific box
                small_y = row_y_coords[0]
                small_bottom = row_y_coords[-1]

                raw_local_y_large = small_y * scale_y
                raw_local_bottom_large = small_bottom * scale_y

                # 2. Apply your requested padding to the local text bounds
                padding_top = 0
                padding_bottom = 0

                padded_y = max(0.0, raw_local_y_large - padding_top)
                padded_bottom = min(float(large_height), raw_local_bottom_large + padding_bottom)

                local_box_y = round(padded_y, 1)
                local_box_h = round(padded_bottom - padded_y, 1)
            else:
                # Fallback if empty: Snap to the black lines
                local_box_y = round(large_top_line_y, 1)
                local_box_h = round(large_bottom_line_y - large_top_line_y, 1)
        # ----------------------------------------------

        new_boxes.append({
            "x": box_x,
            "y": local_box_y,
            "w": box_w,
            "h": local_box_h,
            "cid": cid_counter,
            "added": True,
        })

        if global_y == 0:
            global_y = local_box_y
            global_h = local_box_h

        cid_counter += 1

    # 7. Update JSON and Save (try DB update first, fallback to JSON file)
    json_data["images"].extend(new_boxes)

    updated = _update_db_pages(json_data, new_boxes)
    if updated:
        print(f"Successfully pushed {len(new_boxes)} boxes to DB for page {json_data.get('name')}")

    # 8. Memory Management
    print("Dumping RAM and running garbage collection...")
    del img_small
    del text_mask
    del vertical_projection
    gc.collect()
    
    print("--- Done! ---")


def get_s_img_img_path(name):
    """ 获取字图的路径
    """

    md5 = hp.md5_encode(name)
    inner_path = '/'.join(name.split('_')[:-1])
    page_name = '%s_%s.%s' % (name, md5, 'jpg') # QL_9000_213_f118aa2a8b72122d868bd152a2ce70c1.jpg

    img_path = path.join("/nas/web-static/customer/cowork/pages", inner_path, page_name)

    return img_path


def _update_db_pages(json_data, new_boxes):
    """Try to push `new_boxes` into the corresponding `page` document in DB.
    Falls back to returning False if no matching page found.
    """
    try:
        db = hp.get_db('tw-cowork')
    except Exception as e:
        print(f"Could not connect to DB: {e}")
        return False

    # Try several common keys to locate the page document
    page_name = json_data.get('name') or json_data.get('ouid') or json_data.get('page_name')
    if not page_name:
        return False

    q = {'name': page_name}
    doc = db.page.find_one(q)
    if not doc:
        return False

    processed = []
    for b in new_boxes:
        nb = dict(b)  # shallow copy
        log = {
            'op': 'added',
            'pos': {'x': nb.get('x'), 'y': nb.get('y'), 'w': nb.get('w'), 'h': nb.get('h')},
            'user_id': ObjectId("000000000000000000000000"),  # Placeholder ID
            'username': 'script',
            'create_time': datetime.now(),
        }

        nb.setdefault('box_logs', []).append(log)
        processed.append(nb)

    res = db.page.update_one(q, {'$push': {'images': {'$each': processed}}})
    print(f"DB update matched={res.matched_count} modified={res.modified_count}")
    return True

def delete_script_boxes(page_name="QL_9000_213"):
    """Remove images from the page where any box_logs entry has username 'script'.

    Returns: number of images removed (0 if none), or -1 on DB error.'
    """
    try:
        db = hp.get_db('tw-cowork')
    except Exception as e:
        print(f"Could not connect to DB: {e}")
        return -1

    q = {'name': page_name}
    doc = db.page.find_one(q, {'images': 1})
    if not doc:
        print(f"Page not found: {page_name}")
        return 0

    images = doc.get('images', [])
    before = len(images)

    # Count images that have any box_log with username 'script'
    def has_script(img):
        for log in img.get('box_logs', []):
            if log.get('username') == 'script':
                return True
        return False

    to_remove = [img for img in images if has_script(img)]
    removed_count = len(to_remove)

    print(f"Found {removed_count} images to remove (page={page_name}).")

    # Safer server-side removal: set images to filtered list
    kept = [img for img in images if not has_script(img)]
    res = db.page.update_one(q, {'$set': {'images': kept}})
    print(f"DB update matched={res.matched_count} modified={res.modified_count}. Removed={removed_count}")
    return removed_count

def test_crop_between_lines(image_path, output_path="cropped_test.jpg"):
    print(f"\n--- Testing Line Detection and Cropping ---")
    print(f"Loading image: {image_path}")
    
    # 1. Load the image in grayscale
    img = cv2.imread(image_path, 0)
    if img is None:
        print(f"Error: Could not load image from {image_path}")
        return

    height, width = img.shape
    print(f"Original image size: {width}x{height}")

    # 2. Thresholding: Make dark ink white (255), and background black (0)
    _, ink_mask = cv2.threshold(img, 120, 255, cv2.THRESH_BINARY_INV)

    # 3. Morphology: Create a wide kernel to isolate long horizontal lines
    # We make it 5% of the image width to ignore text characters
    kernel_width = max(10, int(width * 0.05)) 
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1))
    
    # MORPH_OPEN erases anything that isn't a long horizontal line
    lines_only = cv2.morphologyEx(ink_mask, cv2.MORPH_OPEN, horizontal_kernel)

    # 4. Projection: Sum the pixels horizontally to find the peaks
    horizontal_projection = np.sum(lines_only, axis=1)
    
    # Define a peak as having at least 30% of the maximum line's intensity
    peak_threshold = np.max(horizontal_projection) * 0.3
    line_y_coords = np.where(horizontal_projection > peak_threshold)[0]

    if len(line_y_coords) < 2:
        print("Error: Could not detect at least two distinct horizontal lines.")
        return

    # 5. Get the Top and Bottom bounds
    top_line_y = line_y_coords[0]
    bottom_line_y = line_y_coords[-1]
    
    print(f"Detected Top Line at Y: {top_line_y}")
    print(f"Detected Bottom Line at Y: {bottom_line_y}")

    # Step 3 pixels inside the lines to cut out the black border itself
    safe_top = top_line_y + 3
    safe_bottom = bottom_line_y - 3

    # 6. Crop the original image
    cropped_img = img[safe_top:safe_bottom, :]
    print(f"Cropped image size: {cropped_img.shape[1]}x{cropped_img.shape[0]}")

    # 7. Save to verify visually
    cv2.imwrite(output_path, cropped_img)
    print(f"Saved cropped image to: {output_path}")
    print("--- Done! Please check the output image. ---")

# ==========================================
# EXECUTION BLOCK (Server Config)
# ==========================================
if __name__ == "__main__":
    # Default behavior: process all pages in DB with source == 'QL'
    def run_for_db_pages():
        try:
            db = hp.get_db('tw-cowork')
        except Exception as e:
            print(f"Could not connect to DB: {e}")
            return

        # query = {'source': 'QL'}
        query = {'name': 'QL_9000_213'}
        cursor = db.page.find(query, {'name': 1, 'width': 1, 'height': 1, 'images': 1})
        count = 0
        for page in cursor:
            page_name = page.get('name')
            if not page_name:
                continue
            small_img = get_s_img_img_path(page_name)
            if not path.exists(small_img):
                print(f"Small image not found for {page_name}: {small_img}")
                continue

            print(f"Processing page {page_name} using small image {small_img}")
            # generate_scroll_boxes(small_img, page, output_json_path=f"{page_name}_ql_updated.json")
            test_crop_between_lines(small_img)
            count += 1

        print(f"Processed {count} pages from DB (source=QL)")

    # delete_script_boxes("QL_9000_213")
    run_for_db_pages()