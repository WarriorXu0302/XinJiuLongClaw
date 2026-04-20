#!/usr/bin/env bash
# 飞书绑定 + 换 token 端到端测试
set -u
BASE="${BASE:-http://localhost:8001}"
KEY="${FEISHU_AGENT_SERVICE_KEY:-dev-agent-key-CHANGE-ME}"
# 用固定前缀 + PID 保证每次跑不冲突（open_id 是 unique）
OPEN_ID="test_open_$$"
OPEN_ID2="test_open_${$}_b"

code() { curl --noproxy '*' -s -o /tmp/_resp -w '%{http_code}' "$@"; }
body() { cat /tmp/_resp; }

pass=0; fail=0
check() {
  local name="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then echo "✅ $name → $got"; pass=$((pass+1))
  else echo "❌ $name → $got (expected $expected)  body=$(body)"; fail=$((fail+1)); fi
}

echo "== 1. 无 service key =="
c=$(code -X POST "$BASE/api/feishu/bind" -H 'Content-Type: application/json' \
  -d "{\"open_id\":\"$OPEN_ID\",\"username\":\"salesman\",\"password\":\"sales123\"}")
check "bind without key" "422" "$c"   # FastAPI 对 missing required header 返 422

echo "== 2. 错 service key =="
c=$(code -X POST "$BASE/api/feishu/bind" \
  -H 'Content-Type: application/json' -H 'X-Agent-Service-Key: WRONG' \
  -d "{\"open_id\":\"$OPEN_ID\",\"username\":\"salesman\",\"password\":\"sales123\"}")
check "bind wrong key" "401" "$c"

echo "== 3. 正确 key + 错密码 =="
c=$(code -X POST "$BASE/api/feishu/bind" \
  -H 'Content-Type: application/json' -H "X-Agent-Service-Key: $KEY" \
  -d "{\"open_id\":\"$OPEN_ID\",\"username\":\"salesman\",\"password\":\"WRONG\"}")
check "bind wrong password" "401" "$c"

echo "== 4. bind salesman =="
c=$(code -X POST "$BASE/api/feishu/bind" \
  -H 'Content-Type: application/json' -H "X-Agent-Service-Key: $KEY" \
  -d "{\"open_id\":\"$OPEN_ID\",\"username\":\"salesman\",\"password\":\"sales123\"}")
check "bind salesman" "200" "$c"
BOUND_USER_ID=$(body | python3 -c "import sys,json;print(json.load(sys.stdin)['user_id'])")
echo "   → user_id=$BOUND_USER_ID roles=$(body | python3 -c "import sys,json;print(json.load(sys.stdin)['roles'])")"

echo "== 5. exchange-token with bound open_id =="
c=$(code -X POST "$BASE/api/feishu/exchange-token" \
  -H 'Content-Type: application/json' -H "X-Agent-Service-Key: $KEY" \
  -d "{\"open_id\":\"$OPEN_ID\"}")
check "exchange token" "200" "$c"
JWT=$(body | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

echo "== 6. 用该 JWT 调 MCP —— 应当生效且受 RBAC 约束 =="
# 6a: salesman 可以查库存 → 200
c=$(code -X POST "$BASE/mcp/query-inventory" -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' -d '{}')
check "jwt→mcp query-inventory" "200" "$c"
# 6b: salesman 不能查账户余额 → 403
c=$(code -X POST "$BASE/mcp/query-account-balances" -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' -d '{}')
check "jwt→mcp query-account-balances (should 403)" "403" "$c"

echo "== 7. 未绑定的 open_id 换 token =="
c=$(code -X POST "$BASE/api/feishu/exchange-token" \
  -H 'Content-Type: application/json' -H "X-Agent-Service-Key: $KEY" \
  -d "{\"open_id\":\"never_bound_xxx\"}")
check "exchange token unbound" "404" "$c"

echo "== 8. 幂等：重复 bind 同一 open_id 同一账号 =="
c=$(code -X POST "$BASE/api/feishu/bind" \
  -H 'Content-Type: application/json' -H "X-Agent-Service-Key: $KEY" \
  -d "{\"open_id\":\"$OPEN_ID\",\"username\":\"salesman\",\"password\":\"sales123\"}")
check "idempotent bind" "200" "$c"

echo "== 9. 跨账号切换：同 open_id 改绑 boss =="
c=$(code -X POST "$BASE/api/feishu/bind" \
  -H 'Content-Type: application/json' -H "X-Agent-Service-Key: $KEY" \
  -d "{\"open_id\":\"$OPEN_ID\",\"username\":\"boss\",\"password\":\"boss123\"}")
# 注意：第 9 步之前 salesman 已经绑了 OPEN_ID，而 boss 没绑任何 open_id —— 这是干净的 "existing_by_open" 分支
check "rebind same open_id to boss" "200" "$c"

echo "== 10. 换 token 现在应该返回 boss 的 payload =="
c=$(code -X POST "$BASE/api/feishu/exchange-token" \
  -H 'Content-Type: application/json' -H "X-Agent-Service-Key: $KEY" \
  -d "{\"open_id\":\"$OPEN_ID\"}")
check "exchange after rebind" "200" "$c"
ROLES=$(body | python3 -c "import sys,json;print(json.load(sys.stdin)['roles'])")
echo "   → roles=$ROLES (expect ['boss'])"

echo "== 11. unbind =="
c=$(code -X POST "$BASE/api/feishu/unbind" \
  -H 'Content-Type: application/json' -H "X-Agent-Service-Key: $KEY" \
  -d "{\"open_id\":\"$OPEN_ID\"}")
check "unbind" "200" "$c"

echo "== 12. unbind 后不能换 token =="
c=$(code -X POST "$BASE/api/feishu/exchange-token" \
  -H 'Content-Type: application/json' -H "X-Agent-Service-Key: $KEY" \
  -d "{\"open_id\":\"$OPEN_ID\"}")
check "exchange after unbind" "404" "$c"

echo
echo "==== pass=$pass  fail=$fail ===="
[ "$fail" = "0" ]
