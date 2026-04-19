import { useState } from 'react';
import { Card, Col, Empty, Image, Progress, Row, Space, Statistic, Table, Tag, Typography } from 'antd';
import { BankOutlined, CheckCircleOutlined, DollarOutlined, ShoppingCartOutlined, TrophyOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { Line } from '@ant-design/plots';
import api from '../api/client';

interface TrendPoint {
  period: string; sales: number; receipt: number;
  sales_target: number; receipt_target: number;
  commission: number; manager_share: number; bonus: number; actual_pay: number;
}
interface TrendData { employee_id: string; employee_name: string; trend: TrendPoint[] }

const { Title, Text } = Typography;

interface AssessItem {
  item_code: string; item_name: string;
  target_value: number; actual_value: number;
  completion_rate: number; earned_amount: number;
}
interface YearTarget { brand_name: string; sales_target: number; receipt_target: number }
interface SalaryHist {
  period: string; total_pay: number; actual_pay: number; status: string;
  payment_voucher_urls?: string[]; paid_at?: string;
}
interface MyData {
  employee_name: string; employee_no: string;
  brand_positions: Array<{ brand_name: string; position: string; is_primary: boolean }>;
  sales_target_month: number; actual_sales: number; sales_completion: number;
  receipt_target_month: number; actual_receipt: number; receipt_completion: number;
  sales_target_year: number; receipt_target_year: number;
  work_days: number; late_times: number; late_over30_times: number;
  leave_days: number; valid_visits: number; is_full_attendance: boolean;
  commission_total: number; manager_share_total: number; subsidy_total: number;
  salary_actual_pay: number; salary_status?: string;
  assessment_items: AssessItem[];
  year_targets: YearTarget[];
  salary_history: SalaryHist[];
}

function MyDashboard() {
  const [period] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
  });

  const { data, isLoading, isError, error } = useQuery<MyData>({
    queryKey: ['my-dashboard', period],
    queryFn: () => api.get('/performance/me', { params: { period } }).then(r => r.data),
    retry: false,
  });

  const { data: trendData } = useQuery<TrendData>({
    queryKey: ['my-trend'],
    queryFn: () => api.get('/performance/employee-trend', { params: { months: 6 } }).then(r => r.data),
  });

  const salesChart = (trendData?.trend ?? []).flatMap(t => ([
    { period: t.period, type: '实际销售', value: t.sales },
    { period: t.period, type: '销售目标', value: t.sales_target },
    { period: t.period, type: '实际回款', value: t.receipt },
    { period: t.period, type: '回款目标', value: t.receipt_target },
  ]));

  const incomeChart = (trendData?.trend ?? []).map(t => ({
    period: t.period,
    提成: t.commission,
    管理提成: t.manager_share,
    达标奖金: t.bonus,
    实发工资: t.actual_pay,
  }));
  const incomeChartFlat = incomeChart.flatMap(r => [
    { period: r.period, type: '提成', value: r.提成 },
    { period: r.period, type: '管理提成', value: r.管理提成 },
    { period: r.period, type: '达标奖金', value: r.达标奖金 },
    { period: r.period, type: '实发工资', value: r.实发工资 },
  ]);

  if (isLoading) return <div>加载中...</div>;
  if (isError) return <Empty description={`无绩效数据：${(error as any)?.response?.data?.detail || '请联系管理员'}`} />;
  if (!data) return null;

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>
          {data.employee_name} <Text type="secondary" style={{ fontSize: 14 }}>{data.employee_no}</Text>
        </Title>
        {data.brand_positions.map((bp, i) => (
          <Tag key={i} color={bp.is_primary ? 'blue' : 'default'}>{bp.brand_name} · {bp.position}</Tag>
        ))}
        <Tag color="gold">{period}</Tag>
      </Space>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title={<><ShoppingCartOutlined /> 本月销售</>}
              value={data.actual_sales} prefix="¥" precision={0}
              valueStyle={{ color: '#1890ff' }} />
            {data.sales_target_month > 0 && (
              <Progress percent={Math.round(data.sales_completion * 100)} size="small"
                status={data.sales_completion >= 1 ? 'success' : data.sales_completion >= 0.5 ? 'active' : 'exception'} />
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              目标 ¥{data.sales_target_month.toLocaleString()} · 年度 ¥{data.sales_target_year.toLocaleString()}
            </Text>
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title={<><BankOutlined /> 本月回款</>}
              value={data.actual_receipt} prefix="¥" precision={0}
              valueStyle={{ color: '#52c41a' }} />
            {data.receipt_target_month > 0 && (
              <Progress percent={Math.round(data.receipt_completion * 100)} size="small"
                status={data.receipt_completion >= 1 ? 'success' : data.receipt_completion >= 0.5 ? 'active' : 'exception'} />
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              目标 ¥{data.receipt_target_month.toLocaleString()} · 年度 ¥{data.receipt_target_year.toLocaleString()}
            </Text>
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title={<><TrophyOutlined /> 本月提成</>}
              value={data.commission_total + data.manager_share_total}
              prefix="¥" precision={2} valueStyle={{ color: '#fa8c16' }} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              销售 ¥{data.commission_total.toFixed(0)}
              {data.manager_share_total > 0 && ` + 管理 ¥${data.manager_share_total.toFixed(0)}`}
              {data.subsidy_total > 0 && ` + 厂家补贴 ¥${data.subsidy_total.toFixed(0)}`}
            </Text>
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title={<><DollarOutlined /> 本月工资</>}
              value={data.salary_actual_pay} prefix="¥" precision={0}
              valueStyle={{ color: '#ff4d4f' }} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {data.salary_status === 'paid' ? <Tag color="green">已发放</Tag>
                : data.salary_status === 'confirmed' ? <Tag color="blue">已确认</Tag>
                : data.salary_status === 'draft' ? <Tag color="orange">草稿</Tag>
                : <Tag>未生成</Tag>}
            </Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card title={<><CheckCircleOutlined /> 本月考勤</>}>
            <Row gutter={16}>
              <Col span={8}>
                <Statistic title="出勤天数" value={data.work_days} suffix="天" />
              </Col>
              <Col span={8}>
                <Statistic title="迟到" value={data.late_times + data.late_over30_times} suffix="次"
                  valueStyle={{ color: data.late_times > 0 || data.late_over30_times > 0 ? '#ff4d4f' : undefined }} />
              </Col>
              <Col span={8}>
                <Statistic title="请假天数" value={data.leave_days} suffix="天"
                  valueStyle={{ color: data.leave_days > 0 ? '#fa8c16' : undefined }} />
              </Col>
            </Row>
            <div style={{ marginTop: 12 }}>
              <Text type="secondary">有效拜访：<Text strong style={{ color: data.valid_visits >= 120 ? '#52c41a' : '#fa8c16' }}>{data.valid_visits} 次</Text></Text>
              {data.is_full_attendance ? <Tag color="green" style={{ marginLeft: 12 }}>全勤</Tag> : <Tag color="red" style={{ marginLeft: 12 }}>非全勤</Tag>}
            </div>
          </Card>
        </Col>

        <Col span={12}>
          <Card title="月度考核项">
            {data.assessment_items.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未设置本月考核项" />
            ) : (
              <Table size="small" pagination={false} dataSource={data.assessment_items} rowKey="item_code"
                columns={[
                  { title: '考核项', dataIndex: 'item_name' },
                  { title: '目标/实际', key: 'val',
                    render: (_, r) => `${r.actual_value.toLocaleString()} / ${r.target_value.toLocaleString()}` },
                  { title: '完成率', dataIndex: 'completion_rate', width: 140,
                    render: (v: number) => <Progress percent={Math.round(v*100)} size="small" /> },
                  { title: '应发', dataIndex: 'earned_amount', align: 'right' as const,
                    render: (v: number) => <Text strong>¥{v.toFixed(0)}</Text> },
                ]} />
            )}
          </Card>
        </Col>
      </Row>

      {/* 个人 6 个月趋势 */}
      {salesChart.length > 0 && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={12}>
            <Card title="近 6 个月销售/回款 目标 vs 实际" size="small">
              <Line
                data={salesChart}
                xField="period"
                yField="value"
                seriesField="type"
                height={240}
                color={['#1890ff', '#91d5ff', '#52c41a', '#b7eb8f']}
                point={{ size: 3 }}
                smooth
                legend={{ position: 'top-right' }}
                yAxis={{ label: { formatter: (v: string) => `¥${(+v/10000).toFixed(1)}万` } }}
              />
            </Card>
          </Col>
          <Col span={12}>
            <Card title="近 6 个月收入结构" size="small">
              <Line
                data={incomeChartFlat}
                xField="period"
                yField="value"
                seriesField="type"
                height={240}
                color={['#1890ff', '#fa8c16', '#eb2f96', '#ff4d4f']}
                point={{ size: 3 }}
                smooth
                legend={{ position: 'top-right' }}
                yAxis={{ label: { formatter: (v: string) => `¥${(+v).toLocaleString()}` } }}
              />
            </Card>
          </Col>
        </Row>
      )}

      <Row gutter={16}>
        <Col span={24}>
          <Card title="近期工资">
            {data.salary_history.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无工资记录" />
            ) : (
              <Table size="small" pagination={false} dataSource={data.salary_history} rowKey="period"
                columns={[
                  { title: '周期', dataIndex: 'period', width: 100 },
                  { title: '应发', dataIndex: 'total_pay', align: 'right' as const,
                    render: (v: number) => `¥${v.toLocaleString()}` },
                  { title: '实发', dataIndex: 'actual_pay', align: 'right' as const,
                    render: (v: number) => <Text strong>¥{v.toLocaleString()}</Text> },
                  { title: '状态', dataIndex: 'status', width: 100,
                    render: (v: string) => v === 'paid' ? <Tag color="green">已发放</Tag>
                      : v === 'confirmed' ? <Tag color="blue">已确认</Tag> : <Tag color="orange">草稿</Tag> },
                  { title: '发放时间', dataIndex: 'paid_at', width: 150,
                    render: (v?: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
                  { title: '转款凭证', dataIndex: 'payment_voucher_urls', width: 160,
                    render: (urls?: string[]) => (urls?.length ?? 0) > 0 ? (
                      <Image.PreviewGroup>
                        <Space size={4}>
                          {urls!.slice(0, 3).map((u, i) => <Image key={i} width={32} height={32} src={u} />)}
                          {urls!.length > 3 && <Text type="secondary">+{urls!.length-3}</Text>}
                        </Space>
                      </Image.PreviewGroup>
                    ) : <Text type="secondary">-</Text> },
                ]} />
            )}
          </Card>
        </Col>
      </Row>
    </>
  );
}

export default MyDashboard;
