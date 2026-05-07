import { useState } from 'react';
import { Button, Form, Input, InputNumber, message, Modal, Space, Switch, Table, Tag, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../api/client';

const { Title, Text } = Typography;

interface OrgUnit {
  id: string;
  code: string;
  name: string;
  sort_order: number;
  is_active: boolean;
  notes?: string | null;
  created_at: string;
}

const BUILTIN_CODES = new Set(['brand_agent', 'retail', 'mall']);

export default function OrgUnitsList() {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<OrgUnit | null>(null);

  const { data = [], isLoading } = useQuery<OrgUnit[]>({
    queryKey: ['org-units'],
    queryFn: () => api.get('/org-units', { params: { include_inactive: true } })
      .then(r => extractItems<OrgUnit>(r.data)),
  });

  const createMutation = useMutation({
    mutationFn: (v: Partial<OrgUnit>) => api.post('/org-units', v),
    onSuccess: () => {
      message.success('经营单元已创建');
      setModalOpen(false);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['org-units'] });
      queryClient.invalidateQueries({ queryKey: ['business-unit-summary'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  const editMutation = useMutation({
    mutationFn: (v: Partial<OrgUnit>) => api.put(`/org-units/${editing!.id}`, v),
    onSuccess: () => {
      message.success('更新成功');
      setModalOpen(false);
      setEditing(null);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['org-units'] });
      queryClient.invalidateQueries({ queryKey: ['business-unit-summary'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '更新失败'),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/org-units/${id}`),
    onSuccess: () => {
      message.success('已停用');
      queryClient.invalidateQueries({ queryKey: ['org-units'] });
      queryClient.invalidateQueries({ queryKey: ['business-unit-summary'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '停用失败'),
  });

  const columns: ColumnsType<OrgUnit> = [
    {
      title: '编码', dataIndex: 'code', width: 180,
      render: (v: string) => (
        <Space>
          <Tag color={BUILTIN_CODES.has(v) ? 'blue' : 'default'}>{v}</Tag>
          {BUILTIN_CODES.has(v) && <Tag color="gold">内置</Tag>}
        </Space>
      ),
    },
    { title: '名称', dataIndex: 'name', width: 200 },
    { title: '排序', dataIndex: 'sort_order', width: 80, align: 'right' },
    {
      title: '状态', dataIndex: 'is_active', width: 90,
      render: (v: boolean) => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>,
    },
    { title: '备注', dataIndex: 'notes', ellipsis: true },
    {
      title: '操作', key: 'action', width: 150,
      render: (_, record) => (
        <Space>
          <a onClick={() => {
            setEditing(record);
            form.setFieldsValue(record);
            setModalOpen(true);
          }}>编辑</a>
          {!BUILTIN_CODES.has(record.code) && record.is_active && (
            <a style={{ color: '#ff4d4f' }} onClick={() => Modal.confirm({
              title: '确认停用',
              content: `停用经营单元「${record.name}」？停用后在老板看板不显示，但历史数据保留。`,
              onOk: () => deleteMutation.mutate(record.id),
            })}>停用</a>
          )}
        </Space>
      ),
    },
  ];

  const handleOk = () => {
    form.validateFields().then(values => {
      if (editing) editMutation.mutate(values);
      else createMutation.mutate(values);
    });
  };

  return (
    <>
      <Space style={{ marginBottom: 8, justifyContent: 'space-between', width: '100%' }}>
        <Title level={4} style={{ margin: 0 }}>经营单元</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => {
          setEditing(null);
          form.resetFields();
          form.setFieldsValue({ is_active: true, sort_order: 100 });
          setModalOpen(true);
        }}>新建</Button>
      </Space>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        经营单元用于「经营单元看板」按事业部聚合。内置 3 条（brand_agent / retail / mall）不可删除，新增单元后需要在后端写入点加代码映射才会出数据。
      </Text>

      <Table<OrgUnit>
        columns={columns}
        dataSource={data}
        rowKey="id"
        loading={isLoading}
        size="middle"
        pagination={false}
      />

      <Modal
        title={editing ? '编辑经营单元' : '新建经营单元'}
        open={modalOpen}
        onOk={handleOk}
        onCancel={() => { setModalOpen(false); setEditing(null); form.resetFields(); }}
        confirmLoading={createMutation.isPending || editMutation.isPending}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="code"
            label="编码（小写字母+下划线，一经建立不可改）"
            rules={[
              { required: true, message: '必填' },
              { pattern: /^[a-z][a-z0-9_]*$/, message: '小写字母开头，允许 a-z / 0-9 / _' },
            ]}
          >
            <Input placeholder="如 specialty_wholesale" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="如 特产批发事业部" />
          </Form.Item>
          <Form.Item name="sort_order" label="排序（越小越靠前）">
            <InputNumber min={0} max={9999} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="用途说明等" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
