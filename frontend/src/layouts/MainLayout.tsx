import { useEffect, useMemo, useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Button, Layout, Menu, theme, type MenuProps } from 'antd';
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
  SettingOutlined,
  ContainerOutlined,
  ProfileOutlined,
  ApartmentOutlined,
  BuildOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '../stores/authStore';
import { useBrandStore } from '../stores/brandStore';
import { useStoreStore } from '../stores/storeStore';
import api, { extractItems } from '../api/client';

const { Header, Sider, Content } = Layout;

// 扩展 MenuItem：
//   - roles: 权限过滤
//   - meta.brandId: 点此菜单时自动 setBrand(id)（空字符串 = 清 brand；undefined = 不改）
//   - meta.storeId: 同理，驱动 useStoreStore
type MenuMeta = { brandId?: string | null; storeId?: string | null };
type MenuItem = Required<MenuProps>['items'][number] & {
  roles?: string[];
  children?: MenuItem[];
  meta?: MenuMeta;
};

interface BrandRow { id: string; code: string; name: string }
interface WarehouseRow {
  id: string;
  name: string;
  warehouse_type: string;
  brand_id?: string | null;
}

// =============================================================================
// 菜单构建（动态，按当前登录用户权限 + 数据库 brands/stores 生成）
// =============================================================================


function buildBrandAgentChildren(brand: BrandRow): MenuItem[] {
  // 分公司（品牌代理）下的子模块 —— 每个模块 URL 不变，靠 meta.brandId 自动切上下文
  const meta: MenuMeta = { brandId: brand.id };
  return [
    { key: `/orders?brand=${brand.id}`, icon: <ShoppingCartOutlined />, label: '订单', meta },
    { key: `/customers?brand=${brand.id}`, icon: <TeamOutlined />, label: '客户', meta },
    { key: `/policies/requests?brand=${brand.id}`, icon: <FileTextOutlined />, label: '政策申请', meta },
    { key: `/policies/fulfill?brand=${brand.id}`, icon: <CheckCircleOutlined />, label: '政策兑付', meta, roles: ['admin', 'boss', 'finance'] },
    { key: `/policies/dashboard?brand=${brand.id}`, icon: <BankOutlined />, label: '政策应收', meta, roles: ['admin', 'boss', 'finance'] },
    { key: `/sales/targets?brand=${brand.id}`, icon: <DashboardOutlined />, label: '销售目标', meta, roles: ['admin', 'boss', 'sales_manager'] },
    { key: `/inspections/cases?brand=${brand.id}`, icon: <SearchOutlined />, label: '稽查案件', meta, roles: ['admin', 'boss', 'finance'] },
    { key: `/inventory/query?brand=${brand.id}`, icon: <DatabaseOutlined />, label: '库存', meta },
    { key: `/purchase/orders?brand=${brand.id}`, icon: <BarcodeOutlined />, label: '采购', meta, roles: ['admin', 'boss', 'purchase', 'warehouse', 'finance'] },
  ];
}

