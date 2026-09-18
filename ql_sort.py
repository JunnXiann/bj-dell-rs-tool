import os
import json
import argparse
from datetime import datetime

import helper as hp
from bson import ObjectId

fix_list = ['QL_9000_2059',
'QL_9000_2074',
'QL_9000_2140',
'QL_9000_2150',
'QL_9000_2183',
'QL_9000_2188',
'QL_9000_2193',
'QL_9000_2194',
'QL_9000_2197',
'QL_9000_2204',
'QL_9000_2254',
'QL_9000_2256',
'QL_9000_2257',
'QL_9000_226',
'QL_9000_2273',
'QL_9000_2278',
'QL_9000_2298',
'QL_9000_2303',
'QL_9000_2336',
'QL_9000_2360',
'QL_9000_237',
'QL_9000_2390',
'QL_9000_2398',
'QL_9000_2401',
'QL_9000_2410',
'QL_9000_2412',
'QL_9000_2439',
'QL_9000_2447',
'QL_9000_2456',
'QL_9000_246',
'QL_9000_2475',
'QL_9000_25',
'QL_9000_2528',
'QL_9000_2535',
'QL_9000_2542',
'QL_9000_2567',
'QL_9000_2643',
'QL_9000_2655',
'QL_9000_2678',
'QL_9000_2695',
'QL_9000_2696',
'QL_9000_2700',
'QL_9000_2705',
'QL_9000_2706',
'QL_9000_2753',
'QL_9000_279',
'QL_9000_2837',
'QL_9000_2846',
'QL_9000_2857',
'QL_9000_2865',
'QL_9000_2880',
'QL_9000_2902',
'QL_9000_2920',
'QL_9000_2924',
'QL_9000_296',
'QL_9000_2975',
'QL_9000_2981',
'QL_9000_2992',
'QL_9000_2998',
'QL_9000_3001',
'QL_9000_3024',
'QL_9000_3029',
'QL_9000_3035',
'QL_9000_3037',
'QL_9000_3055',
'QL_9000_3064',
'QL_9000_3071',
'QL_9000_3072',
'QL_9000_3073',
'QL_9000_310',
'QL_9000_3100',
'QL_9000_3107',
'QL_9000_3121',
'QL_9000_3130',
'QL_9000_3139',
'QL_9000_3156',
'QL_9000_3160',
'QL_9000_3182',
'QL_9000_3190',
'QL_9000_3192',
'QL_9000_3194',
'QL_9000_3222',
'QL_9000_3229',
'QL_9000_3292',
'QL_9000_330',
'QL_9000_331',
'QL_9000_3322',
'QL_9000_3335',
'QL_9000_3338',
'QL_9000_3365',
'QL_9000_3374',
'QL_9000_3382',
'QL_9000_340',
'QL_9000_3405',
'QL_9000_3415',
'QL_9000_3421',
'QL_9000_3446',
'QL_9000_3501',
'QL_9000_3535',
'QL_9000_3547',
'QL_9000_3553',
'QL_9000_3557',
'QL_9000_3559',
'QL_9000_3566',
'QL_9000_3571',
'QL_9000_3577',
'QL_9000_3612',
'QL_9000_3624',
'QL_9000_3630',
'QL_9000_3644',
'QL_9000_3649',
'QL_9000_3671',
'QL_9000_3712',
'QL_9000_3740',
'QL_9000_3764',
'QL_9000_3797',
'QL_9000_390',
'QL_9000_396',
'QL_9000_412',
'QL_9000_418',
'QL_9000_419',
'QL_9000_42',
'QL_9000_423',
'QL_9000_440',
'QL_9000_443',
'QL_9000_45',
'QL_9000_459',
'QL_9000_486',
'QL_9000_496',
'QL_9000_500',
'QL_9000_512',
'QL_9000_519',
'QL_9000_537',
'QL_9000_564',
'QL_9000_596',
'QL_9000_653',
'QL_9000_665',
'QL_9000_687',
'QL_9000_722',
'QL_9000_74',
'QL_9000_740']

repair = ['QL_9000_3470', 'QL_9000_3561', 'QL_9000_2886']

def is_deleted(box):
    val = box.get('deleted')
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).lower() in ('1', 'true', 'yes')


def _json_default(o):
    if isinstance(o, ObjectId):
        return str(o)
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)

