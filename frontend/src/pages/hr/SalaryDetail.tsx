import { useQuery } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Col, Descriptions, Divider, Empty, Image, Row, Skeleton, Space, Statistic, Table, Tag, Timeline, Typography, Button } from 'antd';
import { ArrowLeftOutlined, DollarOutlined } from '@ant-design/icons';
import api from '../../api/client';

const { Title, Text } = Typography;

interface OrderLine {
  order_no: string;
  customer_name: string;
  brand_name: string;
  receipt_amount: number;
  commission_rate: number;
  kpi_coefficient: number;
  commission_amount: number;
  salesman_name: string;
}
interface AssessLine {
  item_name: string;
  target_value: number;
  actual_value: number;
  completion_rate: number;
  item_amount: number;
  earned_amount: number;
}
interface SubsidyLine { brand_name: string; position_name: string; amount: number; }

interface SalaryDetailResp {
  id: string;
  employee_id: string;
  employee_name: string;
  period: string;
  status: string;
  employee_info: {
    primary_brand_name: string | null;
    primary_position_name: string | null;
    base_salary_fixed: number;
    variable_salary_max: number;
    attendance_bonus_full: number;
    social_security: number;
    company_social_security: number;
  };
  income: {
    fixed_salary: number;
    variable_salary_total: number;
    commission_total: number;
    manager_share_total: number;
    attendance_bonus: number;
    bonus_other: number;
    manufacturer_subsidy_total: number;
  };
  deduction: {
    late_deduction: number;
    absence_deduction: number;
    fine_deduction: number;
    social_security: number;
  };
  total_pay: number;
  actual_pay: number;
  attendance_summary: {
    late_times: number;
    late_over30_times: number;
    leave_days: number;
  };
  order_details: OrderLine[];
  manager_share_details: OrderLine[];
  assessment_details: AssessLine[];
  subsidy_details: SubsidyLine[];
  notes?: string;
  submitted_at?: string;
  approved_at?: string;
  reject_reason?: string;
  paid_at?: string;
  payment_voucher_urls: string[];
}

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  pending_approval: { color: 'gold', text: '待审批' },
  approved: { color: 'blue', text: '已批准' },
  rejected: { color: 'red', text: '已驳回' },
  paid: { color: 'green', text: '已发放' },
};

