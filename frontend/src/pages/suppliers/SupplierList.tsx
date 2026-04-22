import { useState } from 'react';
import { Button, Form, Input, InputNumber, message, Modal, Select, Table, Tag } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

interface SupplierItem {
  id: string;
  code: string;
  name: string;
  type: string;
  contact_name: string | null;
  contact_phone: string | null;
  address: string | null;
  tax_no: string | null;
  status: string;
  credit_limit: number | null;
}

interface SupplierFormValues {
  code: string;
  name: string;
  type: string;
  contact_name: string;
  contact_phone: string;
  address: string;
  tax_no: string;
  credit_limit: number;
}

const TYPE_MAP: Record<string, { color: string; label: string }> = {
  supplier: { color: 'blue', label: '供应商' },
  manufacturer: { color: 'purple', label: '厂家' },
};

const STATUS_COLOR: Record<string, string> = {
  active: 'green',
  inactive: 'default',
};

function SupplierList() {
  const queryClient = useQueryClient();
  const [form] = Form.useForm<SupplierFormValues>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<SupplierItem | null>(null);

  const { brandId, params } = useBrandFilter();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data: brands = [] } = useQuery<{id: string; name: string}[]>({
    queryKey: ['brands-list'],
    queryFn: () => api.get('/products/brands').then(r => extractItems(r.data)),
  });

  const { data: listResp, isLoading } = useQuery<{ items: SupplierItem[]; total: number }>({
    queryKey: ['suppliers', brandId, page, pageSize],
    queryFn: async () => {
      const { data } = await api.get('/suppliers', { params: { ...params, skip: (page - 1) * pageSize, limit: pageSize } });
      return data;
    },
  });
  const data = listResp?.items ?? [];
  const total = listResp?.total ?? 0;

  const createMutation = useMutation({
    mutationFn: async (values: SupplierFormValues) => {
      const { data } = await api.post('/suppliers', values);
      return data;
    },
    onSuccess: () => {
      message.success('创建成功');
      setModalOpen(false);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['suppliers'] });
    },
    onError: (err: any) => {
      message.error(err?.response?.data?.detail ?? '创建失败');
    },
  });

  const editMutation = useMutation({
    mutationFn: async (values: SupplierFormValues) => {
      const { data } = await api.put(`/suppliers/${editingRecord!.id}`, values);
      return data;
    },
    onSuccess: () => {
      message.success('更新成功');
      setModalOpen(false);
      setEditingRecord(null);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['suppliers'] });
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

  const handleCancel = () => {
    setModalOpen(false);
    setEditingRecord(null);
    form.resetFields();
  };

  const handleEdit = (record: SupplierItem) => {
    setEditingRecord(record);
    setModalOpen(true);
    form.setFieldsValue({
      code: record.code,
      name: record.name,
      type: record.type,
      contact_name: record.contact_name ?? '',
      contact_phone: record.contact_phone ?? '',
      address: record.address ?? '',
      tax_no: record.tax_no ?? '',
      credit_limit: record.credit_limit ?? 0,
    });
  };

  const columns: ColumnsType<SupplierItem> = [
    { title: '编号', dataIndex: 'code', width: 120 },
    { title: '名称', dataIndex: 'name', width: 200 },
    {
      title: '类型', dataIndex: 'type', width: 100,
      render: (t: string) => {
        const info = TYPE_MAP[t] ?? { color: 'default', label: t };
        return <Tag color={info.color}>{info.label}</Tag>;
      },
    },
    { title: '联系人', dataIndex: 'contact_name', width: 100 },
    { title: '电话', dataIndex: 'contact_phone', width: 130 },
    {
      title: '状态', dataIndex: 'status', width: 80,
      render: (s: string) => <Tag color={STATUS_COLOR[s] || 'default'}>{s}</Tag>,
    },
    { title: '授信额度', dataIndex: 'credit_limit', width: 120, align: 'right', render: (v: number | null) => v != null ? `¥${Number(v).toFixed(2)}` : '-' },
    { title: '操作', key: 'action', width: 120, render: (_, record) => <><a onClick={() => handleEdit(record)}>编辑</a></> },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>供应商管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingRecord(null); setModalOpen(true); }}>新建供应商</Button>
      </div>
      <Table<SupplierItem> columns={columns} dataSource={data} rowKey="id" loading={isLoading} scroll={{ x: 900 }} pagination={{ current: page, pageSize, total, showTotal: (t) => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} />

      <Modal
        title={editingRecord ? '编辑供应商' : '新建供应商'}
        open={modalOpen}
        onOk={handleOk}
        onCancel={handleCancel}
        confirmLoading={createMutation.isPending || editMutation.isPending}
        okText="确认"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item name="code" label="编号" rules={[{ required: true, message: '请输入编号' }]}>
            <Input placeholder="请输入编号" />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="请输入名称" />
          </Form.Item>
          <Form.Item name="type" label="类型" rules={[{ required: true, message: '请选择类型' }]}>
            <Select placeholder="请选择类型">
              <Select.Option value="supplier">供应商</Select.Option>
              <Select.Option value="manufacturer">厂家</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="brand_id" label="所属品牌">
            <Select showSearch optionFilterProp="label" placeholder="选择品牌" allowClear
              options={brands.map((b: any) => ({ value: b.id, label: b.name }))} />
          </Form.Item>
          <Form.Item name="contact_name" label="联系人">
            <Input placeholder="请输入联系人" />
          </Form.Item>
          <Form.Item name="contact_phone" label="联系电话">
            <Input placeholder="请输入联系电话" />
          </Form.Item>
          <Form.Item name="address" label="地址">
            <Input placeholder="请输入地址" />
          </Form.Item>
          <Form.Item name="tax_no" label="税号">
            <Input placeholder="请输入税号" />
          </Form.Item>
          <Form.Item name="credit_limit" label="授信额度">
            <InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" placeholder="请输入授信额度" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default SupplierList;
