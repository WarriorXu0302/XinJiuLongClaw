#!/usr/bin/env bash
# RBAC 端到端验证 —— 5 个种子账号 × 关键 MCP endpoint
# 期望：有权限 200/非 403；无权限 403
set -u
BASE="${BASE:-http://localhost:8001}"

login() {
  curl --noproxy '*' -sf -X POST "$BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"$2\"}" \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])"
}

echo "== 登录 5 个种子账号 =="
ADMIN_JWT=$(login admin admin123) || { echo "admin 登录失败，后端没起？"; exit 1; }
BOSS_JWT=$(login boss boss123)
FINANCE_JWT=$(login finance finance123)
SALES_JWT=$(login salesman sales123)
WH_JWT=$(login warehouse wh123)
echo "OK"

# ─────────── 测试矩阵 ───────────
# 格式: role|jwt_var|endpoint|body|expected_http
CASES=(
  # query-account-balances: 只给 admin/boss/finance
  "salesman|SALES_JWT|/mcp/query-account-balances|{}|403"
  "warehouse|WH_JWT|/mcp/query-account-balances|{}|403"
  "finance|FINANCE_JWT|/mcp/query-account-balances|{}|200"
  "boss|BOSS_JWT|/mcp/query-account-balances|{}|200"
  "admin|ADMIN_JWT|/mcp/query-account-balances|{}|200"

  # query-salary-records: admin/boss/finance (HR 已排除)
  "salesman|SALES_JWT|/mcp/query-salary-records|{}|403"
  "warehouse|WH_JWT|/mcp/query-salary-records|{}|403"
  "finance|FINANCE_JWT|/mcp/query-salary-records|{}|200"

  # query-inventory: 不给 hr，但 warehouse 给
  "warehouse|WH_JWT|/mcp/query-inventory|{}|200"
  "salesman|SALES_JWT|/mcp/query-inventory|{}|200"

  # approve-fund-transfer: admin/boss/finance
  # 注意：transfer_id 乱传会 500 或 hint，但 403 必须先拦
  "salesman|SALES_JWT|/mcp/approve-fund-transfer?transfer_id=xxx|{}|403"
  "warehouse|WH_JWT|/mcp/approve-fund-transfer?transfer_id=xxx|{}|403"

  # approve-sales-target: admin/boss/sales_manager (finance 不给)
  "finance|FINANCE_JWT|/mcp/approve-sales-target|{\"target_id\":\"xxx\"}|403"
  "salesman|SALES_JWT|/mcp/approve-sales-target|{\"target_id\":\"xxx\"}|403"

  # approve-leave: admin/boss/finance (按你决策"财务管考勤")
  "finance|FINANCE_JWT|/mcp/approve-leave|{\"request_no\":\"xxx\"}|404"
  "salesman|SALES_JWT|/mcp/approve-leave|{\"request_no\":\"xxx\"}|403"

  # 无 token 全部 401
  "anon|NONE|/mcp/query-orders|{}|401"
)

pass=0; fail=0
for c in "${CASES[@]}"; do
  IFS='|' read -r role jwtvar path body expected <<< "$c"
  if [ "$jwtvar" = "NONE" ]; then
    code=$(curl --noproxy '*' -s -o /dev/null -w '%{http_code}' -X POST "$BASE$path" \
      -H 'Content-Type: application/json' -d "$body")
  else
    jwt="${!jwtvar}"
    code=$(curl --noproxy '*' -s -o /dev/null -w '%{http_code}' -X POST "$BASE$path" \
      -H "Authorization: Bearer $jwt" \
      -H 'Content-Type: application/json' -d "$body")
  fi
  if [ "$code" = "$expected" ]; then
    echo "✅ $role $path → $code"
    pass=$((pass+1))
  else
    echo "❌ $role $path → $code (expected $expected)"
    fail=$((fail+1))
  fi
done

echo
echo "==== pass=$pass  fail=$fail ===="
[ "$fail" = "0" ]
