import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Descriptions, Drawer, Form, Input, InputNumber, message, Modal, Select, Space, Table, Tabs, Tag, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import { useBrandFilter } from '../../stores/useBrandFilter';
import api from '../../api/client';

const { Title } = Typography;

interface CustomerItem {
  id: string;
  code: string;
  name: string;
  customer_type: string;
  contact_name: string | null;
  contact_phone: string | null;
  settlement_mode: string;
  credit_days: number | null;
  salesman_id: string | null;
  salesman?: { id: string; name: string };
  status: string;
}

interface OrderItem {
  id: string;
  order_no: string;
  total_amount: string;
  status: string;
  payment_status: string;
  created_at: string;
}

const typeLabel: Record<string, string> = { channel: '渠道', group_purchase: '团购' };
const typeColor: Record<string, string> = { channel: 'blue', group_purchase: 'purple' };

function CustomerList() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<CustomerItem | null>(null);
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [keyword, setKeyword] = useState('');
  const [settlementFilter, setSettlementFilter] = useState<string | undefined>();
  const [drawerCustomer, setDrawerCustomer] = useState<CustomerItem | null>(null);
  const [orderBrandFilter, setOrderBrandFilter] = useState<string | null>(null);
  const [brandBindCustomer, setBrandBindCustomer] = useState<CustomerItem | null>(null);
  const [brandBindForm] = Form.useForm();

  const { brandId, params: brandParams } = useBrandFilter();

  const { data = [], isLoading } = useQuery({
    queryKey: ['customers', typeFilter, keyword, settlementFilter, brandId],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (typeFilter) params.customer_type = typeFilter;
      if (keyword) params.keyword = keyword;
      if (settlementFilter) params.settlement_mode = settlementFilter;
      if (brandId) params.brand_id = brandId;
      const { data } = await api.get('/customers', { params });
      return data;
    },
  });

  const { data: employees = [] } = useQuery<{id: string; name: string}[]>({
    queryKey: ['employees-select', brandId],
    queryFn: () => api.get('/hr/employees', { params }).then(r => r.data),
  });

  const { data: brands = [] } = useQuery<{id: string; name: string}[]>({
    queryKey: ['brands-list'],
    queryFn: () => api.get('/products/brands').then(r => r.data),
  });

  // Brand bindings for selected customer
  const { data: brandBindings = [] } = useQuery<{ id: string; brand_id: string; salesman_id: string }[]>({
    queryKey: ['customer-brand-salesman', brandBindCustomer?.id],
    queryFn: () => api.get(`/customers/${brandBindCustomer!.id}/brand-salesman`).then(r => r.data),
    enabled: !!brandBindCustomer,
  });

  const bindBrandMut = useMutation({
    mutationFn: async (values: any) => {
      const { data } = await api.post(`/customers/${brandBindCustomer!.id}/brand-salesman`, values);
      return data;
    },
    onSuccess: () => { message.success('品牌绑定成功'); brandBindForm.resetFields(); queryClient.invalidateQueries({ queryKey: ['customer-brand-salesman'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '绑定失败'),
  });

  const unbindBrandMut = useMutation({
    mutationFn: async (brandId: string) => {
      await api.delete(`/customers/${brandBindCustomer!.id}/brand-salesman/${brandId}`);
    },
    onSuccess: () => { message.success('已解绑'); queryClient.invalidateQueries({ queryKey: ['customer-brand-salesman'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '解绑失败'),
  });

  const { data: customerOrders = [], isLoading: ordersLoading } = useQuery<OrderItem[]>({
    queryKey: ['customer-orders', drawerCustomer?.id],
    queryFn: () => api.get(`/customers/${drawerCustomer!.id}/orders`).then(r => r.data),
    enabled: !!drawerCustomer,
  });

  const filteredOrders = orderBrandFilter
    ? customerOrders.filter((o: any) => o.brand_id === orderBrandFilter)
    : customerOrders;

  const createMutation = useMutation({
    mutationFn: async (values: Record<string, unknown>) => {
      const { data } = await api.post('/customers', values);
      return data;
    },
    onSuccess: () => {
      message.success('创建成功');
      setModalOpen(false);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['customers'] });
    },
    onError: (err: any) => {
      message.error(err?.response?.data?.detail ?? '创建失败');
    },
  });

  const editMutation = useMutation({
    mutationFn: async (values: Record<string, unknown>) => {
      const { data } = await api.put(`/customers/${editingRecord!.id}`, values);
      return data;
    },
    onSuccess: () => {
      message.success('更新成功');
      setModalOpen(false);
      setEditingRecord(null);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['customers'] });
    },
    onError: (err: any) => {
      message.error(err?.response?.data?.detail ?? '更新失败');
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

  const handleEdit = (record: CustomerItem) => {
    setEditingRecord(record);
    setModalOpen(true);
    form.setFieldsValue(record);
  };

  const orderColumns: ColumnsType<OrderItem> = [
    { title: '订单号', dataIndex: 'order_no', width: 180 },
    { title: '金额', dataIndex: 'total_amount', width: 100, align: 'right', render: (v: string) => `¥${Number(v).toFixed(2)}` },
    { title: '状态', dataIndex: 'status', width: 120, render: (v: string) => <Tag>{v}</Tag> },
    { title: '付款', dataIndex: 'payment_status', width: 100, render: (v: string) => <Tag color={v === 'fully_paid' ? 'green' : 'orange'}>{v}</Tag> },
    { title: '时间', dataIndex: 'created_at', width: 160, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
  ];

  const columns: ColumnsType<CustomerItem> = [
    { title: '编号', dataIndex: 'code', width: 100 },
    { title: '类型', dataIndex: 'customer_type', width: 80, render: (v: string) => <Tag color={typeColor[v] ?? 'default'}>{typeLabel[v] ?? v}</Tag> },
    { title: '名称', dataIndex: 'name', width: 160 },
    { title: '联系人', dataIndex: 'contact_name', width: 100 },
    { title: '电话', dataIndex: 'contact_phone', width: 130 },
    { title: '业务员', key: 'salesman', width: 100, render: (_: unknown, r: CustomerItem) => r.salesman?.name ?? '-' },
    { title: '结算', dataIndex: 'settlement_mode', width: 80, render: (v: string) => v === 'credit' ? '赊销' : '现结' },
    {
      title: '操作', key: 'action', width: 180,
      render: (_, record) => (
        <Space>
          <a onClick={() => navigate(`/customers/${record.id}/360`)}>360</a>
          <a onClick={() => setDrawerCustomer(record)}>订单</a>
          <a style={{ color: '#722ed1' }} onClick={() => setBrandBindCustomer(record)}>品牌</a>
          <a onClick={() => handleEdit(record)}>编辑</a>
        </Space>
      ),
    },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space wrap>
          <Title level={4} style={{ margin: 0 }}>客户管理</Title>
          <Input.Search allowClear placeholder="搜索名称/联系人/电话"
            style={{ width: 240 }} onSearch={setKeyword} />
          <Select placeholder="全部类型" allowClear style={{ width: 120 }} onChange={setTypeFilter}
            options={[{ value: 'channel', label: '渠道客户' }, { value: 'group_purchase', label: '团购客户' }]} />
          <Select placeholder="结算方式" allowClear style={{ width: 110 }} onChange={setSettlementFilter}
            options={[{ value: 'credit', label: '赊销' }, { value: 'cash', label: '现结' }]} />
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingRecord(null); form.resetFields(); setModalOpen(true); }}>新建客户</Button>
      </div>
      <Table<CustomerItem> columns={columns} dataSource={data} rowKey="id" loading={isLoading} pagination={{ pageSize: 20 }} />

      {/* 订单历史抽屉 */}
      <Drawer
        title={drawerCustomer ? `${drawerCustomer.name} — 历史订单` : ''}
        open={!!drawerCustomer}
        onClose={() => setDrawerCustomer(null)}
        width={700}
      >
        {drawerCustomer && (
          <>
            <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="编号">{drawerCustomer.code}</Descriptions.Item>
              <Descriptions.Item label="类型"><Tag color={typeColor[drawerCustomer.customer_type]}>{typeLabel[drawerCustomer.customer_type]}</Tag></Descriptions.Item>
              <Descriptions.Item label="联系人">{drawerCustomer.contact_name}</Descriptions.Item>
              <Descriptions.Item label="电话">{drawerCustomer.contact_phone}</Descriptions.Item>
              <Descriptions.Item label="业务员">{drawerCustomer.salesman?.name ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="结算方式">{drawerCustomer.settlement_mode === 'credit' ? '赊销' : '现结'}</Descriptions.Item>
            </Descriptions>
            <Tabs
              items={[
                { key: 'all', label: '全部' },
                ...brands.map(b => ({ key: b.id, label: b.name })),
              ]}
              onChange={(k) => setOrderBrandFilter(k === 'all' ? null : k)}
              style={{ marginBottom: 8 }}
            />
            <Table<OrderItem>
              columns={orderColumns}
              dataSource={filteredOrders}
              rowKey="id"
              loading={ordersLoading}
              size="small"
              pagination={{ pageSize: 10 }}
            />
          </>
        )}
      </Drawer>

      {/* 新建/编辑弹窗 */}
      <Modal
        title={editingRecord ? '编辑客户' : '新建客户'}
        open={modalOpen}
        onOk={handleOk}
        onCancel={() => { setModalOpen(false); setEditingRecord(null); form.resetFields(); }}
        confirmLoading={createMutation.isPending || editMutation.isPending}
        okText="确认"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical" initialValues={{ customer_type: 'channel', settlement_mode: 'cash' }}>
          <Form.Item name="code" label="客户编号" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="customer_type" label="客户类型" rules={[{ required: true }]}>
            <Select options={[{ value: 'channel', label: '渠道客户' }, { value: 'group_purchase', label: '团购客户' }]} />
          </Form.Item>
          <Form.Item name="salesman_id" label="绑定业务员">
            <Select
              showSearch
              placeholder="请选择业务员"
              optionFilterProp="label"
              options={employees.map(e => ({ value: e.id, label: e.name }))}
              allowClear
            />
          </Form.Item>
          <Form.Item name="contact_name" label="联系人"><Input /></Form.Item>
          <Form.Item name="contact_phone" label="电话"><Input /></Form.Item>
          <Form.Item name="settlement_mode" label="结算方式" rules={[{ required: true }]}>
            <Select options={[{ value: 'cash', label: '现结' }, { value: 'credit', label: '赊销' }]} />
          </Form.Item>
          <Form.Item name="credit_days" label="账期天数"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item>
        </Form>
      </Modal>

      {/* 品牌绑定弹窗 */}
      <Modal title={`品牌绑定 — ${brandBindCustomer?.name ?? ''}`} open={!!brandBindCustomer}
        onCancel={() => { setBrandBindCustomer(null); brandBindForm.resetFields(); }}
        footer={null} width={500}>
        {/* 已绑定列表 */}
        <div style={{ marginBottom: 16 }}>
          {brandBindings.length === 0 ? (
            <div style={{ color: '#999', padding: 8 }}>暂无绑定品牌</div>
          ) : (
            brandBindings.map(b => {
              const brand = brands.find(br => br.id === b.brand_id);
              const emp = employees.find(e => e.id === b.salesman_id);
              return (
                <div key={b.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid #f0f0f0' }}>
                  <Space>
                    <Tag color="blue">{brand?.name ?? b.brand_id.slice(0, 8)}</Tag>
                    <span style={{ color: '#666' }}>业务员：{emp?.name ?? b.salesman_id.slice(0, 8)}</span>
                  </Space>
                  <a style={{ color: '#ff4d4f' }} onClick={() => unbindBrandMut.mutate(b.brand_id)}>解绑</a>
                </div>
              );
            })
          )}
        </div>

        {/* 添加绑定 */}
        <Form form={brandBindForm} layout="inline"
          onFinish={(v) => bindBrandMut.mutate(v)}
          style={{ gap: 8 }}>
          <Form.Item name="brand_id" rules={[{ required: true, message: '选品牌' }]}>
            <Select showSearch optionFilterProp="label" placeholder="选择品牌" style={{ width: 150 }}
              options={brands.filter(b => !brandBindings.some(bb => bb.brand_id === b.id)).map(b => ({ value: b.id, label: b.name }))} />
          </Form.Item>
          <Form.Item name="salesman_id" rules={[{ required: true, message: '选业务员' }]}>
            <Select showSearch optionFilterProp="label" placeholder="选择业务员" style={{ width: 150 }}
              options={employees.map(e => ({ value: e.id, label: e.name }))} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={bindBrandMut.isPending}>绑定</Button>
        </Form>
      </Modal>
    </>
  );
}

export default CustomerList;
