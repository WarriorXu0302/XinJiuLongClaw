import { Navigate, type RouteObject } from 'react-router-dom';
import MainLayout from '../layouts/MainLayout';
import Login from '../pages/Login';
import Dashboard from '../pages/Dashboard';
import OrderList from '../pages/orders/OrderList';
import OrderStockOutPage from '../pages/orders/OrderStockOutPage';
import OrderDeliveryPage from '../pages/orders/OrderDeliveryPage';
import OrderPaymentPage from '../pages/orders/OrderPaymentPage';
import PolicyRequestList from '../pages/policies/PolicyRequestList';
import ArrivalReconcile from '../pages/policies/ArrivalReconcile';
import FulfillManage from '../pages/policies/FulfillManage';
import ClaimList from '../pages/policies/ClaimList';
import TastingManagement from '../pages/policies/TastingManagement';
import PolicyDashboard from '../pages/policies/PolicyDashboard';
import InventoryQuery from '../pages/inventory/InventoryQuery';
import LowStockAlert from '../pages/inventory/LowStockAlert';
import StockFlowList from '../pages/inventory/StockFlowList';
import SpecialWarehouseManage from '../pages/inventory/SpecialWarehouseManage';
import RetailWarehouseManage from '../pages/inventory/RetailWarehouseManage';
import WholesaleWarehouseManage from '../pages/inventory/WholesaleWarehouseManage';
import BackupWarehouseManage from '../pages/inventory/BackupWarehouseManage';
import ReceiveScanPage from '../pages/purchase/ReceiveScanPage';
import CashFlowManage from '../pages/finance/CashFlowManage';
import ExpenseList from '../pages/finance/ExpenseList';
import ReceivableAging from '../pages/finance/ReceivableAging';
import AccountOverview from '../pages/finance/AccountOverview';
import PaymentProgress from '../pages/finance/PaymentProgress';
import ProfitLedger from '../pages/finance/ProfitLedger';
import FinancingManagement from '../pages/finance/FinancingManagement';
import CustomerList from '../pages/customers/CustomerList';
import Customer360 from '../pages/customers/Customer360';
import ProductList from '../pages/products/ProductList';
import BrandList from '../pages/products/BrandList';
import InspectionList from '../pages/inspections/InspectionList';
import BarcodeTracePage from '../pages/inspections/BarcodeTracePage';
import PurchaseOrderList from '../pages/purchase/PurchaseOrderList';
import SupplierList from '../pages/suppliers/SupplierList';
import EmployeeList from '../pages/hr/EmployeeList';
import UserList from '../pages/hr/UserList';
import KPIList from '../pages/hr/KPIList';
import CommissionList from '../pages/hr/CommissionList';
import SalarySchemeList from '../pages/hr/SalarySchemeList';
import KpiRulesList from '../pages/hr/KpiRulesList';
import SalaryRecordList from '../pages/hr/SalaryRecordList';
import SalaryDetail from '../pages/hr/SalaryDetail';
import ManufacturerSubsidyList from '../pages/hr/ManufacturerSubsidyList';
import SalesTargetManage from '../pages/sales/SalesTargetManage';
import AttendancePage from '../pages/attendance/AttendancePage';
import AttendanceMap from '../pages/attendance/AttendanceMap';
import PerformanceDashboard from '../pages/hr/PerformanceDashboard';
import MyDashboard from '../pages/MyDashboard';
import MobileCheckin from '../pages/mobile/MobileCheckin';
import MobileNotifications from '../pages/mobile/MobileNotifications';
import PolicyTemplateList from '../pages/policies/PolicyTemplateList';
import AuditLogList from '../pages/audit/AuditLogList';
import MallOrderList from '../pages/mall/orders/OrderList';
import MallSalesmanList from '../pages/mall/users/SalesmanList';
import MallCategoryTree from '../pages/mall/products/CategoryTree';
import MallProductList from '../pages/mall/products/ProductList';
import MallConsumerList from '../pages/mall/users/ConsumerList';
import MallUserApplicationList from '../pages/mall/users/UserApplicationList';
import MallReturnList from '../pages/mall/orders/ReturnList';
import MallSkipAlertList from '../pages/mall/operations/SkipAlertList';
import MallDashboard from '../pages/mall/Dashboard';
import MallInviteCodeList from '../pages/mall/operations/InviteCodeList';
import MallHousekeepingLogs from '../pages/mall/operations/HousekeepingLogs';
import MallWarehouseList from '../pages/mall/inventory/WarehouseList';
import MallInventoryQuery from '../pages/mall/inventory/InventoryQuery';
import MallNoticeList from '../pages/mall/operations/NoticeList';
import MallSearchKeywords from '../pages/mall/operations/SearchKeywords';
import MallAuditLogList from '../pages/mall/audit/AuditLogList';
import MallLoginLogList from '../pages/mall/audit/LoginLogList';
import MallLoginLogStats from '../pages/mall/audit/LoginLogStats';
import AuthGuard from '../layouts/AuthGuard';
import PolicyApproval from '../pages/approval/PolicyApproval';
import FinanceApproval from '../pages/approval/FinanceApproval';

