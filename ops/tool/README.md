## tunnel脚本  
作用：连接隧道，主要可用于访问dell服务器的mongodb  

用法: /usr/local/bin/tunnel [open|close] -h <host_alias> [-l <local_port>] [-r <remote_port>]  

参数说明:  
  open           启动 SSH 隧道  
  close          关闭 SSH 隧道  
  -h <host>      使用 ~/.ssh/config 中的主机别名  
  -l <port>      本地端口，默认 29019  
  -r <port>      远程端口，默认 27017  
  -help          显示帮助  

示例:  
  /usr/local/bin/tunnel open -h rs-dell  
  /usr/local/bin/tunnel close -h rs-dell  
  /usr/local/bin/tunnel open -h rs-dell -l 12345 -r 27017  

建议将本脚本放置到/usr/local/bin，则可全路径直接执行tunnel命令  

## add_ssh_user.sh
作用：添加linux账户  

用法：sudo bash add_ssh_user.sh <用户名> "ssh-rsa ..." [--sudo]  
参数：--sudo是否赋予sudo权限  "ssh-rsa ..."为用户公钥

## init_raid5.sh  
作用：磁盘组建raid5  

用法：修改RAID_DEVICES、MOUNT_POINT后，执行./init_raid5.sh  
