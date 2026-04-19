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
  FileSearchOutlined,
  TagsOutlined,
  EnvironmentOutlined,
  BellOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '../stores/authStore';
import { useBrandStore } from '../stores/brandStore';
import api from '../api/client';

const { Header, Sider, Content } = Layout;

type MenuItem = Required<MenuProps>['items'][number];

const menuItems: MenuItem[] = [
  {
    key: '/dashboard',
    icon: <DashboardOutlined />,
    label: '仪表盘',
  },
  {
    key: '/me',
    icon: <SolutionOutlined />,
    label: '我的',
  },
  // ───────────────── 日常操作 ─────────────────
  {
    type: 'group',
    label: '日常操作',
    children: [
      {
        key: 'approval',
        icon: <CheckCircleOutlined />,
        label: '审批中心',
        children: [
          { key: '/approval/policy', icon: <AuditOutlined />, label: '政策审批' },
          { key: '/approval/finance', icon: <DollarOutlined />, label: '财务审批' },
        ],
      },
      { key: '/orders', icon: <ShoppingCartOutlined />, label: '订单管理' },
      { key: '/sales/targets', icon: <DashboardOutlined />, label: '销售目标' },
      { key: '/attendance', icon: <CheckCircleOutlined />, label: '考勤打卡' },
      { key: '/attendance/map', icon: <EnvironmentOutlined />, label: '考勤地图' },
      {
        key: 'policies',
        icon: <AuditOutlined />,
        label: '政策管理',
        children: [
          { key: '/policies/requests', icon: <FileTextOutlined />, label: '政策申请' },
          { key: '/policies/fulfill', icon: <CheckCircleOutlined />, label: '兑付管理' },
          { key: '/policies/reconcile', icon: <ReconciliationOutlined />, label: '到账对账' },
          { key: '/policies/tasting-mgmt', icon: <SafetyOutlined />, label: '销瓶对账' },
        ],
      },
      {
        key: 'inventory',
        icon: <DatabaseOutlined />,
        label: '库存管理',
        children: [
          { key: '/inventory/query', icon: <DatabaseOutlined />, label: '库存查询' },
          { key: '/inventory/stock-flow', icon: <SwapOutlined />, label: '出入库流水' },
          { key: '/inventory/low-stock', icon: <BellOutlined />, label: '低库存预警' },
        ],
      },
      {
        key: 'purchase',
        icon: <ShopOutlined />,
        label: '采购管理',
        children: [
          { key: '/purchase/orders', icon: <ShoppingCartOutlined />, label: '采购订单' },
          { key: '/purchase/receive', icon: <BarcodeOutlined />, label: '收货扫码' },
        ],
      },
      {
        key: 'inspections',
        icon: <SafetyOutlined />,
        label: '稽查管理',
        children: [
          { key: '/inspections/cases', icon: <SearchOutlined />, label: '稽查案件' },
          { key: '/inspections/trace', icon: <BarcodeOutlined />, label: '扫码追溯' },
        ],
      },
    ],
  },
  // ───────────────── 财务 ─────────────────
  {
    type: 'group',
    label: '财务',
    children: [
      { key: '/finance/accounts', icon: <BankOutlined />, label: '账户总览' },
      { key: '/finance/profit-ledger', icon: <AccountBookOutlined />, label: '利润台账' },
      { key: '/finance/payment-progress', icon: <DashboardOutlined />, label: '回款进度' },
      { key: '/finance/cash-flow', icon: <ReconciliationOutlined />, label: '资金往来' },
      { key: '/finance/aging', icon: <WarningOutlined />, label: '应收账龄' },
      { key: '/finance/expenses', icon: <PayCircleOutlined />, label: '报销管理' },
      { key: '/policies/dashboard', icon: <BankOutlined />, label: '政策应收' },
      { key: '/finance/financing', icon: <BankOutlined />, label: '融资管理' },
    ],
  },
  // ───────────────── 基础设置 ─────────────────
  {
    type: 'group',
    label: '基础设置',
    children: [
      { key: '/customers', icon: <TeamOutlined />, label: '客户' },
      { key: '/products', icon: <AppstoreOutlined />, label: '商品' },
      { key: '/brands', icon: <TagsOutlined />, label: '品牌' },
      { key: '/suppliers', icon: <ShopOutlined />, label: '供应商' },
      { key: '/policies/templates', icon: <FileTextOutlined />, label: '政策模板' },
      {
        key: 'hr',
        icon: <SolutionOutlined />,
        label: '人事',
        children: [
          { key: '/hr/employees', icon: <TeamOutlined />, label: '员工' },
          { key: '/hr/users', icon: <SafetyOutlined />, label: '用户账号' },
          { key: '/hr/performance', icon: <DashboardOutlined />, label: '绩效档案' },
          { key: '/hr/salary-schemes', icon: <DollarOutlined />, label: '薪酬方案' },
          { key: '/hr/salaries', icon: <AccountBookOutlined />, label: '月度工资' },
          { key: '/hr/manufacturer-subsidies', icon: <BankOutlined />, label: '厂家工资报账' },
          { key: '/hr/kpis', icon: <DashboardOutlined />, label: 'KPI 考核' },
          { key: '/hr/commissions', icon: <DollarOutlined />, label: '佣金' },
        ],
      },
      { key: '/audit-logs', icon: <FileSearchOutlined />, label: '审计日志' },
    ],
  },
];

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
    queryFn: () => api.get('/products/brands').then(r => r.data),
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
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        width={220}
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
          items={menuItems}
          onClick={onClick}
        />
      </Sider>
      <Layout>
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
          minHeight: 280,
        }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

export default MainLayout;
