import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, Col, DatePicker, Input, Row, Select, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs, { type Dayjs } from 'dayjs';
import api from '../../api/client';

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
  resubmit_order: '重新提交订单', confirm_external_policy: '厂家政策确认',
  create_receipt: '客户收款', create_payment: '对外付款',
  create_purchase_order: '创建采购单', approve_purchase_order: '审批采购',
  cancel_purchase_order: '撤销采购', receive_purchase_order: '采购收货',
  create_inspection_case: '新建稽查', execute_inspection_case: '执行稽查',
  create_financing_order: '融资放款', approve_financing_repayment: '融资还款审批',
  create_tasting_wine_usage: '品鉴酒使用', direct_inbound: '直接入库', direct_outbound: '直接出库',
  fulfill_materials: '物料出库', recover_to_stock: '稽查入备用库',
  approve_claim: '审批结算申报', confirm_allocation: '确认分账',
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
};

function AuditLogList() {
  const [entityType, setEntityType] = useState<string | undefined>();
  const [action, setAction] = useState<string | undefined>();
  const [keyword, setKeyword] = useState('');
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);

  const { data: entityTypes = [] } = useQuery<string[]>({
    queryKey: ['audit-entity-types'],
    queryFn: () => api.get('/audit-logs/entity-types').then(r => r.data),
  });
  const { data: actions = [] } = useQuery<string[]>({
    queryKey: ['audit-actions'],
    queryFn: () => api.get('/audit-logs/actions').then(r => r.data),
  });

  const { data, isLoading } = useQuery<AuditLog[]>({
    queryKey: ['audit-logs', entityType, action, keyword, dateRange?.[0]?.format('YYYY-MM-DD'), dateRange?.[1]?.format('YYYY-MM-DD')],
    queryFn: () => {
      const params: Record<string, string> = { limit: '200' };
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
    const entries = Object.entries(v).slice(0, 5);
    const short = entries.map(([k, val]) => `${k}=${typeof val === 'object' ? JSON.stringify(val) : val}`).join(', ');
    return (
      <Tooltip title={<pre style={{ margin: 0, fontSize: 11 }}>{JSON.stringify(v, null, 2)}</pre>}>
        <span style={{ fontSize: 12 }}>{short.slice(0, 80)}{short.length > 80 ? '…' : ''}</span>
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
          <Col><RangePicker value={dateRange} onChange={(v) => setDateRange(v as any)} allowClear /></Col>
          <Col><Text type="secondary">实体</Text></Col>
          <Col><Select placeholder="全部类型" allowClear style={{ width: 150 }} value={entityType}
            onChange={setEntityType} options={entityOpts} showSearch optionFilterProp="label" /></Col>
          <Col><Text type="secondary">动作</Text></Col>
          <Col><Select placeholder="全部动作" allowClear style={{ width: 170 }} value={action}
            onChange={setAction} options={actionOpts} showSearch optionFilterProp="label" /></Col>
          <Col flex="200px"><Input.Search placeholder="搜索关键字" allowClear value={keyword}
            onChange={e => setKeyword(e.target.value)} /></Col>
          <Col>
            <Space>
              <Text type="secondary" style={{ fontSize: 12 }}>共 {data?.length ?? 0} 条</Text>
            </Space>
          </Col>
        </Row>
      </Card>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={data ?? []}
        loading={isLoading}
        size="small"
        pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 1000 }}
      />
    </>
  );
}

export default AuditLogList;
