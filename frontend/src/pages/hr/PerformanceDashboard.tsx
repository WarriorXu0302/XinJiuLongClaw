import { useState } from 'react';
import { Button, Card, Col, Input, message, Progress, Row, Space, Table, Tabs, Tag, Typography } from 'antd';
import { Line } from '@ant-design/plots';
import { DownloadOutlined, SyncOutlined } from '@ant-design/icons';
import * as XLSX from 'xlsx';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';

const { Title, Text } = Typography;

interface TrendPoint {
  period: string; sales: number; receipt: number;
  sales_target: number; receipt_target: number;
  commission: number; manager_share: number; bonus: number; actual_pay: number;
}

function EmployeeTrendChart({ employeeId }: { employeeId: string }) {
  const { data, isLoading } = useQuery<{ trend: TrendPoint[] }>({
    queryKey: ['emp-trend', employeeId],
    queryFn: () => api.get('/performance/employee-trend', { params: { employee_id: employeeId, months: 6 } }).then(r => r.data),
  });
  if (isLoading || !data) return <Text type="secondary">加载中...</Text>;
  const salesChart = data.trend.flatMap(t => ([
    { period: t.period, type: '实际销售', value: t.sales },
    { period: t.period, type: '销售目标', value: t.sales_target },
    { period: t.period, type: '实际回款', value: t.receipt },
    { period: t.period, type: '回款目标', value: t.receipt_target },
  ]));
  const payChart = data.trend.flatMap(t => ([
    { period: t.period, type: '提成', value: t.commission },
    { period: t.period, type: '管理提成', value: t.manager_share },
    { period: t.period, type: '达标奖金', value: t.bonus },
    { period: t.period, type: '实发工资', value: t.actual_pay },
  ]));
  return (
    <Row gutter={12}>
      <Col span={12}>
        <Card size="small" title="销售/回款目标达成">
          <Line data={salesChart} xField="period" yField="value" seriesField="type"
            height={220} point={{ size: 3 }} smooth
            color={['#1890ff', '#91d5ff', '#52c41a', '#b7eb8f']}
            legend={{ position: 'top-right' }} />
        </Card>
      </Col>
      <Col span={12}>
        <Card size="small" title="收入结构">
          <Line data={payChart} xField="period" yField="value" seriesField="type"
            height={220} point={{ size: 3 }} smooth
            color={['#1890ff', '#fa8c16', '#eb2f96', '#ff4d4f']}
            legend={{ position: 'top-right' }} />
        </Card>
      </Col>
    </Row>
  );
}

interface AssessItem {
  item_code: string; item_name: string;
  target_value: number; actual_value: number;
  completion_rate: number; earned_amount: number;
}
interface Row {
  employee_id: string; employee_name: string; employee_no: string; position?: string;
  brand_positions: Array<{ brand_name: string; position: string; is_primary: boolean }>;
  sales_target_month: number; actual_sales: number; sales_completion: number;
  receipt_target_month: number; actual_receipt: number; receipt_completion: number;
  work_days: number; late_times: number; late_over30_times: number;
  leave_days: number; overtime_off_days: number; valid_visits: number;
  is_full_attendance: boolean;
  commission_total: number; manager_share_total: number; subsidy_total: number;
  salary_actual_pay: number; salary_status?: string;
  assessment_items: AssessItem[];
}

const ym = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
};

