#!/bin/bash
# 检测目录下所有超过 255 字节的文件/目录名，并输出到文件
# 用法： ./check_long_names.sh /path/to/scan too_long.log

set -euo pipefail

TARGET_DIR="${1:-.}"
OUTPUT_FILE="${2:-too_long.log}"

echo "开始扫描目录: $TARGET_DIR"
echo "结果将保存到: $OUTPUT_FILE"
echo "-----------------------------------"

# 清空输出文件
: > "$OUTPUT_FILE"

COUNT=0

while IFS= read -r FILE; do
    BASENAME=$(basename "$FILE")
    LEN=$(printf "%s" "$BASENAME" | wc -c)

    if [ "$LEN" -gt 255 ]; then
        echo "过长 ($LEN 字节): $FILE"
        echo "$FILE" >> "$OUTPUT_FILE"
        COUNT=$((COUNT+1))
    fi
done < <(find "$TARGET_DIR" -depth)

if [ "$COUNT" -eq 0 ]; then
    echo "没有发现超过 255 字节的文件/目录名"
else
    echo "共发现 $COUNT 个超长文件/目录名，已保存到 $OUTPUT_FILE"
fi

