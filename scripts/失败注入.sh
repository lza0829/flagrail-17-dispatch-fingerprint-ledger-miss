#!/usr/bin/env bash
# 失败注入自动化入口：断言「有票无计划」假已下发不存在、并发无双有效已下发。
# 用法：
#   bash scripts/失败注入.sh                 # 宿主机直连映射端口 11800
#   BASE=http://127.0.0.1:6800 bash scripts/失败注入.sh
#   docker compose exec backend python scripts/失败注入_计划同票.py   # 容器内
set -u
cd "$(dirname "$0")/.."
BASE="${BASE:-${FLAGRAIL_BASE:-http://127.0.0.1:11800}}"
exec python3 scripts/失败注入_计划同票.py --base "$BASE"
