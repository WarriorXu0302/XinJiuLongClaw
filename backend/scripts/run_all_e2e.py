"""一键跑完所有 E2E 脚本。

用途：
  - 开发回归：改完代码跑一遍看有没破坏其他桥
  - CI（可选）：exit code 非 0 时拦截合并

每个子脚本独立进程跑（subprocess），失败不影响后续继续跑，最后汇总。
任一失败整体 exit 1。

跑法：
  cd backend && python -m scripts.run_all_e2e
  cd backend && python -m scripts.run_all_e2e --stop-on-fail    # 任一失败即停
  cd backend && python -m scripts.run_all_e2e --verbose         # 打印每个脚本完整输出
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path


# (脚本名, 简要说明)
# 顺序：先低依赖 seed，再业务流水
SCRIPTS = [
    ("e2e_verify_4bugs",
     "4 场景：禁用业务员级联 / 推荐人禁用下单 / 员工停用登录 / 驳回重注"),
    ("e2e_reversed_commission_excluded",
     "reversed 状态 commission 被工资单 filter 排除"),
    ("e2e_skip_alert_threshold",
     "dismissed skip_log 不计入跳单告警阈值"),
    ("e2e_mall_partial_close",
     "桥 B3.5：60 天未全款订单坏账折损 + commission + profit"),
    ("e2e_full_mall_flow",
     "mall 10 步贯通：注册→下单→抢单→ship→deliver→凭证→确认→退货"),
    ("e2e_warehouse_transfer",
     "桥 B11：ERP/mall 跨端调拨 4 种路径 + 品牌主仓拦截"),
    ("e2e_store_sale",
     "桥 B12：门店零售收银 5 场景（闭环/越界/credit 拒/越权/无提成率）"),
    ("e2e_store_return",
     "桥 B12 延伸：门店退货 5 场景 + 6 处一致性"),
    ("e2e_store_commission_in_payroll",
     "P0 修复验证：门店提成进月度工资单扫描（m6b3）"),
    ("e2e_mall_profit_aggregation",
     "桥 B3.4 + B3.5：mall 利润聚合多订单/多状态/refunded 排除"),
    ("e2e_mall_return_barcode_revert",
     "桥 B4.4：退货批准后条码 OUTBOUND→IN_STOCK + 订单隔离"),
]


def _run_one(script_name: str, verbose: bool) -> tuple[bool, float, str]:
    """跑一个脚本，返回 (成功?, 耗时秒, 错误摘要)。"""
    start = time.time()
    try:
        result = subprocess.run(
            ["python", "-m", f"scripts.{script_name}"],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return False, time.time() - start, "超时 180s"

    elapsed = time.time() - start
    if result.returncode != 0:
        # 摘取 stderr 最后 30 行
        tail = "\n".join(
            (result.stderr or result.stdout).splitlines()[-30:]
        )
        return False, elapsed, tail
    if verbose:
        print(result.stdout)
    return True, elapsed, ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop-on-fail", action="store_true",
                        help="任一失败即停（默认继续跑后续）")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="打印每个脚本完整输出（默认只汇总）")
    args = parser.parse_args()

    total = len(SCRIPTS)
    results: list[tuple[str, bool, float, str]] = []
    cumulative = time.time()

    print("=" * 80)
    print(f" E2E 全量回归（{total} 个脚本）")
    print("=" * 80)

    for i, (name, desc) in enumerate(SCRIPTS, 1):
        print(f"\n[{i}/{total}] {name}")
        print(f"       {desc}")
        ok, elapsed, err = _run_one(name, args.verbose)
        icon = "✅" if ok else "❌"
        print(f"       {icon} {elapsed:.1f}s")
        if not ok:
            print(f"       错误摘要（最后 30 行）:")
            for line in err.splitlines():
                print(f"         {line}")
        results.append((name, ok, elapsed, err))
        if not ok and args.stop_on_fail:
            print("\n⛔ --stop-on-fail 触发，停止后续脚本")
            break

    total_elapsed = time.time() - cumulative
    passed = sum(1 for _, ok, _, _ in results if ok)
    failed = [r for r in results if not r[1]]

    print("\n" + "=" * 80)
    print(f" 汇总：{passed}/{total} 通过，总耗时 {total_elapsed:.1f}s")
    print("=" * 80)
    for name, ok, elapsed, _ in results:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name:40s}  {elapsed:.1f}s")

    if failed:
        print("\n失败的脚本：")
        for name, _, _, err in failed:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
