import { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Button, Layout, Menu, Select, theme, type MenuProps } from 'antd';
import NotificationBell from '../components/NotificationBell';
import {
  DashboardOutlined,
  ShoppingCartOutlined,
  AuditOutlined,
  FileTextOutlined,
  CheckCircleOutlined,
  DatabaseOutlined,
  SwapOutlined,
  DollarOutlined,
  BankOutlined,
  AccountBookOutlined,
  ReconciliationOutlined,
  PayCircleOutlined,
  TeamOutlined,
  AppstoreOutlined,
  SafetyOutlined,
  SearchOutlined,
  ShopOutlined,
  SolutionOutlined,
  BarcodeOutlined,
  ClockCircleOutlined,
  FileSearchOutlined,
  InboxOutlined,
  RollbackOutlined,
  TagsOutlined,
  EnvironmentOutlined,
  BellOutlined,
  WarningOutlined,
  UserOutlined,
  LoginOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '../stores/authStore';
import { useBrandStore } from '../stores/brandStore';
import api, { extractItems } from '../api/client';

const { Header, Sider, Content } = Layout;

// 扩展 MenuItem: 加 roles 字段用于权限过滤（空/undefined 视为所有角色可见）
type MenuItem = Required<MenuProps>['items'][number] & { roles?: string[]; children?: MenuItem[] };

const menuItems: MenuItem[] = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/me', icon: <SolutionOutlined />, label: '我的' },
  {
    key: 'approval', icon: <CheckCircleOutlined />, label: '审批中心',
    roles: ['admin', 'boss', 'finance', 'hr'],
    children: [
      { key: '/approval/policy', icon: <AuditOutlined />, label: '政策审批', roles: ['admin', 'boss'] },
      { key: '/approval/finance', icon: <DollarOutlined />, label: '综合审批' },
    ],
  },
  // ─── 业务 ───
  {
    type: 'group', label: '业务',
    children: [
      { key: '/orders', icon: <ShoppingCartOutlined />, label: '订单' },
      { key: '/customers', icon: <TeamOutlined />, label: '客户' },
      { key: '/sales/targets', icon: <DashboardOutlined />, label: '销售目标', roles: ['admin', 'boss', 'sales_manager'] },
      {
        key: 'policies', icon: <AuditOutlined />, label: '政策',
        children: [
          { key: '/policies/requests', icon: <FileTextOutlined />, label: '申请' },
          { key: '/policies/fulfill', icon: <CheckCircleOutlined />, label: '兑付', roles: ['admin', 'boss', 'finance'] },
          { key: '/policies/reconcile', icon: <ReconciliationOutlined />, label: '到账对账', roles: ['admin', 'boss', 'finance'] },
          { key: '/policies/tasting-mgmt', icon: <SafetyOutlined />, label: '销瓶对账', roles: ['admin', 'boss', 'finance'] },
          { key: '/policies/dashboard', icon: <BankOutlined />, label: '政策应收', roles: ['admin', 'boss', 'finance'] },
          { key: '/policies/templates', icon: <FileTextOutlined />, label: '模板', roles: ['admin', 'boss'] },
        ],
      },
      {
        key: 'inspections', icon: <SafetyOutlined />, label: '稽查',
        roles: ['admin', 'boss', 'finance'],
        children: [
          { key: '/inspections/cases', icon: <SearchOutlined />, label: '案件' },
          { key: '/inspections/trace', icon: <BarcodeOutlined />, label: '扫码追溯' },
        ],
      },
    ],
  },
  // ─── 仓储采购 ───
  {
    type: 'group', label: '仓储采购',
    roles: ['admin', 'boss', 'warehouse', 'purchase', 'sales_manager'],
    children: [
      { key: '/inventory/query', icon: <DatabaseOutlined />, label: '库存' },
      { key: '/inventory/stock-flow', icon: <SwapOutlined />, label: '出入库流水' },
      { key: '/inventory/transfers', icon: <SwapOutlined />, label: '仓库调拨', roles: ['admin', 'boss', 'warehouse', 'purchase', 'finance'] },
      { key: '/inventory/low-stock', icon: <BellOutlined />, label: '低库存预警' },
      { key: '/purchase/orders', icon: <ShoppingCartOutlined />, label: '采购订单', roles: ['admin', 'boss', 'purchase', 'warehouse', 'finance'] },
      { key: '/purchase/receive', icon: <BarcodeOutlined />, label: '收货扫码', roles: ['admin', 'boss', 'purchase', 'warehouse'] },
    ],
  },
  // ─── 财务 ───
  {
    type: 'group', label: '财务',
    roles: ['admin', 'boss', 'finance'],
    children: [
      { key: '/finance/accounts', icon: <BankOutlined />, label: '账户总览' },
      { key: '/finance/profit-ledger', icon: <AccountBookOutlined />, label: '利润台账' },
      { key: '/finance/payment-progress', icon: <DashboardOutlined />, label: '回款进度' },
      { key: '/finance/cash-flow', icon: <ReconciliationOutlined />, label: '资金往来' },
      { key: '/finance/aging', icon: <WarningOutlined />, label: '应收账龄' },
      { key: '/finance/expenses', icon: <PayCircleOutlined />, label: '报销' },
      { key: '/finance/financing', icon: <BankOutlined />, label: '融资' },
    ],
  },
  // ─── 商城 ───
  {
    type: 'group', label: '商城',
    roles: ['admin', 'boss', 'finance', 'warehouse', 'hr'],
    children: [
      { key: '/mall/dashboard', icon: <DashboardOutlined />, label: '商城看板', roles: ['admin', 'boss', 'finance'] },
      { key: '/mall/orders', icon: <ShoppingCartOutlined />, label: '商城订单', roles: ['admin', 'boss', 'finance'] },
      { key: '/mall/products', icon: <AppstoreOutlined />, label: '商品', roles: ['admin', 'boss', 'purchase'] },
      { key: '/mall/categories', icon: <TagsOutlined />, label: '分类与标签', roles: ['admin', 'boss'] },
      { key: '/mall/warehouses', icon: <InboxOutlined />, label: '商城仓库', roles: ['admin', 'boss', 'warehouse', 'purchase'] },
      { key: '/mall/inventory', icon: <InboxOutlined />, label: '商城库存', roles: ['admin', 'boss', 'warehouse'] },
      { key: '/mall/user-applications', icon: <SolutionOutlined />, label: '注册审批', roles: ['admin', 'boss', 'hr'] },
      { key: '/mall/returns', icon: <RollbackOutlined />, label: '退货审批', roles: ['admin', 'boss', 'finance'] },
      { key: '/mall/consumers', icon: <UserOutlined />, label: 'C 端用户', roles: ['admin', 'boss', 'finance'] },
      { key: '/mall/salesmen', icon: <TeamOutlined />, label: '业务员', roles: ['admin', 'boss', 'hr'] },
      { key: '/mall/skip-alerts', icon: <WarningOutlined />, label: '跳单告警', roles: ['admin', 'boss'] },
      { key: '/mall/invite-codes', icon: <BarcodeOutlined />, label: '邀请码', roles: ['admin', 'boss'] },
      { key: '/mall/notices', icon: <BellOutlined />, label: '店铺公告', roles: ['admin', 'boss'] },
      { key: '/mall/search-keywords', icon: <BellOutlined />, label: '热搜词', roles: ['admin', 'boss'] },
      { key: '/mall/housekeeping-logs', icon: <ClockCircleOutlined />, label: '定时任务', roles: ['admin', 'boss'] },
      {
        key: 'mall-audit', icon: <FileSearchOutlined />, label: '商城审计',
        roles: ['admin', 'boss'],
        children: [
          { key: '/mall/audit/operations', icon: <AuditOutlined />, label: '操作审计' },
          { key: '/mall/audit/login-logs', icon: <LoginOutlined />, label: '登录日志' },
          { key: '/mall/audit/login-stats', icon: <DashboardOutlined />, label: '登录频率' },
        ],
      },
    ],
  },
  // ─── 门店零售 ───
  {
    type: 'group', label: '门店',
    roles: ['admin', 'boss', 'finance', 'warehouse', 'hr'],
    children: [
      { key: '/store/sales', icon: <ShoppingCartOutlined />, label: '门店销售流水', roles: ['admin', 'boss', 'finance', 'warehouse', 'hr'] },
      { key: '/store/stores', icon: <InboxOutlined />, label: '门店管理', roles: ['admin', 'boss'] },
      { key: '/store/commission-rates', icon: <DollarOutlined />, label: '店员提成率', roles: ['admin', 'boss', 'finance', 'hr'] },
    ],
  },
  // ─── 人事 ───
  {
    type: 'group', label: '人事',
    roles: ['admin', 'boss', 'hr', 'finance'],
    children: [
      { key: '/hr/employees', icon: <TeamOutlined />, label: '员工', roles: ['admin', 'boss', 'hr'] },
      { key: '/hr/salaries', icon: <AccountBookOutlined />, label: '工资', roles: ['admin', 'boss', 'hr', 'finance'] },
      { key: '/hr/salary-schemes', icon: <DollarOutlined />, label: '薪酬方案', roles: ['admin', 'boss', 'hr'] },
      { key: '/hr/kpi-rules', icon: <DollarOutlined />, label: 'KPI 系数规则', roles: ['admin', 'boss'] },
      { key: '/hr/manufacturer-subsidies', icon: <BankOutlined />, label: '厂家补贴', roles: ['admin', 'boss', 'hr', 'finance'] },
      { key: '/hr/performance', icon: <DashboardOutlined />, label: '绩效', roles: ['admin', 'boss', 'hr'] },
      { key: '/hr/kpis', icon: <DashboardOutlined />, label: 'KPI', roles: ['admin', 'boss', 'hr'] },
      { key: '/hr/commissions', icon: <DollarOutlined />, label: '佣金', roles: ['admin', 'boss', 'hr', 'finance'] },
      { key: '/attendance', icon: <CheckCircleOutlined />, label: '考勤' },
      { key: '/attendance/map', icon: <EnvironmentOutlined />, label: '考勤地图', roles: ['admin', 'boss', 'hr'] },
    ],
  },
  // ─── 设置 ───
  {
    type: 'group', label: '设置',
    roles: ['admin', 'boss'],
    children: [
      { key: '/products', icon: <AppstoreOutlined />, label: '商品' },
      { key: '/brands', icon: <TagsOutlined />, label: '品牌' },
      { key: '/suppliers', icon: <ShopOutlined />, label: '供应商' },
      { key: '/hr/users', icon: <SafetyOutlined />, label: '用户账号' },
      { key: '/audit-logs', icon: <FileSearchOutlined />, label: '审计日志', roles: ['admin'] },
    ],
  },
];

