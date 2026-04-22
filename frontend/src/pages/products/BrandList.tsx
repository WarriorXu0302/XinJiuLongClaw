import { useState } from 'react';
import { Button, Form, Input, message, Modal, Select, Space, Table, Tag, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';

const { Title } = Typography;

interface BrandItem {
  id: string;
  code: string;
  name: string;
  manufacturer_id?: string;
  status: string;
}

function BrandList() {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<BrandItem | null>(null);

  const { data = [], isLoading } = useQuery<BrandItem[]>({
    queryKey: ['brands'],
    queryFn: () => api.get('/products/brands').then(r => extractItems<BrandItem>(r.data)),
  });

  const { data: suppliers = [] } = useQuery<{id: string; name: string; type: string}[]>({
    queryKey: ['suppliers-select'],
    queryFn: () => api.get('/suppliers').then(r => extractItems<{id: string; name: string; type: string}>(r.data)),
  });

  const manufacturers = suppliers.filter(s => s.type === 'manufacturer');

  const createMutation = useMutation({
    mutationFn: (v: any) => api.post('/products/brands', v),
    onSuccess: () => { message.success('品牌创建成功'); setModalOpen(false); form.resetFields(); queryClient.invalidateQueries({ queryKey: ['brands'] }); queryClient.invalidateQueries({ queryKey: ['brands-list'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  const editMutation = useMutation({
    mutationFn: (v: any) => api.put(`/products/brands/${editingRecord!.id}`, v),
    onSuccess: () => { message.success('更新成功'); setModalOpen(false); setEditingRecord(null); form.resetFields(); queryClient.invalidateQueries({ queryKey: ['brands'] }); queryClient.invalidateQueries({ queryKey: ['brands-list'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '更新失败'),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/products/brands/${id}`),
    onSuccess: () => { message.success('已删除'); queryClient.invalidateQueries({ queryKey: ['brands'] }); queryClient.invalidateQueries({ queryKey: ['brands-list'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '删除失败，可能有关联数据'),
  });

  const columns: ColumnsType<BrandItem> = [
    { title: '编码', dataIndex: 'code', width: 120 },
    { title: '品牌名称', dataIndex: 'name', width: 200 },
    { title: '关联厂家', dataIndex: 'manufacturer_id', width: 150, render: (v: string) => {
      const m = manufacturers.find(s => s.id === v);
      return m?.name ?? (v ? v.slice(0, 8) : '-');
    }},
    { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => <Tag color={v === 'active' ? 'green' : 'default'}>{v === 'active' ? '启用' : '停用'}</Tag> },
    {
      title: '操作', key: 'action', width: 150,
      render: (_, record) => (
        <Space>
          <a onClick={() => { setEditingRecord(record); form.setFieldsValue(record); setModalOpen(true); }}>编辑</a>
          <a style={{ color: '#ff4d4f' }} onClick={() => Modal.confirm({ title: '确认删除', content: `删除品牌「${record.name}」？关联数据可能导致删除失败。`, onOk: () => deleteMutation.mutate(record.id) })}>删除</a>
        </Space>
      ),
    },
  ];

  const handleOk = () => {
    form.validateFields().then(values => {
      if (editingRecord) editMutation.mutate(values);
      else createMutation.mutate(values);
    });
  };

  return (
    <>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Title level={4} style={{ margin: 0 }}>品牌管理</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingRecord(null); form.resetFields(); setModalOpen(true); }}>新建品牌</Button>
      </Space>
      <Table<BrandItem> columns={columns} dataSource={data} rowKey="id" loading={isLoading} size="middle" pagination={false} />

      <Modal title={editingRecord ? '编辑品牌' : '新建品牌'} open={modalOpen} onOk={handleOk}
        onCancel={() => { setModalOpen(false); setEditingRecord(null); form.resetFields(); }}
        confirmLoading={createMutation.isPending || editMutation.isPending}>
        <Form form={form} layout="vertical">
          <Form.Item name="code" label="品牌编码" rules={[{ required: true }]}><Input placeholder="如 QHL" /></Form.Item>
          <Form.Item name="name" label="品牌名称" rules={[{ required: true }]}><Input placeholder="如 青花郎" /></Form.Item>
          <Form.Item name="manufacturer_id" label="关联厂家">
            <Select showSearch optionFilterProp="label" placeholder="选择厂家" allowClear
              options={manufacturers.map(m => ({ value: m.id, label: m.name }))} />
          </Form.Item>
          <Form.Item name="status" label="状态" initialValue="active">
            <Select options={[{ value: 'active', label: '启用' }, { value: 'inactive', label: '停用' }]} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default BrandList;