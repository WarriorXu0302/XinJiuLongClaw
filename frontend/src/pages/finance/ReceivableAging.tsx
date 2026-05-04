import { Card, Col, Progress, Row, Space, Table, Tabs, Tag, Typography } from 'antd';
import { WarningOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import { Column } from '@ant-design/plots';
import api from '../../api/client';
import { useBrandStore } from '../../stores/brandStore';

const { Title, Text } = Typography;

interface Detail {
  receivable_no: string; customer_name: string;
  amount: number; paid_amount: number; remaining: number;
  due_date?: string; days_overdue: number; order_id?: string;
}
interface Bucket {
  label: string; amount: number; count: number;
  percentage: number; details: Detail[];
}
interface AgingData { total_outstanding: number; buckets: Bucket[] }

const BUCKET_COLOR: Record<string, string> = {
  '0-30': '#52c41a', '30-60': '#1890ff', '60-90': '#fa8c16', '90+': '#ff4d4f',
};

function ReceivableAging() {
  const brandId = useBrandStore(s => s.selectedBrandId);
  const { data, isLoading } = useQuery<AgingData>({
    queryKey: ['receivables-aging', brandId],
    queryFn: () => api.get('/receivables/aging', { params: brandId ? { brand_id: brandId } : {} }).then(r => r.data),
  });

  if (isLoading || !data) return <div>加载中...</div>;

  const chartData = data.buckets.map(b => ({ bucket: b.label + ' 天', amount: b.amount, count: b.count }));

  const detailCols: ColumnsType<Detail> = [
    { title: '应收编号', dataIndex: 'receivable_no', width: 180 },
    { title: '客户', dataIndex: 'customer_name', width: 140 },
    { title: '应收', dataIndex: 'amount', width: 110, align: 'right' as const,
      render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '已收', dataIndex: 'paid_amount', width: 110, align: 'right' as const,
      render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '欠款', dataIndex: 'remaining', width: 120, align: 'right' as const,
      render: (v: number) => <Text strong style={{ color: '#ff4d4f' }}>¥{v.toLocaleString()}</Text> },
    { title: '到期日', dataIndex: 'due_date', width: 110 },
    { title: '账龄', dataIndex: 'days_overdue', width: 110,
      render: (v: number) => <Tag color={v < 30 ? 'green' : v < 60 ? 'blue' : v < 90 ? 'orange' : 'red'}>{v} 天</Tag> },
  ];

  return (
    <>
      <Title level={4}><WarningOutlined /> 应收账龄分析</Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Text>未收款总额</Text>
          <Text strong style={{ fontSize: 22, color: '#ff4d4f' }}>
            ¥{data.total_outstanding.toLocaleString()}
          </Text>
        </Space>
      </Card>

      <Row gutter={12} style={{ marginBottom: 16 }}>
        {data.buckets.map(b => (
          <Col span={6} key={b.label}>
            <Card size="small">
              <Space orientation="vertical" style={{ width: '100%' }}>
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Tag color={BUCKET_COLOR[b.label]}>{b.label} 天</Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>{b.count} 笔</Text>
                </Space>
                <Text strong style={{ fontSize: 18 }}>¥{b.amount.toLocaleString()}</Text>
                <Progress percent={b.percentage} size="small" strokeColor={BUCKET_COLOR[b.label]} />
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      <Card title="账龄分布" size="small" style={{ marginBottom: 12 }}>
        {data.total_outstanding > 0 ? (
          <Column data={chartData} xField="bucket" yField="amount" height={240}
            color={({ bucket }: any) => BUCKET_COLOR[bucket.replace(' 天', '')] ?? '#1890ff'}
            columnStyle={{ radius: [4, 4, 0, 0] }}
            label={{ position: 'top' }} />
        ) : <Text type="secondary">无未收款</Text>}
      </Card>

      <Tabs items={data.buckets.filter(b => b.count > 0).map(b => ({
        key: b.label,
        label: <Tag color={BUCKET_COLOR[b.label]}>{b.label} 天 · {b.count}笔 · ¥{b.amount.toLocaleString()}</Tag>,
        children: (
          <Table<Detail> columns={detailCols} dataSource={b.details} rowKey="receivable_no"
            size="small" pagination={{ pageSize: 20 }} />
        ),
      }))} />
    </>
  );
}

export default ReceivableAging;