def deduplicate_exact_boxes(images):
    """
    Filters a list of dictionaries, keeping only the first occurrence 
    of absolutely identical boxes.
    """
    if not images:
        return []

    seen_signatures = set()
    unique_images = []

    for img in images:
        # Convert the entire dictionary into a sorted JSON string.
        # sort_keys=True ensures key order doesn't cause false mismatches.
        # default=str ensures MongoDB types (ObjectId, datetime) don't crash the JSON encoder.
        img_signature = json.dumps(img, sort_keys=True, default=str)
        
        if img_signature not in seen_signatures:
            seen_signatures.add(img_signature)
            unique_images.append(img)
        else:
            # Optional: Print what is being removed for your own logging
            print(f"Removed exact duplicate for CID: {img.get('cid')}")

    return unique_images

def clear_db_box_names(query=None):
    """
    Directly updates MongoDB to strip 'name' from all boxes where 'deleted' is not true.
    """
    try:
        db = hp.get_db('tw-cowork')
    except Exception as e:
        print(f"Could not connect to DB: {e}")
        return 1

    if query is None:
        query = {'source': 'QL'}

    try:
        # This MongoDB update removes the 'name' field from elements in the 'images' array 
        # EXCEPT where 'deleted' is true, 1, or 'yes'.
        res = db.page.update_many(
            query,
            {'$unset': {'images.$[elem].name': ""}},
            array_filters=[{
                '$and': [
                    {'elem.deleted': {'$ne': True}},
                    {'elem.deleted': {'$ne': 1}},
                    {'elem.deleted': {'$ne': '1'}},
                    {'elem.deleted': {'$ne': 'true'}},
                    {'elem.deleted': {'$ne': 'yes'}},
                    {'elem.deleted': {'$ne': 'True'}},
                ]
            }]
        )
        print(f"Matched {res.matched_count} pages. Modified {res.modified_count} pages.")
        return 0
    except Exception as e:
        print(f"Database operation failed: {e}")
        return 1

def remove_duplicates_from_db(query=None):
    """
    Finds exact duplicates in the 'images' array for each page and updates the DB to remove them.
    """
    try:
        db = hp.get_db('tw-cowork')
    except Exception as e:
        print(f"Could not connect to DB: {e}")
        return 1

    if query is None:
        query = {'source': 'QL'}

    # We only need _id, name, and images to process this
    cursor = db.page.find(query, {'name': 1, 'images': 1})
    
    pages_checked = 0
    pages_modified = 0
    total_duplicates_removed = 0

    for page in cursor:
        pages_checked += 1
        page_id = page.get('_id')
        page_name = page.get('name', 'Unknown Page')
        raw_images = page.get('images', [])

        if not raw_images:
            continue

        # Use your existing deduplication logic
        unique_images = deduplicate_exact_boxes(raw_images)

        # If the lengths differ, we found and removed duplicates
        if len(unique_images) < len(raw_images):
            removed_count = len(raw_images) - len(unique_images)
            total_duplicates_removed += removed_count
            
            try:
                # Overwrite the images array with the deduplicated version
                res = db.page.update_one(
                    {'_id': page_id},
                    {'$set': {'images': unique_images}}
                )
                if res.modified_count:
                    pages_modified += 1
                    print(f"Updated '{page_name}': Removed {removed_count} duplicate boxes.")
            except Exception as e:
                print(f"Failed to update DB for page '{page_name}': {e}")

    print("-" * 30)
    print(f"Deduplication Complete!")
    print(f"Pages checked: {pages_checked}")
    print(f"Pages modified: {pages_modified}")
    print(f"Total duplicate boxes removed: {total_duplicates_removed}")
    
    return 0

