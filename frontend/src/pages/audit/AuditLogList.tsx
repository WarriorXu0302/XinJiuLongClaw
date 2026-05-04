import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, Col, DatePicker, Input, Row, Select, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { type Dayjs } from 'dayjs';
import api, { extractItems } from '../../api/client';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

interface AuditLog {
  id: string;
  action: string;
  entity_type: string;
  entity_id?: string;
  actor_id?: string;
  actor_name?: string;
  actor_type: string;
  changes?: Record<string, unknown>;
  ip_address?: string;
  created_at: string;
}

// 动作友好标签
const ACTION_LABEL: Record<string, string> = {
  create_order: '创建订单', approve_policy: '政策审批', ship_order: '订单发货',
  confirm_delivery: '确认送达', upload_delivery: '上传送达凭证', confirm_payment: '确认收款',
  upload_payment_voucher: '上传收款凭证', resubmit_order: '重新提交订单',
  confirm_external_policy: '厂家政策确认', submit_policy: '提交政策审批',
  create_receipt: '客户收款', create_payment: '对外付款',
  create_purchase_order: '创建采购单', approve_purchase_order: '审批采购',
  cancel_purchase_order: '撤销采购', receive_purchase_order: '采购收货',
  create_inspection_case: '新建稽查', execute_inspection_case: '执行稽查',
  create_financing_order: '融资放款', approve_financing_repayment: '融资还款审批',
  create_tasting_wine_usage: '品鉴酒使用', direct_inbound: '直接入库', direct_outbound: '直接出库',
  fulfill_materials: '物料出库', recover_to_stock: '稽查入备用库',
  approve_claim: '审批结算申报', confirm_allocation: '确认分账',
  upsert_sales_target: '设定销售目标', approve_sales_target: '批准销售目标', reject_sales_target: '驳回销售目标',
  upsert_salary_scheme: '更新薪酬方案', submit_salary: '提交工资审批', approve_salary: '批准工资', reject_salary: '驳回工资',
  pay_salary: '发放工资', batch_pay_salary: '批量发放工资', generate_expected_subsidies: '生成补贴应收',
  confirm_subsidy_arrival: '确认补贴到账', reimburse_manufacturer_subsidy: '厂家补贴报账',
  confirm_payment_request: '确认垫付返还', approve_transfer: '批准资金调拨', reject_transfer: '驳回调拨',
  approve_expense: '批准报销', reject_expense: '驳回报销', pay_expense: '报销付款',
};

// 动作分类颜色
const actionColor = (a: string): string => {
  if (a.startsWith('create')) return 'green';
  if (a.startsWith('approve')) return 'blue';
  if (a.startsWith('cancel') || a.startsWith('delete') || a.startsWith('reject')) return 'red';
  if (a.includes('execute') || a.includes('fulfill')) return 'purple';
  if (a.startsWith('confirm') || a.startsWith('upload')) return 'cyan';
  if (a.startsWith('ship') || a.startsWith('receive')) return 'geekblue';
  return 'default';
};

const ENTITY_LABEL: Record<string, string> = {
  Order: '订单', PurchaseOrder: '采购单', PolicyRequest: '政策申请',
  InspectionCase: '稽查案件', FinancingOrder: '融资单',
  Receipt: '客户收款', Payment: '对外付款', Expense: '报销',
  StockFlow: '库存流水', Account: '账户', ExpenseClaim: '结算申报',
  MarketCleanupCase: '市场清理', TastingWineUsage: '品鉴酒使用',
  PolicyTemplate: '政策模板', Supplier: '供应商',
  SalaryRecord: '工资单', ManufacturerSalarySubsidy: '厂家工资补贴',
  BrandSalaryScheme: '薪酬方案', SalesTarget: '销售目标',
  FinancePaymentRequest: '垫付返还', FundFlow: '资金流水',
  Customer: '客户', Product: '商品', Brand: '品牌',
  Employee: '员工', Commission: '提成', AssessmentItem: '考核项',
};

// 变更详情字段翻译
const CHANGE_KEY_LABEL: Record<string, string> = {
  amount: '金额', source_type: '来源', employee: '员工', period: '周期',
  status: '状态', count: '数量', total: '合计', name: '名称',
  commission: '提成', manager_share: '管理提成', subsidy: '补贴',
  total_pay: '应发', order_count: '订单数', brand_id: '品牌',
  created: '创建数', reason: '原因', approved: '已批准',
};
const SOURCE_TYPE_LABEL: Record<string, string> = {
  customer: '客户付款', employee_advance: '业务员垫付', company_advance: '公司内部',
};

