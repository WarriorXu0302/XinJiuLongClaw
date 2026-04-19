import { useState } from 'react';
import { Button, Form, Input, InputNumber, message, Modal, Select, Table, Tag } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import { useBrandFilter } from '../../stores/useBrandFilter';
import api from '../../api/client';

interface ProductItem {
  id: string;
  code: string;
  name: string;
  category: string;
  brand_id: string | null;
  brand?: { name: string };
  unit: string;
  bottles_per_case: number;
  spec?: string;
  purchase_price?: number;
  sale_price?: number;
  status: string;
}

const CATEGORY_OPTIONS = [
  { value: 'liquor', label: '酒类' },
  { value: 'gift', label: '赠品' },
  { value: 'material', label: '物料' },
  { value: 'other', label: '其他' },
];
const CATEGORY_LABEL: Record<string, string> = { liquor: '酒类', gift: '赠品', material: '物料', other: '其他' };
const CATEGORY_COLOR: Record<string, string> = { liquor: 'blue', gift: 'purple', material: 'cyan', other: 'default' };

function ProductList() {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const watchCategory = Form.useWatch('category', form) ?? 'liquor';
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<ProductItem | null>(null);
  const { brandId, params } = useBrandFilter();

  const { data = [], isLoading } = useQuery({
    queryKey: ['products', brandId],
    queryFn: async () => { const { data } = await api.get('/products', { params }); return data; },
  });

  const createMutation = useMutation({
    mutationFn: async (values: any) => {
      // 自动绑定当前品牌
      if (brandId) values.brand_id = brandId;
      const { data } = await api.post('/products', values);
      return data;
    },
    onSuccess: () => {
      message.success('创建成功');
      setModalOpen(false);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
    onError: (err: any) => message.error(err?.response?.data?.detail ?? '创建失败'),
  });

  const editMutation = useMutation({
    mutationFn: async (values: any) => {
      const { data } = await api.put(`/products/${editingRecord!.id}`, values);
      return data;
    },
    onSuccess: () => {
      message.success('更新成功');
      setModalOpen(false);
      setEditingRecord(null);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
    onError: (err: any) => message.error(err?.response?.data?.detail ?? '更新失败'),
  });

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingRecord) editMutation.mutate(values);
      else createMutation.mutate(values);
    } catch { /* validation */ }
  };

  const handleEdit = (record: ProductItem) => {
    setEditingRecord(record);
    setModalOpen(true);
    form.setFieldsValue({ code: record.code, name: record.name, category: record.category, unit: record.unit, bottles_per_case: record.bottles_per_case, spec: record.spec ?? '', purchase_price: record.purchase_price, sale_price: record.sale_price });
  };

  const columns: ColumnsType<ProductItem> = [
    { title: '商品编号', dataIndex: 'code', width: 110 },
    { title: '种类', dataIndex: 'category', width: 70, render: (v: string) => <Tag color={CATEGORY_COLOR[v] ?? 'default'}>{CATEGORY_LABEL[v] ?? v}</Tag> },
    { title: '名称', dataIndex: 'name', width: 180 },
    { title: '规格', dataIndex: 'spec', width: 110, render: (v: string) => v || '-' },
    { title: '装箱', key: 'bpc', width: 80, render: (_, r) => r.category === 'liquor' ? `${r.bottles_per_case}瓶/箱` : '-' },
    { title: '进货价', dataIndex: 'purchase_price', width: 80, align: 'right', render: (v: number) => v ? `¥${Number(v).toFixed(0)}` : '-' },
    { title: '售价', dataIndex: 'sale_price', width: 80, align: 'right', render: (v: number) => v ? `¥${Number(v).toFixed(0)}` : '-' },
    { title: '状态', dataIndex: 'status', width: 60, render: (v: string) => <Tag color={v === 'active' ? 'green' : 'default'}>{v === 'active' ? '启用' : '停用'}</Tag> },
    { title: '操作', key: 'action', width: 60, render: (_, record) => <a onClick={() => handleEdit(record)}>编辑</a> },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>商品管理</h2>
        <Button type="primary" icon={<PlusOutlined />} disabled={!brandId}
          onClick={() => { setEditingRecord(null); form.resetFields(); setModalOpen(true); }}>
          {brandId ? '新建商品' : '请先选择品牌'}
        </Button>
      </div>
      <Table<ProductItem> columns={columns} dataSource={data} rowKey="id" loading={isLoading} pagination={{ pageSize: 20 }} />

      <Modal title={editingRecord ? '编辑商品' : '新建商品'} open={modalOpen} onOk={handleOk}
        onCancel={() => { setModalOpen(false); setEditingRecord(null); form.resetFields(); }}
        confirmLoading={createMutation.isPending || editMutation.isPending} destroyOnHidden>
        <Form form={form} layout="vertical" initialValues={{ category: 'liquor', unit: '瓶', bottles_per_case: 6 }}>
          <div style={{ display: 'flex', gap: 16 }}>
            <Form.Item name="code" label="商品编号" rules={[{ required: true }]} style={{ flex: 1 }}><Input placeholder="如 QHL-53-500" /></Form.Item>
            <Form.Item name="category" label="种类" rules={[{ required: true }]} style={{ flex: 1 }}>
              <Select options={CATEGORY_OPTIONS} onChange={(v) => {
                if (v !== 'liquor') { form.setFieldsValue({ unit: '个', bottles_per_case: 1 }); }
                else { form.setFieldsValue({ unit: '瓶', bottles_per_case: 6 }); }
              }} />
            </Form.Item>
          </div>
          <Form.Item name="name" label="商品名称" rules={[{ required: true }]}><Input placeholder="如 青花郎53度500ml" /></Form.Item>
          <Form.Item name="spec" label="规格"><Input placeholder="如 500ml / 53度" /></Form.Item>
          {watchCategory === 'liquor' ? (
            <div style={{ display: 'flex', gap: 16 }}>
              <Form.Item name="unit" label="基本单位" rules={[{ required: true }]} style={{ flex: 1 }}>
                <Select options={[{ value: '瓶', label: '瓶' }, { value: '箱', label: '箱' }]} />
              </Form.Item>
              <Form.Item name="bottles_per_case" label="每箱瓶数" rules={[{ required: true }]} style={{ flex: 1 }}>
                <InputNumber min={1} max={99} style={{ width: '100%' }} placeholder="6" />
              </Form.Item>
            </div>
          ) : (
            <Form.Item name="unit" label="单位" initialValue="个">
              <Select options={[{ value: '个', label: '个' }, { value: '套', label: '套' }, { value: '瓶', label: '瓶' }]} />
            </Form.Item>
          )}
          <div style={{ display: 'flex', gap: 16 }}>
            <Form.Item name="purchase_price" label="进货价" style={{ flex: 1 }}>
              <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" />
            </Form.Item>
            <Form.Item name="sale_price" label="售价" style={{ flex: 1 }}>
              <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" />
            </Form.Item>
          </div>
        </Form>
      </Modal>
    </>
  );
}

export default ProductList;