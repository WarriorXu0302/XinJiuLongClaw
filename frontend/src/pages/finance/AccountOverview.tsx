import { useState, useEffect } from 'react';
import { Button, Card, Col, Descriptions, Divider, Form, Input, InputNumber, message, Modal, Row, Select, Space, Statistic, Table, Tag, Typography } from 'antd';
import { BankOutlined, DownloadOutlined, PlusOutlined, SwapOutlined } from '@ant-design/icons';
import { exportExcel } from '../../utils/exportExcel';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useBrandStore } from '../../stores/brandStore';
import { useCanSeeMasterAccount } from '../../stores/authStore';

const { Title, Text } = Typography;

interface Account { id: string; code: string; name: string; account_type: string; level: string; brand_id?: string; brand_name?: string; balance: number; }
interface BrandGroup { brand_id?: string; brand_name: string; cash_balance: number; f_class_balance: number; financing_balance: number; total: number; accounts: Account[]; }
interface Summary { master_balance: number; project_total: number; grand_total: number; master_accounts: Account[]; brand_groups: BrandGroup[]; }
interface FundFlowItem { id: string; flow_no: string; account_id: string; flow_type: string; amount: number; balance_after: number; related_type?: string; notes?: string; created_at: string; }
interface FinancingOrder { id: string; order_no: string; brand_id: string; amount: number; interest_rate?: number; outstanding_balance: number; start_date: string; status: string; }

const typeLabel: Record<string, string> = { cash: '现金', f_class: 'F类', financing: '融资', payment_to_mfr: '回款账户' };
const typeColor: Record<string, string> = { cash: '#52c41a', f_class: '#1890ff', financing: '#722ed1', payment_to_mfr: '#fa8c16' };
const flowLabel: Record<string, string> = { credit: '收入', debit: '支出', transfer_in: '拨入', transfer_out: '拨出', financing_drawdown: '融资放款', financing_repayment: '融资还本' };
const flowColor: Record<string, string> = { credit: 'green', debit: 'red', transfer_in: 'blue', transfer_out: 'orange', financing_drawdown: 'purple', financing_repayment: 'cyan' };

