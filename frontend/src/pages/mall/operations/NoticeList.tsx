/**
 * 店铺公告管理
 *
 * 列表（状态过滤）+ 新建 + 编辑 + 发布/撤回 + 删除
 */
import { useState } from 'react';
import {
  Button, Form, Input, InputNumber, message, Modal, Popconfirm, Space, Table, Tabs, Tag, Typography,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title } = Typography;

interface Notice {
  id: number;
  title: string;
  content?: string;
  publish_at?: string;
  sort_order: number;
  status: 'draft' | 'published';
  created_at: string;
  updated_at?: string;
}

export default function NoticeList() {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Notice | null>(null);
  const [statusTab, setStatusTab] = useState<string>('all');

  const { data, isLoading } = useQuery<{ records: Notice[]; total: number }>({
    queryKey: ['mall-notices', statusTab],
    queryFn: () => api.get('/mall/admin/notices', {
      params: { status: statusTab === 'all' ? undefined : statusTab, limit: 100 },
    }).then(r => r.data),
  });
  const rows = data?.records || [];

  const createMut = useMutation({
    mutationFn: (body: any) => api.post('/mall/admin/notices', body),
    onSuccess: () => {
      message.success('已新建');
      setModalOpen(false); form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['mall-notices'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '新建失败'),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) => api.put(`/mall/admin/notices/${id}`, body),
    onSuccess: () => {
      message.success('已更新');
      setModalOpen(false); setEditing(null); form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['mall-notices'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '更新失败'),
  });

  const publishMut = useMutation({
    mutationFn: (id: number) => api.post(`/mall/admin/notices/${id}/publish`),
    onSuccess: () => {
      message.success('已发布');
      queryClient.invalidateQueries({ queryKey: ['mall-notices'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '发布失败'),
  });

  const unpublishMut = useMutation({
    mutationFn: (id: number) => api.post(`/mall/admin/notices/${id}/unpublish`),
    onSuccess: () => {
      message.success('已撤回');
      queryClient.invalidateQueries({ queryKey: ['mall-notices'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '撤回失败'),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.delete(`/mall/admin/notices/${id}`),
    onSuccess: () => {
      message.success('已删除');
      queryClient.invalidateQueries({ queryKey: ['mall-notices'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '删除失败'),
  });

  const openCreate = () => { setEditing(null); form.resetFields(); form.setFieldsValue({ status: 'draft', sort_order: 0 }); setModalOpen(true); };
  const openEdit = (n: Notice) => {
    setEditing(n);
    form.setFieldsValue({ title: n.title, content: n.content, sort_order: n.sort_order });
    setModalOpen(true);
  };

  const columns: ColumnsType<Notice> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: '标题', dataIndex: 'title',
      render: (v: string, r) => <>
        {v}
        {r.sort_order > 0 && <Tag color="gold" style={{ marginLeft: 8 }}>置顶 {r.sort_order}</Tag>}
      </>,
    },
    {
      title: '内容摘要', dataIndex: 'content', width: 300, ellipsis: true,
      render: (v?: string) => v ? v.slice(0, 60) : '-',
    },
    {
      title: '状态', dataIndex: 'status', width: 80,
      render: (v: string) => v === 'published'
        ? <Tag color="green">已发布</Tag>
        : <Tag>草稿</Tag>,
    },
    {
      title: '发布时间', dataIndex: 'publish_at', width: 160,
      render: (v?: string) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '操作', key: 'act', width: 260, fixed: 'right' as const,
      render: (_, r) => (
        <Space size="small">
          <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
          {r.status === 'draft' ? (
            <Button size="small" type="primary" onClick={() => publishMut.mutate(r.id)}>
              发布
            </Button>
          ) : (
            <Button size="small" onClick={() => unpublishMut.mutate(r.id)}>
              撤回
            </Button>
          )}
          <Popconfirm title={`删除公告「${r.title}」？`} onConfirm={() => deleteMut.mutate(r.id)}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const onFinish = (values: any) => {
    if (editing) updateMut.mutate({ id: editing.id, body: values });
    else createMut.mutate(values);
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4}>店铺公告</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建公告</Button>
      </div>

      <Tabs
        activeKey={statusTab}
        onChange={setStatusTab}
        items={[
          { key: 'all', label: '全部' },
          { key: 'published', label: '已发布' },
          { key: 'draft', label: '草稿' },
        ]}
      />

      <Table
        dataSource={rows}
        rowKey="id"
        columns={columns}
        loading={isLoading}
        size="middle"
        pagination={false}
      />

      <Modal
        title={editing ? '编辑公告' : '新建公告'}
        open={modalOpen}
        onOk={() => form.submit()}
        onCancel={() => { setModalOpen(false); setEditing(null); form.resetFields(); }}
        confirmLoading={createMut.isPending || updateMut.isPending}
        destroyOnHidden
        width={640}
      >
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item name="title" label="标题" rules={[{ required: true, max: 200 }]}>
            <Input placeholder="公告标题" />
          </Form.Item>
          <Form.Item name="content" label="内容">
            <Input.TextArea rows={8} placeholder="公告正文" />
          </Form.Item>
          <Form.Item name="sort_order" label="排序权重（数值越大越靠前）">
            <InputNumber min={0} max={9999} />
          </Form.Item>
          {!editing && (
            <Form.Item name="status" label="发布状态">
              <Input.Group compact>
                <Button.Group>
                  <Button
                    type={form.getFieldValue('status') === 'draft' ? 'primary' : 'default'}
                    onClick={() => form.setFieldsValue({ status: 'draft' })}
                  >
                    保存为草稿
                  </Button>
                  <Button
                    type={form.getFieldValue('status') === 'published' ? 'primary' : 'default'}
                    onClick={() => form.setFieldsValue({ status: 'published' })}
                  >
                    立即发布
                  </Button>
                </Button.Group>
              </Input.Group>
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
}
