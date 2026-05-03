/**
 * 商城仓库管理
 *
 * 列表 + 新建 + 禁用/启用 + 绑定业务员管理员
 */
import { useState } from 'react';
import {
  Button, Form, Input, message, Modal, Select, Space, Switch, Table, Tag, Typography,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title } = Typography;

interface MallWarehouse {
  id: string;
  code: string;
  name: string;
  address?: string;
  manager_user_id?: string;
  manager?: { nickname: string; phone?: string };
  is_active: boolean;
  created_at: string;
}

export default function WarehouseList() {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<MallWarehouse | null>(null);

  const { data, isLoading } = useQuery<{ records: MallWarehouse[]; total: number }>({
    queryKey: ['mall-warehouses'],
    queryFn: () => api.get('/mall/admin/warehouses').then(r => r.data),
  });
  const rows = data?.records || [];

  // 业务员下拉（用于选管理员）
  const { data: salesmenResp } = useQuery<any>({
    queryKey: ['mall-salesmen-active'],
    queryFn: () => api.get('/mall/admin/salesmen', { params: { status: 'active', limit: 100 } })
      .then(r => r.data).catch(() => ({ records: [] })),
  });
  const salesmen: any[] = salesmenResp?.records || [];

  const createMut = useMutation({
    mutationFn: (body: any) => api.post('/mall/admin/warehouses', body),
    onSuccess: () => {
      message.success('已新建仓库');
      setModalOpen(false); form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['mall-warehouses'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '新建失败'),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: any }) => api.put(`/mall/admin/warehouses/${id}`, body),
    onSuccess: () => {
      message.success('已更新');
      setEditing(null); setModalOpen(false); form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['mall-warehouses'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '更新失败'),
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api.put(`/mall/admin/warehouses/${id}`, { is_active }),
    onSuccess: () => {
      message.success('状态已切换');
      queryClient.invalidateQueries({ queryKey: ['mall-warehouses'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '切换失败'),
  });

  const openCreate = () => { setEditing(null); form.resetFields(); setModalOpen(true); };
  const openEdit = (w: MallWarehouse) => {
    setEditing(w);
    form.setFieldsValue({
      code: w.code, name: w.name, address: w.address,
      manager_user_id: w.manager_user_id,
    });
    setModalOpen(true);
  };

  const columns: ColumnsType<MallWarehouse> = [
    { title: '编码', dataIndex: 'code', width: 140 },
    { title: '名称', dataIndex: 'name' },
    { title: '地址', dataIndex: 'address', ellipsis: true },
    {
      title: '管理员', key: 'mgr', width: 160,
      render: (_, r) => r.manager
        ? <span>{r.manager.nickname}{r.manager.phone && <span style={{ color: '#999', fontSize: 12 }}> · {r.manager.phone}</span>}</span>
        : <span style={{ color: '#999' }}>未绑定</span>,
    },
    {
      title: '状态', dataIndex: 'is_active', width: 90,
      render: (v: boolean, r) => (
        <Switch
          checked={v}
          onChange={(checked) => toggleMut.mutate({ id: r.id, is_active: checked })}
        />
      ),
    },
    {
      title: '创建时间', dataIndex: 'created_at', width: 160,
      render: (v?: string) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '操作', key: 'act', width: 90, fixed: 'right' as const,
      render: (_, r) => <Button size="small" onClick={() => openEdit(r)}>编辑</Button>,
    },
  ];

  const onFinish = (values: any) => {
    const body = {
      code: values.code, name: values.name,
      address: values.address || null,
      manager_user_id: values.manager_user_id || null,
    };
    if (editing) updateMut.mutate({ id: editing.id, body });
    else createMut.mutate(body);
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4}>商城仓库</Title>
        <Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建仓库</Button>
        </Space>
      </div>

      <Table
        dataSource={rows}
        rowKey="id"
        columns={columns}
        loading={isLoading}
        size="middle"
        pagination={false}
      />

      <Modal
        title={editing ? '编辑仓库' : '新建仓库'}
        open={modalOpen}
        onOk={() => form.submit()}
        onCancel={() => { setModalOpen(false); setEditing(null); form.resetFields(); }}
        confirmLoading={createMut.isPending || updateMut.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item name="code" label="仓库编码" rules={[{ required: true, max: 20 }]}>
            <Input placeholder="如 W001" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="name" label="仓库名称" rules={[{ required: true, max: 80 }]}>
            <Input placeholder="如 主仓" />
          </Form.Item>
          <Form.Item name="address" label="地址">
            <Input.TextArea rows={2} placeholder="仓库地址（选填）" />
          </Form.Item>
          <Form.Item
            name="manager_user_id"
            label="管理员（业务员）"
            extra="CHECK 约束：仅可选 user_type=salesman"
          >
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="选择业务员做仓库管理员"
              options={salesmen.map((s: any) => ({
                value: s.id,
                label: `${s.nickname || s.username}${s.phone ? ' · ' + s.phone : ''}`,
              }))}
            />
          </Form.Item>
          {editing && (
            <Form.Item label="状态">
              <Tag color={editing.is_active ? 'success' : 'default'}>
                {editing.is_active ? '启用中' : '已停用'}
              </Tag>
              <span style={{ color: '#999', fontSize: 12 }}> （在列表里用开关切换）</span>
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
}
