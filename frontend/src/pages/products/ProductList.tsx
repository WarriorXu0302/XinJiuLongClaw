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
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data: listResp, isLoading } = useQuery<{ items: ProductItem[]; total: number }>({
    queryKey: ['products', brandId, page, pageSize],
    queryFn: async () => {
      const { data } = await api.get('/products', { params: { ...params, skip: (page - 1) * pageSize, limit: pageSize } });
      return data;
    },
  });
  const data = listResp?.items ?? [];
  const total = listResp?.total ?? 0;

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
    form.setFieldsValue({
      code: record.code, name: record.name, category: record.category,
      unit: record.unit, bottles_per_case: record.bottles_per_case,
      spec: record.spec ?? '',
      purchase_price: record.purchase_price, sale_price: record.sale_price,
      min_sale_price: (record as any).min_sale_price,
      max_sale_price: (record as any).max_sale_price,
    });
  };

  // 下架/启用切换：下架前查 mall 侧挂靠商品数，有则弹确认框问"是否同步下架商城商品"
  const handleToggleStatus = async (record: ProductItem) => {
    if (record.status !== 'active') {
      try {
        await api.put(`/products/${record.id}`, { status: 'active' });
        message.success('已启用');
        queryClient.invalidateQueries({ queryKey: ['products'] });
      } catch (err: any) {
        message.error(err?.response?.data?.detail ?? '操作失败');
      }
      return;
    }
    // active → inactive：查 mall 影响
    try {
      const { data: impact } = await api.get(`/products/${record.id}/mall-cascade-impact`);
      const onSaleCount = impact?.mall_on_sale ?? 0;
      if (onSaleCount === 0) {
        Modal.confirm({
          title: '确认下架该商品？',
          content: '商城未挂靠在售商品。',
          okText: '下架',
          cancelText: '取消',
          onOk: async () => {
            try {
              await api.put(`/products/${record.id}`, { status: 'inactive' });
              message.success('已下架');
              queryClient.invalidateQueries({ queryKey: ['products'] });
            } catch (err: any) {
              message.error(err?.response?.data?.detail ?? '操作失败');
            }
          },
        });
        return;
      }
      const names = (impact.mall_on_sale_items ?? []).map((m: any) => m.name).slice(0, 5).join('、');
      Modal.confirm({
        title: '商城侧有挂靠商品仍在售',
        width: 560,
        content: (
          <div>
            <p>本商品被 <b>{onSaleCount}</b> 个在售商城商品引用（source_product_id）。</p>
            <p style={{ color: '#8c8c8c' }}>{names}{onSaleCount > 5 ? ` 等 ${onSaleCount} 个` : ''}</p>
            <p>如果仅下架 ERP 端，C 端下单时可能仍能买到此商品。建议一并下架商城商品。</p>
          </div>
        ),
        okText: '同步下架商城',
        cancelText: '仅下架 ERP',
        onOk: async () => {
          try {
            await api.put(`/products/${record.id}?cascade_mall=true`, { status: 'inactive' });
            message.success(`已下架 ERP 与 ${onSaleCount} 个商城商品`);
            queryClient.invalidateQueries({ queryKey: ['products'] });
          } catch (err: any) {
            message.error(err?.response?.data?.detail ?? '操作失败');
          }
        },
        onCancel: async () => {
          try {
            await api.put(`/products/${record.id}`, { status: 'inactive' });
            message.success('已下架 ERP；商城侧仍在售，请手动处理');
            queryClient.invalidateQueries({ queryKey: ['products'] });
          } catch (err: any) {
            message.error(err?.response?.data?.detail ?? '操作失败');
          }
        },
      });
    } catch (err: any) {
      message.error(err?.response?.data?.detail ?? '查询商城影响失败');
    }
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
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_, record) => (
        <>
          <a onClick={() => handleEdit(record)}>编辑</a>
          <span style={{ margin: '0 8px', color: '#d9d9d9' }}>|</span>
          <a onClick={() => handleToggleStatus(record)}>{record.status === 'active' ? '下架' : '启用'}</a>
        </>
      ),
    },
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
      <Table<ProductItem> columns={columns} dataSource={data} rowKey="id" loading={isLoading} pagination={{ current: page, pageSize, total, showTotal: (t) => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} />

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
          <div style={{ display: 'flex', gap: 16 }}>
            <Form.Item name="min_sale_price" label="门店零售下限"
              tooltip="专卖店店员收银时售价不得低于此值；空 = 未启用门店零售" style={{ flex: 1 }}>
              <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" />
            </Form.Item>
            <Form.Item name="max_sale_price" label="门店零售上限"
              tooltip="专卖店店员收银时售价不得超过此值" style={{ flex: 1 }}>
              <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" />
            </Form.Item>
          </div>
        </Form>
      </Modal>
    </>
  );
}

export default ProductList;