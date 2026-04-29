/**
 * 操作审计日志（共用 audit_logs 表 + app='mall'）
 *
 * 列：actor / 操作时间 / action / resource / before/after JSON diff / IP / reason
 * 过滤：actor / resource_type / action / 日期
 * 导出 CSV
 *
 * TODO(M5): GET /api/mall/admin/audit-logs
 */
export default function AuditLogList() {
  return <div>操作审计（TODO M5）</div>;
}
