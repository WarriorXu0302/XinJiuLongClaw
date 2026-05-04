import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Table, Typography, Button, Modal, Form, Input, InputNumber, Select, Space, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

const { Title } = Typography;

interface KPIItem {
  id: string;
  employee_id: string;
  employee?: { name: string };
  period_type: string;
  period_value: string;
  kpi_type: string;
  target_value: number;
  actual_value: number;
  score?: number;
  notes?: string;
  created_at: string;
}

const periodTypeLabel: Record<string, string> = { monthly: '月度', quarterly: '季度', yearly: '年度' };

function KPIList() {
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<KPIItem | null>(null);
  const [form] = Form.useForm();
  const queryClient = useQueryClient();

  const { brandId, params } = useBrandFilter();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data: listResp, isLoading } = useQuery<{ items: KPIItem[]; total: number }>({
    queryKey: ['kpis', brandId, page, pageSize],
    queryFn: () => api.get('/hr/kpis', { params: { ...params, skip: (page - 1) * pageSize, limit: pageSize } }).then((r) => r.data),
  });
  const data = listResp?.items ?? [];
  const total = listResp?.total ?? 0;

  const { data: employees = [] } = useQuery<{id: string; name: string}[]>({
    queryKey: ['employees-select', brandId],
    queryFn: () => api.get('/hr/employees', { params }).then(r => extractItems(r.data)),
  });

  const { data: brands = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ['brands-select'],
    queryFn: () => api.get('/products/brands').then(r => extractItems(r.data)),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/hr/kpis/${id}`),
    onSuccess: () => { message.success('已删除'); queryClient.invalidateQueries({ queryKey: ['kpis'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '删除失败'),
  });

  const createMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.post('/hr/kpis', values),
    onSuccess: () => { message.success('创建成功'); queryClient.invalidateQueries({ queryKey: ['kpis'] }); setModalOpen(false); form.resetFields(); },
  });

  const editMutation = useMutation({
    mutationFn: ({ id, ...values }: Record<string, unknown>) => api.put(`/hr/kpis/${id}`, values),
    onSuccess: () => { message.success('更新成功'); queryClient.invalidateQueries({ queryKey: ['kpis'] }); setModalOpen(false); setEditingRecord(null); form.resetFields(); },
  });

  const columns: ColumnsType<KPIItem> = [
    { title: '员工', dataIndex: ['employee', 'name'], key: 'employee', width: 100, render: (v: string, r: KPIItem) => v || r.employee_id?.slice(0, 8) },
    { title: '周期类型', dataIndex: 'period_type', key: 'period_type', width: 90, render: (v: string) => periodTypeLabel[v] ?? v },
    { title: '周期', dataIndex: 'period_value', key: 'period_value', width: 100 },
    { title: 'KPI类型', dataIndex: 'kpi_type', key: 'kpi_type', width: 120 },
    { title: '目标值', dataIndex: 'target_value', key: 'target_value', width: 100, align: 'right' },
    { title: '实际值', dataIndex: 'actual_value', key: 'actual_value', width: 100, align: 'right' },
    { title: '得分', dataIndex: 'score', key: 'score', width: 80, align: 'right', render: (v: number | null) => v ?? '-' },
    {
      title: '操作', key: 'actions', width: 120,
      render: (_: unknown, record: KPIItem) => (
        <Space>
          <a onClick={() => { setEditingRecord(record); form.setFieldsValue(record); setModalOpen(true); }}>编辑</a>
          <a style={{ color: '#ff4d4f' }} onClick={() => Modal.confirm({ title: '确认删除？', onOk: () => deleteMutation.mutate(record.id) })}>删除</a>
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
        <Title level={4} style={{ margin: 0 }}>KPI 考核</Title>
        <Button type="primary" onClick={() => { setEditingRecord(null); form.resetFields(); setModalOpen(true); }}>新建</Button>
      </Space>
      <Table rowKey="id" columns={columns} dataSource={data} loading={isLoading} size="middle" pagination={{ current: page, pageSize, total, showTotal: (t) => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} />
      <Modal title={editingRecord ? '编辑 KPI' : '新建 KPI'} open={modalOpen} onOk={handleSubmit} onCancel={() => { setModalOpen(false); setEditingRecord(null); form.resetFields(); }} confirmLoading={createMutation.isPending || editMutation.isPending}>
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
          <Form.Item name="period_type" label="周期类型" rules={[{ required: true }]}>
            <Select options={[{ value: 'monthly', label: '月度' }, { value: 'quarterly', label: '季度' }, { value: 'yearly', label: '年度' }]} />
          </Form.Item>
          <Form.Item name="period_value" label="周期值" rules={[{ required: true }]}><Input placeholder="如 2026-Q1 或 2026-04" /></Form.Item>
          <Form.Item name="kpi_type" label="KPI类型" rules={[{ required: true }]}><Input placeholder="如 sales_amount" /></Form.Item>
          <Form.Item name="target_value" label="目标值"><InputNumber style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="actual_value" label="实际值"><InputNumber style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="score" label="得分"><InputNumber style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default KPIList;
