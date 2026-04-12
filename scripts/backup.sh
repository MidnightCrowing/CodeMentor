#!/bin/bash
# ==========================================
# 自动备份脚本 (Docker 版本)
# 使用方法: ./backup.sh
# ==========================================

# 切换到项目根目录执行
cd "$(dirname "$0")/.."

# 确保存放备份的目录存在
mkdir -p ./database_backups

# 生成类似于 backup_codementor_20260412_160530.sql 的时间戳名称
DATE=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="./database_backups/backup_codementor_${DATE}.sql"

echo "⏳ 开始备份数据库至: ${BACKUP_FILE} ..."

# 执行容器内部的原生 pg_dump 导出命令
docker exec codementor_db pg_dump -U postgres -d codementor > "${BACKUP_FILE}"

if [ $? -eq 0 ]; then
    echo "✅ 备份成功！"
    # 可选：打印文件大小
    ls -lh "${BACKUP_FILE}"
else
    echo "❌ 备份失败！"
    # 如果失败，删除空文件
    rm -f "${BACKUP_FILE}"
fi
