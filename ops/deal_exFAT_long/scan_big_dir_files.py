import os
from openpyxl import Workbook


def scan_and_write(root_dir, output_prefix="file_list", max_rows=500000):
    """
    扫描文件夹并将结果写入 Excel
    每个 Excel 文件最多写 max_rows 行（包含表头），超过后自动生成新文件。
    经查询，Excel 对单个工作表的行数限制为 1,048,576 行，太大会卡顿，因此默认上限为50万行
    """
    file_index = 1
    row_count = 0

    def new_workbook():
        wb = Workbook()
        ws = wb.active
        ws.title = "Files"
        ws.append(["目录", "文件名"])  # 表头
        return wb, ws, 1  # 从第 1 行（表头）开始

    wb, ws, row_count = new_workbook()
    output_file = f"{output_prefix}_{file_index}.xlsx"

    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            ws.append([dirpath, filename])
            row_count += 1

            if row_count >= max_rows:  # 达到行数限制，保存并换新文件
                wb.save(output_file)
                print(f"保存完成: {output_file} ({row_count} 行)")
                file_index += 1
                wb, ws, row_count = new_workbook()
                output_file = f"{output_prefix}_{file_index}.xlsx"

    # 保存最后一个文件
    wb.save(output_file)
    print(f"保存完成: {output_file} ({row_count} 行)")
    print(f"任务完成：共生成 {file_index} 个文件")

if __name__ == "__main__":
    scan_and_write("/mnt/disk2_raid5/wuxiu_data", output_prefix="wuxiu_file_list", max_rows=500000)
