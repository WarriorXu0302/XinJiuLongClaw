import { useState, type ReactElement } from 'react';
import { Button, Card, Col, Input, message, Modal, Row, Select, Space, Table, Tabs, Tag, Typography } from 'antd';
import { BankOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';

const { Title, Text } = Typography;

interface Subsidy {
  id: string;
  employee_id: string;
  employee_name: string;
  brand_id: string;
  brand_name: string;
  period: string;
  subsidy_amount: number;
  status: string;
  advanced_at?: string;
  arrival_billcode?: string;
  arrival_at?: string;
  reimbursed_at?: string;
}

interface Brand { id: string; name: string }

function ym(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

const STATUS_TAG: Record<string, ReactElement> = {
  pending: <Tag color="gold">待收（未发薪）</Tag>,
  advanced: <Tag color="orange">已垫付</Tag>,
  reimbursed: <Tag color="green">已到账</Tag>,
};

function ManufacturerSubsidyList() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<string>('pending_advanced');
  const [brandFilter, setBrandFilter] = useState<string | undefined>();
  const [period, setPeriod] = useState<string>('');
  const [genPeriod, setGenPeriod] = useState<string>(ym());
  const [genOpen, setGenOpen] = useState(false);

  const { data: brands = [] } = useQuery<Brand[]>({
    queryKey: ['brands-select'],
    queryFn: () => api.get('/products/brands').then(r => r.data),
  });

  const statusParam = tab === 'pending_advanced' ? undefined : 'reimbursed';
  const { data: allData = [], isLoading } = useQuery<Subsidy[]>({
    queryKey: ['subsidies', brandFilter, period, tab],
    queryFn: () => {
      const params: Record<string, string> = {};
      if (brandFilter) params.brand_id = brandFilter;
      if (period) params.period = period;
      if (statusParam) params.status = statusParam;
      return api.get('/payroll/manufacturer-subsidies', { params }).then(r => r.data);
    },
  });

  const data = tab === 'pending_advanced'
    ? allData.filter(r => r.status === 'pending' || r.status === 'advanced')
    : allData;

  const genMut = useMutation({
    mutationFn: (p: string) => api.post('/payroll/manufacturer-subsidies/generate-expected', { period: p }),
    onSuccess: (r: any) => {
      message.success(r.data.detail);
      setGenOpen(false);
      qc.invalidateQueries({ queryKey: ['subsidies'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '生成失败'),
  });

  // 按品牌+周期聚合
  const groupByBrandPeriod: Record<string, { brand_id: string; brand_name: string; period: string; total: number; pending: number; advanced: number; items: Subsidy[] }> = {};
  data.forEach(r => {
    const key = `${r.brand_id}|${r.period}`;
    if (!groupByBrandPeriod[key]) {
      groupByBrandPeriod[key] = { brand_id: r.brand_id, brand_name: r.brand_name, period: r.period, total: 0, pending: 0, advanced: 0, items: [] };
    }
    const g = groupByBrandPeriod[key];
    g.total += r.subsidy_amount;
    if (r.status === 'pending') g.pending += r.subsidy_amount;
    if (r.status === 'advanced') g.advanced += r.subsidy_amount;
    g.items.push(r);
  });
  const groups = Object.values(groupByBrandPeriod).sort((a, b) => b.period.localeCompare(a.period));

  const totalPending = groups.reduce((s, g) => s + g.pending, 0);
  const totalAdvanced = groups.reduce((s, g) => s + g.advanced, 0);
  const totalReimbursed = allData.filter(r => r.status === 'reimbursed').reduce((s, r) => s + r.subsidy_amount, 0);

  const columns: ColumnsType<Subsidy> = [
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    { title: '品牌', dataIndex: 'brand_name', width: 120,
      render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '周期', dataIndex: 'period', width: 100 },
    { title: '补贴金额', dataIndex: 'subsidy_amount', width: 110, align: 'right' as const,
      render: (v: number) => <Text strong>¥{v.toLocaleString()}</Text> },
    { title: '状态', dataIndex: 'status', width: 130,
      render: (v: string) => STATUS_TAG[v] ?? <Tag>{v}</Tag> },
    { title: '垫付时间', dataIndex: 'advanced_at', width: 150,
      render: (v?: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
    { title: '厂家到账', key: 'arr', width: 180,
      render: (_, r) => r.arrival_at ? (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{new Date(r.arrival_at).toLocaleString('zh-CN')}</Text>
          {r.arrival_billcode && <Text type="secondary" style={{ fontSize: 11 }}>单据 {r.arrival_billcode}</Text>}
        </Space>
      ) : <Text type="secondary">-</Text> },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}><BankOutlined /> 厂家工资补贴</Title>
        <Space>
          <Button icon={<ThunderboltOutlined />} type="primary" style={{ background: '#722ed1' }}
            onClick={() => setGenOpen(true)}>生成本月应收</Button>
        </Space>
      </div>

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small"><Text type="secondary">待收（未发薪）</Text><div style={{ fontSize: 18, fontWeight: 600, color: '#faad14' }}>¥{totalPending.toLocaleString()}</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">已垫付</Text><div style={{ fontSize: 18, fontWeight: 600, color: '#fa8c16' }}>¥{totalAdvanced.toLocaleString()}</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">已到账累计</Text><div style={{ fontSize: 18, fontWeight: 600, color: '#52c41a' }}>¥{totalReimbursed.toLocaleString()}</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">品牌×周期分组</Text><div style={{ fontSize: 18, fontWeight: 600 }}>{groups.length} 组</div></Card></Col>
      </Row>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <span>品牌</span>
          <Select placeholder="全部" allowClear style={{ width: 150 }} value={brandFilter}
            onChange={setBrandFilter} options={brands.map(b => ({ value: b.id, label: b.name }))} />
          <span>周期</span>
          <Input style={{ width: 120 }} placeholder="2026-04 留空=全部" value={period}
            onChange={e => setPeriod(e.target.value)} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            对账入口在 <a href="/policies/reconcile">政策到账对账</a>（Excel 上传，金额+周期自动匹配）
          </Text>
        </Space>
      </Card>

      <Tabs activeKey={tab} onChange={setTab} items={[
        {
          key: 'pending_advanced',
          label: <span>待到账 <Tag color="orange">{groups.reduce((s, g) => s + g.items.filter(i => i.status !== 'reimbursed').length, 0)}</Tag></span>,
          children: (
            <>
              <Card size="small" style={{ marginBottom: 12 }}>
                <Text strong>按品牌×周期聚合（对账单应付金额）</Text>
                <Table dataSource={groups} rowKey={(r) => `${r.brand_id}|${r.period}`} size="small" pagination={false}
                  style={{ marginTop: 8 }}
                  columns={[
                    { title: '品牌', dataIndex: 'brand_name', width: 150, render: (v) => <Tag color="blue">{v}</Tag> },
                    { title: '周期', dataIndex: 'period', width: 100 },
                    { title: '人数', key: 'cnt', width: 80, render: (_, r) => r.items.length },
                    { title: '应收合计', dataIndex: 'total', align: 'right' as const, width: 120,
                      render: (v: number) => <Text strong style={{ color: '#fa8c16', fontSize: 14 }}>¥{v.toLocaleString()}</Text> },
                    { title: '其中未发薪', dataIndex: 'pending', align: 'right' as const, width: 120,
                      render: (v: number) => v > 0 ? `¥${v.toLocaleString()}` : <Text type="secondary">-</Text> },
                    { title: '其中已垫付', dataIndex: 'advanced', align: 'right' as const, width: 120,
                      render: (v: number) => v > 0 ? `¥${v.toLocaleString()}` : <Text type="secondary">-</Text> },
                  ]} />
              </Card>
              <Table<Subsidy> columns={columns} dataSource={data} rowKey="id" loading={isLoading}
                pagination={{ pageSize: 50 }} size="small" />
            </>
          )
        },
        {
          key: 'reimbursed',
          label: <span>已到账</span>,
          children: (
            <Table<Subsidy> columns={columns} dataSource={allData} rowKey="id" loading={isLoading}
              pagination={{ pageSize: 50 }} size="small" />
          )
        },
      ]} />

      <Modal title="生成本月厂家补贴应收" open={genOpen}
        onOk={() => genMut.mutate(genPeriod)}
        onCancel={() => setGenOpen(false)} confirmLoading={genMut.isPending}
        okText="生成" destroyOnHidden>
        <p>系统会按"员工×品牌"的补贴配置，为 <b>{genPeriod}</b> 挂账 <Tag color="gold">pending</Tag> 应收记录。</p>
        <ul>
          <li>已存在的记录会跳过（幂等）</li>
          <li>发薪时自动升级为"已垫付"</li>
          <li>厂家对账单到账后在"政策到账对账"页统一核销，钱进 F 类账户</li>
        </ul>
        <Space>
          <span>周期：</span>
          <Input style={{ width: 120 }} value={genPeriod} onChange={e => setGenPeriod(e.target.value)} placeholder="2026-04" />
        </Space>
      </Modal>
    </>
  );
}

export default ManufacturerSubsidyList;
