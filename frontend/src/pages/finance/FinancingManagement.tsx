import { useState } from 'react';
import { Button, Card, Col, DatePicker, Descriptions, Divider, Form, Input, InputNumber, message, Modal, Progress, Row, Select, Space, Statistic, Table, Tag, Typography } from 'antd';
import { BankOutlined, DollarOutlined, PlusOutlined, RollbackOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api, { extractItems } from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

const { Title, Text } = Typography;

interface FinancingOrder {
  id: string; order_no: string; brand_id: string; financing_account_id: string;
  amount: number; interest_rate?: number; start_date: string; maturity_date?: string;
  total_interest: number; repaid_principal: number; repaid_interest: number;
  outstanding_balance: number; status: string; bank_name?: string; bank_loan_no?: string;
  manufacturer_notes?: string; notes?: string; created_at: string;
}
interface Repayment {
  id: string; repayment_no: string; financing_order_id: string; repayment_date: string;
  principal_amount: number; interest_amount: number; total_amount: number;
  payment_account_id: string; f_class_amount: number; f_class_account_id?: string;
  voucher_url?: string; notes?: string; created_at: string;
}
interface Account { id: string; name: string; account_type: string; level: string; brand_id?: string; brand_name?: string; balance: number; }

const STATUS_COLOR: Record<string, string> = { active: 'orange', partially_repaid: 'blue', fully_repaid: 'green', defaulted: 'red', returned: 'volcano' };
const STATUS_LABEL: Record<string, string> = { active: '进行中', partially_repaid: '部分还款', fully_repaid: '已还清', defaulted: '已违约', returned: '已退仓' };

function FinancingManagement() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [detailOrder, setDetailOrder] = useState<FinancingOrder | null>(null);
  const [createForm] = Form.useForm();
  const { brandId, params } = useBrandFilter();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data: rawOrders, isLoading } = useQuery<{ items: FinancingOrder[]; total: number }>({
    queryKey: ['financing-orders', brandId, page, pageSize],
    queryFn: () => api.get('/financing-orders', { params: { ...params, skip: (page - 1) * pageSize, limit: pageSize } }).then(r => r.data),
  });
  const orders = rawOrders?.items ?? [];
  const ordersTotal = rawOrders?.total ?? 0;

  const { data: accounts = [] } = useQuery<Account[]>({
    queryKey: ['accounts-select', brandId],
    queryFn: () => api.get('/accounts', { params }).then(r => extractItems(r.data)),
  });

  const { data: repayments = [] } = useQuery<Repayment[]>({
    queryKey: ['financing-repayments', detailOrder?.id],
    queryFn: () => api.get(`/financing-orders/${detailOrder!.id}/repayments`).then(r => extractItems(r.data)),
    enabled: !!detailOrder,
  });

  const cashAccounts = accounts.filter(a => a.level === 'project' && a.account_type === 'cash');

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['financing-orders'] });
    queryClient.invalidateQueries({ queryKey: ['account-summary'] });
    queryClient.invalidateQueries({ queryKey: ['accounts-select'] });
  };

  const createMut = useMutation({
    mutationFn: async (values: any) => {
      const payload = {
        brand_id: brandId,
        amount: values.amount,
        interest_rate: values.interest_rate || null,
        start_date: values.start_date?.format('YYYY-MM-DD'),
        maturity_date: values.maturity_date?.format('YYYY-MM-DD') ?? null,
        total_interest: values.total_interest || 0,
        bank_name: values.bank_name || null,
        bank_loan_no: values.bank_loan_no || null,
        manufacturer_notes: values.manufacturer_notes || null,
        notes: values.notes || null,
      };
      return api.post('/financing-orders', payload).then(r => r.data);
    },
    onSuccess: () => { message.success('融资订单已创建'); setCreateOpen(false); createForm.resetFields(); invalidate(); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  const returnMut = useMutation({
    mutationFn: (orderId: string) => api.post(`/financing-orders/${orderId}/submit-return`).then(r => r.data),
    onSuccess: (data: any) => { message.success(`退仓申请已提交，利息 ¥${Number(data.interest_amount).toLocaleString()}，等待审批`); invalidate(); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '提交失败'),
  });

  // Stats
  const totalPrincipal = orders.reduce((s, o) => s + Number(o.amount), 0);
  const totalOutstanding = orders.reduce((s, o) => s + Number(o.outstanding_balance), 0);
  const totalRepaid = orders.reduce((s, o) => s + Number(o.repaid_principal), 0);
  const activeCount = orders.filter(o => o.status === 'active' || o.status === 'partially_repaid').length;

  const columns: ColumnsType<FinancingOrder> = [
    { title: '融资单号', dataIndex: 'order_no', width: 170 },
    { title: '本金', dataIndex: 'amount', width: 110, align: 'right', render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '年利率', dataIndex: 'interest_rate', width: 80, align: 'right', render: (v?: number) => v ? `${Number(v).toFixed(2)}%` : '-' },
    { title: '放款日', dataIndex: 'start_date', width: 110, render: (v: string) => v?.slice(0, 10) },
    { title: '到期日', dataIndex: 'maturity_date', width: 110, render: (v?: string) => v?.slice(0, 10) ?? '-' },
    { title: '已还本金', dataIndex: 'repaid_principal', width: 110, align: 'right', render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '已还利息', dataIndex: 'repaid_interest', width: 100, align: 'right', render: (v: number) => Number(v) > 0 ? `¥${Number(v).toLocaleString()}` : '-' },
    { title: '未还余额', dataIndex: 'outstanding_balance', width: 120, align: 'right', render: (v: number) => <Text strong style={{ color: Number(v) > 0 ? '#ff4d4f' : '#52c41a' }}>¥{Number(v).toLocaleString()}</Text> },
    { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <Tag color={STATUS_COLOR[v] ?? 'default'}>{STATUS_LABEL[v] ?? v}</Tag> },
    { title: '操作', key: 'act', width: 160, render: (_, r) => (
      <Space>
        {(r.status === 'active' || r.status === 'partially_repaid') && (
          <Button size="small" danger icon={<RollbackOutlined />}
            loading={returnMut.isPending}
            onClick={() => Modal.confirm({
              title: '确认退仓',
              content: <div>
                <p>融资单 {r.order_no}，未还余额 ¥{Number(r.outstanding_balance).toLocaleString()}</p>
                <p>退仓 = 厂家代还本金，公司只付利息</p>
                <p style={{ color: '#ff4d4f' }}>系统将自动计算利息并提交审批</p>
              </div>,
              onOk: () => returnMut.mutate(r.id),
            })}>退仓</Button>
        )}
        <Button size="small" onClick={() => setDetailOrder(r)}>明细</Button>
      </Space>
    )},
  ];

  const repayColumns: ColumnsType<Repayment> = [
    { title: '还款单号', dataIndex: 'repayment_no', width: 170 },
    { title: '还款日', dataIndex: 'repayment_date', width: 110, render: (v: string) => v?.slice(0, 10) },
    { title: '还本金', dataIndex: 'principal_amount', width: 100, align: 'right', render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '还利息', dataIndex: 'interest_amount', width: 90, align: 'right', render: (v: number) => Number(v) > 0 ? `¥${Number(v).toLocaleString()}` : '-' },
    { title: 'F类结算', dataIndex: 'f_class_amount', width: 100, align: 'right', render: (v: number) => Number(v) > 0 ? <Text style={{ color: '#1890ff' }}>¥{Number(v).toLocaleString()}</Text> : '-' },
    { title: '合计', dataIndex: 'total_amount', width: 100, align: 'right', render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '凭证', dataIndex: 'voucher_url', width: 60, render: (v?: string) => v ? <a onClick={() => Modal.info({ title: '还款凭证', width: 500, content: <img src={v} alt="凭证" style={{ maxWidth: '100%' }} /> })}>查看</a> : '-' },
    { title: '备注', dataIndex: 'notes', width: 150, ellipsis: true },
  ];

  return (
    <>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Title level={4} style={{ margin: 0 }}><BankOutlined /> 融资管理</Title>
        <Button type="primary" icon={<PlusOutlined />} disabled={!brandId}
          onClick={() => { createForm.resetFields(); setCreateOpen(true); }}>
          {brandId ? '新建融资订单' : '请先选择品牌'}
        </Button>
      </Space>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title="融资总额" value={totalPrincipal} precision={2} prefix="¥" /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="未还余额" value={totalOutstanding} precision={2} prefix="¥" styles={{ content: { color: '#ff4d4f' } }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="已还本金" value={totalRepaid} precision={2} prefix="¥" styles={{ content: { color: '#52c41a' } }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="进行中" value={activeCount} suffix="笔" /></Card></Col>
      </Row>

      <Table<FinancingOrder> columns={columns} dataSource={orders} rowKey="id" loading={isLoading}
        size="middle" pagination={{ current: page, pageSize, total: ordersTotal, showTotal: t => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} />

      {/* 新建融资订单 */}
      <Modal title="新建融资订单" open={createOpen} width={600}
        onOk={() => createForm.validateFields().then(v => createMut.mutate(v))}
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); }}
        confirmLoading={createMut.isPending} okText="确认创建">
        <Form form={createForm} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="amount" label="融资本金" rules={[{ required: true, message: '请输入融资金额' }]}>
                <InputNumber style={{ width: '100%' }} min={0.01} precision={2} prefix="¥" placeholder="250000" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="interest_rate" label="年利率(%)">
                <InputNumber style={{ width: '100%' }} min={0} max={100} precision={2} suffix="%" placeholder="5.50" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="start_date" label="放款日" rules={[{ required: true, message: '请选择放款日期' }]}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="maturity_date" label="到期日">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="bank_name" label="贷款银行">
                <Input placeholder="如：中国银行" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="bank_loan_no" label="银行贷款编号">
                <Input placeholder="银行贷款合同号" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="total_interest" label="预估总利息">
            <InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" placeholder="0" />
          </Form.Item>
          <Form.Item name="manufacturer_notes" label="厂家备注">
            <Input.TextArea rows={2} placeholder="厂家担保信息、季度任务说明等" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input placeholder="其他说明" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 还款明细弹窗 */}
      <Modal title={null} open={!!detailOrder} width={860}
        onCancel={() => setDetailOrder(null)} footer={null}>
        {detailOrder && (() => {
          const amount = Number(detailOrder.amount);
          const repaidP = Number(detailOrder.repaid_principal);
          const outstanding = Number(detailOrder.outstanding_balance);
          const pct = amount > 0 ? Math.round((repaidP / amount) * 100) : 0;
          return (
            <>
              {/* 顶部标题栏 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                <Space size="middle">
                  <BankOutlined style={{ fontSize: 24, color: '#722ed1' }} />
                  <div>
                    <Title level={5} style={{ margin: 0 }}>{detailOrder.order_no}</Title>
                    <Text type="secondary">{detailOrder.bank_name ?? '银行融资'} {detailOrder.bank_loan_no ? `| ${detailOrder.bank_loan_no}` : ''}</Text>
                  </div>
                </Space>
                <Tag color={STATUS_COLOR[detailOrder.status]} style={{ fontSize: 14, padding: '4px 12px' }}>
                  {STATUS_LABEL[detailOrder.status]}
                </Tag>
              </div>

              {/* 还款进度 */}
              <Card size="small" style={{ marginBottom: 16 }}>
                <Row gutter={24} align="middle">
                  <Col span={6}>
                    <Progress type="dashboard" percent={pct} size={100} strokeColor={pct >= 100 ? '#52c41a' : '#722ed1'}
                      format={() => <div style={{ textAlign: 'center' }}><div style={{ fontSize: 20, fontWeight: 600 }}>{pct}%</div><div style={{ fontSize: 11, color: '#999' }}>还款进度</div></div>} />
                  </Col>
                  <Col span={18}>
                    <Row gutter={16}>
                      <Col span={8}>
                        <Statistic title="融资本金" value={amount} precision={2} prefix="¥"
                          styles={{ content: { fontSize: 20 } }} />
                      </Col>
                      <Col span={8}>
                        <Statistic title="已还本金" value={repaidP} precision={2} prefix="¥"
                          styles={{ content: { color: '#52c41a', fontSize: 20 } }} />
                      </Col>
                      <Col span={8}>
                        <Statistic title="未还余额" value={outstanding} precision={2} prefix="¥"
                          styles={{ content: { color: outstanding > 0 ? '#ff4d4f' : '#52c41a', fontSize: 20, fontWeight: 600 } }} />
                      </Col>
                    </Row>
                    <Progress percent={pct} showInfo={false} strokeColor="#722ed1" trailColor="#f0f0f0"
                      style={{ marginTop: 8 }} />
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>已还 ¥{repaidP.toLocaleString()}</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>总计 ¥{amount.toLocaleString()}</Text>
                    </div>
                  </Col>
                </Row>
              </Card>

              {/* 贷款信息 */}
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={12}>
                  <Card size="small" title={<><CalendarOutlined /> 贷款信息</>}>
                    <Descriptions column={1} size="small">
                      <Descriptions.Item label="年利率">{detailOrder.interest_rate ? <Text strong>{Number(detailOrder.interest_rate).toFixed(2)}%</Text> : '-'}</Descriptions.Item>
                      <Descriptions.Item label="放款日">{detailOrder.start_date?.slice(0, 10)}</Descriptions.Item>
                      <Descriptions.Item label="到期日">{detailOrder.maturity_date?.slice(0, 10) ?? '-'}</Descriptions.Item>
                    </Descriptions>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size="small" title={<><DollarOutlined /> 还款统计</>}>
                    <Descriptions column={1} size="small">
                      <Descriptions.Item label="累计还本金"><Text style={{ color: '#52c41a' }}>¥{repaidP.toLocaleString()}</Text></Descriptions.Item>
                      <Descriptions.Item label="累计还利息">¥{Number(detailOrder.repaid_interest).toLocaleString()}</Descriptions.Item>
                      <Descriptions.Item label="累计支出"><Text strong>¥{(repaidP + Number(detailOrder.repaid_interest)).toLocaleString()}</Text></Descriptions.Item>
                    </Descriptions>
                  </Card>
                </Col>
              </Row>

              {detailOrder.manufacturer_notes && (
                <Card size="small" style={{ marginBottom: 16, background: '#fffbe6', borderColor: '#ffe58f' }}>
                  <Text type="secondary"><FieldTimeOutlined /> 厂家备注：</Text> {detailOrder.manufacturer_notes}
                </Card>
              )}

              {/* 还款记录 */}
              <Divider orientation="left" style={{ margin: '12px 0' }}>还款记录 ({repayments.length} 笔)</Divider>
              {repayments.length === 0
                ? <div style={{ textAlign: 'center', padding: 24, color: '#999' }}>暂无还款记录</div>
                : <Table<Repayment> columns={repayColumns} dataSource={repayments} rowKey="id" size="small" pagination={false} />
              }
            </>
          );
        })()}
      </Modal>
    </>
  );
}

export default FinancingManagement;