function hasAccess(item: MenuItem, userRoles: string[]): boolean {
  if (userRoles.includes('admin')) return true;
  if (!item.roles?.length) return true;
  return item.roles.some(r => userRoles.includes(r));
}

function filterMenu(items: MenuItem[], userRoles: string[]): MenuItem[] {
  return items
    .filter(it => hasAccess(it, userRoles))
    .map(it => {
      if (!it.children?.length) return it;
      const kids = filterMenu(it.children, userRoles);
      // 如果所有子菜单都被过滤掉，隐藏父节点（group 除外）
      if (!kids.length && (it as any).type !== 'group') return null as any;
      return { ...it, children: kids };
    })
    .filter(Boolean) as MenuItem[];
}

function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { token: { colorBgContainer, borderRadiusLG } } = theme.useToken();
  const username = useAuthStore((s) => s.username);
  const roles = useAuthStore((s) => s.roles);
  const userBrandIds = useAuthStore((s) => s.brandIds);
  const logout = useAuthStore((s) => s.logout);
  const { selectedBrandId, setBrand } = useBrandStore();
  const { data: allBrands = [] } = useQuery<{id: string; code: string; name: string}[]>({
    queryKey: ['brands-list'],
    queryFn: () => api.get('/products/brands').then(r => extractItems<{id: string; code: string; name: string}>(r.data)),
  });

  // Admin/boss see all brands; others only see their bound brands
  const isAdmin = roles?.some(r => ['admin', 'boss'].includes(r));
  const brands = isAdmin || !userBrandIds?.length
    ? allBrands
    : allBrands.filter(b => userBrandIds.includes(b.id));

  // Derive open submenu keys from current path
  const pathParts = location.pathname.split('/').filter(Boolean);
  const defaultOpenKeys = pathParts.length > 1 ? [pathParts[0]] : [];

  const onClick: MenuProps['onClick'] = ({ key }) => {
    navigate(key);
  };

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        width={220}
        style={{ overflow: 'auto', height: '100vh', position: 'fixed', left: 0, top: 0, bottom: 0, zIndex: 10 }}
      >
        <div style={{
          height: 48,
          margin: 12,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontWeight: 700,
          fontSize: collapsed ? 16 : 18,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
        }}>
          {collapsed ? 'ERP' : '新鑫久隆 ERP'}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          defaultOpenKeys={defaultOpenKeys}
          items={filterMenu(menuItems, roles ?? [])}
          onClick={onClick}
        />
      </Sider>
      <Layout style={{ marginLeft: collapsed ? 80 : 220, transition: 'margin-left 0.2s' }}>
        <Header style={{
          padding: '0 24px',
          background: colorBgContainer,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          fontSize: 14,
          borderBottom: '1px solid #f0f0f0',
        }}>
          <Select
            placeholder="全部品牌"
            allowClear
            style={{ width: 140, marginRight: 16 }}
            value={selectedBrandId}
            onChange={(v) => setBrand(v ?? null)}
            options={brands.map(b => ({ value: b.id, label: b.name }))}
          />
          <NotificationBell />
          <span style={{ marginRight: 16, marginLeft: 8 }}>{username ?? '用户'}</span>
          <Button size="small" onClick={() => { logout(); navigate('/login'); }}>退出</Button>
        </Header>
        <Content style={{
          margin: 16,
          padding: 24,
          background: colorBgContainer,
          borderRadius: borderRadiusLG,
          overflow: 'auto',
        }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

export default MainLayout;
