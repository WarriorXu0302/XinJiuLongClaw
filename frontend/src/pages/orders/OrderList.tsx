import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Button, Card, Col, Collapse, Descriptions, Divider, Form, Image, Input, InputNumber, message, Modal, Row, Select, Space, Statistic, Table, Tag, Typography } from 'antd';
import { DownloadOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { exportExcel } from '../../utils/exportExcel';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

interface Order {
  id: string;
  order_no: string;
  customer_id: string | null;
  salesman_id: string | null;
  total_amount: number;
  status: string;
  payment_status: string;
  payment_voucher_urls?: string[];
  created_at: string;
  customer?: { id: string; name: string };
  salesman?: { id: string; name: string };
}

interface OrderCreateForm {
  customer_id: string;
  salesman_id: string;
  notes: string;
  items: { product_id: string; quantity: number; unit_price: number; quantity_unit?: string }[];
  deal_unit_price?: number;
  settlement_mode?: string;
  advance_payer_id?: string;
  warehouse_id?: string;
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  policy_pending_internal: 'orange',
  policy_pending_external: 'blue',
  approved: 'cyan',
  shipped: 'geekblue',
  delivered: 'green',
  completed: 'green',
  policy_rejected: 'red',
};

function OrderList() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { brandId, params } = useBrandFilter();
  const [form] = Form.useForm<OrderCreateForm>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<Order | null>(null);
  const [detailRecord, setDetailRecord] = useState<any>(null);
  const [selectedBrand, setSelectedBrand] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [paymentFilter, setPaymentFilter] = useState<string | undefined>();
  const [keyword, setKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data: listResp, isLoading } = useQuery<{ items: Order[]; total: number }>({
    queryKey: ['orders', brandId, statusFilter, paymentFilter, keyword, page, pageSize],
    queryFn: async () => {
      const p: Record<string, string | number> = { ...params, skip: (page - 1) * pageSize, limit: pageSize };
      if (statusFilter) p.status = statusFilter;
      if (paymentFilter) p.payment_status = paymentFilter;
      if (keyword) p.keyword = keyword;
      const { data } = await api.get('/orders', { params: p });
      return data;
    },
  });
  const data = listResp?.items ?? [];
  const total = listResp?.total ?? 0;

  const { data: brands = [] } = useQuery<{id: string; name: string}[]>({
    queryKey: ['brands-select'],
    queryFn: () => api.get('/products/brands').then(r => extractItems(r.data)),
  });

  const { data: customers = [] } = useQuery<{id: string; name: string}[]>({
    queryKey: ['customers-select', brandId],
    queryFn: () => api.get('/customers', { params }).then(r => extractItems(r.data)),
  });

  const { data: employees = [] } = useQuery<{id: string; name: string}[]>({
    queryKey: ['employees-select', brandId],
    queryFn: () => api.get('/hr/employees', { params }).then(r => extractItems(r.data)),
  });

  const { data: products = [] } = useQuery<{id: string; name: string; brand_id?: string; points_per_case?: number}[]>({
    queryKey: ['products-select', brandId],
    queryFn: () => api.get('/products', { params }).then(r => extractItems(r.data)),
  });

  const brandProducts = selectedBrand ? products.filter(p => p.brand_id === selectedBrand) : products;

  // ── Policy pricing ──────────────────────────────────────────────
  const [matchedPolicies, setMatchedPolicies] = useState<any[]>([]);
  const [selectedPolicy, setSelectedPolicy] = useState<any | null>(null);
  const [adjustedRules, setAdjustedRules] = useState<string>('');
  const formItems = Form.useWatch('items', form);
  const dealUnitPrice = Form.useWatch('deal_unit_price', form) || 0;
  const settlementMode = Form.useWatch('settlement_mode', form);

  // Calculate totals
  const totalQty = (formItems ?? []).reduce((s: number, it: any) => s + (it?.quantity || 0), 0);
  const totalAmount = (formItems ?? []).reduce((s: number, it: any) => s + ((it?.quantity || 0) * (it?.unit_price || 0)), 0);
  const dealAmount = dealUnitPrice * totalQty;
  const policyGap = totalAmount - dealAmount;
  const policyValue = selectedPolicy?.total_policy_value ?? 0;
  const policySurplus = policyValue - policyGap;

  useEffect(() => {
    if (!formItems || formItems.length === 0 || !modalOpen) {
      setMatchedPolicies([]);
      return;
    }
    // Group by brand: sum cases and points
    const brandStats: Record<string, { cases: number; points: number; unitPrice: number }> = {};
    for (const item of formItems) {
      if (!item?.product_id || !item?.quantity) continue;
      const product = products.find(p => p.id === item.product_id);
      if (product?.brand_id) {
        if (!brandStats[product.brand_id]) brandStats[product.brand_id] = { cases: 0, points: 0, unitPrice: 0 };
        brandStats[product.brand_id].cases += item.quantity;
        brandStats[product.brand_id].points += item.quantity * (product.points_per_case ?? 0);
        // Use the unit_price from the order item (per case price / 6 = per bottle, or use as-is)
        if (item.unit_price) brandStats[product.brand_id].unitPrice = item.unit_price;
      }
    }
    const fetchAll = async () => {
      const results: any[] = [];
      for (const [brandId, stats] of Object.entries(brandStats)) {
        try {
          const { data } = await api.get('/policy-templates/templates/match', {
            params: { brand_id: brandId, cases: stats.cases, points: stats.points, unit_price: stats.unitPrice },
          });
          results.push(...data);
        } catch { /* ignore */ }
      }
      setMatchedPolicies(results);
    };
    const timer = setTimeout(fetchAll, 300);
    return () => clearTimeout(timer);
  }, [formItems, products, modalOpen]);

  const createMutation = useMutation({
    mutationFn: async (values: OrderCreateForm) => {
      if (!selectedPolicy) {
        throw new Error('请先选择政策模板，没有政策的订单无法出库');
      }

      // 1. Parse adjusted policy content
      let policySnapshot = selectedPolicy.benefit_rules;
      let isAdjusted = false;
      if (adjustedRules.trim()) {
        try {
          const parsed = JSON.parse(adjustedRules);
          if (JSON.stringify(parsed) !== JSON.stringify(selectedPolicy.benefit_rules)) {
            isAdjusted = true;
          }
          policySnapshot = parsed;
        } catch {
          throw new Error('政策微调内容 JSON 格式不正确');
        }
      }

      if (!values.settlement_mode) {
        throw new Error('请选择结算模式');
      }

      // 2. Create order — 指导价来自政策模板，前端不再手填单价
      const { data: order } = await api.post('/orders', {
        customer_id: values.customer_id,
        salesman_id: values.salesman_id,
        notes: values.notes,
        items: (values.items ?? []).map((it: any) => ({
          product_id: it.product_id,
          quantity: it.quantity,
          quantity_unit: it.quantity_unit,
          unit_price: selectedPolicy.required_unit_price,
        })),
        policy_template_id: selectedPolicy.id,
        deal_unit_price: values.deal_unit_price ?? selectedPolicy.customer_unit_price ?? null,
        settlement_mode: values.settlement_mode,
        advance_payer_id: values.advance_payer_id || null,
        warehouse_id: values.warehouse_id || null,
      });

      // 3. Create policy request with structured items
      await api.post('/policies/requests', {
        request_source: 'order',
        approval_mode: isAdjusted ? 'internal_plus_external' : 'internal_only',
        order_id: order.id,
        customer_id: values.customer_id,
        brand_id: selectedPolicy.brand_id,
        policy_id: selectedPolicy.id,
        policy_template_id: selectedPolicy.id,
        total_policy_value: selectedPolicy.total_policy_value || 0,
        total_gap: order.policy_gap || 0,
        settlement_mode: values.settlement_mode || null,
        scheme_no: isAdjusted ? null : selectedPolicy.default_scheme_no,
        usage_purpose: isAdjusted
          ? `${selectedPolicy.name} - 微调申请，需审批`
          : `${selectedPolicy.name} - 标准政策`,
        policy_snapshot: policySnapshot,
        request_items: (selectedPolicy.benefits ?? []).map((b: any, i: number) => ({
          benefit_type: b.benefit_type,
          name: b.name,
          quantity: b.quantity,
          quantity_unit: b.quantity_unit || '次',
          standard_unit_value: b.standard_unit_value || 0,
          unit_value: b.unit_value,
          product_id: b.product_id || null,
          is_material: b.is_material || false,
          fulfill_mode: b.fulfill_mode || (b.is_material ? 'material' : 'claim'),
          advance_payer_type: values.settlement_mode === 'customer_pay' ? 'customer' : values.settlement_mode === 'employee_pay' ? 'employee' : 'company',
          advance_payer_id: values.settlement_mode === 'employee_pay' ? values.advance_payer_id : null,
          sort_order: i,
        })),
      });

      // 4. Submit order for policy approval
      await api.post(`/orders/${order.id}/submit-policy`);

      return order;
    },
    onSuccess: () => {
      message.success('订单已创建，政策申请已提交待审批');
      setModalOpen(false);
      form.resetFields();
      setSelectedPolicy(null);
      setAdjustedRules('');
      setMatchedPolicies([]);
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (err: any) => {
      message.error(err?.message || err?.response?.data?.detail || '创建失败');
    },
  });

  const editMutation = useMutation({
    mutationFn: async (values: OrderCreateForm) => {
      const { data } = await api.put(`/orders/${editingRecord!.id}`, {
        customer_id: values.customer_id,
        salesman_id: values.salesman_id,
        notes: values.notes,
        items: values.items ?? [],
      });
      return data;
    },
    onSuccess: () => {
      message.success('更新成功');
      setModalOpen(false);
      setEditingRecord(null);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (err: any) => {
      message.error(err?.response?.data?.detail ?? '更新失败');
    },
  });

  // ── Order status actions ────────────────────────────────────────
  const actionMutation = useMutation({
    mutationFn: async ({ id, action, data }: { id: string; action: string; data?: any }) => {
      return api.post(`/orders/${id}/${action}`, data ?? {});
    },
    onSuccess: (_, { action }) => {
      const labels: Record<string, string> = {
        'approve-policy': '审批通过',
        'reject-policy': '已驳回',
        'confirm-external': '外部确认通过',
        'ship': '已出库',
        'confirm-delivery': '已妥投',
        'complete': '已完成',
      };
      message.success(labels[action] ?? '操作成功');
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (err: any) => {
      message.error(err?.response?.data?.detail ?? '操作失败');
    },
  });

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingRecord) {
        editMutation.mutate(values);
      } else {
        createMutation.mutate(values);
      }
    } catch {
      // validation failed
    }
  };

  const handleCancel = () => {
    setModalOpen(false);
    setEditingRecord(null);
    form.resetFields();
  };

  const handleEdit = (record: Order) => {
    setEditingRecord(record);
    setModalOpen(true);
    form.setFieldsValue({
      customer_id: record.customer_id ?? '',
      salesman_id: record.salesman_id ?? '',
      notes: '',
      items: [],
    });
  };

  const STATUS_LABEL: Record<string, string> = {
    pending: '待提交', policy_pending_internal: '内部审批中', policy_pending_external: '厂家审批中',
    approved: '已审批', shipped: '已出库', delivered: '已妥投', completed: '已完成', policy_rejected: '已驳回',
  };
  const PAY_LABEL: Record<string, string> = { unpaid: '未付款', partially_paid: '部分付款', fully_paid: '已付清' };

  const columns: ColumnsType<Order> = [
    { title: '订单编号', dataIndex: 'order_no', width: 160, render: (v: string, r: Order) => <a onClick={() => setDetailRecord(r)}>{v}</a> },
    { title: '客户', key: 'customer', width: 100, render: (_: any, r: Order) => (r as any).customer?.name ?? customers.find(c => c.id === r.customer_id)?.name ?? '-' },
    { title: '业务员', key: 'salesman', width: 80, render: (_: any, r: Order) => (r as any).salesman?.name ?? employees.find(e => e.id === r.salesman_id)?.name ?? '-' },
    { title: '商品', key: 'products', width: 180, ellipsis: true, render: (_: any, r: Order) => {
      const items = (r as any).items ?? [];
      if (!items.length) return '-';
      return items.map((it: any) => `${it.product?.name ?? '商品'}×${it.quantity}${it.quantity_unit || '瓶'}`).join('、');
    }},
    { title: '金额', dataIndex: 'total_amount', width: 90, align: 'right', render: (v: number) => `¥${Number(v).toFixed(0)}` },
    { title: '状态', dataIndex: 'status', width: 100, render: (s: string) => <Tag color={STATUS_COLOR[s] || 'default'}>{STATUS_LABEL[s] ?? s}</Tag> },
    { title: '创建时间', dataIndex: 'created_at', width: 140, render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
    {
      title: '操作', key: 'action', width: 200, fixed: 'right' as const,
      render: (_, record) => {
        const s = record.status;
        return (
          <Space size="small">
            <a onClick={() => setDetailRecord(record)}>查看</a>
            {s === 'pending' && (
              <a onClick={() => actionMutation.mutate({ id: record.id, action: 'submit-policy' })}>提交审批</a>
            )}
            {(s === 'policy_pending_internal' || s === 'policy_pending_external') && (
              <Tag color="orange">审批中</Tag>
            )}
            {s === 'approved' && (
              <a style={{ color: '#1890ff', fontWeight: 600 }} onClick={() => navigate(`/orders/${record.id}/stock-out`)}>扫码出库</a>
            )}
            {s === 'shipped' && (
              <a style={{ color: '#52c41a' }} onClick={() => navigate(`/orders/${record.id}/delivery`)}>上传送货照片</a>
            )}
            {s === 'delivered' && (() => {
              const hasVoucher = (record.payment_voucher_urls?.length ?? 0) > 0;
              const fullyPaid = record.payment_status === 'fully_paid';
              if (fullyPaid && hasVoucher) {
                return <Tag color="blue">已全款，待财务确认</Tag>;
              }
              if (hasVoucher) {
                return (
                  <Space size="small">
                    <Tag color="gold">已传凭证，待补款</Tag>
                    <a onClick={() => navigate(`/orders/${record.id}/payment`)}>继续补传</a>
                  </Space>
                );
              }
              return <a onClick={() => navigate(`/orders/${record.id}/payment`)}>上传收款凭证</a>;
            })()}
            {s === 'policy_rejected' && (
              <a style={{ color: '#fa8c16' }} onClick={() => actionMutation.mutate({ id: record.id, action: 'resubmit' })}>重新提交</a>
            )}
            {s === 'completed' && <Tag color="green">已完成</Tag>}
            {(s === 'pending' || s === 'policy_rejected') && <a onClick={() => handleEdit(record)}>编辑</a>}
          </Space>
        );
      },
    },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <Space wrap>
          <h2 style={{ margin: 0 }}>订单管理</h2>
          <Input.Search allowClear placeholder="订单号/客户名" style={{ width: 200 }} onSearch={(v) => { setKeyword(v); setPage(1); }} />
          <Select placeholder="订单状态" allowClear style={{ width: 140 }} value={statusFilter} onChange={(v) => { setStatusFilter(v); setPage(1); }}
            options={[
              { value: 'pending', label: '待审批' },
              { value: 'policy_pending_internal', label: '内部待审' },
              { value: 'policy_pending_external', label: '厂家待审' },
              { value: 'approved', label: '已审批' },
              { value: 'shipped', label: '已发货' },
              { value: 'delivered', label: '已送达' },
              { value: 'completed', label: '已完成' },
              { value: 'policy_rejected', label: '已驳回' },
            ]} />
          <Select placeholder="付款状态" allowClear style={{ width: 120 }} value={paymentFilter} onChange={(v) => { setPaymentFilter(v); setPage(1); }}
            options={[
              { value: 'unpaid', label: '未付款' },
              { value: 'partially_paid', label: '部分' },
              { value: 'fully_paid', label: '已付清' },
            ]} />
        </Space>
        <Space>
          <Button icon={<DownloadOutlined />} onClick={() => {
            const rows = (data as Order[]).map(o => ({
              '订单号': o.order_no,
              '客户': o.customer?.name || '-',
              '业务员': o.salesman?.name || '-',
              '总金额': Number(o.total_amount),
              '订单状态': o.status,
              '付款状态': o.payment_status,
              '创建时间': new Date(o.created_at).toLocaleString('zh-CN'),
            }));
            const total = rows.reduce((s, r) => s + (r['总金额'] || 0), 0);
            exportExcel('订单列表', '订单', rows, [
              { wch: 24 }, { wch: 16 }, { wch: 10 }, { wch: 14 }, { wch: 12 }, { wch: 10 }, { wch: 18 },
            ], {
              '订单号': '合计', '客户': '', '业务员': '', '总金额': total,
              '订单状态': '', '付款状态': '', '创建时间': '',
            } as any);
          }}>导出 Excel</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingRecord(null); setSelectedPolicy(null); setAdjustedRules(''); setMatchedPolicies([]); setSelectedBrand(null); form.resetFields(); form.setFieldsValue({ items: [{}] }); setModalOpen(true); }}>新建订单</Button>
        </Space>
      </div>
      <Table<Order> columns={columns} dataSource={data} rowKey="id" loading={isLoading} size="middle" scroll={{ x: 1100 }} pagination={{ current: page, pageSize, total, showTotal: (t) => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} />

      <Modal
        title={editingRecord ? '编辑订单' : '新建订单'}
        open={modalOpen}
        onOk={handleOk}
        onCancel={handleCancel}
        confirmLoading={createMutation.isPending || editMutation.isPending}
        okText={editingRecord ? '保存' : '提交订单并申请政策审批'}
        cancelText="取消"
        destroyOnHidden={false}
        width={850}
      >
        <Form form={form} layout="vertical" initialValues={{ items: [] }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="customer_id" label="客户" rules={[{ required: true, message: '请选择客户' }]}>
                <Select showSearch optionFilterProp="label" placeholder="选择客户" options={customers.map(c => ({ value: c.id, label: c.name }))} allowClear />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="salesman_id" label="业务员" rules={[{ required: true, message: '请选择业务员' }]}>
                <Select showSearch optionFilterProp="label" placeholder="选择业务员" options={employees.map(e => ({ value: e.id, label: e.name }))} allowClear />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="备注" />
          </Form.Item>

          <Divider>商品明细</Divider>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 80px 70px 100px 40px', gap: 8, padding: '4px 0', borderBottom: '2px solid #d9d9d9', fontSize: 12, color: '#555', fontWeight: 600, marginBottom: 4 }}>
            <span>商品</span><span>数量</span><span>单位</span><span>指导价/瓶</span><span></span>
          </div>
          <Form.List name="items">
            {(fields, { add, remove }) => (
              <>
                {fields.map(({ key, name, ...restField }) => (
                  <div key={key} style={{ display: 'grid', gridTemplateColumns: '1fr 80px 70px 100px 40px', gap: 8, alignItems: 'center', padding: '4px 0', borderBottom: '1px solid #f5f5f5' }}>
                    <Form.Item {...restField} name={[name, 'product_id']} rules={[{ required: true }]} style={{ marginBottom: 0 }}>
                      <Select showSearch optionFilterProp="label" placeholder="选择商品" size="small" options={products.map(p => ({ value: p.id, label: `${p.name}${(p as any).bottles_per_case ? ` (${(p as any).bottles_per_case}瓶/箱)` : ''}` }))} />
                    </Form.Item>
                    <Form.Item {...restField} name={[name, 'quantity']} rules={[{ required: true }]} style={{ marginBottom: 0 }}>
                      <InputNumber placeholder="数量" min={1} max={9999} style={{ width: '100%' }} size="small" />
                    </Form.Item>
                    <Form.Item {...restField} name={[name, 'quantity_unit']} initialValue="箱" style={{ marginBottom: 0 }}>
                      <Select size="small" options={[{ value: '箱', label: '箱' }, { value: '瓶', label: '瓶' }]} />
                    </Form.Item>
                    <Form.Item {...restField} name={[name, 'unit_price']} rules={[{ required: true, message: '选政策后自动填充' }]} style={{ marginBottom: 0 }}>
                      <InputNumber placeholder="选政策后自动" min={0} precision={2} style={{ width: '100%' }} size="small" disabled />
                    </Form.Item>
                    <a style={{ color: '#ff4d4f', fontSize: 12 }} onClick={() => remove(name)}>删除</a>
                  </div>
                ))}
                <Button type="dashed" onClick={() => add({ quantity_unit: '箱' })} block style={{ marginTop: 8 }}>添加商品</Button>
              </>
            )}
          </Form.List>

          {/* 价格与结算 */}
          {totalAmount > 0 && (
            <>
              <Divider>价格与结算</Divider>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item name="deal_unit_price" label="承诺到手价/瓶">
                    <InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" placeholder="如 650" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="settlement_mode" label="结算模式">
                    <Select placeholder="选择" allowClear options={[
                      { value: 'customer_pay', label: '客户按进货价结账' },
                      { value: 'employee_pay', label: '业务垫付差价' },
                      { value: 'company_pay', label: '公司垫付差价' },
                    ]} />
                  </Form.Item>
                </Col>
                {settlementMode === 'employee_pay' && (
                  <Col span={8}>
                    <Form.Item name="advance_payer_id" label="垫付业务员" rules={[{ required: true }]}>
                      <Select showSearch optionFilterProp="label" placeholder="选择" options={employees.map(e => ({ value: e.id, label: e.name }))} />
                    </Form.Item>
                  </Col>
                )}
              </Row>
              {dealUnitPrice > 0 && (
                <div style={{ padding: 16, background: '#f0f5ff', borderRadius: 8, marginBottom: 16 }}>
                  <Row gutter={[16, 12]}>
                    <Col span={8}>
                      <div style={{ textAlign: 'center' }}>
                        <div style={{ color: '#888', fontSize: 12 }}>订单货款</div>
                        <div style={{ fontSize: 18, fontWeight: 600 }}>¥{totalAmount.toLocaleString()}</div>
                      </div>
                    </Col>
                    <Col span={8}>
                      <div style={{ textAlign: 'center' }}>
                        <div style={{ color: '#888', fontSize: 12 }}>客户到手总额</div>
                        <div style={{ fontSize: 18, fontWeight: 600 }}>¥{dealAmount.toLocaleString()}</div>
                      </div>
                    </Col>
                    <Col span={8}>
                      <div style={{ textAlign: 'center' }}>
                        <div style={{ color: '#888', fontSize: 12 }}>政策差额</div>
                        <div style={{ fontSize: 18, fontWeight: 600, color: '#fa8c16' }}>¥{policyGap.toLocaleString()}</div>
                      </div>
                    </Col>
                  </Row>
                  {policyValue > 0 && (
                    <>
                      <Divider style={{ margin: '12px 0' }} />
                      <Row gutter={[16, 12]}>
                        <Col span={8}>
                          <div style={{ textAlign: 'center' }}>
                            <div style={{ color: '#888', fontSize: 12 }}>政策价值</div>
                            <div style={{ fontSize: 18, fontWeight: 600, color: '#1890ff' }}>¥{policyValue.toLocaleString()}</div>
                          </div>
                        </Col>
                        <Col span={8}>
                          <div style={{ textAlign: 'center' }}>
                            <div style={{ color: '#888', fontSize: 12 }}>{policySurplus >= 0 ? '政策套利' : '政策亏损'}</div>
                            <div style={{ fontSize: 20, fontWeight: 700, color: policySurplus >= 0 ? '#52c41a' : '#ff4d4f' }}>
                              {policySurplus >= 0 ? '+' : ''}¥{policySurplus.toLocaleString()}
                            </div>
                          </div>
                        </Col>
                        <Col span={8}>
                          <div style={{ textAlign: 'center' }}>
                            <div style={{ color: '#888', fontSize: 12 }}>政策应收</div>
                            <div style={{ fontSize: 18, fontWeight: 600, color: '#722ed1' }}>
                              ¥{(settlementMode === 'customer_pay' ? 0 : policyGap).toLocaleString()}
                            </div>
                          </div>
                        </Col>
                      </Row>
                    </>
                  )}
                </div>
              )}
            </>
          )}

          {matchedPolicies.length > 0 && (
            <>
              <Divider>自动匹配政策模板</Divider>
              {matchedPolicies.map((p, idx) => (
                <Card
                  key={idx}
                  size="small"
                  style={{
                    marginBottom: 8,
                    borderColor: selectedPolicy?.id === p.id ? '#52c41a' : undefined,
                    background: selectedPolicy?.id === p.id ? '#f6ffed' : undefined,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>
                      <Tag color={p.template_type === 'channel' ? 'blue' : 'purple'}>
                        {p.template_type === 'channel' ? '渠道' : '团购'}
                      </Tag>
                      <strong>{p.name}</strong>（{p.code}）
                      {p.member_tier && <Tag color="gold">{p.member_tier}</Tag>}
                      <span style={{ marginLeft: 8, color: '#999' }}>
                        方案号：{p.default_scheme_no ?? '待回填'}
                        {p.required_unit_price && ` | 要求单价：¥${Number(p.required_unit_price).toFixed(0)}`}
                      </span>
                    </span>
                    {selectedPolicy?.id === p.id ? (
                      <Tag color="green">已选用</Tag>
                    ) : (
                      <Button size="small" type="primary" onClick={() => {
                        setSelectedPolicy(p);
                        setAdjustedRules(JSON.stringify(p.benefit_rules, null, 2));
                        // 自动用指导价覆盖所有商品行 unit_price + 填入客户到手价
                        const curItems = form.getFieldValue('items') ?? [];
                        const guide = Number(p.required_unit_price || 0);
                        form.setFieldsValue({
                          items: curItems.map((x: any) => ({ ...x, unit_price: guide })),
                          deal_unit_price: Number(p.customer_unit_price || 0) || undefined,
                        });
                      }}>应用此政策</Button>
                    )}
                  </div>

                  {/* 政策明细预览 */}
                  {p.benefits?.length > 0 ? (
                    <div style={{ marginTop: 8, color: '#666', fontSize: 13 }}>
                      {p.benefits.map((b: any, i: number) => (
                        <Tag key={i} style={{ marginBottom: 4 }}>{b.name} ×{b.quantity}{b.quantity_unit || '次'} 面值¥{Number(b.standard_total ?? 0).toLocaleString()}/折算¥{Number(b.total_value).toLocaleString()}</Tag>
                      ))}
                      <Tag color="blue">折算总价值 ¥{Number(p.total_policy_value).toLocaleString()}</Tag>
                    </div>
                  ) : p.benefit_rules && (
                    <div style={{ marginTop: 8, color: '#666', fontSize: 13 }}>
                      {Object.entries(p.benefit_rules as Record<string, unknown>).map(([k, v]) => {
                        const label: Record<string, string> = {
                          品鉴酒: '品鉴酒', 陈列费: '陈列费', 品鉴会: '品鉴会',
                          旅游: '旅游', 返利: '返利', 其他: '其他',
                        };
                        const display = typeof v === 'number' ? `¥${v.toLocaleString()}`
                          : typeof v === 'string' ? v
                          : Array.isArray(v) ? v.join('、')
                          : '-';
                        return <Tag key={k} style={{ marginBottom: 4 }}>{label[k] ?? k}：{display}</Tag>;
                      })}
                    </div>
                  )}
                </Card>
              ))}
            </>
          )}

          {/* 微调区域 */}
          {selectedPolicy && (
            <>
              <Divider><EditOutlined /> 政策微调（可选）</Divider>
              <Alert
                type="info"
                showIcon
                message={`当前选用：${selectedPolicy.name}，如需微调请直接编辑下方内容`}
                style={{ marginBottom: 8 }}
              />
              <Input.TextArea
                rows={6}
                value={adjustedRules}
                onChange={e => setAdjustedRules(e.target.value)}
                placeholder="编辑政策内容 JSON，如调整品鉴会场次、返利金额等"
              />
              <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                <Button size="small" onClick={() => setAdjustedRules(JSON.stringify(selectedPolicy.benefit_rules, null, 2))}>
                  恢复原始
                </Button>
                <Button size="small" danger onClick={() => { setSelectedPolicy(null); setAdjustedRules(''); }}>
                  取消政策
                </Button>
              </div>
            </>
          )}
        </Form>
      </Modal>

      {/* 订单详情弹窗 */}
      <Modal title="订单详情" open={!!detailRecord} onCancel={() => setDetailRecord(null)} footer={null} width={700}>
        {detailRecord && (() => {
          const o = detailRecord;
          const settlementLabel: Record<string, string> = { customer_pay: '客户按进货价结账', employee_pay: '业务垫付', company_pay: '公司垫付' };
          return (
            <>
              <Descriptions column={3} size="small" bordered style={{ marginBottom: 12 }}>
                <Descriptions.Item label="订单号"><Typography.Text copyable>{o.order_no}</Typography.Text></Descriptions.Item>
                <Descriptions.Item label="状态"><Tag color={STATUS_COLOR[o.status] || 'default'}>{STATUS_LABEL[o.status] ?? o.status}</Tag></Descriptions.Item>
                <Descriptions.Item label="付款"><Tag color={o.payment_status === 'fully_paid' ? 'green' : o.payment_status === 'partially_paid' ? 'orange' : 'default'}>{PAY_LABEL[o.payment_status] ?? o.payment_status}</Tag></Descriptions.Item>
                <Descriptions.Item label="客户">{o.customer?.name ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="业务员">{o.salesman?.name ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="结算模式">{settlementLabel[o.settlement_mode] ?? o.settlement_mode ?? '-'}</Descriptions.Item>
              </Descriptions>

              <Divider orientation="left" style={{ margin: '8px 0' }}>商品明细</Divider>
              <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                <thead><tr style={{ background: '#fafafa', textAlign: 'left' }}>
                  <th style={{ padding: '6px 8px' }}>商品</th>
                  <th style={{ padding: '6px 8px', width: 80 }}>数量</th>
                  <th style={{ padding: '6px 8px', width: 100, textAlign: 'right' }}>单价</th>
                  <th style={{ padding: '6px 8px', width: 100, textAlign: 'right' }}>小计</th>
                </tr></thead>
                <tbody>
                  {(o.items ?? []).map((it: any, i: number) => (
                    <tr key={i} style={{ borderBottom: '1px solid #f0f0f0' }}>
                      <td style={{ padding: '6px 8px' }}>{it.product?.name ?? it.product_id?.slice(0, 8)}</td>
                      <td style={{ padding: '6px 8px' }}>{it.quantity}{it.quantity_unit || '瓶'}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right' }}>¥{Number(it.unit_price).toLocaleString()}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 600 }}>¥{(Number(it.unit_price) * it.quantity).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <Divider orientation="left" style={{ margin: '12px 0 8px' }}>价格与政策</Divider>
              <Descriptions column={3} size="small" bordered>
                <Descriptions.Item label="订单货款"><Typography.Text strong>¥{Number(o.total_amount).toLocaleString()}</Typography.Text></Descriptions.Item>
                <Descriptions.Item label="到手单价">{o.deal_unit_price ? `¥${Number(o.deal_unit_price).toLocaleString()}` : '-'}</Descriptions.Item>
                <Descriptions.Item label="到手总额">{o.deal_amount ? `¥${Number(o.deal_amount).toLocaleString()}` : '-'}</Descriptions.Item>
                <Descriptions.Item label="政策差额">{o.policy_gap ? <Typography.Text type="warning">¥{Number(o.policy_gap).toLocaleString()}</Typography.Text> : '-'}</Descriptions.Item>
                <Descriptions.Item label="政策价值">{o.policy_value ? `¥${Number(o.policy_value).toLocaleString()}` : '-'}</Descriptions.Item>
                <Descriptions.Item label="政策红利">{o.policy_surplus != null ? <Typography.Text strong style={{ color: Number(o.policy_surplus) >= 0 ? '#52c41a' : '#ff4d4f' }}>{Number(o.policy_surplus) >= 0 ? '+' : ''}¥{Number(o.policy_surplus).toLocaleString()}</Typography.Text> : '-'}</Descriptions.Item>
                <Descriptions.Item label="客户实付">{o.customer_paid_amount ? `¥${Number(o.customer_paid_amount).toLocaleString()}` : '-'}</Descriptions.Item>
                <Descriptions.Item label="政策应收">{o.policy_receivable ? <Typography.Text type="danger">¥{Number(o.policy_receivable).toLocaleString()}</Typography.Text> : '¥0'}</Descriptions.Item>
              </Descriptions>

              <Divider orientation="left" style={{ margin: '12px 0 8px' }}>时间线</Divider>
              <Descriptions column={2} size="small">
                <Descriptions.Item label="创建">{o.created_at ? new Date(o.created_at).toLocaleString('zh-CN') : '-'}</Descriptions.Item>
                <Descriptions.Item label="出库">{o.shipped_at ? new Date(o.shipped_at).toLocaleString('zh-CN') : '-'}</Descriptions.Item>
                <Descriptions.Item label="送达">{o.delivered_at ? new Date(o.delivered_at).toLocaleString('zh-CN') : '-'}</Descriptions.Item>
                <Descriptions.Item label="完成">{o.completed_at ? new Date(o.completed_at).toLocaleString('zh-CN') : '-'}</Descriptions.Item>
              </Descriptions>

              {o.rejection_reason && (
                <>
                  <Divider orientation="left" style={{ margin: '12px 0 8px' }}>驳回原因</Divider>
                  <Typography.Text type="danger">{o.rejection_reason}</Typography.Text>
                </>
              )}

              {/* 送货照片 */}
              {o.delivery_photos?.length > 0 && (
                <>
                  <Divider orientation="left" style={{ margin: '12px 0 8px' }}>送货照片</Divider>
                  <Image.PreviewGroup>
                    <Space wrap>
                      {o.delivery_photos.map((url: string, i: number) => (
                        <Image key={i} src={url} width={80} height={80} style={{ objectFit: 'cover', borderRadius: 4 }} />
                      ))}
                    </Space>
                  </Image.PreviewGroup>
                </>
              )}

              {/* 收款凭证 */}
              {o.payment_voucher_urls?.length > 0 && (
                <>
                  <Divider orientation="left" style={{ margin: '12px 0 8px' }}>收款凭证</Divider>
                  <Image.PreviewGroup>
                    <Space wrap>
                      {o.payment_voucher_urls.map((url: string, i: number) => (
                        <Image key={i} src={url} width={80} height={80} style={{ objectFit: 'cover', borderRadius: 4 }} />
                      ))}
                    </Space>
                  </Image.PreviewGroup>
                </>
              )}

              {/* 政策兑付入口 */}
              {(o.status === 'completed' || o.status === 'delivered' || o.status === 'shipped') && (
                <div style={{ marginTop: 12, textAlign: 'center' }}>
                  <Button type="primary" ghost onClick={() => { setDetailRecord(null); navigate('/policies/requests'); }}>
                    查看政策兑付进度
                  </Button>
                </div>
              )}

              {o.notes && (
                <>
                  <Divider orientation="left" style={{ margin: '12px 0 8px' }}>备注</Divider>
                  <Typography.Text>{o.notes}</Typography.Text>
                </>
              )}
            </>
          );
        })()}
      </Modal>
    </>
  );
}

export default OrderList;
