import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Table, Tag, Typography, Button, Modal, Form, Input, InputNumber, Select, Space, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

const { Title } = Typography;

interface CommissionItem {
  id: string;
  employee_id: string;
  employee?: { name: string };
  order_id?: string;
  commission_amount: number;
  status: string;
  settled_at?: string;
  notes?: string;
  created_at: string;
}

const statusColor: Record<string, string> = { pending: 'orange', approved: 'blue', settled: 'green', cancelled: 'default' };
const statusLabel: Record<string, string> = { pending: '待结算', approved: '已审批', settled: '已结算', cancelled: '已取消' };

function CommissionList() {
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<CommissionItem | null>(null);
  const [form] = Form.useForm();
  const queryClient = useQueryClient();

  const { brandId, params } = useBrandFilter();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data: listResp, isLoading } = useQuery<{ items: CommissionItem[]; total: number }>({
    queryKey: ['commissions', brandId, page, pageSize],
    queryFn: () => api.get('/hr/commissions', { params: { ...params, skip: (page - 1) * pageSize, limit: pageSize } }).then((r) => r.data),
  });
  const data = listResp?.items ?? [];
  const total = listResp?.total ?? 0;

  const { data: employees = [] } = useQuery<{id: string; name: string}[]>({
    queryKey: ['employees-select', brandId],
    queryFn: () => api.get('/hr/employees', { params }).then(r => extractItems(r.data)),
  });

  const { data: orders = [] } = useQuery<{id: string; order_no: string}[]>({
    queryKey: ['orders-select'],
    queryFn: () => api.get('/orders').then(r => extractItems(r.data)),
  });

  const { data: brands = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ['brands-select'],
    queryFn: () => api.get('/products/brands').then(r => extractItems(r.data)),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/hr/commissions/${id}`),
    onSuccess: () => { message.success('已删除'); queryClient.invalidateQueries({ queryKey: ['commissions'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '删除失败'),
  });

  const createMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.post('/hr/commissions', values),
    onSuccess: () => { message.success('创建成功'); queryClient.invalidateQueries({ queryKey: ['commissions'] }); setModalOpen(false); form.resetFields(); },
  });

  const editMutation = useMutation({
    mutationFn: ({ id, ...values }: Record<string, unknown>) => api.put(`/hr/commissions/${id}`, values),
    onSuccess: () => { message.success('更新成功'); queryClient.invalidateQueries({ queryKey: ['commissions'] }); setModalOpen(false); setEditingRecord(null); form.resetFields(); },
  });

  const settleMutation = useMutation({
    mutationFn: (id: string) => api.post(`/hr/commissions/${id}/settle`),
    onSuccess: () => { message.success('结算成功'); queryClient.invalidateQueries({ queryKey: ['commissions'] }); },
  });

  const columns: ColumnsType<CommissionItem> = [
    { title: '员工', dataIndex: ['employee', 'name'], key: 'employee', width: 100, render: (v: string, r: CommissionItem) => v || r.employee_id?.slice(0, 8) },
    { title: '关联订单', dataIndex: 'order_id', key: 'order_id', width: 120, render: (v: string) => v?.slice(0, 8) || '-' },
    { title: '佣金金额', dataIndex: 'commission_amount', key: 'commission_amount', width: 110, align: 'right', render: (v: number) => `¥${Number(v).toFixed(2)}` },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (v: string) => <Tag color={statusColor[v] ?? 'default'}>{statusLabel[v] ?? v}</Tag> },
    { title: '结算时间', dataIndex: 'settled_at', key: 'settled_at', width: 160, render: (v: string | null) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 160, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
    {
      title: '操作', key: 'actions', width: 180,
      render: (_: unknown, record: CommissionItem) => (
        <Space>
          <a onClick={() => { setEditingRecord(record); form.setFieldsValue(record); setModalOpen(true); }}>编辑</a>
          {record.status === 'pending' && <a style={{ color: '#52c41a' }} onClick={() => settleMutation.mutate(record.id)}>结算</a>}
          {record.status !== 'settled' && (
            <a style={{ color: '#ff4d4f' }} onClick={() => Modal.confirm({ title: '确认删除？', onOk: () => deleteMutation.mutate(record.id) })}>删除</a>
          )}
        </Space>
      ),
    },
  ];

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      if (editingRecord) {
        editMutation.mutate({ id: editingRecord.id, ...values });
      } else {
        createMutation.mutate(values);
      }
    });
  };

  return (
    <>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Title level={4} style={{ margin: 0 }}>佣金管理</Title>
        <Button type="primary" onClick={() => { setEditingRecord(null); form.resetFields(); setModalOpen(true); }}>新建</Button>
      </Space>
      <Table rowKey="id" columns={columns} dataSource={data} loading={isLoading} size="middle" pagination={{ current: page, pageSize, total, showTotal: (t) => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} />
      <Modal title={editingRecord ? '编辑佣金' : '新建佣金'} open={modalOpen} onOk={handleSubmit} onCancel={() => { setModalOpen(false); setEditingRecord(null); form.resetFields(); }} confirmLoading={createMutation.isPending || editMutation.isPending}>
        <Form form={form} layout="vertical">
          <Form.Item name="employee_id" label="员工" rules={[{ required: true }]}>
            <Select
              showSearch
              placeholder="请选择员工"
              optionFilterProp="label"
              options={employees.map(e => ({ value: e.id, label: e.name }))}
              allowClear
            />
          </Form.Item>
          <Form.Item name="brand_id" label="品牌">
            <Select allowClear showSearch optionFilterProp="label" placeholder="选择品牌"
              options={brands.map(b => ({ value: b.id, label: b.name }))} />
          </Form.Item>
          <Form.Item name="order_id" label="关联订单">
            <Select
              showSearch
              placeholder="请选择订单"
              optionFilterProp="label"
              options={orders.map(o => ({ value: o.id, label: o.order_no }))}
              allowClear
            />
          </Form.Item>
          <Form.Item name="commission_amount" label="佣金金额" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} min={0} precision={2} /></Form.Item>
          {editingRecord && (
            <Form.Item name="status" label="状态">
              <Select options={[
                { value: 'pending', label: '待结算' }, { value: 'approved', label: '已审批' },
                { value: 'settled', label: '已结算' }, { value: 'cancelled', label: '已取消' },
              ]} />
            </Form.Item>
          )}
          <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default CommissionList;
