#!/bin/bash
set -e

RAID_DEVICES=(/dev/sdb /dev/sdc /dev/sdd /dev/sde /dev/sdf /dev/sdh /dev/sdi)
MOUNT_POINT="/mnt/disk2_raid5"
MD_DEVICE="/dev/md0"
FILESYSTEM="ext4"

echo "=== 安装 mdadm ==="
sudo apt update && sudo apt install -y mdadm

echo "=== 清除旧 RAID 信息 ==="
for dev in "${RAID_DEVICES[@]}"; do
  echo "  清除 $dev"
  sudo mdadm --zero-superblock --force "$dev" || true
done

echo "=== 创建 RAID 5 阵列 ==="
sudo mdadm --create --verbose "$MD_DEVICE" \
  --level=5 --raid-devices=7 "${RAID_DEVICES[@]}"

echo "=== 等待 RAID 初始化（后台可继续）==="
cat /proc/mdstat

echo "=== 创建文件系统（$FILESYSTEM）==="
sudo mkfs.$FILESYSTEM "$MD_DEVICE"

echo "=== 创建挂载点并挂载 ==="
sudo mkdir -p "$MOUNT_POINT"
sudo mount "$MD_DEVICE" "$MOUNT_POINT"

echo "=== 获取 UUID 写入 /etc/fstab 实现自动挂载 ==="
UUID=$(blkid -s UUID -o value "$MD_DEVICE")
echo "UUID=$UUID $MOUNT_POINT $FILESYSTEM defaults 0 2" | sudo tee -a /etc/fstab

echo "=== 保存 RAID 配置到 /etc/mdadm/mdadm.conf ==="
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf
sudo update-initramfs -u

echo "RAID 5 初始化完成，已挂载于 $MOUNT_POINT"

# 维护
# 监控阵列健康：sudo mdadm --detail /dev/md0
# 检查同步状态：cat /proc/mdstat
# 添加热备盘（可选）：sudo mdadm --add /dev/md0 /dev/sdj
