import { useState } from 'react';
import { Button, Card, Divider, Form, Input, InputNumber, message, Modal, Select, Space, Table, Tag, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';
import type { PolicyRequest, RequestItem } from './policyTypes';
import { BENEFIT_LABEL, PAYER_LABEL, SETTLEMENT_LABEL } from './policyTypes';

const { Text } = Typography;

const FULFILL_LABEL: Record<string, string> = { pending: '待申请', applied: '已申请', arrived: '已到账', fulfilled: '已兑付', settled: '已归档' };
const FULFILL_COLOR: Record<string, string> = { pending: 'default', applied: 'orange', arrived: 'blue', fulfilled: 'green', settled: 'cyan' };

function PolicyRequestList() {
  const queryClient = useQueryClient();
  const { brandId, params } = useBrandFilter();
  const [fulfillOpen, setFulfillOpen] = useState(false);
  const [fulfillItem, setFulfillItem] = useState<RequestItem | null>(null);
  const [fulfillRequestId, setFulfillRequestId] = useState('');
  const [fulfillForm] = Form.useForm();
  const watchActualCost = Form.useWatch('actual_cost', fulfillForm) ?? 0;

  const { data = [], isLoading } = useQuery<PolicyRequest[]>({
    queryKey: ['policy-requests', brandId],
    queryFn: () => api.get('/policies/requests', { params: { ...params, has_items: true, limit: 200 } }).then(r => r.data),
  });

  // 物料出库弹窗
  const [materialOpen, setMaterialOpen] = useState(false);
  const [materialItem, setMaterialItem] = useState<RequestItem | null>(null);
  const [materialRequestId, setMaterialRequestId] = useState('');
  const [materialQty, setMaterialQty] = useState(1);
  const [materialBarcode, setMaterialBarcode] = useState('');
  // 费用弹窗
  const [expenseOpen, setExpenseOpen] = useState(false);
  const [expenseItem, setExpenseItem] = useState<RequestItem | null>(null);
  const [expenseForm] = Form.useForm();

  const { data: products = [] } = useQuery<any[]>({
    queryKey: ['products-select', brandId],
    queryFn: () => api.get('/products', { params }).then(r => r.data),
    enabled: !!brandId,
  });

  // F类报账创建
  const [fclassOpen, setFclassOpen] = useState(false);
  const [fclassForm] = Form.useForm();

  const createFclassMut = useMutation({
    mutationFn: async (values: any) => {
      // 1. 创建PolicyRequest (source=f_class, status=pending_internal)
      const items = (values.items ?? []).filter((it: any) => it?.name).map((it: any, i: number) => ({
        benefit_type: it.benefit_type || 'other',
        name: it.name,
        quantity: it.quantity || 1,
        quantity_unit: it.quantity_unit || '次',
        standard_unit_value: it.amount || 0,
        unit_value: 0,  // F类没有承诺客户，盈亏 = 面值 - 实际花费
        product_id: it.product_id || null,
        is_material: it.fulfill_mode === 'material',
        fulfill_mode: it.fulfill_mode || 'claim',
        advance_payer_type: 'company',
        sort_order: i,
      }));
      const totalValue = items.reduce((s: number, it: any) => s + (it.standard_unit_value * it.quantity), 0);
      const { data: pr } = await api.post('/policies/requests', {
        request_source: 'f_class',
        approval_mode: 'internal_then_external',
        brand_id: brandId,
        usage_purpose: values.title,
        total_policy_value: totalValue,
        request_items: items,
      });
      return pr;
    },
    onSuccess: () => {
      message.success('F类报账已创建，等待审批');
      setFclassOpen(false); fclassForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['policy-requests'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  // 显示已审批的 + F类待审批的
  const approvedRequests = data.filter(r => r.status === 'approved' || (r.request_source === 'f_class' && ['pending_internal', 'pending_external'].includes(r.status)));

  const addExpenseMut = useMutation({
    mutationFn: async (values: any) => (await api.post(`/policies/request-items/${expenseItem!.id}/expenses`, values)).data,
    onSuccess: () => { message.success('费用已添加'); setExpenseOpen(false); expenseForm.resetFields(); queryClient.invalidateQueries({ queryKey: ['policy-requests'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '添加失败'),
  });

  const applyFulfillMut = useMutation({
    mutationFn: async (values: any) => {
      return (await api.post(`/policies/requests/${fulfillRequestId}/fulfill-item-status`, {
        request_item_id: fulfillItem!.id,
        fulfill_status: 'applied',
        fulfill_qty: values.fulfill_qty ?? 0,
        scheme_no: values.scheme_no || null,
        actual_cost: values.actual_cost ?? 0,
        notes: values.notes || null,
      })).data;
    },
    onSuccess: () => { message.success('兑付申请已提交'); setFulfillOpen(false); fulfillForm.resetFields(); queryClient.invalidateQueries({ queryKey: ['policy-requests'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '提交失败'),
  });

  const fulfillMaterialMut = useMutation({
    mutationFn: async () => {
      if (!materialBarcode.trim()) throw new Error('请扫描条码，用于货品追溯');
      // materialQty 按 RequestItem 的 quantity_unit 解释（瓶/箱）
      const unit = materialItem!.quantity_unit || '瓶';
      return (await api.post(`/policies/requests/${materialRequestId}/fulfill-materials`, {
        items: [{ product_id: materialItem!.product_id, quantity: materialQty, quantity_unit: unit, request_item_id: materialItem!.id, barcode: materialBarcode }],
      })).data;
    },
    onSuccess: () => {
      const unit = materialItem?.quantity_unit || '瓶';
      message.success(`出库 ${materialQty} ${unit}成功`);
      setMaterialOpen(false); setMaterialBarcode('');
      queryClient.invalidateQueries({ queryKey: ['policy-requests'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '出库失败'),
  });

  // 福利直兑（庄园之旅、赠品等）
  const directFulfillMut = useMutation({
    mutationFn: async ({ requestId, item }: { requestId: string; item: RequestItem }) => {
      return (await api.post(`/policies/requests/${requestId}/fulfill-item-status`, {
        request_item_id: item.id, fulfill_status: 'applied', fulfill_qty: item.quantity,
      })).data;
    },
    onSuccess: () => { message.success('已标记兑付（福利类）'); queryClient.invalidateQueries({ queryKey: ['policy-requests'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '操作失败'),
  });

  // 统计
  const allItems = approvedRequests.flatMap(r => r.request_items ?? []);
  const countPending = allItems.filter(i => i.fulfill_status === 'pending').length;
  const countApplied = allItems.filter(i => i.fulfill_status === 'applied').length;

  const expandedRowRender = (record: PolicyRequest) => {
    const items = record.request_items ?? [];
    if (!items.length) return <Text type="secondary">无政策明细</Text>;

    const cols: ColumnsType<RequestItem> = [
      { title: '类型', dataIndex: 'benefit_type', width: 90, render: (v: string) => <Tag>{BENEFIT_LABEL[v] ?? v}</Tag> },
      { title: '名称', dataIndex: 'name', width: 120, render: (v: string, r) => <>{v}{r.product_name ? <Text type="secondary" style={{ fontSize: 11 }}> ({r.product_name})</Text> : ''}{r.is_material ? <Tag color="cyan" style={{ marginLeft: 4, fontSize: 10 }}>物料</Tag> : ''}</> },
      { title: '数量/已兑付', key: 'qty', width: 100, render: (_, r) => {
        const u = r.quantity_unit || '次';
        const mode = r.fulfill_mode ?? (r.is_material ? 'material' : 'claim');
        const verb = mode === 'material' ? '已出库' : '已兑付';
        if (r.fulfilled_qty === 0) return <span>{r.quantity}{u} <Text type="warning" style={{ fontSize: 11 }}>({verb}0)</Text></span>;
        if (r.fulfilled_qty >= r.quantity) return <span>{r.quantity}{u} <Tag color="green" style={{ fontSize: 10 }}>{verb}全</Tag></span>;
        return <span>{r.quantity}{u} <Tag color="orange" style={{ fontSize: 10 }}>{verb}{r.fulfilled_qty}</Tag></span>;
      }},
      { title: '面值', dataIndex: 'standard_total', width: 70, align: 'right', render: (v: number) => `¥${(v ?? 0).toLocaleString()}` },
      { title: '兑付方式', key: 'mode', width: 70, render: (_, r) => {
        const m = r.fulfill_mode ?? (r.is_material ? 'material' : 'claim');
        return m === 'claim' ? <Tag color="blue">对账</Tag> : m === 'direct' ? <Tag color="green">福利</Tag> : <Tag color="cyan">出库</Tag>;
      }},
      { title: '方案号', dataIndex: 'scheme_no', width: 100, render: (v: string) => v || '-' },
      { title: '状态', dataIndex: 'fulfill_status', width: 70, render: (v: string) => <Tag color={FULFILL_COLOR[v]}>{FULFILL_LABEL[v] ?? v}</Tag> },
      { title: '费用', key: 'expenses', width: 70, render: (_, r) => {
        const exps = r.expenses ?? [];
        return exps.length > 0 ? <Text type="secondary">{exps.length}笔 ¥{exps.reduce((s, e) => s + e.cost_amount, 0).toLocaleString()}</Text> : <Text type="secondary">无</Text>;
      }},
      { title: '操作', key: 'action', width: 200, render: (_, item) => {
        const remaining = item.quantity - item.fulfilled_qty;
        const mode = item.fulfill_mode ?? (item.is_material ? 'material' : 'claim');
        const hasExpenses = (item.expenses ?? []).length > 0;
        const isLocked = remaining === 0;  // 全部兑付完=锁定
        return (
          <Space size="small" wrap>
            {/* 物料出库 */}
            {mode === 'material' && item.product_id && remaining > 0 && (
              <Button size="small" type="primary" onClick={() => { setMaterialItem(item); setMaterialRequestId(record.id); setMaterialQty(1); setMaterialBarcode(''); setMaterialOpen(true); }}>
                {item.fulfilled_qty > 0 ? `出库(剩${remaining})` : '出库'}
              </Button>
            )}
            {/* 需对账：申请兑付填方案号 */}
            {mode === 'claim' && remaining > 0 && (
              <Button size="small" type="primary" onClick={() => { setFulfillItem(item); setFulfillRequestId(record.id); fulfillForm.resetFields(); fulfillForm.setFieldsValue({ fulfill_qty: 1 }); setFulfillOpen(true); }}>
                {item.fulfilled_qty > 0 ? `继续(剩${remaining})` : '申请兑付'}
              </Button>
            )}
            {/* 福利直兑：必须先有费用才能兑付 */}
            {mode === 'direct' && remaining > 0 && !hasExpenses && (
              <Text type="warning" style={{ fontSize: 11 }}>请先+费用</Text>
            )}
            {mode === 'direct' && remaining > 0 && hasExpenses && (
              <Button size="small" style={{ color: '#52c41a', borderColor: '#52c41a' }}
                onClick={() => directFulfillMut.mutate({ requestId: record.id, item })}>
                直接兑付
              </Button>
            )}
            {/* +费用：兑付完成前可加，完成后锁定 */}
            {!isLocked && (
              <Button size="small" onClick={() => { setExpenseItem(item); expenseForm.resetFields(); setExpenseOpen(true); }}>+费用</Button>
            )}
            {item.fulfilled_qty > 0 && <Tag color={remaining > 0 ? 'orange' : 'green'}>{item.fulfilled_qty}/{item.quantity}</Tag>}
            {isLocked && <Tag color="cyan">已完成</Tag>}
          </Space>
        );
      } },
    ];

    return <Table columns={cols} dataSource={items} rowKey="id" size="small" pagination={false} />;
  };

  const SOURCE_LABEL: Record<string, string> = { order: '订单', f_class: 'F类报账', hospitality: '客情', manual: '手工' };
  const SOURCE_COLOR: Record<string, string> = { order: 'blue', f_class: 'purple', hospitality: 'cyan', manual: 'default' };

  const columns: ColumnsType<PolicyRequest> = [
    { title: '来源', dataIndex: 'request_source', width: 80, render: (v: string) => <Tag color={SOURCE_COLOR[v] ?? 'default'}>{SOURCE_LABEL[v] ?? v}</Tag> },
    { title: '编号', key: 'no', width: 100, render: (_, r) => <Text code style={{ fontSize: 11 }}>{r.id.slice(0, 8)}</Text> },
    { title: '客户/说明', key: 'customer', width: 140, render: (_, r) => r.customer?.name ?? r.order?.customer?.name ?? r.usage_purpose ?? '-' },
    { title: '订单号', key: 'order', width: 130, ellipsis: true, render: (_, r) => r.order?.order_no ?? (r.request_source === 'f_class' ? <Text type="secondary" style={{ fontSize: 11 }}>F类（无订单）</Text> : '-') },
    { title: '政策价值', key: 'value', width: 90, align: 'right', render: (_, r) => r.total_policy_value ? <Text strong style={{ color: '#1890ff' }}>¥{r.total_policy_value.toLocaleString()}</Text> : '-' },
    { title: '结算', key: 'settlement', width: 80, render: (_, r) => SETTLEMENT_LABEL[r.settlement_mode ?? ''] ?? '-' },
    { title: '审批', key: 'approval', width: 70, render: (_, r) => {
      if (r.status === 'pending_internal') return <Tag color="orange">待审批</Tag>;
      if (r.status === 'pending_external') return <Tag color="blue">厂家审批</Tag>;
      return <Tag color="green">已通过</Tag>;
    }},
    { title: '进度', key: 'progress', width: 120, render: (_, r) => {
      const items = r.request_items ?? [];
      const pending = items.filter(i => i.fulfill_status === 'pending').length;
      const applied = items.filter(i => i.fulfill_status !== 'pending').length;
      return pending > 0 ? <Tag>{pending}项待申请</Tag> : <Tag color="orange">{applied}项已提交</Tag>;
    }},
    { title: '时间', dataIndex: 'created_at', width: 120, render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>政策申请</h2>
        <Button type="primary" icon={<PlusOutlined />} disabled={!brandId} onClick={() => { fclassForm.resetFields(); fclassForm.setFieldsValue({ items: [{ quantity: 1, quantity_unit: '次' }] }); setFclassOpen(true); }}>
          新建F类报账
        </Button>
      </div>

      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <Card size="small" style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ color: '#888', fontSize: 12 }}>待申请</div>
          <div style={{ fontSize: 20, fontWeight: 600, color: '#fa8c16' }}>{countPending}</div>
        </Card>
        <Card size="small" style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ color: '#888', fontSize: 12 }}>已提交等待对账</div>
          <div style={{ fontSize: 20, fontWeight: 600, color: '#1890ff' }}>{countApplied}</div>
        </Card>
      </div>

      <Table<PolicyRequest>
        columns={columns} dataSource={approvedRequests} rowKey="id" loading={isLoading}
        size="middle" scroll={{ x: 700 }}
        expandable={{ expandedRowRender, rowExpandable: r => (r.request_items?.length ?? 0) > 0 }}
        pagination={{ pageSize: 20 }}
      />

      {/* 申请兑付弹窗 */}
      <Modal title={`申请兑付 — ${fulfillItem ? (BENEFIT_LABEL[fulfillItem.benefit_type] ?? '') + ' ' + fulfillItem.name : ''}`}
        open={fulfillOpen}
        onOk={() => fulfillForm.validateFields().then(v => applyFulfillMut.mutate(v))}
        onCancel={() => { setFulfillOpen(false); fulfillForm.resetFields(); }}
        confirmLoading={applyFulfillMut.isPending} okText="提交申请" destroyOnHidden>
        {fulfillItem && (() => {
          const fv = fulfillItem.standard_total, pv = fulfillItem.total_value;
          const hasPv = pv > 0; // F类没有承诺客户，pv=0
          const pl = hasPv ? fv - pv - watchActualCost : fv - watchActualCost;
          return (
            <div style={{ marginBottom: 16, padding: 12, background: '#f0f5ff', borderRadius: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-around', textAlign: 'center', gap: 8 }}>
                <div><div style={{ color: '#888', fontSize: 11 }}>{hasPv ? '面值(厂家)' : '报销额'}</div><div style={{ fontSize: 16, fontWeight: 600 }}>¥{fv.toLocaleString()}</div></div>
                {hasPv && <>
                  <div style={{ color: '#aaa', alignSelf: 'center' }}>-</div>
                  <div><div style={{ color: '#888', fontSize: 11 }}>承诺客户</div><div style={{ fontSize: 16, fontWeight: 600, color: '#1890ff' }}>¥{pv.toLocaleString()}</div></div>
                </>}
                <div style={{ color: '#aaa', alignSelf: 'center' }}>-</div>
                <div><div style={{ color: '#888', fontSize: 11 }}>实际花费</div><div style={{ fontSize: 16, fontWeight: 600, color: '#fa8c16' }}>¥{Number(watchActualCost).toLocaleString()}</div></div>
                <div style={{ color: '#aaa', alignSelf: 'center' }}>=</div>
                <div><div style={{ color: '#888', fontSize: 11, fontWeight: 600 }}>盈亏</div><div style={{ fontSize: 18, fontWeight: 700, color: pl >= 0 ? '#52c41a' : '#ff4d4f' }}>{pl >= 0 ? '+' : ''}¥{pl.toLocaleString()}</div></div>
              </div>
              <div style={{ textAlign: 'center', marginTop: 6, color: '#999', fontSize: 11 }}>垫付方: {PAYER_LABEL[fulfillItem.advance_payer_type ?? ''] ?? '未指定'}</div>
            </div>
          );
        })()}
        <Form form={fulfillForm} layout="vertical">
          {fulfillItem && fulfillItem.quantity > 1 && (
            <Form.Item name="fulfill_qty" label={`本次数量（总${fulfillItem.quantity}，已${fulfillItem.fulfilled_qty}）`} rules={[{ required: true }]}>
              <InputNumber style={{ width: '100%' }} min={1} max={fulfillItem.quantity - fulfillItem.fulfilled_qty} precision={0} />
            </Form.Item>
          )}
          <Form.Item name="actual_cost" label="实际花费" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" placeholder="0" />
          </Form.Item>
          <Form.Item name="scheme_no" label="方案号" extra="厂家方案编号，用于到账对账匹配">
            <Input placeholder="如 FA04220241209412" />
          </Form.Item>
          <Form.Item name="notes" label="备注" rules={[{ validator: (_, v) => { if (!fulfillForm.getFieldValue('scheme_no') && !v) return Promise.reject('没方案号时必须填备注'); return Promise.resolve(); }}]}>
            <Input.TextArea rows={2} placeholder="没方案号时必填" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 物料出库弹窗 */}
      <Modal title={`物料出库 — ${materialItem?.product_name ?? materialItem?.name ?? ''}`}
        open={materialOpen}
        onOk={() => fulfillMaterialMut.mutate()}
        onCancel={() => { setMaterialOpen(false); setMaterialBarcode(''); }}
        confirmLoading={fulfillMaterialMut.isPending} okText="确认出库" destroyOnHidden>
        {materialItem && (
          <div style={{ marginBottom: 12, padding: 10, background: '#f0f5ff', borderRadius: 6, fontSize: 13 }}>
            总数: <Text strong>{materialItem.quantity}</Text>
            &nbsp;· 已出库: <Text strong>{materialItem.fulfilled_qty}</Text>
            &nbsp;· 剩余: <Text strong style={{ color: '#fa8c16' }}>{materialItem.quantity - materialItem.fulfilled_qty}</Text>
          </div>
        )}
        <div style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 6, fontWeight: 500 }}>本次出库数量</div>
          <InputNumber value={materialQty} onChange={v => setMaterialQty(v ?? 1)} min={1}
            max={materialItem ? materialItem.quantity - materialItem.fulfilled_qty : 1}
            style={{ width: '100%' }} />
        </div>
        <div>
          <div style={{ marginBottom: 6, fontWeight: 500, color: '#ff4d4f' }}>扫码出库（必须）</div>
          <Input
            prefix={<span>📦</span>}
            placeholder="扫描条码后回车"
            value={materialBarcode}
            onChange={e => setMaterialBarcode(e.target.value)}
            onPressEnter={() => { if (!materialBarcode.trim()) { message.warning('请扫描条码'); return; } fulfillMaterialMut.mutate(); }}
            autoFocus
          />
          {!materialBarcode.trim() && <div style={{ color: '#ff4d4f', fontSize: 12, marginTop: 4 }}>请扫描条码，用于货品追溯</div>}
        </div>
      </Modal>

      {/* F类报账创建弹窗 */}
      <Modal title="新建F类报账" open={fclassOpen} width={650}
        onOk={() => fclassForm.validateFields().then(v => createFclassMut.mutate(v))}
        onCancel={() => { setFclassOpen(false); fclassForm.resetFields(); }}
        confirmLoading={createFclassMut.isPending} okText="提交" destroyOnHidden>
        <Form form={fclassForm} layout="vertical">
          <Form.Item name="title" label="费用标题" rules={[{ required: true }]}>
            <Input placeholder="如：某店品鉴会厂家支持、大型活动物料费" />
          </Form.Item>
          <Divider>费用明细</Divider>
          <Form.List name="items">
            {(fields, { add, remove }) => (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: '80px 1fr 45px 45px 80px 65px 110px 20px', gap: 4, fontSize: 11, color: '#555', fontWeight: 600, marginBottom: 4 }}>
                  <span>类型</span><span>名称</span><span>数量</span><span>单位</span><span>金额</span><span>兑付</span><span>关联商品</span><span></span>
                </div>
                {fields.map(({ key, name, ...rest }) => {
                  const rowType = fclassForm.getFieldValue(['items', name, 'benefit_type']);
                  const isMaterial = rowType === 'tasting_wine' || rowType === 'gift';
                  return (
                  <div key={key} style={{ display: 'grid', gridTemplateColumns: '80px 1fr 45px 45px 80px 65px 110px 20px', gap: 4, alignItems: 'center', marginBottom: 6 }}>
                    <Form.Item {...rest} name={[name, 'benefit_type']} initialValue="other" style={{ marginBottom: 0 }}>
                      <Select size="small" onChange={(v) => {
                        // 品鉴酒/赠品物料 → 强制 material（出库）；品鉴会 → claim（对账）；庄园之旅 → direct（福利）
                        const mode = v === 'tasting_wine' || v === 'gift' ? 'material'
                          : v === 'travel' ? 'direct' : 'claim';
                        const unit = v === 'tasting_wine' ? '瓶' : v === 'gift' ? '个' : '次';
                        const items = fclassForm.getFieldValue('items') ?? [];
                        items[name] = { ...items[name], fulfill_mode: mode, quantity_unit: unit };
                        fclassForm.setFieldsValue({ items });
                      }} options={[
                        { value: 'tasting_meal', label: '品鉴会' }, { value: 'tasting_wine', label: '品鉴酒' },
                        { value: 'travel', label: '庄园之旅' }, { value: 'gift', label: '赠品/物料' },
                        { value: 'other', label: '其他' },
                      ]} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'name']} rules={[{ required: true }]} style={{ marginBottom: 0 }}>
                      <Input size="small" placeholder="名称" />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'quantity']} initialValue={1} style={{ marginBottom: 0 }}>
                      <InputNumber size="small" min={1} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'quantity_unit']} initialValue="次" style={{ marginBottom: 0 }}>
                      <Select size="small" options={[{ value: '次', label: '次' }, { value: '场', label: '场' }, { value: '瓶', label: '瓶' }, { value: '个', label: '个' }, { value: '笔', label: '笔' }]} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'amount']} rules={[{ required: true }]} style={{ marginBottom: 0 }}>
                      <InputNumber size="small" min={0} precision={2} prefix="¥" style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'fulfill_mode']} initialValue="claim" style={{ marginBottom: 0 }}>
                      <Select size="small" disabled={isMaterial} options={[{ value: 'claim', label: '对账' }, { value: 'direct', label: '福利' }, { value: 'material', label: '出库' }]} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'product_id']}
                      rules={[{ required: isMaterial, message: '物料必须选商品' }]}
                      style={{ marginBottom: 0 }}>
                      <Select size="small" allowClear placeholder={isMaterial ? '必选商品' : '商品'} showSearch optionFilterProp="label"
                        status={isMaterial ? 'warning' : undefined}
                        options={products.map((p: any) => ({ value: p.id, label: p.name }))} />
                    </Form.Item>
                    <a style={{ color: '#ff4d4f', fontSize: 11 }} onClick={() => remove(name)}>删</a>
                  </div>
                );})}
                <Button type="dashed" onClick={() => add({ quantity: 1, quantity_unit: '次' })} block size="small" style={{ marginTop: 4 }}>添加明细</Button>
              </>
            )}
          </Form.List>
        </Form>
      </Modal>

      {/* 添加费用弹窗 */}
      <Modal title={`添加关联费用 — ${expenseItem?.name ?? ''}`} open={expenseOpen}
        onOk={() => expenseForm.validateFields().then(v => addExpenseMut.mutate(v))}
        onCancel={() => { setExpenseOpen(false); expenseForm.resetFields(); }}
        confirmLoading={addExpenseMut.isPending} okText="添加" destroyOnHidden>
        <Form form={expenseForm} layout="vertical">
          <Form.Item name="name" label="费用名称" rules={[{ required: true }]}>
            <Input placeholder="如：往返机票、场地费、餐费" />
          </Form.Item>
          <div style={{ display: 'flex', gap: 16 }}>
            <Form.Item name="cost_amount" label="实际支出" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" />
            </Form.Item>
            <Form.Item name="reimburse_amount" label="厂家报销额" style={{ flex: 1 }}>
              <InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" placeholder="0" />
            </Form.Item>
          </div>
          <Form.Item name="payer_type" label="垫付方">
            <Select allowClear placeholder="谁垫付" options={[
              { value: 'company', label: '公司' }, { value: 'employee', label: '业务员' },
            ]} />
          </Form.Item>
          <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default PolicyRequestList;
