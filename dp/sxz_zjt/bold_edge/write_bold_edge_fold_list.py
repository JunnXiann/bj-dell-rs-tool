import json


def write_bold_edge_fold_list():
    bold_fold_id_list = []
    for i in range(8):
        with open(f"result/{i}.json", "r") as f:
            tmp_list = json.loads(f.read())
            tmp_fold_id_list = [tmp.get("filename")[3: -4] for tmp in tmp_list]
            bold_fold_id_list.extend(tmp_fold_id_list)
    print(bold_fold_id_list)
    print(f"数量=={len(bold_fold_id_list)}")

write_bold_edge_fold_list()