function fmt(d?: string) { return d ? new Date(d).toLocaleString('zh-CN') : '-'; }
function yuan(v: number) { return `¥${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }

function SalaryDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const { data, isLoading } = useQuery<SalaryDetailResp>({
    queryKey: ['salary-detail', id],
    queryFn: () => api.get(`/payroll/salary-records/${id}/detail`).then(r => r.data),
    enabled: !!id,
  });

  if (isLoading) return <Skeleton active />;
  if (!data) return <Empty description="工资单不存在" />;

  const { color, text } = STATUS_MAP[data.status] ?? { color: 'default', text: data.status };
  const incomeSum = data.income.fixed_salary + data.income.variable_salary_total + data.income.commission_total
    + data.income.manager_share_total + data.income.attendance_bonus + data.income.bonus_other;
  const deductSum = data.deduction.late_deduction + data.deduction.absence_deduction + data.deduction.fine_deduction + data.deduction.social_security;

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => nav(-1)}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>工资明细</Title>
        <Tag color={color}>{text}</Tag>
      </Space>

      <Card style={{ marginBottom: 16 }}>
        <Row gutter={24}>
          <Col span={6}>
            <Statistic title="员工" valueRender={() => <Text strong style={{ fontSize: 18 }}>{data.employee_name}</Text>} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              周期：{data.period}
              {data.employee_info.primary_brand_name && <> · 主属 {data.employee_info.primary_brand_name}/{data.employee_info.primary_position_name}</>}
            </Text>
          </Col>
          <Col span={6}>
            <Statistic title="应发合计" value={data.total_pay} precision={2} prefix="¥" styles={{ content: { color: '#1890ff' } }} />
          </Col>
          <Col span={6}>
            <Statistic title="扣款合计" value={deductSum} precision={2} prefix="-¥" styles={{ content: { color: '#faad14' } }} />
          </Col>
          <Col span={6}>
            <Statistic title="实发到手" value={data.actual_pay} precision={2} prefix="¥" styles={{ content: { color: '#ff4d4f', fontSize: 24 } }} />
          </Col>
        </Row>
      </Card>

      <Row gutter={16}>
        <Col span={16}>
          <Card title="收入构成" size="small" style={{ marginBottom: 16 }}>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="固定底薪">{yuan(data.income.fixed_salary)}</Descriptions.Item>
              <Descriptions.Item label="浮动底薪（考核）">{yuan(data.income.variable_salary_total)}</Descriptions.Item>
              <Descriptions.Item label="销售提成"><Text style={{ color: '#1890ff' }}>{yuan(data.income.commission_total)}</Text></Descriptions.Item>
              <Descriptions.Item label="管理提成"><Text style={{ color: '#fa8c16' }}>{yuan(data.income.manager_share_total)}</Text></Descriptions.Item>
              <Descriptions.Item label="全勤奖">
                {yuan(data.income.attendance_bonus)}
                <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                  (全额 ¥{data.employee_info.attendance_bonus_full.toFixed(0)} · 迟到{data.attendance_summary.late_times + data.attendance_summary.late_over30_times}次 · 请假{data.attendance_summary.leave_days}天)
                </Text>
              </Descriptions.Item>
              <Descriptions.Item label="其他奖金" span={2}>{yuan(data.income.bonus_other)}</Descriptions.Item>
              <Descriptions.Item label="合计" span={2}>
                <Text strong>{yuan(incomeSum)}</Text>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          {data.order_details.length > 0 && (
            <Card title={`销售提成订单明细 (${data.order_details.length} 单)`} size="small" style={{ marginBottom: 16 }}>
              <Table dataSource={data.order_details} rowKey={(_, i) => String(i)} size="small" pagination={false}
                columns={[
                  { title: '订单号', dataIndex: 'order_no', width: 100 },
                  { title: '客户', dataIndex: 'customer_name' },
                  { title: '品牌', dataIndex: 'brand_name', width: 100 },
                  { title: '回款', dataIndex: 'receipt_amount', align: 'right' as const, width: 100, render: (v: number) => yuan(v) },
                  { title: '费率', dataIndex: 'commission_rate', width: 80, align: 'right' as const, render: (v: number) => `${(v * 100).toFixed(2)}%` },
                  { title: 'KPI系数', dataIndex: 'kpi_coefficient', width: 80, align: 'right' as const, render: (v: number) => v.toFixed(2) },
                  { title: '提成', dataIndex: 'commission_amount', width: 100, align: 'right' as const,
                    render: (v: number) => <Text strong style={{ color: '#1890ff' }}>{yuan(v)}</Text> },
                ]}
                summary={() => (
                  <Table.Summary.Row>
                    <Table.Summary.Cell index={0} colSpan={6} align="right"><Text strong>合计</Text></Table.Summary.Cell>
                    <Table.Summary.Cell index={1} align="right">
                      <Text strong style={{ color: '#1890ff' }}>
                        {yuan(data.order_details.reduce((s, o) => s + o.commission_amount, 0))}
                      </Text>
                    </Table.Summary.Cell>
                  </Table.Summary.Row>
                )}
              />
            </Card>
          )}

          {data.manager_share_details.length > 0 && (
            <Card title={`管理提成 - 下属业务员订单 (${data.manager_share_details.length} 单)`} size="small" style={{ marginBottom: 16 }}>
              <Table dataSource={data.manager_share_details} rowKey={(_, i) => String(i)} size="small" pagination={false}
                columns={[
                  { title: '订单号', dataIndex: 'order_no', width: 100 },
                  { title: '业务员', dataIndex: 'salesman_name', width: 100 },
                  { title: '客户', dataIndex: 'customer_name' },
                  { title: '品牌', dataIndex: 'brand_name', width: 100 },
                  { title: '回款', dataIndex: 'receipt_amount', align: 'right' as const, width: 100, render: (v: number) => yuan(v) },
                  { title: '管理费率', dataIndex: 'commission_rate', width: 90, align: 'right' as const, render: (v: number) => `${(v * 100).toFixed(2)}%` },
                  { title: '提成', dataIndex: 'commission_amount', width: 100, align: 'right' as const,
                    render: (v: number) => <Text strong style={{ color: '#fa8c16' }}>{yuan(v)}</Text> },
                ]}
                summary={() => (
                  <Table.Summary.Row>
                    <Table.Summary.Cell index={0} colSpan={6} align="right"><Text strong>合计</Text></Table.Summary.Cell>
                    <Table.Summary.Cell index={1} align="right">
                      <Text strong style={{ color: '#fa8c16' }}>
                        {yuan(data.manager_share_details.reduce((s, o) => s + o.commission_amount, 0))}
                      </Text>
                    </Table.Summary.Cell>
                  </Table.Summary.Row>
                )}
              />
            </Card>
          )}

          {data.assessment_details.length > 0 && (
            <Card title="考核项明细" size="small" style={{ marginBottom: 16 }}>
              <Table dataSource={data.assessment_details} rowKey={(_, i) => String(i)} size="small" pagination={false}
                columns={[
                  { title: '考核项', dataIndex: 'item_name' },
                  { title: '目标', dataIndex: 'target_value', align: 'right' as const, width: 100, render: (v: number) => v.toLocaleString() },
                  { title: '实际', dataIndex: 'actual_value', align: 'right' as const, width: 100, render: (v: number) => v.toLocaleString() },
                  { title: '完成率', dataIndex: 'completion_rate', width: 80, align: 'right' as const,
                    render: (v: number) => `${(v * 100).toFixed(0)}%` },
                  { title: '额度', dataIndex: 'item_amount', width: 80, align: 'right' as const, render: (v: number) => yuan(v) },
                  { title: '实得', dataIndex: 'earned_amount', width: 100, align: 'right' as const,
                    render: (v: number) => <Text strong>{yuan(v)}</Text> },
                ]}
              />
            </Card>
          )}

          <Card title="扣款明细" size="small">
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="迟到扣款">{yuan(data.deduction.late_deduction)}</Descriptions.Item>
              <Descriptions.Item label="旷工扣款">{yuan(data.deduction.absence_deduction)}</Descriptions.Item>
              <Descriptions.Item label="罚款">{yuan(data.deduction.fine_deduction)}</Descriptions.Item>
              <Descriptions.Item label="社保代扣（个人）">{yuan(data.deduction.social_security)}</Descriptions.Item>
              <Descriptions.Item label="合计" span={2}>
                <Text type="danger" strong>-{yuan(deductSum)}</Text>
              </Descriptions.Item>
            </Descriptions>
            <Divider style={{ margin: '12px 0' }} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              公司代缴社保：{yuan(data.employee_info.company_social_security)}（不扣本人，计入公司成本）
            </Text>
          </Card>
        </Col>

        <Col span={8}>
          <Card title="考勤汇总" size="small" style={{ marginBottom: 16 }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="迟到 < 30分">{data.attendance_summary.late_times} 次</Descriptions.Item>
              <Descriptions.Item label="迟到 ≥ 30分">{data.attendance_summary.late_over30_times} 次</Descriptions.Item>
              <Descriptions.Item label="请假天数">{data.attendance_summary.leave_days} 天</Descriptions.Item>
            </Descriptions>
          </Card>

          <Card title="审批流程" size="small" style={{ marginBottom: 16 }}>
            <Timeline items={[
              { color: 'blue', children: <>生成草稿</> },
              data.submitted_at ? { color: 'gold', children: <>提交审批<br /><Text type="secondary" style={{ fontSize: 12 }}>{fmt(data.submitted_at)}</Text></> } : undefined,
              data.approved_at ? { color: 'green', children: <>已批准<br /><Text type="secondary" style={{ fontSize: 12 }}>{fmt(data.approved_at)}</Text></> } : undefined,
              data.reject_reason ? { color: 'red', children: <><Text type="danger">驳回</Text><br /><Text type="secondary" style={{ fontSize: 12 }}>{data.reject_reason}</Text></> } : undefined,
              data.paid_at ? { color: 'green', children: <><DollarOutlined /> 已发放<br /><Text type="secondary" style={{ fontSize: 12 }}>{fmt(data.paid_at)}</Text></> } : undefined,
            ].filter(Boolean) as any} />
          </Card>

          {data.payment_voucher_urls.length > 0 && (
            <Card title="转款凭证" size="small" style={{ marginBottom: 16 }}>
              <Image.PreviewGroup>
                <Space wrap>
                  {data.payment_voucher_urls.map((u, i) => (
                    <Image key={i} width={90} src={u} />
                  ))}
                </Space>
              </Image.PreviewGroup>
            </Card>
          )}

          {data.notes && (
            <Card title="备注" size="small">
              <Text>{data.notes}</Text>
            </Card>
          )}
        </Col>
      </Row>
    </>
  );
}

export default SalaryDetail;
