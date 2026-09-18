check_long_names.sh  
    扫描出所有长度大于255字节的目录名或文件名 保存到too_long.log  
rename_and_copy.sh  
    1.	读取 too_long.log 中的路径列表。  
	2.	检查路径是否存在，区分目录和文件处理。  
	3.	通过 inode 改短名（避免原始名字过长导致操作失败）。  
        •	目录重命名为 dir_时间戳  
        •	文件重命名为 file_时间戳.扩展名  
	4.	拷贝到指定目标目录 /mnt/disk2_raid5/wuxiu_data/too_long_path(根据实际需要修改)  
	5.	记录映射关系到绝对路径的 copy_record.log，格式为 目标路径 -> 原始路径  
  
用法：  
./check_long_names.sh /path/to/scan too_long.log  
./rename_and_copy.sh  
