import json
from datetime import datetime
from bson import ObjectId
import helper as hp

def generate_scroll_boxes_math(json_data, leaf_width, default_text_y, default_text_height):
    print(f"\n--- Starting Pure Math Processing for: {json_data.get('name')} ---")

    # Get original dimensions
    large_width = json_data.get("width")
    large_height = json_data.get("height")
    
    if not large_width or not large_height:
        print("Error: JSON must contain both 'width' and 'height' fields.")
        return

    existing_boxes = json_data.get("images", [])

    # 1 Leaf = 5 columns + 1 seam gap
    core_leaves = 5
    core_width = leaf_width * core_leaves # 5 leaves = exactly 25 columns
    padding_width = (leaf_width / 5.0) - 20 # 1/5th of a leaf is roughly 1 column
    
    # 1. Determine Starting Coordinates (Right-to-Left) and Dynamic Y
    if existing_boxes:
        start_box = existing_boxes[-1] 
        starting_x_large = start_box["x"]
        cid_counter = max([box["cid"] for box in existing_boxes]) + 1
        
        # --- DYNAMIC Y & HEIGHT FROM EXISTING BOX ---
        text_y = float(start_box.get("y", default_text_y))
        text_height = float(start_box.get("h", default_text_height))
        print(f"-> Found existing boxes! Inheriting Y: {text_y} and Height: {text_height}")
        
    else:
        starting_x_large = float(large_width) 
        cid_counter = 1
        
        # --- NEW: VERTICAL CENTERING FALLBACK ---
        text_height = float(default_text_height)
        
        # Calculate 'a' margin: (Total Height - Text Height) / 2
        a_margin = (float(large_height) - text_height) / 2.0
        
        # Ensure 'y' isn't negative just in case text_height > large_height
        text_y = max(0.0, round(a_margin, 1))
        
        print(f"-> No existing boxes. Vertically centering! Calculated Y: {text_y} based on Height: {text_height}")
    
    new_boxes = []
    current_x = starting_x_large

    print(f"-> Single Leaf Width (5 cols + gap): {leaf_width}px")
    print(f"-> Core Box Step (25 cols): {core_width}px")
    print("Calculating boxes...")

    # 3. Loop Right-to-Left until we run out of image
    while current_x - core_width >= 0:
        
        # Calculate the absolute edges of the 25-column core
        core_right = current_x
        if existing_boxes and cid_counter == max([box["cid"] for box in existing_boxes]) + 1:
            core_left = current_x - core_width + padding_width
        else:
            core_left = current_x - core_width
        
        # Add the ~1-column padding to the left and right
        if existing_boxes and cid_counter == max([box["cid"] for box in existing_boxes]) + 1:
            # For the very first box (if existing), only pad the left side to avoid overlap
            padded_right = core_right
        else:
            padded_right = min(float(large_width), core_right + padding_width)
        padded_left = max(0.0, core_left - padding_width)
        
        box_w = padded_right - padded_left
        box_x = padded_left
        
        new_boxes.append({
            "x": round(box_x, 1),
            "y": float(text_y),
            "w": round(box_w, 1),
            "h": float(text_height),
            "cid": cid_counter,
            "added": True,
        })
        
        # Step the current_x leftward by exactly the core width
        current_x = core_left + padding_width 
        cid_counter += 1
        
    # 4. Catch the remaining leftover columns at the far left edge
    if current_x > 0:
        padded_right = min(float(large_width), current_x + padding_width)
        padded_left = 0.0
        
        box_w = padded_right - padded_left
        box_x = padded_left
        
        new_boxes.append({
            "x": round(box_x, 1),
            "y": float(text_y),
            "w": round(box_w, 1),
            "h": float(text_height),
            "cid": cid_counter,
            "added": True,
        })

    # 5. Update JSON and Save to DB
    if "images" not in json_data:
        json_data["images"] = []
    json_data["images"].extend(new_boxes)

    updated = _update_db_pages(json_data, new_boxes)
    if updated:
        print(f"Successfully pushed {len(new_boxes)} pure-math boxes to DB for {json_data.get('name')}!")
    
    print("--- Done! ---")


# ==========================================
# DB HELPER FUNCTIONS (Untouched)
# ==========================================