function AccountOverview() {
  const canSeeMaster = useCanSeeMasterAccount();
  const queryClient = useQueryClient();
  const [transferOpen, setTransferOpen] = useState(false);
  const [form] = Form.useForm();
  const selectedBrandId = useBrandStore(s => s.selectedBrandId);
  const [isFinancingMode, setIsFinancingMode] = useState(false);
  const [interestPreview, setInterestPreview] = useState<{ interest: number; days: number; total: number } | null>(null);

  const { data: summary } = useQuery<Summary>({
    queryKey: ['account-summary', selectedBrandId],
    queryFn: () => api.get('/accounts/summary').then(r => r.data),
    refetchInterval: 10000,
  });

  const { data: flows = [] } = useQuery<FundFlowItem[]>({
    queryKey: ['fund-flows', selectedBrandId],
    queryFn: () => api.get('/accounts/fund-flows', { params: { limit: '200', ...(selectedBrandId ? { brand_id: selectedBrandId } : {}) } }).then(r => extractItems(r.data)),
  });

  // Financing orders for the selected brand (active/partially_repaid only)
  const { data: financingOrders = [] } = useQuery<FinancingOrder[]>({
    queryKey: ['financing-orders-active', selectedBrandId],
    queryFn: () => api.get('/financing-orders', { params: selectedBrandId ? { brand_id: selectedBrandId } : {} }).then(r =>
      extractItems(r.data).filter((o: any) => o.status === 'active' || o.status === 'partially_repaid')
    ),
    enabled: isFinancingMode,
  });

  // Data for PO creation when F-class > 0
  const fClassAmount = Form.useWatch('f_class_amount', form) || 0;
  const repayAmount = Form.useWatch('amount', form) || 0;
  const poItems = Form.useWatch('po_items', form) || [];
  const needPO = isFinancingMode && fClassAmount > 0;
  const poTotal = (poItems as any[]).reduce((sum: number, item: any) => {
    if (!item) return sum;
    return sum + (item.quantity || 0) * (item.unit_price || 0);
  }, 0);
  const expectedPoTotal = repayAmount + fClassAmount;
  const { data: suppliers = [] } = useQuery<any[]>({
    queryKey: ['suppliers-select', selectedBrandId],
    queryFn: () => api.get('/suppliers', { params: selectedBrandId ? { brand_id: selectedBrandId } : {} }).then(r => extractItems(r.data)),
    enabled: needPO,
  });
  const { data: warehouses = [] } = useQuery<any[]>({
    queryKey: ['warehouses-select', selectedBrandId],
    queryFn: () => api.get('/inventory/warehouses', { params: selectedBrandId ? { brand_id: selectedBrandId } : {} }).then(r => extractItems(r.data)),
    enabled: needPO,
  });
  const { data: products = [] } = useQuery<any[]>({
    queryKey: ['products-select', selectedBrandId],
    queryFn: () => api.get('/products', { params: selectedBrandId ? { brand_id: selectedBrandId } : {} }).then(r => extractItems(r.data)),
    enabled: needPO,
  });
  const mainWarehouses = warehouses.filter((w: any) => w.warehouse_type === 'main');

  const toAccountId = Form.useWatch('to_account_id', form);
  const masterAccounts = summary?.master_accounts ?? [];
  const brandGroups = selectedBrandId
    ? (summary?.brand_groups ?? []).filter(g => g.brand_id === selectedBrandId)
    : (summary?.brand_groups ?? []);
  const projectAccounts = brandGroups.flatMap(g => g.accounts);
  const selectedTargetBrandId = projectAccounts.find(a => a.id === toAccountId)?.brand_id;
  const fClassAccounts = projectAccounts.filter(a => a.account_type === 'f_class' && (!selectedTargetBrandId || a.brand_id === selectedTargetBrandId));

  // Detect if selected target is financing account
  useEffect(() => {
    const acc = projectAccounts.find(a => a.id === toAccountId);
    const financing = acc?.account_type === 'financing';
    setIsFinancingMode(financing);
    if (!financing) {
      setInterestPreview(null);
      form.setFieldValue('financing_order_id', undefined);
    }
  }, [toAccountId]);

  // Normal transfer mutation
  const transferMutation = useMutation({
    mutationFn: (v: any) => api.post('/accounts/transfer', v),
    onSuccess: (res) => { message.success(res.data.message); closeModal(); queryClient.invalidateQueries({ queryKey: ['account-summary'] }); },
    onError: (err: any) => message.error(err?.response?.data?.detail ?? '提交失败'),
  });

  // Financing repayment mutation
  const financingRepayMut = useMutation({
    mutationFn: (v: any) => api.post(`/financing-orders/${v.financing_order_id}/submit-repayment`, {
      principal_amount: v.amount,
      payment_account_id: v.cash_account_id,
      f_class_amount: v.f_class_amount || 0,
      f_class_account_id: v.f_class_account_id || null,
      supplier_id: v.supplier_id || null,
      warehouse_id: v.warehouse_id || null,
      items: (v.po_items ?? []).map((it: any) => ({
        product_id: it.product_id, quantity: it.quantity, unit_price: it.unit_price,
      })),
      notes: v.notes,
    }),
    onSuccess: () => { message.success('融资还款申请已提交，等待审批'); closeModal(); queryClient.invalidateQueries({ queryKey: ['account-summary'] }); },
    onError: (err: any) => message.error(err?.response?.data?.detail ?? '提交失败'),
  });

  const closeModal = () => { setTransferOpen(false); form.resetFields(); setIsFinancingMode(false); setInterestPreview(null); };

  // Fetch interest preview when financing order or amount changes
  const financingOrderId = Form.useWatch('financing_order_id', form);
  useEffect(() => {
    if (!isFinancingMode || !financingOrderId || !repayAmount || repayAmount <= 0) {
      setInterestPreview(null);
      return;
    }
    api.get(`/financing-orders/${financingOrderId}/calc-interest`, { params: { principal: repayAmount } })
      .then(r => setInterestPreview({ interest: r.data.interest_amount, days: r.data.interest_days, total: r.data.total_cash_deduction }))
      .catch(() => setInterestPreview(null));
  }, [isFinancingMode, financingOrderId, repayAmount]);

  const handleSubmit = () => {
    form.validateFields().then(v => {
      if (isFinancingMode) {
        if (needPO) {
          const items = v.po_items || [];
          const total = items.reduce((s: number, it: any) => s + (it.quantity || 0) * (it.unit_price || 0), 0);
          const expected = (v.amount || 0) + (v.f_class_amount || 0);
          if (Math.abs(total - expected) > 0.01) {
            message.error(`商品总价 ¥${total.toFixed(2)} 与还款本金+F类金额 ¥${expected.toFixed(2)} 不一致，无法提交`);
            return;
          }
        }
        // Find brand's cash account for payment
        const brandId = projectAccounts.find(a => a.id === v.to_account_id)?.brand_id;
        const cashAcc = projectAccounts.find(a => a.brand_id === brandId && a.account_type === 'cash');
        if (!cashAcc) { message.error('该品牌没有现金账户'); return; }
        financingRepayMut.mutate({ ...v, cash_account_id: cashAcc.id });
      } else {
        transferMutation.mutate(v);
      }
    });
  };

  const accountMap: Record<string, Account> = {};
  [...masterAccounts, ...(summary?.brand_groups ?? []).flatMap(g => g.accounts)].forEach(a => { accountMap[a.id] = a; });

  const flowColumns: ColumnsType<FundFlowItem> = [
    { title: '时间', dataIndex: 'created_at', width: 155, fixed: 'left' as const, render: (v: string) => new Date(v).toLocaleString('zh-CN'), defaultSortOrder: 'descend' as const, sorter: (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime() },
    { title: '账户', dataIndex: 'account_id', width: 180, render: (v: string) => { const acc = accountMap[v]; return acc ? <><Tag color={typeColor[acc.account_type] ?? 'default'}>{typeLabel[acc.account_type] ?? acc.account_type}</Tag>{acc.name}</> : v?.slice(0, 8); } },
    { title: '类型', dataIndex: 'flow_type', width: 80, render: (v: string) => <Tag color={flowColor[v] ?? 'default'}>{flowLabel[v] ?? v}</Tag> },
    { title: '金额', dataIndex: 'amount', width: 120, align: 'right' as const, render: (v: number, r) => <span style={{ color: r.flow_type === 'credit' || r.flow_type === 'transfer_in' ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>{r.flow_type === 'credit' || r.flow_type === 'transfer_in' ? '+' : '-'}¥{Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</span> },
    { title: '余额', dataIndex: 'balance_after', width: 130, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}` },
    { title: '关联', dataIndex: 'related_type', width: 110, render: (v?: string) => {
      const map: Record<string, string> = {
        receipt: '客户收款', salary_payment: '工资发放', inspection_payment: '稽查回收',
        inspection_penalty: '稽查罚款', inspection_income: '稽查回售', advance_refund: '垫付返还',
        f_class_arrival: 'F类到账', manufacturer_salary_arrival: '工资补贴到账',
        manufacturer_salary_reimburse: '补贴报账', transfer_in: '调拨入', transfer_out: '调拨出',
        transfer_pending: '待审拨款', expense_payment: '报销付款', purchase_payment: '采购付款',
      };
      return map[v ?? ''] ?? v ?? '-';
    }},
    { title: '备注', dataIndex: 'notes', ellipsis: true },
    { title: '流水号', dataIndex: 'flow_no', width: 170 },
  ];

  return (
    <>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Title level={4} style={{ margin: 0 }}><BankOutlined /> 账户总览</Title>
        <Button type="primary" icon={<SwapOutlined />} onClick={() => setTransferOpen(true)}>申请拨款</Button>
      </Space>

      {/* 总资金池（仅 admin/boss 可见） */}
      <Card style={{ marginBottom: 16, background: '#f0f5ff', borderColor: '#adc6ff' }}>
        <Row gutter={16} align="middle">
          {canSeeMaster && (
            <Col span={6}>
              <Statistic title="公司总资金池" value={summary?.master_balance ?? 0} precision={2} prefix="¥" styles={{ content: { color: '#1890ff', fontSize: 28 } }} />
            </Col>
          )}
          <Col span={canSeeMaster ? 6 : 8}>
            <Statistic title="品牌资产合计" value={summary?.project_total ?? 0} precision={2} prefix="¥" styles={{ content: { fontSize: 20 } }} />
          </Col>
          {canSeeMaster && (
            <Col span={6}>
              <Statistic title="系统总资产" value={summary?.grand_total ?? 0} precision={2} prefix="¥" styles={{ content: { color: '#52c41a', fontSize: 20 } }} />
            </Col>
          )}
          <Col span={canSeeMaster ? 6 : 8}>
            <Statistic title="融资负债合计" value={brandGroups.reduce((s, g) => s + g.financing_balance, 0)} precision={2} prefix="¥" styles={{ content: { color: '#ff4d4f', fontSize: 20 } }} />
          </Col>
        </Row>
      </Card>

      {/* 品牌项目账户 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {(brandGroups).map(g => (
          <Col span={8} key={g.brand_id ?? 'none'}>
            <Card title={<Tag color="blue" style={{ fontSize: 14 }}>{g.brand_name}</Tag>} size="small">
              <Descriptions column={1} size="small">
                <Descriptions.Item label="现金"><Text style={{ color: typeColor.cash }}>¥{Number(g.cash_balance).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</Text></Descriptions.Item>
                <Descriptions.Item label="F类"><Text style={{ color: typeColor.f_class }}>¥{Number(g.f_class_balance).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</Text></Descriptions.Item>
                <Descriptions.Item label="资产小计"><Text strong>¥{Number(g.total).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</Text></Descriptions.Item>
                <Descriptions.Item label={<Text type="danger">融资负债</Text>}><Text style={{ color: '#ff4d4f' }}>¥{Number(g.financing_balance).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</Text></Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 资金流水 */}
      <Divider>
        <Space>
          资金流水明细
          <Button size="small" icon={<DownloadOutlined />} onClick={() => {
            const rows = flows.map(f => {
              const acc = accountMap[f.account_id];
              const signed = f.flow_type === 'credit' || f.flow_type === 'transfer_in' ? Number(f.amount) : -Number(f.amount);
              return {
                '时间': new Date(f.created_at).toLocaleString('zh-CN'),
                '账户': acc?.name ?? f.account_id.slice(0, 8),
                '账户类型': acc ? (typeLabel[acc.account_type] ?? acc.account_type) : '-',
                '类型': flowLabel[f.flow_type] ?? f.flow_type,
                '金额': Number(f.amount),
                '带符号金额': signed,
                '余额': Number(f.balance_after),
                '关联': f.related_type ?? '',
                '备注': f.notes ?? '',
                '流水号': f.flow_no,
              };
            });
            exportExcel('资金流水', '流水', rows, [
              { wch: 18 }, { wch: 18 }, { wch: 10 }, { wch: 10 }, { wch: 12 }, { wch: 14 }, { wch: 14 }, { wch: 16 }, { wch: 30 }, { wch: 24 },
            ]);
          }}>导出 Excel</Button>
        </Space>
      </Divider>
      <Table<FundFlowItem> columns={flowColumns} dataSource={flows} rowKey="id" size="small" pagination={{ pageSize: 20 }} />

      {/* 拨款弹窗 */}
      <Modal title={isFinancingMode ? '融资还款申请（需审批）' : '申请拨款（需审批）'} open={transferOpen}
        onOk={handleSubmit}
        onCancel={closeModal}
        confirmLoading={transferMutation.isPending || financingRepayMut.isPending}
        okText="提交申请" width={isFinancingMode ? 700 : 550}>
        <Form form={form} layout="vertical">
          {!isFinancingMode && (
            <Form.Item name="from_account_id" label="总账户（转出）" rules={[{ required: true }]}>
              <Select options={masterAccounts.map(a => ({ value: a.id, label: `${a.name}（余额 ¥${Number(a.balance).toLocaleString()}）` }))} />
            </Form.Item>
          )}
          <Form.Item name="to_account_id" label="目标账户" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label"
              options={projectAccounts.filter(a => a.account_type === 'cash' || a.account_type === 'financing').map(a => ({
                value: a.id,
                label: `${a.brand_name ?? ''} ${a.name}（${typeLabel[a.account_type]}${a.account_type === 'financing' ? ' - 还款' : ''}）`,
              }))} />
          </Form.Item>

          {isFinancingMode && (
            <>
              <Form.Item name="financing_order_id" label="选择融资订单" rules={[{ required: true, message: '请选择要还款的融资订单' }]}>
                <Select showSearch optionFilterProp="label" placeholder="选择融资订单"
                  options={financingOrders.map(o => ({
                    value: o.id,
                    label: `${o.order_no} | 本金 ¥${Number(o.amount).toLocaleString()} | 未还 ¥${Number(o.outstanding_balance).toLocaleString()} | 利率 ${o.interest_rate ?? 0}%`,
                  }))} />
              </Form.Item>
              <Form.Item name="amount" label="还款本金" rules={[{ required: true }]}>
                <InputNumber style={{ width: '100%' }} min={0.01} precision={2} prefix="¥"
                  max={financingOrders.find(o => o.id === financingOrderId)?.outstanding_balance}
                  placeholder="输入还款本金" />
              </Form.Item>
              {interestPreview && (
                <Card size="small" style={{ marginBottom: 16, background: '#fff7e6', borderColor: '#ffd591' }}>
                  <Row gutter={16}>
                    <Col span={8}><Statistic title="借款天数" value={interestPreview.days} suffix="天" /></Col>
                    <Col span={8}><Statistic title="应付利息" value={interestPreview.interest} precision={2} prefix="¥" styles={{ content: { color: '#fa8c16' } }} /></Col>
                    <Col span={8}><Statistic title="现金扣款合计" value={interestPreview.total} precision={2} prefix="¥" styles={{ content: { color: '#ff4d4f', fontWeight: 600 } }} /></Col>
                  </Row>
                  <Text type="secondary" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
                    利息 = 还款本金 × 年利率 × {interestPreview.days}天 / 365，审批通过后从品牌现金账户扣款
                  </Text>
                </Card>
              )}

              <Divider style={{ margin: '12px 0' }}>F类结算（可选）</Divider>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="f_class_account_id" label="F类账户">
                    <Select allowClear showSearch optionFilterProp="label" placeholder="选择F类账户"
                      options={fClassAccounts.map(a => ({ value: a.id, label: `${a.brand_name ?? ''} ${a.name}（余额 ¥${Number(a.balance).toLocaleString()}）` }))} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="f_class_amount" label="F类结算金额">
                    <InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" placeholder="0" />
                  </Form.Item>
                </Col>
              </Row>

              {needPO && (
                <>
                  <Card size="small" style={{ marginBottom: 12, background: '#e6f7ff', borderColor: '#91d5ff' }}>
                    <Text type="secondary">F类结算 &gt; 0 = 厂家发货，请填写入库商品明细</Text>
                  </Card>
                  <Row gutter={16}>
                    <Col span={12}>
                      <Form.Item name="supplier_id" label="供应商（厂家）" rules={[{ required: true, message: '请选择供应商' }]}>
                        <Select showSearch optionFilterProp="label" placeholder="选择供应商"
                          options={suppliers.map((s: any) => ({ value: s.id, label: s.name }))} />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="warehouse_id" label="入库仓库" rules={[{ required: true, message: '请选择仓库' }]}>
                        <Select showSearch optionFilterProp="label" placeholder="选择仓库"
                          options={mainWarehouses.map((w: any) => ({ value: w.id, label: w.name }))} />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.List name="po_items">
                    {(fields, { add, remove }) => (
                      <>
                        {fields.map(({ key, name, ...rest }) => (
                          <div key={key} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                            <Form.Item {...rest} name={[name, 'product_id']} rules={[{ required: true }]} style={{ flex: 3, marginBottom: 0 }}>
                              <Select showSearch optionFilterProp="label" placeholder="商品"
                                options={products.map((p: any) => ({ value: p.id, label: p.name }))} />
                            </Form.Item>
                            <Form.Item {...rest} name={[name, 'quantity']} rules={[{ required: true }, { type: 'number', max: 9999, message: '数量不能超过9999' }]} style={{ flex: 1, marginBottom: 0 }}>
                              <InputNumber placeholder="数量" min={1} max={9999} precision={0} style={{ width: '100%' }} />
                            </Form.Item>
                            <Form.Item {...rest} name={[name, 'unit_price']} rules={[{ required: true }]} style={{ flex: 1.5, marginBottom: 0 }}>
                              <InputNumber placeholder="单价" min={0} precision={2} prefix="¥" style={{ width: '100%' }} />
                            </Form.Item>
                            <a style={{ color: '#ff4d4f' }} onClick={() => remove(name)}>删除</a>
                          </div>
                        ))}
                        <Button type="dashed" onClick={() => add()} block icon={<PlusOutlined />} style={{ marginBottom: 12 }}>添加商品</Button>
                      </>
                    )}
                  </Form.List>
                  <Card size="small" style={{ marginBottom: 12, background: Math.abs(poTotal - expectedPoTotal) > 0.01 && poTotal > 0 ? '#fff1f0' : '#f6ffed', borderColor: Math.abs(poTotal - expectedPoTotal) > 0.01 && poTotal > 0 ? '#ffa39e' : '#b7eb8f' }}>
                    <Row gutter={16}>
                      <Col span={8}><Statistic title="还款本金 + F类" value={expectedPoTotal} precision={2} prefix="¥" /></Col>
                      <Col span={8}><Statistic title="商品总价" value={poTotal} precision={2} prefix="¥" /></Col>
                      <Col span={8}><Statistic title="差额" value={Math.abs(poTotal - expectedPoTotal)} precision={2} prefix="¥" styles={{ content: { color: Math.abs(poTotal - expectedPoTotal) > 0.01 ? '#ff4d4f' : '#52c41a' } }} /></Col>
                    </Row>
                    {Math.abs(poTotal - expectedPoTotal) > 0.01 && poTotal > 0 && (
                      <Text type="danger" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>商品总价必须等于还款本金 + F类结算金额，否则无法提交</Text>
                    )}
                  </Card>
                </>
              )}
            </>
          )}

          {!isFinancingMode && (
            <Form.Item name="amount" label="拨款金额" rules={[{ required: true }]}>
              <InputNumber style={{ width: '100%' }} min={0.01} precision={2} prefix="¥" />
            </Form.Item>
          )}

          <Form.Item name="notes" label="备注"><Input.TextArea rows={2} placeholder={isFinancingMode ? '还款说明' : '拨款用途'} /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default AccountOverview;