function buildMallChildren(): MenuItem[] {
  // 商城属于跨品牌分公司 —— 进任一子页时清空 brand（避免上一次选的品牌影响）
  const meta: MenuMeta = { brandId: null };
  return [
    { key: '/mall/dashboard', icon: <DashboardOutlined />, label: '商城看板', meta, roles: ['admin', 'boss', 'finance'] },
    {
      key: 'mall-orders-returns', icon: <ShoppingCartOutlined />, label: '订单 & 退货',
      roles: ['admin', 'boss', 'finance'],
      children: [
        { key: '/mall/orders', icon: <ShoppingCartOutlined />, label: '商城订单', meta, roles: ['admin', 'boss', 'finance'] },
        { key: '/mall/returns', icon: <RollbackOutlined />, label: '退货审批', meta, roles: ['admin', 'boss', 'finance'] },
      ],
    },
    {
      key: 'mall-products', icon: <AppstoreOutlined />, label: '商品目录',
      roles: ['admin', 'boss', 'purchase'],
      children: [
        { key: '/mall/products', icon: <AppstoreOutlined />, label: '商品', meta, roles: ['admin', 'boss', 'purchase'] },
        { key: '/mall/categories', icon: <TagsOutlined />, label: '分类与标签', meta, roles: ['admin', 'boss'] },
      ],
    },
    {
      key: 'mall-warehouse', icon: <InboxOutlined />, label: '仓库与库存',
      roles: ['admin', 'boss', 'warehouse'],
      children: [
        { key: '/mall/warehouses', icon: <InboxOutlined />, label: '商城仓库', meta, roles: ['admin', 'boss', 'warehouse', 'purchase'] },
        { key: '/mall/inventory', icon: <InboxOutlined />, label: '商城库存', meta, roles: ['admin', 'boss', 'warehouse'] },
      ],
    },
    {
      key: 'mall-users', icon: <UserOutlined />, label: '用户',
      roles: ['admin', 'boss', 'finance', 'hr'],
      children: [
        { key: '/mall/user-applications', icon: <SolutionOutlined />, label: '注册审批', meta, roles: ['admin', 'boss', 'hr'] },
        { key: '/mall/consumers', icon: <UserOutlined />, label: 'C 端用户', meta, roles: ['admin', 'boss', 'finance'] },
        { key: '/mall/salesmen', icon: <TeamOutlined />, label: '业务员', meta, roles: ['admin', 'boss', 'hr'] },
      ],
    },
    {
      key: 'mall-ops', icon: <ToolOutlined />, label: '运营',
      roles: ['admin', 'boss'],
      children: [
        { key: '/mall/skip-alerts', icon: <WarningOutlined />, label: '跳单告警', meta, roles: ['admin', 'boss'] },
        { key: '/mall/invite-codes', icon: <BarcodeOutlined />, label: '邀请码', meta, roles: ['admin', 'boss'] },
        { key: '/mall/notices', icon: <BellOutlined />, label: '店铺公告', meta, roles: ['admin', 'boss'] },
        { key: '/mall/search-keywords', icon: <BellOutlined />, label: '热搜词', meta, roles: ['admin', 'boss'] },
        { key: '/mall/housekeeping-logs', icon: <ClockCircleOutlined />, label: '定时任务', meta, roles: ['admin', 'boss'] },
      ],
    },
    {
      key: 'mall-audit', icon: <FileSearchOutlined />, label: '审计',
      roles: ['admin', 'boss'],
      children: [
        { key: '/mall/audit/operations', icon: <AuditOutlined />, label: '操作审计', meta },
        { key: '/mall/audit/login-logs', icon: <LoginOutlined />, label: '登录日志', meta },
        { key: '/mall/audit/login-stats', icon: <DashboardOutlined />, label: '登录频率', meta },
      ],
    },
  ];
}

function buildStoreChildren(store: WarehouseRow): MenuItem[] {
  const meta: MenuMeta = { storeId: store.id, brandId: null };
  return [
    { key: `/store/sales?store=${store.id}`, icon: <ShoppingCartOutlined />, label: '销售流水', meta },
    { key: `/store/commission-rates?store=${store.id}`, icon: <DollarOutlined />, label: '店员提成率', meta, roles: ['admin', 'boss', 'finance', 'hr'] },
  ];
}