function PerformanceDashboard() {
  const qc = useQueryClient();
  const [period, setPeriod] = useState(ym());

  const { data = [], isLoading, refetch } = useQuery<Row[]>({
    queryKey: ['performance-monthly', period],
    queryFn: () => api.get(`/performance/employee-monthly`, { params: { period } }).then(r => r.data),
  });

  const refreshMut = useMutation({
    mutationFn: () => api.post(`/performance/refresh-assessment-actual?period=${period}`),
    onSuccess: (r: any) => {
      message.success(r.data.detail);
      qc.invalidateQueries({ queryKey: ['performance-monthly'] });
    },
  });

  const initMut = useMutation({
    mutationFn: () => api.post(`/performance/init-assessment-items?period=${period}`),
    onSuccess: (r: any) => {
      message.success(r.data.detail);
      qc.invalidateQueries({ queryKey: ['performance-monthly'] });
    },
  });

  const columns: ColumnsType<Row> = [
    { title: '员工', dataIndex: 'employee_name', width: 100, fixed: 'left' as const,
      render: (v: string) => <Text strong>{v}</Text> },
    { title: '岗位', key: 'bp', width: 160,
      render: (_, r) => r.brand_positions.length === 0 ? <Text type="secondary">-</Text>
        : <Space size={2} wrap>
          {r.brand_positions.map((bp, i) => (
            <Tag key={i} color={bp.is_primary ? 'blue' : 'default'}>{bp.brand_name}·{bp.position}</Tag>
          ))}
        </Space> },
    { title: '销售目标', dataIndex: 'sales_target_month', width: 100, align: 'right' as const,
      render: (v: number) => v > 0 ? `¥${v.toLocaleString()}` : '-' },
    { title: '实际销售', dataIndex: 'actual_sales', width: 100, align: 'right' as const,
      render: (v: number) => <Text style={{ color: '#1890ff' }}>¥{v.toLocaleString()}</Text> },
    { title: '销售完成', dataIndex: 'sales_completion', width: 120,
      render: (v: number, r) => r.sales_target_month > 0 ? (
        <Progress percent={Math.round(v*100)} size="small"
          status={v >= 1 ? 'success' : v >= 0.8 ? 'normal' : v >= 0.5 ? 'active' : 'exception'} />
      ) : <Text type="secondary">-</Text> },
    { title: '回款目标', dataIndex: 'receipt_target_month', width: 100, align: 'right' as const,
      render: (v: number) => v > 0 ? `¥${v.toLocaleString()}` : '-' },
    { title: '实际回款', dataIndex: 'actual_receipt', width: 100, align: 'right' as const,
      render: (v: number) => <Text style={{ color: '#52c41a' }}>¥{v.toLocaleString()}</Text> },
    { title: '回款完成', dataIndex: 'receipt_completion', width: 120,
      render: (v: number, r) => r.receipt_target_month > 0 ? (
        <Progress percent={Math.round(v*100)} size="small"
          status={v >= 1 ? 'success' : v >= 0.8 ? 'normal' : v >= 0.5 ? 'active' : 'exception'} />
      ) : <Text type="secondary">-</Text> },
    { title: '出勤/迟到/请假', key: 'att', width: 170,
      render: (_, r) => (
        <Space size={4} wrap>
          <Tag>{r.work_days}天</Tag>
          {r.late_times > 0 && <Tag color="orange">迟{r.late_times}</Tag>}
          {r.late_over30_times > 0 && <Tag color="red">严迟{r.late_over30_times}</Tag>}
          {r.leave_days > 0 && <Tag color="purple">假{r.leave_days}天</Tag>}
          {r.is_full_attendance && <Tag color="green">全勤</Tag>}
        </Space>
      ) },
    { title: '有效拜访', dataIndex: 'valid_visits', width: 90, align: 'center' as const,
      render: (v: number) => <Tag color={v >= 120 ? 'green' : v >= 80 ? 'blue' : 'orange'}>{v} 次</Tag> },
    { title: '本月提成', dataIndex: 'commission_total', width: 110, align: 'right' as const,
      render: (v: number) => v > 0 ? <Text style={{ color: '#1890ff' }}>¥{v.toLocaleString()}</Text> : '-' },
    { title: '管理提成', dataIndex: 'manager_share_total', width: 100, align: 'right' as const,
      render: (v: number) => v > 0 ? <Text style={{ color: '#fa8c16' }}>¥{v.toLocaleString()}</Text> : '-' },
    { title: '厂家补贴', dataIndex: 'subsidy_total', width: 100, align: 'right' as const,
      render: (v: number) => v > 0 ? <Text style={{ color: '#52c41a' }}>¥{v.toLocaleString()}</Text> : '-' },
    { title: '实发工资', dataIndex: 'salary_actual_pay', width: 110, align: 'right' as const,
      render: (v: number, r) => v > 0 ? (
        <Space direction="vertical" size={0}>
          <Text strong style={{ color: '#ff4d4f' }}>¥{v.toLocaleString()}</Text>
          {r.salary_status === 'paid' ? <Tag color="green">已发</Tag>
            : r.salary_status === 'confirmed' ? <Tag color="blue">已确认</Tag>
            : <Tag color="orange">草稿</Tag>}
        </Space>
      ) : <Text type="secondary">未生成</Text> },
  ];

  const expandedRowRender = (r: Row) => {
    return (
      <Tabs size="small" defaultActiveKey="kpi" items={[
        {
          key: 'kpi',
          label: '本月考核项',
          children: r.assessment_items.length === 0 ? <Text type="secondary">未设置本月考核项</Text> : (
            <Table size="small" pagination={false} dataSource={r.assessment_items} rowKey="item_code"
              columns={[
                { title: '考核项', dataIndex: 'item_name', width: 140 },
                { title: '目标值', dataIndex: 'target_value', width: 110, align: 'right' as const,
                  render: (v: number) => v.toLocaleString() },
                { title: '实际值', dataIndex: 'actual_value', width: 110, align: 'right' as const,
                  render: (v: number) => v.toLocaleString() },
                { title: '完成率', dataIndex: 'completion_rate', width: 120,
                  render: (v: number) => <Progress percent={Math.round(v*100)} size="small" /> },
                { title: '应发金额', dataIndex: 'earned_amount', width: 110, align: 'right' as const,
                  render: (v: number) => <Text strong>¥{v.toLocaleString()}</Text> },
              ]} />
          ),
        },
        {
          key: 'trend',
          label: '6 个月趋势',
          children: <EmployeeTrendChart employeeId={r.employee_id} />,
        },
      ]} />
    );
  };

  const exportExcel = () => {
    if (data.length === 0) { message.warning('无数据'); return; }
    const rows = data.map(r => ({
      '员工': r.employee_name,
      '工号': r.employee_no,
      '岗位': r.brand_positions.map(bp => `${bp.brand_name}·${bp.position}${bp.is_primary ? '(主)' : ''}`).join(' / '),
      '销售目标': r.sales_target_month,
      '实际销售': r.actual_sales,
      '销售完成率': `${(r.sales_completion * 100).toFixed(1)}%`,
      '回款目标': r.receipt_target_month,
      '实际回款': r.actual_receipt,
      '回款完成率': `${(r.receipt_completion * 100).toFixed(1)}%`,
      '出勤天数': r.work_days,
      '迟到': r.late_times + r.late_over30_times,
      '请假天数': r.leave_days,
      '有效拜访': r.valid_visits,
      '全勤': r.is_full_attendance ? '是' : '否',
      '销售提成': r.commission_total,
      '管理提成': r.manager_share_total,
      '厂家补贴': r.subsidy_total,
      '实发工资': r.salary_actual_pay,
      '工资状态': r.salary_status === 'paid' ? '已发放' : r.salary_status === 'confirmed' ? '已确认' : r.salary_status === 'draft' ? '草稿' : '未生成',
    }));
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, `绩效-${period}`);
    XLSX.writeFile(wb, `绩效档案_${period}.xlsx`);
    message.success('已导出');
  };

  const totalSales = data.reduce((s, r) => s + r.actual_sales, 0);
  const totalReceipt = data.reduce((s, r) => s + r.actual_receipt, 0);
  const totalCommission = data.reduce((s, r) => s + r.commission_total + r.manager_share_total, 0);
  const totalPayroll = data.reduce((s, r) => s + r.salary_actual_pay, 0);

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>月度绩效档案</Title>
          <span>周期：</span>
          <Input style={{ width: 110 }} value={period} onChange={e => setPeriod(e.target.value)} placeholder="2026-04" />
          <Button loading={initMut.isPending} onClick={() => initMut.mutate()}>
            初始化本月考核项
          </Button>
          <Button icon={<SyncOutlined />} loading={refreshMut.isPending} onClick={() => refreshMut.mutate()}>
            刷新考核实际值
          </Button>
          <Button icon={<DownloadOutlined />} onClick={exportExcel}>导出 Excel</Button>
        </Space>
      </div>

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small"><Text type="secondary">本月销售</Text>
          <div style={{ fontSize: 18, fontWeight: 600, color: '#1890ff' }}>¥{totalSales.toLocaleString()}</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">本月回款</Text>
          <div style={{ fontSize: 18, fontWeight: 600, color: '#52c41a' }}>¥{totalReceipt.toLocaleString()}</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">提成合计</Text>
          <div style={{ fontSize: 18, fontWeight: 600, color: '#fa8c16' }}>¥{totalCommission.toLocaleString()}</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">工资实发合计</Text>
          <div style={{ fontSize: 18, fontWeight: 600, color: '#ff4d4f' }}>¥{totalPayroll.toLocaleString()}</div></Card></Col>
      </Row>

      <Table<Row>
        columns={columns} dataSource={data} rowKey="employee_id"
        loading={isLoading} pagination={{ pageSize: 20 }}
        expandable={{ expandedRowRender, expandIcon: () => null, expandRowByClick: true }}
        size="small" scroll={{ x: 1500 }}
      />
    </>
  );
}

export default PerformanceDashboard;
