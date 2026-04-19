import { Card, Col, Row, Statistic, Table, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

const { Title, Text } = Typography;

interface RequestItem {
  id: string; name: string; benefit_type: string; total_value: number;
  fulfill_status: string; settled_amount: number; advance_payer_type?: string;
}

interface PolicyRequest {
  id: string; order_id?: string; usage_purpose?: string; brand_id?: string; status: string;
  total_policy_value?: number; total_gap?: number; settlement_mode?: string;
  request_items: RequestItem[]; created_at: string;
}

const FULFILL_COLOR: Record<string, string> = { pending: 'default', applied: 'blue', fulfilled: 'green', settled: 'cyan' };
const FULFILL_LABEL: Record<string, string> = { pending: '待兑付', applied: '已申请', fulfilled: '已兑付', settled: '已到账' };

function PolicyDashboard() {
  const { brandId, params } = useBrandFilter();

  const { data: requests = [], isLoading } = useQuery<PolicyRequest[]>({
    queryKey: ['policy-dashboard', brandId],
    queryFn: () => api.get('/policies/requests', { params: { ...params, limit: '500' } }).then(r => r.data),
  });

  const approvedRequests = requests.filter(r => r.status === 'approved' && r.request_items?.length > 0);
  const allItems = approvedRequests.flatMap(r => r.request_items);

  // Summary
  const totalPolicyValue = allItems.reduce((s, i) => s + i.total_value, 0);
  const totalSettled = allItems.reduce((s, i) => s + i.settled_amount, 0);
  const totalFulfilled = allItems.filter(i => ['fulfilled', 'settled'].includes(i.fulfill_status)).reduce((s, i) => s + i.total_value, 0);
  const totalPending = allItems.filter(i => i.fulfill_status === 'pending').reduce((s, i) => s + i.total_value, 0);
  const totalApplied = allItems.filter(i => i.fulfill_status === 'applied').reduce((s, i) => s + i.total_value, 0);
  const policyReceivable = totalPolicyValue - totalSettled; // 厂家还欠的

  // By payer type
  const byPayer: Record<string, { value: number; settled: number }> = {};
  allItems.forEach(i => {
    const pt = i.advance_payer_type ?? 'unknown';
    if (!byPayer[pt]) byPayer[pt] = { value: 0, settled: 0 };
    byPayer[pt].value += i.total_value;
    byPayer[pt].settled += i.settled_amount;
  });

  const PAYER_LABEL: Record<string, string> = { customer: '客户垫付', employee: '业务垫付', company: '公司垫付', unknown: '未指定' };

  // Overdue items: fulfilled but not yet applied for > 30 days
  const now = Date.now();
  const overdueItems = allItems.filter(i => {
    if (i.fulfill_status !== 'fulfilled') return false;
    return true; // all fulfilled but not yet settled are "overdue candidates"
  });

  // Table: all items flat
  const itemColumns: ColumnsType<RequestItem & { _purpose: string; _created: string }> = [
    { title: '政策申请', dataIndex: '_purpose', width: 200, ellipsis: true },
    { title: '政策项', dataIndex: 'name', width: 150 },
    { title: '类型', dataIndex: 'benefit_type', width: 90, render: (v: string) => <Tag>{v}</Tag> },
    { title: '价值', dataIndex: 'total_value', width: 100, align: 'right', render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '已到账', dataIndex: 'settled_amount', width: 100, align: 'right', render: (v: number) => v > 0 ? <Text type="success">¥{Number(v).toLocaleString()}</Text> : '-' },
    { title: '未到账', key: 'unsettled', width: 100, align: 'right', render: (_, r) => { const v = r.total_value - r.settled_amount; return v > 0 ? <Text type="warning">¥{Number(v).toLocaleString()}</Text> : <Text type="success">已结清</Text>; } },
    { title: '兑付状态', dataIndex: 'fulfill_status', width: 90, render: (v: string) => <Tag color={FULFILL_COLOR[v]}>{FULFILL_LABEL[v] ?? v}</Tag> },
    { title: '创建时间', dataIndex: '_created', width: 150 },
  ];

  const tableData = approvedRequests.flatMap(r =>
    r.request_items.map(i => ({ ...i, _purpose: r.usage_purpose ?? r.id.slice(0, 8), _created: r.created_at?.replace('T', ' ').slice(0, 19) }))
  );

  return (
    <>
      <Title level={4} style={{ marginBottom: 16 }}>政策应收对账</Title>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}><Card size="small"><Statistic title="政策总价值" value={totalPolicyValue} precision={0} prefix="¥" valueStyle={{ color: '#1890ff' }} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="待兑付" value={totalPending} precision={0} prefix="¥" valueStyle={{ color: '#fa8c16' }} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="已申请" value={totalApplied} precision={0} prefix="¥" valueStyle={{ color: '#1890ff' }} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="已兑付" value={totalFulfilled} precision={0} prefix="¥" valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="已到账" value={totalSettled} precision={0} prefix="¥" valueStyle={{ color: '#722ed1' }} /></Card></Col>
        <Col span={4}><Card size="small" style={{ background: policyReceivable > 0 ? '#fff7e6' : '#f6ffed' }}><Statistic title="政策应收" value={policyReceivable} precision={0} prefix="¥" valueStyle={{ color: policyReceivable > 0 ? '#ff4d4f' : '#52c41a', fontWeight: 600 }} /></Card></Col>
      </Row>

      {/* By payer type */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {Object.entries(byPayer).map(([pt, stats]) => (
          <Col span={6} key={pt}>
            <Card size="small" title={PAYER_LABEL[pt] ?? pt}>
              <Row gutter={16}>
                <Col span={12}><Statistic title="政策价值" value={stats.value} precision={0} prefix="¥" valueStyle={{ fontSize: 16 }} /></Col>
                <Col span={12}><Statistic title="已到账" value={stats.settled} precision={0} prefix="¥" valueStyle={{ fontSize: 16, color: '#52c41a' }} /></Col>
              </Row>
            </Card>
          </Col>
        ))}
      </Row>

      {overdueItems.length > 0 && (
        <Card size="small" style={{ marginBottom: 16, background: '#fff1f0', borderColor: '#ffa39e' }}>
          <Text type="danger" strong>预警：{overdueItems.length} 项已兑付但未到账，请尽快向厂家申报</Text>
        </Card>
      )}

      <Table
        columns={itemColumns}
        dataSource={tableData}
        rowKey="id"
        loading={isLoading}
        size="small"
        pagination={{ pageSize: 50 }}
      />
    </>
  );
}

export default PolicyDashboard;