const routes: RouteObject[] = [
  { path: '/login', element: <Login /> },
  // 手机端（无侧边栏）
  { path: '/m/checkin', element: <AuthGuard><MobileCheckin /></AuthGuard> },
  { path: '/m/notifications', element: <AuthGuard><MobileNotifications /></AuthGuard> },
  {
    path: '/',
    element: <AuthGuard><MainLayout /></AuthGuard>,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: <Dashboard /> },

      // 审批中心
      { path: 'approval/policy', element: <PolicyApproval /> },
      { path: 'approval/finance', element: <FinanceApproval /> },

      // 订单
      { path: 'orders', element: <OrderList /> },
      { path: 'orders/:orderId/stock-out', element: <OrderStockOutPage /> },
      { path: 'orders/:orderId/delivery', element: <OrderDeliveryPage /> },
      { path: 'orders/:orderId/payment', element: <OrderPaymentPage /> },

      // 政策
      { path: 'policies/requests', element: <PolicyRequestList /> },
      { path: 'policies/reconcile', element: <ArrivalReconcile /> },
      { path: 'policies/fulfill', element: <FulfillManage /> },
      { path: 'policies/claims', element: <ClaimList /> },
      { path: 'policies/tasting-mgmt', element: <TastingManagement /> },
      { path: 'policies/dashboard', element: <PolicyDashboard /> },
      { path: 'policies/templates', element: <PolicyTemplateList /> },

      // 库存
      { path: 'inventory/query', element: <InventoryQuery /> },
      { path: 'inventory/stock-flow', element: <StockFlowList /> },
      { path: 'inventory/low-stock', element: <LowStockAlert /> },
      { path: 'inventory/tasting-warehouse', element: <SpecialWarehouseManage /> },
      { path: 'inventory/backup-warehouse', element: <BackupWarehouseManage /> },
      { path: 'inventory/retail-warehouse', element: <RetailWarehouseManage /> },
      { path: 'inventory/wholesale-warehouse', element: <WholesaleWarehouseManage /> },

      // 财务
      { path: 'finance/profit-ledger', element: <ProfitLedger /> },
      { path: 'finance/payment-progress', element: <PaymentProgress /> },
      { path: 'finance/accounts', element: <AuthGuard requiredRoles={['admin', 'boss', 'finance']}><AccountOverview /></AuthGuard> },
      { path: 'finance/cash-flow', element: <CashFlowManage /> },
      { path: 'finance/expenses', element: <ExpenseList /> },
      { path: 'finance/aging', element: <ReceivableAging /> },
      { path: 'finance/financing', element: <FinancingManagement /> },

      // 客户 & 商品
      { path: 'customers', element: <CustomerList /> },
      { path: 'customers/:customerId/360', element: <Customer360 /> },
      { path: 'products', element: <ProductList /> },
      { path: 'brands', element: <BrandList /> },

      // 稽查
      { path: 'inspections/cases', element: <InspectionList /> },
      { path: 'inspections/trace', element: <BarcodeTracePage /> },

      // 采购
      { path: 'purchase/orders', element: <PurchaseOrderList /> },
      { path: 'purchase/receive', element: <ReceiveScanPage /> },

      // 供应商
      { path: 'suppliers', element: <SupplierList /> },

      // 人事
      { path: 'hr/users', element: <UserList /> },
      { path: 'hr/employees', element: <EmployeeList /> },
      { path: 'hr/kpis', element: <KPIList /> },
      { path: 'hr/commissions', element: <CommissionList /> },
      { path: 'hr/salary-schemes', element: <AuthGuard requiredRoles={['admin', 'boss', 'hr']}><SalarySchemeList /></AuthGuard> },
      { path: 'hr/kpi-rules', element: <AuthGuard requiredRoles={['admin', 'boss']}><KpiRulesList /></AuthGuard> },
      { path: 'hr/salaries', element: <AuthGuard requiredRoles={['admin', 'boss', 'hr']}><SalaryRecordList /></AuthGuard> },
      { path: 'hr/salaries/:id', element: <SalaryDetail /> },
      { path: 'hr/manufacturer-subsidies', element: <AuthGuard requiredRoles={['admin', 'boss', 'hr']}><ManufacturerSubsidyList /></AuthGuard> },
      { path: 'sales/targets', element: <AuthGuard requiredRoles={['admin', 'boss', 'sales_manager']}><SalesTargetManage /></AuthGuard> },
      { path: 'attendance', element: <AttendancePage /> },
      { path: 'attendance/map', element: <AttendanceMap /> },
      { path: 'hr/performance', element: <PerformanceDashboard /> },
      { path: 'me', element: <MyDashboard /> },

      // 商城
      { path: 'mall', element: <MallDashboard /> },
      { path: 'mall/dashboard', element: <MallDashboard /> },
      { path: 'mall/orders', element: <MallOrderList /> },
      { path: 'mall/salesmen', element: <MallSalesmanList /> },
      { path: 'mall/categories', element: <MallCategoryTree /> },
      { path: 'mall/products', element: <MallProductList /> },
      { path: 'mall/consumers', element: <MallConsumerList /> },
      { path: 'mall/user-applications', element: <MallUserApplicationList /> },
      { path: 'mall/returns', element: <MallReturnList /> },
      { path: 'mall/skip-alerts', element: <MallSkipAlertList /> },
      { path: 'mall/invite-codes', element: <MallInviteCodeList /> },
      { path: 'mall/housekeeping-logs', element: <AuthGuard requiredRoles={['admin', 'boss']}><MallHousekeepingLogs /></AuthGuard> },
      { path: 'mall/warehouses', element: <MallWarehouseList /> },
      { path: 'mall/inventory', element: <MallInventoryQuery /> },
      { path: 'mall/notices', element: <MallNoticeList /> },
      { path: 'mall/search-keywords', element: <MallSearchKeywords /> },
      { path: 'mall/audit/operations', element: <AuthGuard requiredRoles={['admin', 'boss']}><MallAuditLogList /></AuthGuard> },
      { path: 'mall/audit/login-logs', element: <AuthGuard requiredRoles={['admin', 'boss']}><MallLoginLogList /></AuthGuard> },
      { path: 'mall/audit/login-stats', element: <AuthGuard requiredRoles={['admin', 'boss']}><MallLoginLogStats /></AuthGuard> },

      // 审计
      { path: 'audit-logs', element: <AuthGuard requiredRoles={['admin']}><AuditLogList /></AuthGuard> },
    ],
  },
];

export default routes;
