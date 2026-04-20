#!/usr/bin/env bash
# MCP Bridge 端到端测试 —— 角色可见清单 + 允许/禁止工具调用
set -u
BASE="${BASE:-http://localhost:8001}"

login() {
  curl --noproxy '*' -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"$2\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])"
}

mcp() {
  local jwt="$1" method="$2" params="$3"
  curl --noproxy '*' -s -X POST "$BASE/mcp/stream/" \
    -H "Authorization: Bearer $jwt" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$method\",\"params\":$params}"
}

BOSS=$(login boss boss123)
SAL=$(login salesman sales123)
WH=$(login warehouse wh123)
FIN=$(login finance finance123)

pass=0; fail=0
check() {
  local name="$1" want="$2" got="$3"
  if [ "$got" = "$want" ]; then echo "✅ $name → $got"; pass=$((pass+1))
  else echo "❌ $name → $got (want $want)"; fail=$((fail+1)); fi
}

echo "== tools/list 按角色数量 =="
for row in "boss $BOSS 28" "salesman $SAL 13" "warehouse $WH 6" "finance $FIN 24"; do
  set -- $row
  role=$1; jwt=$2; want=$3
  n=$(mcp "$jwt" tools/list '{}' | python3 -c "import sys,json; print(len(json.load(sys.stdin)['result']['tools']))")
  check "tools/list $role count" "$want" "$n"
done

echo
echo "== 关键 call 命中/被拒 =="

# salesman 调 query-orders → isError=False，text 非空
out=$(mcp "$SAL" tools/call '{"name":"query-orders","arguments":{}}')
is_err=$(echo "$out" | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['isError'])")
text_starts=$(echo "$out" | python3 -c "import sys,json;t=json.load(sys.stdin)['result']['content'][0]['text'];print('JSON' if t.startswith('[') or t.startswith('{') else 'OTHER')")
check "salesman→query-orders isError" "False" "$is_err"
check "salesman→query-orders text looks like JSON" "JSON" "$text_starts"

# salesman 调 query-account-balances → text 以 "[HTTP 403]" 开头
out=$(mcp "$SAL" tools/call '{"name":"query-account-balances","arguments":{}}')
text=$(echo "$out" | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['content'][0]['text'][:10])")
check "salesman→query-account-balances blocked" "[HTTP 403]" "$text"

# 用一个有 body schema 的 endpoint 测"salesman 不在清单的工具被拒":approve-sales-target
out=$(mcp "$SAL" tools/call '{"name":"approve-sales-target","arguments":{"target_id":"xxx","approved":true}}')
text=$(echo "$out" | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['content'][0]['text'][:10])")
check "salesman→approve-sales-target blocked" "[HTTP 403]" "$text"

# warehouse 调 query-inventory → 允许
out=$(mcp "$WH" tools/call '{"name":"query-inventory","arguments":{}}')
is_err=$(echo "$out" | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['isError'])")
check "warehouse→query-inventory ok" "False" "$is_err"

# warehouse 调 query-salary-records → 403
out=$(mcp "$WH" tools/call '{"name":"query-salary-records","arguments":{}}')
text=$(echo "$out" | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['content'][0]['text'][:10])")
check "warehouse→query-salary-records blocked" "[HTTP 403]" "$text"

echo
echo "== 匿名请求 =="
code=$(curl --noproxy '*' -s -o /dev/null -w '%{http_code}' -X POST "$BASE/mcp/stream/" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
check "anon → 401" "401" "$code"

echo
echo "==== pass=$pass fail=$fail ===="
[ "$fail" = "0" ]