def _update_db_pages(json_data, new_boxes):
    try:
        db = hp.get_db('tw-cowork')
    except Exception as e:
        print(f"Could not connect to DB: {e}")
        return False

    page_name = json_data.get('name') or json_data.get('ouid') or json_data.get('page_name')
    if not page_name:
        return False

    q = {'name': page_name}
    doc = db.page.find_one(q)
    if not doc:
        return False

    processed = []
    for b in new_boxes:
        nb = dict(b)  
        log = {
            'op': 'added',
            'pos': {'x': nb.get('x'), 'y': nb.get('y'), 'w': nb.get('w'), 'h': nb.get('h')},
            'user_id': ObjectId("000000000000000000000000"),  
            'username': 'script',
            'create_time': datetime.now(),
        }

        nb.setdefault('box_logs', []).append(log)
        processed.append(nb)

    res = db.page.update_one(q, {'$push': {'images': {'$each': processed}}})
    print(f"DB update matched={res.matched_count} modified={res.modified_count}")
    return True

def delete_script_boxes(page_name="QL_9000_213"):
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
    
    def has_script(img):
        for log in img.get('box_logs', []):
            if log.get('username') == 'script':
                return True
        return False

    to_remove = [img for img in images if has_script(img)]
    removed_count = len(to_remove)

    print(f"Found {removed_count} images to remove (page={page_name}).")

    kept = [img for img in images if not has_script(img)]
    res = db.page.update_one(q, {'$set': {'images': kept}})
    print(f"DB update matched={res.matched_count} modified={res.modified_count}. Removed={removed_count}")
    return removed_count

small = ['QL_9000_97',
'QL_9000_96',
'QL_9000_3756',
'QL_9000_3755',
'QL_9000_3754',
'QL_9000_3753',
'QL_9000_3752',
'QL_9000_3751',
'QL_9000_3750',
'QL_9000_3749',
'QL_9000_3748',
'QL_9000_3747',
'QL_9000_3746',
'QL_9000_3745',
'QL_9000_3744',
'QL_9000_3743',
'QL_9000_3599',
'QL_9000_3598',
'QL_9000_3597',
'QL_9000_3596',
'QL_9000_3595',
'QL_9000_3594',
'QL_9000_3592',
'QL_9000_3591',
'QL_9000_3590',
'QL_9000_3589',
'QL_9000_3588',
'QL_9000_3587',
'QL_9000_3586',
'QL_9000_3585',
'QL_9000_3584',
'QL_9000_3489',
'QL_9000_3488',
'QL_9000_3487',
'QL_9000_3486',
'QL_9000_3485',
'QL_9000_3484',
'QL_9000_3483',
'QL_9000_3481',
'QL_9000_3480',
'QL_9000_3479',
'QL_9000_3478',
'QL_9000_3477',
'QL_9000_3476',
'QL_9000_3475',
'QL_9000_3474',
'QL_9000_3473',
'QL_9000_3280',
'QL_9000_3279',
'QL_9000_3278',
'QL_9000_3277',
'QL_9000_3276',
'QL_9000_3275',
'QL_9000_3274',
'QL_9000_3273',
'QL_9000_3272',
'QL_9000_3271',
'QL_9000_3270',
'QL_9000_3269',
'QL_9000_3268',
'QL_9000_3267',
'QL_9000_3266',
'QL_9000_3265',
'QL_9000_3264',
'QL_9000_3263',
'QL_9000_3262',
'QL_9000_3261',
'QL_9000_3260',
'QL_9000_3254',
'QL_9000_3253',
'QL_9000_3252',
'QL_9000_3251',
'QL_9000_3250',
'QL_9000_3249',
'QL_9000_3248',
'QL_9000_3247',
'QL_9000_3246',
'QL_9000_3245',
'QL_9000_3244',
'QL_9000_3243',
'QL_9000_3242',
'QL_9000_3241',
'QL_9000_3240',
'QL_9000_3239',
'QL_9000_2527',
'QL_9000_2526',
'QL_9000_2525',
'QL_9000_2524',
'QL_9000_2523',
'QL_9000_2522',
'QL_9000_2521',
'QL_9000_2520',
'QL_9000_2519',
'QL_9000_2518',
'QL_9000_2517',
'QL_9000_2516',
'QL_9000_2515',
'QL_9000_2514',
'QL_9000_2513',
'QL_9000_2512',
'QL_9000_2511',
'QL_9000_2510',
'QL_9000_2509',
'QL_9000_2508',
'QL_9000_2507',
'QL_9000_2506',
'QL_9000_2505',
'QL_9000_2504',
'QL_9000_2503',
'QL_9000_2502',
'QL_9000_2501',
'QL_9000_2500',
'QL_9000_2499',
'QL_9000_2498',
'QL_9000_2497',
'QL_9000_2496',
'QL_9000_2495',
'QL_9000_2494',
'QL_9000_2493',
'QL_9000_2492',
'QL_9000_2252',
'QL_9000_2251',
'QL_9000_2250',
'QL_9000_2249',
'QL_9000_2248',
'QL_9000_2247',
'QL_9000_2246',
'QL_9000_2245',
'QL_9000_2244',
'QL_9000_2243',
'QL_9000_2242',
'QL_9000_2241',
'QL_9000_2240',
'QL_9000_2239',
'QL_9000_2238',
'QL_9000_2237',
'QL_9000_2236',
'QL_9000_2235',
'QL_9000_2234',
'QL_9000_2174',
'QL_9000_2173',
'QL_9000_2172',
'QL_9000_2171',
'QL_9000_2170',
'QL_9000_2133',
'QL_9000_2132',
'QL_9000_2131',
'QL_9000_2130',
'QL_9000_2129',
'QL_9000_2128',
'QL_9000_2127',
'QL_9000_2126',
'QL_9000_2125',
'QL_9000_2124',
'QL_9000_2123',
'QL_9000_2122',
'QL_9000_2121',
'QL_9000_2120',
'QL_9000_2119',
'QL_9000_2118',
'QL_9000_2117',
'QL_9000_2116',
'QL_9000_2115',
'QL_9000_2070',
'QL_9000_1978',
'QL_9000_1977',
'QL_9000_1976',
'QL_9000_1732',
'QL_9000_1720',
'QL_9000_1719',
'QL_9000_1718',
'QL_9000_1717',
'QL_9000_1716',
'QL_9000_1715',
'QL_9000_1714',
'QL_9000_1713',
'QL_9000_1712',
'QL_9000_1711',
'QL_9000_1710',
'QL_9000_1709',
'QL_9000_1708',
'QL_9000_1707',
'QL_9000_1706',
'QL_9000_1705',
'QL_9000_1704',
'QL_9000_1703',
'QL_9000_1702',
'QL_9000_1378',
'QL_9000_1037',
'QL_9000_1036',
'QL_9000_1035',
'QL_9000_1034',
'QL_9000_1033',
'QL_9000_1032',
'QL_9000_1031',
'QL_9000_1030',
'QL_9000_1029',
'QL_9000_1028',
'QL_9000_1027',
'QL_9000_1026',
'QL_9000_1025',
'QL_9000_1024',
'QL_9000_1023',
'QL_9000_1022',
'QL_9000_1021',
'QL_9000_1020',
'QL_9000_1019',
'QL_9000_1018',
'QL_9000_1017',
'QL_9000_3482',
'QL_9000_3593',
]

