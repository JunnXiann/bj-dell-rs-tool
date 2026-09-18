import os
import time

# 需要统计的文件扩展名（小写）
TARGET_EXTENSIONS = ['.txt', '.csv', '.json', '.doc', '.docx', '.pdf', '.zip', '.gz', '.rar', '.7z', '.tar',
                     '.xml', '.tsv', '.rtf', '.odt', '.epub', '.uvz', '.pdg', '.html', '.sqlite', '.sqlite3', '.db',
                     '.db3', '.sql', '.mdf', '.bak', '.pdb', '.bson', '.dump', '.rdb']

image_formats = [
    # 主流图片格式
    ".jpg", ".jpeg",  # JPEG 图像（有损压缩）
    ".png",  # PNG 图像（无损，支持透明）
    ".gif",  # GIF 动图/简单动画
    ".webp",  # WebP（Google 推出的高压缩格式）
    ".bmp",  # BMP（位图，无压缩）
    ".tiff", ".tif",  # TIFF（高质量无损，常用于印刷）

    # 矢量图格式
    ".svg",  # SVG（矢量图形）

    # 专业/相机原始格式
    ".raw", ".arw", ".cr2", ".nef", ".dng",  # 相机 RAW 格式
    ".psd",  # Adobe Photoshop 文件
    ".ai",  # Adobe Illustrator 文件
]

video_formats = [
    # 常见视频格式
    ".mp4",  # MPEG-4（最通用）
    ".avi",  # AVI（较老的无损格式）
    ".mov",  # QuickTime（Apple 常用）
    ".mkv",  # Matroska（支持多轨道）
    ".webm",  # WebM（网页视频，VP9 编码）
    ".flv",  # Flash 视频（逐渐淘汰）
    ".wmv",  # Windows Media Video

    # 专业/编辑格式
    ".mpeg", ".mpg",  # MPEG-1/2
    ".m4v",  # Apple MPEG-4 变体
    ".3gp",  # 旧手机视频格式
    ".vob",  # DVD 视频文件
]

audio_formats = [
    # 有损压缩格式
    ".mp3",  # MP3（最通用）
    ".aac",  # AAC（苹果/流媒体常用）
    ".ogg", ".oga",  # Ogg Vorbis（开源格式）
    ".wma",  # Windows Media Audio

    # 无损压缩格式
    ".flac",  # FLAC（无损压缩）
    ".alac",  # Apple Lossless

    # 未压缩格式
    ".wav",  # WAV（PCM 无损）
    ".aiff", ".aif",  # AIFF（苹果无损）

    # 其他
    ".m4a",  # Apple AAC 音频
    ".opus",  # Opus（低延迟，用于语音/流媒体）
    ".mid", ".midi",  # MIDI 音乐指令文件
]

TARGET_EXTENSIONS.extend(image_formats)
TARGET_EXTENSIONS.extend(video_formats)
TARGET_EXTENSIONS.extend(audio_formats)
print(TARGET_EXTENSIONS)


def scan_and_record(drive='E:\\', output_prefix='e_disk_files', max_records=1000000):
    """
    扫描指定磁盘并将文件路径记录到TXT文件
    :param drive: 要扫描的磁盘路径，如'E:\\'
    :param output_prefix: 输出文件前缀
    :param max_records: 每个TXT文件最大记录数
    """
    start_time = time.time()
    file_counter = 0
    file_part = 1
    current_records = 0

    # 创建第一个输出文件
    output_file = f"{output_prefix}_{file_part}.txt"
    f = open(output_file, 'w', encoding='utf-8')
    print(f"创建输出文件: {output_file}")

    print(f"开始扫描 {drive}...")

    for root, dirs, files in os.walk(drive):
        if '$RECYCLE.BIN' in root:
            continue
        print(root)
        for file in files:
            try:
                file_path = os.path.join(root, file)


                # 获取文件扩展名并检查是否在目标列表中
                ext = os.path.splitext(file)[1].lower()
                if ext not in TARGET_EXTENSIONS:
                    continue

                # 获取文件大小并转换为MB
                size_bytes = os.path.getsize(file_path)
                size_mb = size_bytes / (1024 * 1024)  # 转换为MB

                # 写入文件路径
                f.write('%s\t%s\t%s\n' % (file_path, size_mb, ext))
                file_counter += 1
                current_records += 1

                # 每10000条记录显示一次进度
                if file_counter % 10000 == 0:
                    print(f"已扫描 {file_counter} 个文件...")

                # 检查是否达到最大记录数
                if current_records >= max_records:
                    f.close()
                    file_part += 1
                    output_file = f"{output_prefix}_{file_part}.txt"
                    f = open(output_file, 'w', encoding='utf-8')
                    print(f"创建新的输出文件: {output_file}")
                    current_records = 0
            except Exception as e:
                print(f"扫描过程中发生错误: {str(e)}")

        # 每处理完一个目录显示一次进度
        print(f"扫描进度: 已处理 {len(dirs)} 个子目录，找到 {file_counter} 个文件")



    elapsed_time = time.time() - start_time
    print(f"\n扫描完成!")
    print(f"总文件数: {file_counter}")
    print(f"生成文件数: {file_part}")
    print(f"耗时: {elapsed_time:.2f} 秒")
    print(f"输出文件前缀: {output_prefix}_*.txt")


if __name__ == "__main__":
    # 配置参数
    drive_to_scan = 'E:\\'  # 要扫描的磁盘
    output_prefix = r'D:\HJL_TMP\disk_files'  # 输出文件前缀
 
    max_records_per_file = 1000000  # 每个TXT文件最大记录数  1000000

    # 开始扫描
    scan_and_record(drive=drive_to_scan,
                    output_prefix=output_prefix,
                    max_records=max_records_per_file)
