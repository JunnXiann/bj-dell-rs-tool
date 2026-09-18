#!/bin/bash
SCRIPT_DIR=$(pwd)   # 保存脚本执行时的初始工作目录
LOG_FILE="too_long.log"
TARGET_DIR="/mnt/disk2_raid5/wuxiu_data/too_long_path"
RECORD_FILE="$SCRIPT_DIR/copy_record.log"  # 使用绝对路径，防止写到改名的相对路径

while IFS= read -r path; do
    # 判断路径是否存在
    if [ ! -e "$path" ]; then
        echo "路径不存在: $path"
        continue
    fi

    # 判断是目录还是文件
    if [ -d "$path" ]; then
        # 目录处理
        PARENT_DIR=$(dirname "$path")
        BASENAME=$(basename "$path")
        SHORTNAME="dir_$(date +%s%N)"  # 生成短名，可以自定义规则

        cd "$PARENT_DIR" || { echo "cd失败: $PARENT_DIR"; continue; }

        # 获取 inode
        # INODE=$(ls -i | awk -v name="$BASENAME" '$2==name {print $1}')
	    INODE=$(ls -i | awk -v name="$BASENAME" '$0 ~ name {print $1}')
        if [ -z "$INODE" ]; then
            echo "未找到 inode: $path"
            continue
        fi

        # 使用 inode 拷贝目录
        find . -maxdepth 1 -inum "$INODE" -exec cp -rp  -- '{}' "$TARGET_DIR/$SHORTNAME" \;
        # 使用 inode 改名
        # find . -maxdepth 1 -inum "$INODE" -exec mv {} "$SHORTNAME" \;
        # 拷贝到目标目录
        # cp -r "$SHORTNAME" "$TARGET_DIR/"

        # 记录原始路径
        echo "$TARGET_DIR/$SHORTNAME -> $path" >> "$RECORD_FILE"

    elif [ -f "$path" ]; then
        # 文件处理
        PARENT_DIR=$(dirname "$path")
        BASENAME=$(basename "$path")
        SHORTNAME="file_$(date +%s%N)"  # 可以保留原扩展名
        EXT="${BASENAME##*.}"
        SHORTNAME="$SHORTNAME.$EXT"

        cd "$PARENT_DIR" || { echo "cd失败: $PARENT_DIR"; continue; }

        INODE=$(ls -i | awk -v name="$BASENAME" '$0 ~ name {print $1}')
        if [ -z "$INODE" ]; then
            echo "未找到 inode: $path"
            continue
        fi

        find . -maxdepth 1 -inum "$INODE" -exec cp -p  -- '{}' "$TARGET_DIR/$SHORTNAME" \;
        # find . -maxdepth 1 -inum "$INODE" -exec mv {} "$SHORTNAME" \;
        # cp "$SHORTNAME" "$TARGET_DIR/"

        echo "$TARGET_DIR/$SHORTNAME -> $path" >> "$RECORD_FILE"

    else
        echo "未知类型: $path"
    fi

done < "$LOG_FILE"

