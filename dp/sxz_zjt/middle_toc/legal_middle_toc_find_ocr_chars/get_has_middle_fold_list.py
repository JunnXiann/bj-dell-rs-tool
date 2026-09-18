import json


def get_error_middle_toc_list():

    has_middle_toc_list = []
    file_order_list = [1, 3, 4]
    for i in file_order_list:
        with open(f"has_middle_toc_fold_id_list_{i}.json", "r") as f:
            tmp_list = json.loads(f.read())
            has_middle_toc_list.extend(tmp_list)
    print(len(has_middle_toc_list))


get_error_middle_toc_list()


