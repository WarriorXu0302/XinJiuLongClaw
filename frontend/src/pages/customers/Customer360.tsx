import { Card, Col, Descriptions, Empty, Row, Space, Statistic, Table, Tabs, Tag, Typography } from 'antd';
import { ArrowLeftOutlined, BankOutlined, CalendarOutlined, FileTextOutlined, ShoppingOutlined, UserOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';

const { Title, Text } = Typography;

interface Customer360Data {
  customer: {
    id: string; name: string; phone?: string; address?: string;
    customer_type?: string; settlement_mode?: string; credit_days?: number; status: string;
  };
  summary: {
    total_orders: number; total_sales: number;
    total_received: number; total_outstanding: number;
    visits_count: number; policies_count: number;
  };
  orders: Array<{
    id: string; order_no: string; total_amount: number;
    status: string; payment_status: string;
    salesman_name?: string; brand_name?: string; created_at: string;
  }>;
  receipts: Array<{
    id: string; receipt_no: string; amount: number;
    receipt_date?: string; payment_method?: string; order_id?: string;
  }>;
  receivables: Array<{
    id: string; receivable_no: string; amount: number; paid_amount: number;
    remaining: number; due_date?: string; status: string; order_id?: string;
  }>;
  visits: Array<{
    id: string; employee_name?: string; visit_date?: string;
    enter_time?: string; leave_time?: string;
    duration_minutes?: number; is_valid: boolean;
  }>;
  policies: Array<{
    id: string; status: string; usage_purpose?: string;
    total_policy_value: number; request_source: string; created_at: string;
  }>;
}

function Customer360() {
  const { customerId } = useParams<{ customerId: string }>();
  const navigate = useNavigate();

  const { data, isLoading, isError } = useQuery<Customer360Data>({
    queryKey: ['customer-360', customerId],
    queryFn: () => api.get(`/customers/${customerId}/360`).then(r => r.data),
    enabled: !!customerId,
  });

  if (isLoading) return <div>加载中...</div>;
  if (isError || !data) return <Empty description="客户数据加载失败" />;

  const orderCols: ColumnsType<Customer360Data['orders'][0]> = [
    { title: '订单号', dataIndex: 'order_no', width: 180 },
    { title: '品牌', dataIndex: 'brand_name', width: 100,
      render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-' },
    { title: '业务员', dataIndex: 'salesman_name', width: 80 },
    { title: '金额', dataIndex: 'total_amount', width: 110, align: 'right' as const,
      render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '订单状态', dataIndex: 'status', width: 110 },
    { title: '付款', dataIndex: 'payment_status', width: 100,
      render: (v: string) => {
        const m: Record<string, {c: string; t: string}> = {
          fully_paid: { c: 'green', t: '已付清' },
          pending_confirmation: { c: 'gold', t: '待审批' },
          partially_paid: { c: 'orange', t: '部分' },
          unpaid: { c: 'red', t: '未付' },
        };
        const e = m[v] ?? { c: 'default', t: v };
        return <Tag color={e.c}>{e.t}</Tag>;
      } },
    { title: '时间', dataIndex: 'created_at', width: 150 },
  ];

  const receiptCols: ColumnsType<Customer360Data['receipts'][0]> = [
    { title: '收款号', dataIndex: 'receipt_no', width: 180 },
    { title: '日期', dataIndex: 'receipt_date', width: 110 },
    { title: '金额', dataIndex: 'amount', width: 120, align: 'right' as const,
      render: (v: number) => <Text strong style={{ color: '#52c41a' }}>¥{v.toLocaleString()}</Text> },
    { title: '方式', dataIndex: 'payment_method', width: 100 },
    { title: '订单', dataIndex: 'order_id', width: 100,
      render: (v: string) => v ? <Text code style={{ fontSize: 11 }}>{v.slice(0, 8)}</Text> : '-' },
  ];

  const recvCols: ColumnsType<Customer360Data['receivables'][0]> = [
    { title: '应收号', dataIndex: 'receivable_no', width: 180 },
    { title: '应收', dataIndex: 'amount', width: 110, align: 'right' as const,
      render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '已收', dataIndex: 'paid_amount', width: 110, align: 'right' as const,
      render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '欠款', dataIndex: 'remaining', width: 110, align: 'right' as const,
      render: (v: number) => v > 0 ? <Text strong style={{ color: '#ff4d4f' }}>¥{v.toLocaleString()}</Text> : '-' },
    { title: '到期', dataIndex: 'due_date', width: 110 },
    { title: '状态', dataIndex: 'status', width: 90,
      render: (v: string) => <Tag color={v === 'paid' ? 'green' : v === 'partial' ? 'orange' : 'red'}>{v}</Tag> },
  ];

  const visitCols: ColumnsType<Customer360Data['visits'][0]> = [
    { title: '日期', dataIndex: 'visit_date', width: 110 },
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    { title: '进店', dataIndex: 'enter_time', width: 160 },
    { title: '出店', dataIndex: 'leave_time', width: 160,
      render: (v: string) => v || <Tag color="orange">进行中</Tag> },
    { title: '时长', dataIndex: 'duration_minutes', width: 90,
      render: (v: number) => v != null ? `${v} 分钟` : '-' },
    { title: '有效', dataIndex: 'is_valid', width: 80,
      render: (v: boolean) => v ? <Tag color="green">有效</Tag> : <Tag>-</Tag> },
  ];

  const policyCols: ColumnsType<Customer360Data['policies'][0]> = [
    { title: '来源', dataIndex: 'request_source', width: 90 },
    { title: '用途', dataIndex: 'usage_purpose', width: 200 },
    { title: '政策价值', dataIndex: 'total_policy_value', width: 120, align: 'right' as const,
      render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '状态', dataIndex: 'status', width: 120 },
    { title: '时间', dataIndex: 'created_at', width: 160 },
  ];

  const c = data.customer;
  const s = data.summary;

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <a onClick={() => navigate('/customers')}><ArrowLeftOutlined /> 返回客户列表</a>
        <Title level={3} style={{ margin: 0, marginLeft: 16 }}>
          <UserOutlined /> {c.name}
        </Title>
        <Tag color={c.status === 'active' ? 'green' : 'default'}>{c.status}</Tag>
      </Space>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Descriptions column={3} size="small">
          <Descriptions.Item label="电话">{c.phone || '-'}</Descriptions.Item>
          <Descriptions.Item label="地址">{c.address || '-'}</Descriptions.Item>
          <Descriptions.Item label="客户类型">{c.customer_type || '-'}</Descriptions.Item>
          <Descriptions.Item label="结算方式">{c.settlement_mode === 'credit' ? '信用' : c.settlement_mode === 'cash' ? '现金' : c.settlement_mode}</Descriptions.Item>
          <Descriptions.Item label="账期">{c.credit_days != null ? `${c.credit_days} 天` : '-'}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col span={4}><Card><Statistic title={<><ShoppingOutlined /> 订单</>} value={s.total_orders} suffix="单" /></Card></Col>
        <Col span={5}><Card><Statistic title="销售总额" value={s.total_sales} precision={0} prefix="¥" styles={{ content: { color: '#1890ff' } }} /></Card></Col>
        <Col span={5}><Card><Statistic title="累计回款" value={s.total_received} precision={0} prefix="¥" styles={{ content: { color: '#52c41a' } }} /></Card></Col>
        <Col span={5}><Card><Statistic title={<><BankOutlined /> 未收款</>} value={s.total_outstanding} precision={0} prefix="¥" styles={{ content: { color: '#ff4d4f' } }} /></Card></Col>
        <Col span={5}><Card><Statistic title={<><CalendarOutlined /> 拜访</>} value={s.visits_count} suffix="次" /></Card></Col>
      </Row>

      <Tabs defaultActiveKey="orders" items={[
        {
          key: 'orders',
          label: `订单 (${s.total_orders})`,
          children: (
            <Table<Customer360Data['orders'][0]>
              columns={orderCols} dataSource={data.orders} rowKey="id" size="small"
              pagination={{ pageSize: 20 }} />
          ),
        },
        {
          key: 'receipts',
          label: `收款 (${data.receipts.length})`,
          children: (
            <Table<Customer360Data['receipts'][0]>
              columns={receiptCols} dataSource={data.receipts} rowKey="id" size="small"
              pagination={{ pageSize: 20 }} />
          ),
        },
        {
          key: 'receivables',
          label: `应收 (${data.receivables.length})`,
          children: (
            <Table<Customer360Data['receivables'][0]>
              columns={recvCols} dataSource={data.receivables} rowKey="id" size="small"
              pagination={{ pageSize: 20 }} />
          ),
        },
        {
          key: 'policies',
          label: <><FileTextOutlined /> 政策 ({s.policies_count})</>,
          children: (
            <Table<Customer360Data['policies'][0]>
              columns={policyCols} dataSource={data.policies} rowKey="id" size="small"
              pagination={{ pageSize: 20 }} />
          ),
        },
        {
          key: 'visits',
          label: `拜访 (${s.visits_count})`,
          children: (
            <Table<Customer360Data['visits'][0]>
              columns={visitCols} dataSource={data.visits} rowKey="id" size="small"
              pagination={{ pageSize: 20 }} />
          ),
        },
      ]} />
    </>
  );
}

export default Customer360;