def process_and_update_pages(query=None):
    """
    Fetches pages, sorts active boxes, applies names, 
    and saves the cleaned array directly back to MongoDB.
    """
    try:
        db = hp.get_db('tw-cowork')
    except Exception as e:
        print(f"Could not connect to DB: {e}")
        return 1

    if query is None:
        query = {'source': 'QL'}

    # We only need the fields required for the update logic
    cursor = db.page.find(query, {'name': 1, 'images': 1})

    pages_processed = 0
    pages_updated = 0

    for page in cursor:
        page_name = page.get('name')
        if not page_name:
            continue

        images = page.get('images', []) or []
        
        # 1. Separate active and deleted boxes
        deleted = []
        active = []
        for img in images:
            if is_deleted(img):
                deleted.append(img)
            else:
                active.append(img)

        # 2. Sort active boxes right-to-left
        def x_key(b):
            try:
                return float(b.get('x', 0))
            except Exception:
                return 0.0

        active_sorted = sorted(active, key=x_key, reverse=True)

        # 3. Assign positional names
        for i, box in enumerate(active_sorted, start=1):
            box['name'] = f"{page_name}_{i}"

        # 4. Rebuild images array mapping active back to original spots where possible
        cid_to_box = {b.get('cid'): b for b in active_sorted if b.get('cid') is not None}
        new_images = []
        used_cids = set()

        for img in images:
            if is_deleted(img):
                new_images.append(img)
            else:
                cid = img.get('cid')
                if cid in cid_to_box:
                    new_images.append(cid_to_box[cid])
                    used_cids.add(cid)
                else:
                    # Fallback if cid is missing/mismatched
                    if active_sorted:
                        nb = active_sorted.pop(0)
                        new_images.append(nb)
                        if nb.get('cid') is not None:
                            used_cids.add(nb.get('cid'))
                    else:
                        new_images.append(img)

        # Append remaining unplaced boxes
        # -- BUG FIX APPLIED HERE: Validate against used_cids --
        for nb in active_sorted:
            cid = nb.get('cid')
            if cid not in used_cids:
                new_images.append(nb)
                if cid is not None:
                    used_cids.add(cid)

        # 5. Push the clean array back to MongoDB
        try:
            res = db.page.update_one(
                {'_id': page.get('_id')},
                {'$set': {'images': new_images}}
            )
            if res.modified_count:
                pages_updated += 1
        except Exception as e:
            print(f"Failed to update page {page_name}: {e}")

        pages_processed += 1

    # Final summary metrics
    print("-" * 30)
    print("Database Pipeline Complete")
    print("-" * 30)
    print(f"Pages processed:         {pages_processed}")
    print(f"Pages modified in DB:    {pages_updated}")

    return 0

def export_pages_to_json(query=None, outdir='exported_pages_fix4.0'):
    """
    Fetches documents from the database and exports each as a separate JSON file.
    """
    os.makedirs(outdir, exist_ok=True)
    try:
        db = hp.get_db('tw-cowork')
    except Exception as e:
        print(f"Could not connect to DB: {e}")
        return 1

    if query is None:
        query = {'name': {'$in': repair}}

    # Fetch the full document (no field projection limitation here)
    cursor = db.page.find(query)

    count = 0
    for page in cursor:
        page_name = page.get('name')
        
        # Fallback if a document somehow doesn't have a name
        if not page_name:
            page_name = str(page.get('_id', f'unknown_doc_{count}'))

        # Sanitize filename to prevent OS path issues
        safe_name = str(page_name).replace('/', '_').replace('\\', '_')
        out_path = os.path.join(outdir, f"{safe_name}.json")
        
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(page, f, ensure_ascii=False, indent=2, default=_json_default)
        
        count += 1

    print("-" * 30)
    print("Export Complete")
    print("-" * 30)
    print(f"Total pages exported: {count}")
    print(f"Saved to directory:   {os.path.abspath(outdir)}")
    print()

    return 0

def main():

    # parser = argparse.ArgumentParser(description='Sort boxes by x (right-to-left), name them, and export JSON')
    
    # parser.add_argument('--outdir', '-o', default='exported_pages', help='Directory to write exported JSON')
    # parser.add_argument('--query', '-q', default=None, help='MongoDB query as JSON string (default: {"source":"QL"})')
    # parser.add_argument('--write-db', action='store_true', help='If set, write the renamed images back into the DB')

    # args = parser.parse_args()

    # query = None
    # if args.query:
    #     try:
    #         query = json.loads(args.query)
    #     except Exception as e:
    #         print(f"Invalid JSON for --query: {e}")
    #         return 2

    # return export_pages(query=query, outdir=args.outdir, write_db=args.write_db)
    export_pages_to_json()
    # for name in fix_list:
    #     process_and_update_pages({"name": name})


if __name__ == '__main__':
    raise SystemExit(main())
