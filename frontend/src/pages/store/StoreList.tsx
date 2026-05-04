/**
 * 门店列表
 * 门店其实是 warehouse_type='store' 的仓库。CRUD 复用 /warehouses 端点。
 */
import { useState } from 'react';
import {
  Button, Form, Input, message, Modal, Table, Tag, Typography,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';

const { Title } = Typography;

interface Store {
  id: string;
  code: string;
  name: string;
  warehouse_type: string;
  brand_id?: string;
  address?: string;
  is_active: boolean;
}

export default function StoreList() {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Store | null>(null);

  const { data: allWhs = [], isLoading } = useQuery<Store[]>({
    queryKey: ['warehouses-all-for-store'],
    queryFn: () => api.get('/inventory/warehouses').then(r => extractItems<Store>(r.data)),
  });
  const stores = allWhs.filter(w => w.warehouse_type === 'store');

  const createMut = useMutation({
    mutationFn: (v: any) => api.post('/warehouses', { ...v, warehouse_type: 'store' }),
    onSuccess: () => {
      message.success('门店已创建');
      setModalOpen(false); form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['warehouses-all-for-store'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: any }) =>
      api.put(`/warehouses/${id}`, body),
    onSuccess: () => {
      message.success('已更新');
      setModalOpen(false); setEditing(null); form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['warehouses-all-for-store'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '更新失败'),
  });

  const columns: ColumnsType<Store> = [
    { title: '编码', dataIndex: 'code', width: 140 },
    { title: '名称', dataIndex: 'name', width: 200 },
    { title: '地址', dataIndex: 'address', ellipsis: true },
    {
      title: '状态', dataIndex: 'is_active', width: 80,
      render: (v) => v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>,
    },
    {
      title: '操作', key: 'act', width: 80,
      render: (_, r) => (
        <a onClick={() => {
          setEditing(r);
          form.setFieldsValue(r);
          setModalOpen(true);
        }}>编辑</a>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>门店</Title>
        <Button type="primary" icon={<PlusOutlined />}
          onClick={() => { setEditing(null); form.resetFields(); setModalOpen(true); }}>
          新建门店
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={stores}
        rowKey="id"
        loading={isLoading}
        pagination={false}
        size="middle"
      />

      <Modal
        title={editing ? '编辑门店' : '新建门店'}
        open={modalOpen}
        onCancel={() => { setModalOpen(false); setEditing(null); form.resetFields(); }}
        onOk={() => form.validateFields().then((v: any) => {
          if (editing) updateMut.mutate({ id: editing.id, body: v });
          else createMut.mutate(v);
        })}
        confirmLoading={createMut.isPending || updateMut.isPending}
        width={520}
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="code" label="门店编码"
            rules={[{ required: true }]}
            extra="建议用拼音缩写如 QHL / WLY / HZ / XJL">
            <Input placeholder="QHL01" />
          </Form.Item>
          <Form.Item name="name" label="门店名称" rules={[{ required: true }]}>
            <Input placeholder="青花郎专卖店（北京）" />
          </Form.Item>
          <Form.Item name="address" label="地址">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