function buildMenuItems(
  brands: BrandRow[],
  stores: WarehouseRow[],
  isAdmin: boolean,
): MenuItem[] {
  const brandChildren: MenuItem[] = brands.map(b => ({
    key: `branch-brand-${b.id}`,
    icon: <ContainerOutlined />,
    label: b.name,
    meta: { brandId: b.id },
    children: buildBrandAgentChildren(b),
  }));

  const storeChildren: MenuItem[] = stores.map(s => ({
    key: `branch-store-${s.id}`,
    icon: <ShopOutlined />,
    label: s.name,
    meta: { storeId: s.id, brandId: null },
    children: buildStoreChildren(s),
  }));

  // admin 多一个"门店管理"入口（新建/停用门店）
  if (isAdmin) {
    storeChildren.push({
      key: '/store/stores',
      icon: <BuildOutlined />,
      label: '门店管理',
      meta: { storeId: null },
    });
  }

  return [
    { key: '/dashboard', icon: <DashboardOutlined />, label: '仪表盘' },
    { key: '/boss-view', icon: <AppstoreOutlined />, label: '老板驾驶舱', roles: ['admin', 'boss'] },
    { key: '/me', icon: <SolutionOutlined />, label: '我的' },

    // ─── 分公司 ───（核心重组）
    {
      key: 'branches', icon: <ApartmentOutlined />, label: '分公司',
      children: [
        {
          key: 'branch-brand-agents', icon: <ContainerOutlined />, label: '品牌代理',
          children: brandChildren.length ? brandChildren : [{ key: 'brand-empty', label: '（暂无品牌）', disabled: true } as any],
        },
        {
          key: 'branch-mall', icon: <AppstoreOutlined />, label: '批发商城',
          roles: ['admin', 'boss', 'finance', 'warehouse', 'hr', 'purchase'],
          children: buildMallChildren(),
        },
        {
          key: 'branch-stores', icon: <ShopOutlined />, label: '门店',
          roles: ['admin', 'boss', 'finance', 'warehouse', 'hr'],
          children: storeChildren.length ? storeChildren : [{ key: 'store-empty', label: '（暂无门店）', disabled: true } as any],
        },
      ],
    },

    // ─── 审批中心 ───
    {
      key: 'approval', icon: <CheckCircleOutlined />, label: '审批中心',
      roles: ['admin', 'boss', 'finance', 'hr'],
      children: [
        { key: '/approval/policy', icon: <AuditOutlined />, label: '政策审批', roles: ['admin', 'boss'] },
        { key: '/approval/finance', icon: <DollarOutlined />, label: '综合审批' },
      ],
    },

    // ─── 财务中心 ───
    {
      key: 'finance', icon: <BankOutlined />, label: '财务中心',
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

    // ─── 人事中心 ───
    {
      key: 'hr', icon: <ProfileOutlined />, label: '人事中心',
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

    // ─── 工具 ───（常用跨分公司动作）
    {
      key: 'tools', icon: <ToolOutlined />, label: '工具',
      roles: ['admin', 'boss', 'warehouse', 'purchase', 'finance', 'sales_manager'],
      children: [
        { key: '/inspections/trace', icon: <BarcodeOutlined />, label: '扫码追溯' },
        { key: '/purchase/receive', icon: <BarcodeOutlined />, label: '收货扫码', roles: ['admin', 'boss', 'purchase', 'warehouse'] },
        { key: '/inventory/transfers', icon: <SwapOutlined />, label: '仓库调拨', roles: ['admin', 'boss', 'warehouse', 'purchase', 'finance'] },
        { key: '/inventory/stock-flow', icon: <SwapOutlined />, label: '出入库流水' },
        { key: '/inventory/low-stock', icon: <BellOutlined />, label: '低库存预警' },
      ],
    },

    // ─── 系统设置 ───（全局主数据 + admin）
    {
      key: 'settings', icon: <SettingOutlined />, label: '系统设置',
      roles: ['admin', 'boss'],
      children: [
        { key: '/products', icon: <AppstoreOutlined />, label: '商品' },
        { key: '/brands', icon: <TagsOutlined />, label: '品牌' },
        { key: '/org-units', icon: <AppstoreOutlined />, label: '经营单元' },
        { key: '/suppliers', icon: <ShopOutlined />, label: '供应商' },
        { key: '/hr/users', icon: <SafetyOutlined />, label: '用户账号' },
        { key: '/audit-logs', icon: <FileSearchOutlined />, label: '审计日志', roles: ['admin'] },
      ],
    },
  ];
}

// =============================================================================
// 权限过滤
// =============================================================================


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
      if (!kids.length) return null as any;
      return { ...it, children: kids };
    })
    .filter(Boolean) as MenuItem[];
}

/**
 * 给定当前 URL（只匹配 pathname，不管 query），返回它在菜单树里祖先 key 列表。
 */
function findOpenKeysForPath(items: MenuItem[], pathname: string): string[] {
  for (const it of items) {
    const itemPath = typeof it.key === 'string' ? it.key.split('?')[0] : '';
    if (itemPath === pathname) return [];
    if (it.children?.length) {
      const childOpen = findOpenKeysForPath(it.children as MenuItem[], pathname);
      const matched = (it.children as MenuItem[]).some(c => {
        const cp = typeof c.key === 'string' ? c.key.split('?')[0] : '';
        return cp === pathname;
      }) || childOpen.length > 0;
      if (matched) return [String(it.key), ...childOpen];
    }
  }
  return [];
}

/** 在菜单树里按 key 查找项（用于 onClick 时取 meta） */
function findItemByKey(items: MenuItem[], key: string): MenuItem | null {
  for (const it of items) {
    if (it.key === key) return it;
    if (it.children?.length) {
      const found = findItemByKey(it.children as MenuItem[], key);
      if (found) return found;
    }
  }
  return null;
}

