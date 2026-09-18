#!/bin/bash
set -euo pipefail

# 用法说明
# sudo bash add_ssh_user.sh 用户名 "ssh-rsa ..." [--sudo]
if [ "$#" -lt 2 ]; then
  echo "用法: sudo bash $0 用户名 'ssh-rsa AAAAB3... user@example.com' [--sudo]"
  exit 1
fi

USERNAME="$1"
shift

# 检查是否带有 --sudo 参数
ADD_SUDO="no"
if [[ "${@: -1}" == "--sudo" ]]; then
  ADD_SUDO="yes"
  USER_PUBKEY="${*:1:$(($#-1))}"  # 除去最后一个参数（--sudo）
else
  USER_PUBKEY="$*"
fi

# 创建用户（如果不存在）
if id "$USERNAME" &>/dev/null; then
  echo "用户 $USERNAME 已存在"
else
  sudo adduser --disabled-password --gecos "" "$USERNAME"
  echo "用户 $USERNAME 创建成功"
fi

# 创建 .ssh 目录并写入公钥
sudo mkdir -p /home/$USERNAME/.ssh
sudo chmod 700 /home/$USERNAME/.ssh
echo "$USER_PUBKEY" | sudo tee /home/$USERNAME/.ssh/authorized_keys > /dev/null
sudo chmod 600 /home/$USERNAME/.ssh/authorized_keys
sudo chown -R $USERNAME:$USERNAME /home/$USERNAME/.ssh

# 添加 sudo 权限（可选）
if [ "$ADD_SUDO" == "yes" ]; then
  sudo usermod -aG sudo "$USERNAME"
  echo "用户 $USERNAME 已加入 sudo 组，拥有管理员权限"
fi

echo "用户 $USERNAME 已配置 SSH 公钥登录成功！"
