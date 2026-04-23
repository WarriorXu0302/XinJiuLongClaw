import { Card, Col, Row, Statistic, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { Line, Pie, Column } from '@ant-design/plots';
import api from '../api/client';
import { useBrandStore } from '../stores/brandStore';

const { Title, Text } = Typography;

interface BrandKPI { brand_id: string; brand_name: string; today_order_count: number; pending_policy_count: number; unsettled_claim_amount: number; inventory_value: number; account_balance: number; }
interface Summary { today_order_count: number; pending_policy_count: number; low_stock_count: number; unsettled_claim_amount: number; total_inventory_value: number; by_brand: BrandKPI[]; }
interface TrendPoint { date: string; sales: number; receipt: number }
interface BrandSales { brand_id: string | null; brand_name: string; sales: number }
interface OrderStatus { status: string; count: number }
interface TrendData { trend: TrendPoint[]; brand_sales: BrandSales[]; order_status: OrderStatus[] }

const STATUS_LABEL: Record<string, string> = {
  pending: '待审批', policy_pending_internal: '内部待审', policy_pending_external: '厂家待审',
  approved: '已审批', shipped: '已发货', delivered: '已送达', completed: '已完成',
  policy_rejected: '已驳回',
};

function Dashboard() {
  const brandId = useBrandStore(s => s.selectedBrandId);
  const { data } = useQuery<Summary>({
    queryKey: ['dashboard', brandId],
    queryFn: () => api.get('/dashboard/summary').then(r => r.data),
    refetchInterval: 30000,
  });

  const { data: trendData } = useQuery<TrendData>({
    queryKey: ['dashboard-trend', brandId],
    queryFn: () => api.get('/dashboard/trend', {
      params: { days: 30, ...(brandId ? { brand_id: brandId } : {}) },
    }).then(r => r.data),
    refetchInterval: 60000,
  });

  const brandKPIs = brandId ? data?.by_brand?.filter(b => b.brand_id === brandId) : data?.by_brand;

  // 折线图数据
  const trendChart = (trendData?.trend ?? []).flatMap(t => ([
    { date: t.date, type: '销售', value: t.sales },
    { date: t.date, type: '回款', value: t.receipt },
  ]));
  const trendSum = (trendData?.trend ?? []).reduce((s, t) => ({
    sales: s.sales + t.sales, receipt: s.receipt + t.receipt,
  }), { sales: 0, receipt: 0 });

  return (
    <>
      <Title level={4}>仪表盘</Title>

      {/* 顶部 KPI */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Statistic title="今日订单" value={data?.today_order_count ?? 0} /></Card></Col>
        <Col span={6}><Card><Statistic title="待审政策" value={data?.pending_policy_count ?? 0} styles={{ content: { color: '#faad14' } }} /></Card></Col>
        <Col span={6}><Card><Statistic title="库存总价值" value={data?.total_inventory_value ?? 0} precision={0} prefix="¥" styles={{ content: { color: '#1890ff' } }} /></Card></Col>
        <Col span={6}><Card><Statistic title="未核销金额" value={data?.unsettled_claim_amount ?? 0} precision={0} prefix="¥" styles={{ content: { color: '#ff4d4f' } }} /></Card></Col>
      </Row>

      {/* 趋势图 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={16}>
          <Card title={
            <span>近 30 天销售与回款趋势
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 12 }}>
                累计销售 ¥{trendSum.sales.toLocaleString()} · 回款 ¥{trendSum.receipt.toLocaleString()}
              </Text>
            </span>
          }>
            {trendChart.length > 0 ? (
              <Line
                data={trendChart}
                xField="date"
                yField="value"
                seriesField="type"
                height={260}
                point={{ size: 3 }}
                color={['#1890ff', '#52c41a']}
                smooth
                legend={{ position: 'top-right' }}
                yAxis={{ label: { formatter: (v: string) => `¥${(+v).toLocaleString()}` } }}
              />
            ) : <Text type="secondary">暂无数据</Text>}
          </Card>
        </Col>
        <Col span={8}>
          <Card title="本月各品牌销售">
            {(trendData?.brand_sales?.length ?? 0) > 0 ? (
              <Pie
                data={trendData!.brand_sales.map(b => ({ type: b.brand_name, value: b.sales }))}
                angleField="value"
                colorField="type"
                height={260}
                radius={0.85}
                label={{ type: 'inner', content: (d: any) => `${(d.percent * 100).toFixed(0)}%` }}
                legend={{ position: 'bottom' }}
              />
            ) : <Text type="secondary">暂无数据</Text>}
          </Card>
        </Col>
      </Row>

      {/* 订单状态分布 + 品牌概览 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={10}>
          <Card title="30 天订单状态分布" size="small">
            {(trendData?.order_status?.length ?? 0) > 0 ? (
              <Column
                data={trendData!.order_status.map(s => ({ status: STATUS_LABEL[s.status] ?? s.status, count: s.count }))}
                xField="status"
                yField="count"
                height={220}
                columnStyle={{ radius: [4, 4, 0, 0] }}
                color="#1890ff"
                label={{ position: 'top' }}
              />
            ) : <Text type="secondary">暂无数据</Text>}
          </Card>
        </Col>
        <Col span={14}>
          <Card title="品牌项目概览" size="small">
            <Row gutter={8}>
              {(brandKPIs ?? []).map(b => (
                <Col span={12} key={b.brand_id} style={{ marginBottom: 8 }}>
                  <Card size="small" title={<Tag color="blue">{b.brand_name}</Tag>} bodyStyle={{ padding: 12 }}>
                    <Row gutter={8}>
                      <Col span={12}><Statistic title="今日订单" value={b.today_order_count} styles={{ content: { fontSize: 16 } }} /></Col>
                      <Col span={12}><Statistic title="待审政策" value={b.pending_policy_count} styles={{ content: { fontSize: 16, color: '#faad14' } }} /></Col>
                    </Row>
                    <Row gutter={8} style={{ marginTop: 8 }}>
                      <Col span={12}><Statistic title="库存价值" value={b.inventory_value} precision={0} prefix="¥" styles={{ content: { fontSize: 14, color: '#1890ff' } }} /></Col>
                      <Col span={12}><Statistic title="账户" value={b.account_balance} precision={0} prefix="¥" styles={{ content: { fontSize: 14, color: '#52c41a' } }} /></Col>
                    </Row>
                    {b.unsettled_claim_amount > 0 && (
                      <div style={{ marginTop: 6, fontSize: 12 }}>
                        <Text type="secondary">未核销: </Text>
                        <Text strong style={{ color: '#ff4d4f' }}>¥{b.unsettled_claim_amount.toLocaleString()}</Text>
                      </div>
                    )}
                  </Card>
                </Col>
              ))}
            </Row>
          </Card>
        </Col>
      </Row>
    </>
  );
}

export default Dashboard;