function AuditLogList() {
  const [entityType, setEntityType] = useState<string | undefined>();
  const [action, setAction] = useState<string | undefined>();
  const [keyword, setKeyword] = useState('');
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const { data: entityTypes = [] } = useQuery<string[]>({
    queryKey: ['audit-entity-types'],
    queryFn: () => api.get('/audit-logs/entity-types').then(r => extractItems<string>(r.data)),
  });
  const { data: actions = [] } = useQuery<string[]>({
    queryKey: ['audit-actions'],
    queryFn: () => api.get('/audit-logs/actions').then(r => extractItems<string>(r.data)),
  });

  const { data, isLoading } = useQuery<{ items: AuditLog[]; total: number }>({
    queryKey: ['audit-logs', entityType, action, keyword, dateRange?.[0]?.format('YYYY-MM-DD'), dateRange?.[1]?.format('YYYY-MM-DD'), page, pageSize],
    queryFn: () => {
      const params: Record<string, string | number> = { skip: (page - 1) * pageSize, limit: pageSize };
      if (entityType) params.entity_type = entityType;
      if (action) params.action = action;
      if (keyword) params.keyword = keyword;
      if (dateRange?.[0]) params.date_from = dateRange[0].format('YYYY-MM-DD');
      if (dateRange?.[1]) params.date_to = dateRange[1].format('YYYY-MM-DD');
      return api.get('/audit-logs', { params }).then(r => r.data);
    },
  });

  const renderChanges = (v: Record<string, unknown> | null | undefined) => {
    if (!v || Object.keys(v).length === 0) return <Text type="secondary">-</Text>;
    const formatVal = (key: string, val: unknown): string => {
      if (key === 'source_type' && typeof val === 'string') return SOURCE_TYPE_LABEL[val] ?? val;
      if (typeof val === 'number') return `¥${val.toLocaleString()}`;
      if (typeof val === 'object') return JSON.stringify(val);
      return String(val);
    };
    const entries = Object.entries(v).slice(0, 5);
    const short = entries.map(([k, val]) => `${CHANGE_KEY_LABEL[k] ?? k}：${formatVal(k, val)}`).join('，');
    return (
      <Tooltip title={<div style={{ fontSize: 11 }}>{Object.entries(v).map(([k, val]) => <div key={k}>{CHANGE_KEY_LABEL[k] ?? k}：{formatVal(k, val)}</div>)}</div>}>
        <span style={{ fontSize: 12 }}>{short.slice(0, 100)}{short.length > 100 ? '…' : ''}</span>
      </Tooltip>
    );
  };

  const columns: ColumnsType<AuditLog> = [
    { title: '时间', dataIndex: 'created_at', width: 155, fixed: 'left' as const,
      render: (v: string) => new Date(v).toLocaleString('zh-CN') },
    { title: '操作人', dataIndex: 'actor_name', width: 100,
      render: (v: string, r) => v ? <Text strong>{v}</Text> : (r.actor_id ? <Text type="secondary">{r.actor_id.slice(0, 8)}</Text> : <Text type="secondary">系统</Text>) },
    { title: '动作', dataIndex: 'action', width: 170,
      render: (v: string) => <Tag color={actionColor(v)}>{ACTION_LABEL[v] ?? v}</Tag> },
    { title: '实体类型', dataIndex: 'entity_type', width: 110,
      render: (v: string) => ENTITY_LABEL[v] ?? v },
    { title: '实体编号', dataIndex: 'entity_id', width: 110,
      render: (v: string) => v ? <Text code style={{ fontSize: 11 }}>{v.slice(0, 8)}</Text> : '-' },
    { title: '变更详情', dataIndex: 'changes', render: renderChanges },
    { title: 'IP', dataIndex: 'ip_address', width: 120,
      render: (v: string) => v ? <Text type="secondary" style={{ fontSize: 11 }}>{v}</Text> : '-' },
  ];

  const actionOpts = actions.map(a => ({ value: a, label: ACTION_LABEL[a] ?? a }));
  const entityOpts = entityTypes.map(e => ({ value: e, label: ENTITY_LABEL[e] ?? e }));

  return (
    <>
      <Title level={4} style={{ marginBottom: 12 }}>审计日志</Title>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Row gutter={12} align="middle">
          <Col><Text type="secondary">时间范围</Text></Col>
          <Col><RangePicker value={dateRange} onChange={(v) => { setDateRange(v as any); setPage(1); }} allowClear /></Col>
          <Col><Text type="secondary">实体</Text></Col>
          <Col><Select placeholder="全部类型" allowClear style={{ width: 150 }} value={entityType}
            onChange={(v) => { setEntityType(v); setPage(1); }} options={entityOpts} showSearch optionFilterProp="label" /></Col>
          <Col><Text type="secondary">动作</Text></Col>
          <Col><Select placeholder="全部动作" allowClear style={{ width: 170 }} value={action}
            onChange={(v) => { setAction(v); setPage(1); }} options={actionOpts} showSearch optionFilterProp="label" /></Col>
          <Col flex="200px"><Input.Search placeholder="搜索关键字" allowClear value={keyword}
            onChange={e => { setKeyword(e.target.value); setPage(1); }} /></Col>
          <Col>
            <Space>
              <Text type="secondary" style={{ fontSize: 12 }}>共 {data?.total ?? 0} 条</Text>
            </Space>
          </Col>
        </Row>
      </Card>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={data?.items ?? []}
        loading={isLoading}
        size="small"
        pagination={{ current: page, pageSize, total: data?.total ?? 0, showTotal: t => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }}
        scroll={{ x: 1000 }}
      />
    </>
  );
}

export default AuditLogList;
