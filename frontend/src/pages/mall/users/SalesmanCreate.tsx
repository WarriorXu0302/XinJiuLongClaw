/**
 * 手动新建业务员账号
 *
 * 字段：
 *   username（必填，唯一）
 *   初始密码（留空则后端自动生成）
 *   linked_employee_id（必填，从 ERP employees 下拉）
 *   assigned_brand_id（默认取 employee 主属 brand）
 *   phone / nickname
 *
 * 创建成功：显示用户名 + 临时密码，提示 HR 告知业务员首次登录改密码（must_change_password）
 *
 * TODO(M5): POST /api/mall/admin/salesmen
 */
export default function SalesmanCreate() {
  return <div>新建业务员（TODO M5）</div>;
}
