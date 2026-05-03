/**
 * 热搜词管理
 *
 * 列表 + 新增 / 编辑 / 启用切换 / 删除
 * C 端 /api/mall/search/hot-keywords 读 is_active=true 的按 sort_order 展示
 */
import { useState } from 'react';
import {
  Button, Form, Input, InputNumber, message, Modal, Popconfirm, Space, Switch, Table, Tag, Typography,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title } = Typography;

interface Keyword {
  id: number;
  keyword: string;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at?: string;
}

export default function SearchKeywords() {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Keyword | null>(null);

  const { data, isLoading } = useQuery<{ records: Keyword[]; total: number }>({
    queryKey: ['mall-search-keywords'],
    queryFn: () => api.get('/mall/admin/search-keywords').then(r => r.data),
  });
  const rows = data?.records || [];

  const createMut = useMutation({
    mutationFn: (body: any) => api.post('/mall/admin/search-keywords', body),
    onSuccess: () => {
      message.success('已新增');
      setModalOpen(false); form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['mall-search-keywords'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '新增失败'),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) =>
      api.put(`/mall/admin/search-keywords/${id}`, body),
    onSuccess: () => {
      message.success('已更新');
      setModalOpen(false); setEditing(null); form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['mall-search-keywords'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '更新失败'),
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      api.put(`/mall/admin/search-keywords/${id}`, { is_active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mall-search-keywords'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '操作失败'),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.delete(`/mall/admin/search-keywords/${id}`),
    onSuccess: () => {
      message.success('已删除');
      queryClient.invalidateQueries({ queryKey: ['mall-search-keywords'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '删除失败'),
  });

  const columns: ColumnsType<Keyword> = [
    {
      title: '关键词',
      dataIndex: 'keyword',
      render: (v: string) => <span style={{ fontWeight: 500 }}>{v}</span>,
    },
    {
      title: '排序',
      dataIndex: 'sort_order',
      width: 80,
      render: (v: number) => <Tag>{v}</Tag>,
    },
    {
      title: '启用',
      dataIndex: 'is_active',
      width: 100,
      render: (v: boolean, r) => (
        <Switch
          checked={v}
          onChange={(checked) => toggleMut.mutate({ id: r.id, is_active: checked })}
        />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'act',
      width: 160,
      render: (_, r) => (
        <Space>
          <a onClick={() => {
            setEditing(r);
            form.setFieldsValue({ keyword: r.keyword, sort_order: r.sort_order, is_active: r.is_active });
            setModalOpen(true);
          }}>编辑</a>
          <Popconfirm
            title={`删除关键词「${r.keyword}」？`}
            onConfirm={() => deleteMut.mutate(r.id)}
          >
            <a style={{ color: '#ff4d4f' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={4}>热搜词管理</Title>

      <Space style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setEditing(null);
            form.resetFields();
            form.setFieldsValue({ sort_order: 0, is_active: true });
            setModalOpen(true);
          }}
        >新增关键词</Button>
      </Space>

      <Table
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={isLoading}
        size="middle"
        pagination={{ pageSize: 50, showTotal: t => `共 ${t} 个` }}
      />

      <Modal
        title={editing ? '编辑关键词' : '新增关键词'}
        open={modalOpen}
        onCancel={() => { setModalOpen(false); setEditing(null); form.resetFields(); }}
        onOk={() => {
          form.validateFields().then((v: any) => {
            if (editing) updateMut.mutate({ id: editing.id, body: v });
            else createMut.mutate(v);
          });
        }}
        confirmLoading={createMut.isPending || updateMut.isPending}
        width={480}
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="keyword"
            label="关键词"
            rules={[{ required: true, min: 1, max: 100, message: '1-100 字' }]}
          >
            <Input placeholder="例：飞天茅台" />
          </Form.Item>
          <Form.Item name="sort_order" label="排序（越小越靠前）" initialValue={0}>
            <InputNumber min={0} max={9999} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