// =============================================================================
// 组件
// =============================================================================


function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { token: { colorBgContainer, borderRadiusLG } } = theme.useToken();
  const username = useAuthStore((s) => s.username);
  const roles = useAuthStore((s) => s.roles) ?? [];
  const userBrandIds = useAuthStore((s) => s.brandIds);
  const logout = useAuthStore((s) => s.logout);
  const { setBrand } = useBrandStore();
  const { setStore } = useStoreStore();

  const { data: allBrands = [] } = useQuery<BrandRow[]>({
    queryKey: ['brands-list'],
    queryFn: () => api.get('/products/brands').then(r => extractItems<BrandRow>(r.data)),
  });

  const { data: allWarehouses = [] } = useQuery<WarehouseRow[]>({
    queryKey: ['warehouses-for-menu'],
    queryFn: () => api.get('/inventory/warehouses').then(r => extractItems<WarehouseRow>(r.data)),
  });

  const isAdmin = roles.some(r => ['admin', 'boss'].includes(r));

  // admin/boss 看全部品牌；其他角色只看自己绑定的
  const brands = useMemo<BrandRow[]>(() =>
    isAdmin || !userBrandIds?.length
      ? allBrands
      : allBrands.filter(b => userBrandIds.includes(b.id)),
    [allBrands, isAdmin, userBrandIds]);

  // 门店取 warehouse_type='store'，过滤掉 E2E 测试仓库让菜单干净
  const stores = useMemo<WarehouseRow[]>(() =>
    allWarehouses
      .filter(w => w.warehouse_type === 'store')
      .filter(w => !w.name.startsWith('E2E')),
    [allWarehouses]);

  const filteredMenu = useMemo(
    () => filterMenu(buildMenuItems(brands, stores, isAdmin), roles),
    [brands, stores, roles, isAdmin],
  );

  const [openKeys, setOpenKeys] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem('mainlayout-open-menus');
      if (saved) return JSON.parse(saved) as string[];
    } catch {}
    return [];
  });

  // 路径变化时，把目标组自动加入 openKeys
  useEffect(() => {
    const required = findOpenKeysForPath(filteredMenu, location.pathname);
    if (required.length === 0) return;
    setOpenKeys(prev => {
      const merged = Array.from(new Set([...prev, ...required]));
      if (merged.length === prev.length) return prev;
      return merged;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, brands.length, stores.length]);

  useEffect(() => {
    try {
      localStorage.setItem('mainlayout-open-menus', JSON.stringify(openKeys));
    } catch {}
  }, [openKeys]);

  const onClick: MenuProps['onClick'] = ({ key }) => {
    const keyStr = String(key);
    const item = findItemByKey(filteredMenu, keyStr);
    // 点菜单项前先同步上下文
    if (item?.meta) {
      if (item.meta.brandId !== undefined) setBrand(item.meta.brandId ?? null);
      if (item.meta.storeId !== undefined) setStore(item.meta.storeId ?? null);
    }
    // key 可能包含 ?brand=X 之类的 query，navigate 原样传（路由会忽略 query 差异但会带到 location.search）
    navigate(keyStr);
  };

  // Menu 组件用 pathname 匹配 selectedKeys，忽略 query 差异（避免多个同 path 带不同 brand 的 key 都被高亮）
  const selectedKeys = useMemo(() => [location.pathname], [location.pathname]);

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        width={240}
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
        {!collapsed && openKeys.length > 0 && (
          <div style={{
            padding: '0 16px 8px',
            display: 'flex',
            justifyContent: 'flex-end',
          }}>
            <a
              onClick={() => setOpenKeys([])}
              style={{ color: 'rgba(255,255,255,0.45)', fontSize: 12 }}
            >
              全部折叠
            </a>
          </div>
        )}
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={selectedKeys}
          openKeys={openKeys}
          onOpenChange={(keys) => setOpenKeys(keys as string[])}
          items={filteredMenu}
          onClick={onClick}
        />
      </Sider>
      <Layout style={{ marginLeft: collapsed ? 80 : 240, transition: 'margin-left 0.2s' }}>
        <Header style={{
          padding: '0 24px',
          background: colorBgContainer,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          fontSize: 14,
          borderBottom: '1px solid #f0f0f0',
        }}>
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