# ==========================================
# EXECUTION BLOCK (Server Config)
# ==========================================
if __name__ == "__main__":
    def run_for_db_pages():
        try:
            db = hp.get_db('tw-cowork')
        except Exception as e:
            print(f"Could not connect to DB: {e}")
            return

        # query = {'name': 'QL_9000_2984'}
        query = {'source': 'QL'}
        cursor = db.page.find(query, {'name': 1, 'width': 1, 'height': 1, 'images': 1})
        count = 0
        
        # =========================================================
        # REFERENCE DOCUMENT DIMENSIONS (Based on QL_9000_213)
        # =========================================================
        REF_HEIGHT = 2560.0
        
        BASE_LEAF_WIDTH = 585.0 
        BASE_TEXT_HEIGHT = 1474.7 
        BASE_TEXT_Y_FALLBACK = 567.2 
        # =========================================================

        for page in cursor:
            page_name = page.get('name')
            if not page_name or page_name in small:
                continue
                
            existing_boxes = page.get("images", [])
            
            # 1. Find the True Optical Scale (Uniform Scaling)
            if existing_boxes:
                # If a human drew a box, their box height is the ultimate truth for DPI/Zoom
                human_height = float(existing_boxes[0].get("h", BASE_TEXT_HEIGHT))
                true_scale = human_height / BASE_TEXT_HEIGHT
            else:
                # Fallback to the page height ratio if no boxes exist
                page_height = float(page.get('height', REF_HEIGHT))
                true_scale = page_height / REF_HEIGHT

            # 2. Apply the SAME scale multiplier to everything
            dynamic_leaf_width = BASE_LEAF_WIDTH * true_scale
            dynamic_text_height = BASE_TEXT_HEIGHT * true_scale
            dynamic_text_y = BASE_TEXT_Y_FALLBACK * true_scale
            
            # print(f"Processing {page_name} - True Scale: {true_scale:.2f}x")

            # delete_script_boxes(page_name)
            
            # 3. Pass the uniformly scaled variables into the math function
            generate_scroll_boxes_math(
                page, 
                dynamic_leaf_width, 
                dynamic_text_y, 
                dynamic_text_height
            )
            count += 1

        print(f"Processed {count} pages from DB")

    run_for_db_pages()