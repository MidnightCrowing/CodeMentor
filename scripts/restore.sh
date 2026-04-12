#!/bin/bash
# ==========================================
# 自动恢复脚本 (Docker 版本)
# 使用方法: ./restore.sh <备份文件路径>
# 例如: ./restore.sh ../database_backups/backup_codementor_20260412.sql
# ==========================================

# 切换到项目根目录执行
cd "$(dirname "$0")/.."

BACKUP_FILE="$1"

if [ -z "$BACKUP_FILE" ]; then
    echo "⚠️  错误: 请指定要恢复的 SQL 备份文件路径！"
    echo "用法: ./restore.sh <备份文件路径>"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "⚠️  错误: 找不到文件 '$BACKUP_FILE'！"
    exit 1
fi

echo "⚠️  警告: 这将覆盖现有的数据库数据！"
read -p "确定要继续吗？(y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "已取消。"
    exit 0
fi

echo "⏳ 正在恢复数据库 (${BACKUP_FILE}) ..."

# 通过重定向将宿主机的文件打入运行的容器中执行
cat "${BACKUP_FILE}" | docker exec -i codementor_db psql -U postgres -d codementor

if [ $? -eq 0 ]; then
    echo "✅ 恢复成功！请检查终端输出是否有表冲突等严重错误。"
else
    echo "❌ 恢复时可能发生错误，请查看上述报错日志！"
fi
