import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Col, DatePicker, Divider, Form, Input, InputNumber, message, Modal, Radio, Row, Select, Space, Statistic, Table, Tag, Typography, Upload } from 'antd';
import { PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

const { Title, Text } = Typography;

interface PO {
  id: string; po_no: string; brand_id?: string; brand_name?: string;
  supplier_id: string; supplier_name?: string;
  warehouse_id?: string; warehouse?: { name: string; warehouse_type?: string };
  target_warehouse_type?: 'erp_warehouse' | 'mall_warehouse';
  mall_warehouse_id?: string;
  total_amount: number; cash_amount: number; f_class_amount: number; financing_amount: number;
  status: string; voucher_url?: string; created_at: string;
  items: { id: string; product_id: string; product_name?: string; quantity: number; unit_price: number }[];
}

const STATUS_COLOR: Record<string, string> = { pending: 'orange', paid: 'blue', shipped: 'cyan', received: 'green', completed: 'green', cancelled: 'red' };
const STATUS_LABEL: Record<string, string> = { pending: '待审批', paid: '已付款', shipped: '已发货', received: '已收货', completed: '已完成', cancelled: '已取消' };

function PurchaseOrderList() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const { brandId, params } = useBrandFilter();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data: listResp, isLoading } = useQuery<{ items: PO[]; total: number }>({
    queryKey: ['purchase-orders', brandId, page, pageSize],
    queryFn: () => api.get('/purchase-orders', { params: { ...params, skip: (page - 1) * pageSize, limit: pageSize } }).then(r => r.data),
  });
  const data = listResp?.items ?? [];
  const total = listResp?.total ?? 0;

  const { data: suppliers = [] } = useQuery<any[]>({
    queryKey: ['suppliers-select', brandId],
    queryFn: () => api.get('/suppliers', { params }).then(r => extractItems(r.data)),
  });
  const { data: warehouses = [] } = useQuery<any[]>({
    queryKey: ['warehouses-select', brandId],
    queryFn: () => api.get('/inventory/warehouses', { params }).then(r => extractItems(r.data)),
  });
  const mainWarehouses = warehouses.filter((w: any) => w.warehouse_type === 'main');
  const tastingWarehouses = warehouses.filter((w: any) => w.warehouse_type === 'tasting');
  const manufacturerWarehouses = [...mainWarehouses, ...tastingWarehouses];
  const supplierWarehouses = warehouses.filter((w: any) => ['backup', 'retail', 'wholesale'].includes(w.warehouse_type));

  const { data: products = [] } = useQuery<any[]>({
    queryKey: ['products-select', brandId],
    queryFn: () => api.get('/products', { params }).then(r => extractItems(r.data)),
  });

  // mall 仓下拉（用于 target_warehouse_type=mall_warehouse 时选仓）
  const { data: mallWarehousesResp } = useQuery<any>({
    queryKey: ['mall-warehouses-select'],
    queryFn: () => api.get('/mall/admin/warehouses', { params: { is_active: true, limit: 100 } })
      .then(r => r.data).catch(() => ({ records: [] })),
  });
  const mallWarehouses: any[] = mallWarehousesResp?.records || mallWarehousesResp?.items || [];
  const { data: accounts = [] } = useQuery<any[]>({
    queryKey: ['accounts-select', brandId],
    queryFn: () => api.get('/accounts', { params }).then(r => extractItems(r.data)),
  });

  const brandCashAccounts = accounts.filter((a: any) => a.level === 'project' && a.account_type === 'cash');
  const brandFClassAccounts = accounts.filter((a: any) => a.level === 'project' && a.account_type === 'f_class');

  // Determine if selected supplier is a manufacturer
  const selectedSupplierId = Form.useWatch('supplier_id', form);
  const selectedSupplier = suppliers.find((s: any) => s.id === selectedSupplierId);
  const isManufacturer = selectedSupplier?.type === 'manufacturer';
  const selectedWarehouseId = Form.useWatch('warehouse_id', form);
  const isTastingWarehouse = tastingWarehouses.some(w => w.id === selectedWarehouseId);
  // 目标仓库类型：'erp_warehouse'（默认）或 'mall_warehouse'（进商城仓）
  const targetWarehouseType = Form.useWatch('target_warehouse_type', form) || 'erp_warehouse';
  const isMallTarget = targetWarehouseType === 'mall_warehouse';

  const approveMut = useMutation({
    mutationFn: (id: string) => api.post(`/purchase-orders/${id}/approve`),
    onSuccess: () => { message.success('采购单已审批通过'); queryClient.invalidateQueries({ queryKey: ['purchase-orders'] }); queryClient.invalidateQueries({ queryKey: ['accounts-select'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '审批失败'),
  });
  const rejectMut = useMutation({
    mutationFn: (id: string) => api.post(`/purchase-orders/${id}/reject`),
    onSuccess: () => { message.success('采购单已驳回'); queryClient.invalidateQueries({ queryKey: ['purchase-orders'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '驳回失败'),
  });
  const receiveMut = useMutation({
    mutationFn: (id: string) => api.post(`/purchase-orders/${id}/receive?batch_no=PO-${Date.now()}`),
    onSuccess: () => { message.success('收货入库成功'); queryClient.invalidateQueries({ queryKey: ['purchase-orders'] }); queryClient.invalidateQueries({ queryKey: ['inventory'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '收货失败'),
  });

  const createMutation = useMutation({
    mutationFn: async (values: any) => {
      const payload = {
        brand_id: brandId,
        supplier_id: values.supplier_id,
        target_warehouse_type: values.target_warehouse_type || 'erp_warehouse',
        warehouse_id: values.target_warehouse_type === 'mall_warehouse' ? null : values.warehouse_id,
        mall_warehouse_id: values.target_warehouse_type === 'mall_warehouse' ? values.mall_warehouse_id : null,
        cash_amount: values.cash_amount || 0,
        f_class_amount: values.f_class_amount || 0,
        cash_account_id: values.cash_account_id || null,
        f_class_account_id: values.f_class_account_id || null,
        voucher_url: values.voucher_url || null,
        expected_date: values.expected_date?.format('YYYY-MM-DD') ?? null,
        notes: values.notes,
        items: (values.items ?? []).map((it: any) => ({
          product_id: it.product_id, quantity: it.quantity, quantity_unit: it.quantity_unit || '箱', unit_price: it.unit_price || 0,
        })),
      };
      const { data } = await api.post('/purchase-orders', payload);
      return data;
    },
    onSuccess: () => { message.success('采购单已创建，等待审批'); setModalOpen(false); form.resetFields(); queryClient.invalidateQueries({ queryKey: ['purchase-orders'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  // Watch form to calculate totals
  const formItems = Form.useWatch('items', form);
  const cashAmount = Form.useWatch('cash_amount', form) || 0;
  const fClassAmount = Form.useWatch('f_class_amount', form) || 0;
  const itemTotal = (formItems ?? []).reduce((s: number, it: any) => s + ((it?.quantity || 0) * (it?.unit_price || 0)), 0);
  const cashAccountId = Form.useWatch('cash_account_id', form);
  const fClassAccountId = Form.useWatch('f_class_account_id', form);
  const cashBalance = brandCashAccounts.find((a: any) => a.id === cashAccountId)?.balance ?? 0;
  const fClassBalance = brandFClassAccounts.find((a: any) => a.id === fClassAccountId)?.balance ?? 0;
  const cashMax = Math.min(itemTotal, Number(cashBalance));
  const fClassMax = Math.min(itemTotal, Number(fClassBalance));

  // mall_warehouse_id → name 的反查表
  const mallWhMap: Record<string, string> = {};
  mallWarehouses.forEach((w: any) => { mallWhMap[w.id] = `${w.code ? w.code + ' · ' : ''}${w.name}`; });

  const columns: ColumnsType<PO> = [
    { title: '采购单号', dataIndex: 'po_no', width: 160 },
    { title: '品牌', dataIndex: 'brand_name', width: 100, render: (v: string) => v || '-' },
    { title: '供货方', dataIndex: 'supplier_name', width: 120, render: (v: string) => v || '-' },
    {
      title: '入库仓', key: 'target_wh', width: 150,
      render: (_, r) => {
        if (r.target_warehouse_type === 'mall_warehouse') {
          const label = r.mall_warehouse_id ? (mallWhMap[r.mall_warehouse_id] || r.mall_warehouse_id.slice(0, 8) + '...') : '-';
          return <><Tag color="gold">商城</Tag>{label}</>;
        }
        return <><Tag>ERP</Tag>{r.warehouse?.name || '-'}</>;
      },
    },
    { title: '商品', key: 'items', width: 200, ellipsis: true, render: (_, r) => r.items?.map((it: any) => `${it.product_name ?? ''} ×${it.quantity}${it.quantity_unit || '箱'}`).join(', ') || '-' },
    { title: '总额', dataIndex: 'total_amount', width: 100, align: 'right', render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '现金', dataIndex: 'cash_amount', width: 90, align: 'right', render: (v: number) => Number(v) > 0 ? `¥${Number(v).toLocaleString()}` : '-' },
    { title: 'F类', dataIndex: 'f_class_amount', width: 90, align: 'right', render: (v: number) => Number(v) > 0 ? `¥${Number(v).toLocaleString()}` : '-' },
    { title: '融资', dataIndex: 'financing_amount', width: 90, align: 'right', render: (v: number) => Number(v) > 0 ? `¥${Number(v).toLocaleString()}` : '-' },
    { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => <Tag color={STATUS_COLOR[v] ?? 'default'}>{STATUS_LABEL[v] ?? v}</Tag> },
    { title: '操作', key: 'action', width: 150, render: (_, r) => (
      <Space size="small">
        {r.status === 'pending' && <Tag color="orange">审批中心处理</Tag>}
        {['approved', 'paid', 'shipped'].includes(r.status) && <a onClick={() => navigate(`/purchase/receive?po_id=${r.id}`)}>扫码入库收货</a>}
        {r.status === 'received' && <Tag color="green">已收货</Tag>}
      </Space>
    ) },
  ];

  return (
    <>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Title level={4} style={{ margin: 0 }}>采购订单</Title>
        <Button type="primary" icon={<PlusOutlined />} disabled={!brandId}
          onClick={() => { form.resetFields(); form.setFieldsValue({ items: [{}] }); setModalOpen(true); }}>
          {brandId ? '新建采购单' : '请先选择品牌'}
        </Button>
      </Space>
      <Table<PO> columns={columns} dataSource={data} rowKey="id" loading={isLoading} size="middle" pagination={{ current: page, pageSize, total, showTotal: (t) => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} />

      <Modal title="新建采购单（提交后需审批）" open={modalOpen} width={750}
        onOk={() => form.validateFields().then(v => createMutation.mutate(v))}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        confirmLoading={createMutation.isPending} okText="提交采购单" destroyOnHidden={false}>
        <Form form={form} layout="vertical" initialValues={{ items: [{}], target_warehouse_type: 'erp_warehouse' }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="supplier_id" label="供货方" rules={[{ required: true }]}>
                <Select showSearch optionFilterProp="label" placeholder="选择供货方"
                  onChange={() => { form.setFieldsValue({ warehouse_id: undefined, cash_amount: undefined, f_class_amount: undefined, cash_account_id: undefined, f_class_account_id: undefined }); }}
                  options={suppliers.map((s: any) => ({ value: s.id, label: `${s.name}（${s.type === 'manufacturer' ? '厂家' : '供应商'}）` }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="target_warehouse_type" label="目标仓库类型" rules={[{ required: true }]}>
                <Radio.Group
                  onChange={() => form.setFieldsValue({ warehouse_id: undefined, mall_warehouse_id: undefined })}
                >
                  <Radio value="erp_warehouse">ERP 仓</Radio>
                  <Radio value="mall_warehouse">商城仓</Radio>
                </Radio.Group>
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            {!isMallTarget ? (
              <Col span={24}>
                <Form.Item name="warehouse_id" label={isManufacturer ? '入库仓库' : '入库仓库'} rules={[{ required: true, message: '请选择 ERP 仓' }]}>
                  <Select showSearch optionFilterProp="label" placeholder={isManufacturer ? '选择仓库（主仓/品鉴物料仓）' : '选择仓库'}
                    options={(isManufacturer ? manufacturerWarehouses : supplierWarehouses).map((w: any) => ({ value: w.id, label: w.name }))} />
                </Form.Item>
              </Col>
            ) : (
              <Col span={24}>
                <Form.Item
                  name="mall_warehouse_id"
                  label="商城仓库"
                  rules={[{ required: true, message: '请选择商城仓' }]}
                  extra="入商城仓后，商品必须已在「商城商品」映射过（source_product_id = ERP 商品 id）"
                >
                  <Select
                    showSearch
                    optionFilterProp="label"
                    placeholder={mallWarehouses.length ? '选择商城仓' : '未找到商城仓，请先在「商城仓库」管理页创建'}
                    options={mallWarehouses.map((w: any) => ({ value: w.id, label: `${w.code ? w.code + ' · ' : ''}${w.name}` }))}
                  />
                </Form.Item>
              </Col>
            )}
          </Row>

          <Divider>采购商品明细</Divider>
          <Form.List name="items">
            {(fields, { add, remove }) => (
              <>
                {fields.map(({ key, name, ...rest }) => {
                  const qty = form.getFieldValue(['items', name, 'quantity']) || 0;
                  const price = form.getFieldValue(['items', name, 'unit_price']) || 0;
                  const subtotal = qty * price;
                  return (
                    <div key={key} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                      <Form.Item {...rest} name={[name, 'product_id']} rules={[{ required: true }]} style={{ flex: 3, marginBottom: 0 }}>
                        <Select showSearch optionFilterProp="label" placeholder="商品"
                          options={products.map((p: any) => ({ value: p.id, label: `${p.name}${p.bottles_per_case ? ` (${p.bottles_per_case}瓶/箱)` : ''}` }))} />
                      </Form.Item>
                      <Form.Item {...rest} name={[name, 'quantity']} rules={[{ required: true }, { type: 'number', max: 9999, message: '数量不能超过9999' }]} style={{ flex: 1, marginBottom: 0 }}>
                        <InputNumber placeholder="数量" min={1} max={9999} precision={0} style={{ width: '100%' }} onChange={() => form.validateFields()} />
                      </Form.Item>
                      <Form.Item {...rest} name={[name, 'quantity_unit']} initialValue="箱" style={{ flex: 0.8, marginBottom: 0 }}>
                        <Select options={[{ value: '箱', label: '箱' }, { value: '瓶', label: '瓶' }, { value: '个', label: '个' }]} />
                      </Form.Item>
                      {!isTastingWarehouse && (
                        <Form.Item {...rest} name={[name, 'unit_price']} rules={[{ required: !isTastingWarehouse }]} style={{ flex: 1.5, marginBottom: 0 }}>
                          <InputNumber placeholder="单价" min={0} precision={2} prefix="¥" style={{ width: '100%' }} onChange={() => form.validateFields()} />
                        </Form.Item>
                      )}
                      {!isTastingWarehouse && <Text type="secondary" style={{ width: 80, textAlign: 'right' }}>¥{subtotal.toLocaleString()}</Text>}
                      <a style={{ color: '#ff4d4f' }} onClick={() => remove(name)}>删除</a>
                    </div>
                  );
                })}
                <Button type="dashed" onClick={() => add()} block icon={<PlusOutlined />}>添加商品</Button>
              </>
            )}
          </Form.List>

          {isTastingWarehouse ? (
            <Card size="small" style={{ marginTop: 16, background: '#f9f0ff', borderColor: '#d3adf7' }}>
              <Text type="secondary">品鉴物料仓入库：厂家待兑付物品，无需填写价格和付款信息</Text>
            </Card>
          ) : (
            <>
              <Card size="small" style={{ marginTop: 16, background: '#f0f5ff' }}>
                <Row gutter={16}>
                  <Col span={isManufacturer ? 8 : 12}><Statistic title="商品总额" value={itemTotal} precision={2} prefix="¥" /></Col>
                  <Col span={isManufacturer ? 8 : 12}><Statistic title="现金付" value={cashAmount} precision={2} prefix="¥" styles={{ content: { color: '#52c41a' } }} /></Col>
                  {isManufacturer && <Col span={8}><Statistic title="F类付" value={fClassAmount} precision={2} prefix="¥" styles={{ content: { color: '#1890ff' } }} /></Col>}
                </Row>
              </Card>

              <Divider>付款方式（从品牌账户扣款）</Divider>
              <Row gutter={16}>
                <Col span={isManufacturer ? 12 : 24}>
                  <Form.Item name="cash_account_id" label="现金账户" rules={[{ required: true, message: '请选择现金账户' }]}>
                    <Select allowClear placeholder="选择现金账户"
                      options={brandCashAccounts.map((a: any) => ({ value: a.id, label: `${a.name}（余额 ¥${Number(a.balance).toLocaleString()}）` }))} />
                  </Form.Item>
                  <Form.Item name="cash_amount" label={`现金付款（上限 ¥${cashMax.toLocaleString()}）`}>
                    <InputNumber style={{ width: '100%' }} min={0} max={cashMax} precision={2} prefix="¥" placeholder="0"
                      onChange={(v) => { if (isManufacturer) form.setFieldValue('f_class_amount', Math.max(0, Number((itemTotal - (v || 0)).toFixed(2)))); }} />
                  </Form.Item>
                </Col>
                {isManufacturer && (
                  <Col span={12}>
                    <Form.Item name="f_class_account_id" label="F类账户">
                      <Select allowClear placeholder="选择F类账户"
                        options={brandFClassAccounts.map((a: any) => ({ value: a.id, label: `${a.name}（余额 ¥${Number(a.balance).toLocaleString()}）` }))} />
                    </Form.Item>
                    <Form.Item name="f_class_amount" label={`F类付款（上限 ¥${fClassMax.toLocaleString()}）`}>
                      <InputNumber style={{ width: '100%' }} min={0} max={fClassMax} precision={2} prefix="¥" placeholder="0"
                        onChange={(v) => { form.setFieldValue('cash_amount', Math.max(0, Number((itemTotal - (v || 0)).toFixed(2)))); }} />
                    </Form.Item>
                  </Col>
                )}
              </Row>

              <Divider />
              <Form.Item name="voucher_url" label="付款凭证（必传）" rules={[{ required: !isTastingWarehouse, message: '请上传付款凭证图片' }]}
                extra="支持粘贴图片URL，或将截图直接拖入输入框">
                <Input.TextArea rows={2} placeholder="请粘贴银行回单/转账截图的URL" />
              </Form.Item>
              {form.getFieldValue('voucher_url') && (
                <div style={{ marginBottom: 16 }}>
                  <Text type="secondary">凭证预览：</Text>
                  <img src={form.getFieldValue('voucher_url')} alt="凭证" style={{ maxWidth: '100%', maxHeight: 200, marginTop: 4, border: '1px solid #d9d9d9', borderRadius: 4 }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }} />
                </div>
              )}
            </>
          )}
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="expected_date" label="预计到货"><DatePicker style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="notes" label="备注"><Input placeholder="采购说明" /></Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </>
  );
}

export default PurchaseOrderList;