/**
 * 门店店员利润提成率
 *
 * 每员工 × 每商品 一行。核心运营工具：没配就无法收银（收银时会 400）。
 */
import { useState } from 'react';
import {
  Button, Form, Input, InputNumber, message, Modal, Popconfirm, Select, Space, Table, Typography,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';

const { Title } = Typography;

interface Rate {
  id: string;
  employee_id: string;
  product_id: string;
  rate_on_profit: string;
  notes?: string;
}

interface Employee {
  id: string;
  name: string;
  position?: string;
  assigned_store_id?: string;
}

interface Product {
  id: string;
  code: string;
  name: string;
}

export default function RetailCommissionRates() {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Rate | null>(null);
  const [filterEmployee, setFilterEmployee] = useState<string | undefined>();

  const { data, isLoading } = useQuery<{ records: Rate[]; total: number }>({
    queryKey: ['retail-commission-rates', filterEmployee],
    queryFn: () => api.get('/retail-commission-rates', {
      params: { employee_id: filterEmployee, limit: 500 },
    }).then(r => r.data),
  });
  const rates = data?.records || [];

  const { data: employees = [] } = useQuery<Employee[]>({
    queryKey: ['employees-cashiers'],
    queryFn: () => api.get('/hr/employees').then(r => extractItems<Employee>(r.data)),
  });
  const cashiers = employees.filter(e => !!e.assigned_store_id);

  const { data: products = [] } = useQuery<Product[]>({
    queryKey: ['products-for-rate'],
    queryFn: () => api.get('/products', { params: { limit: 500 } })
      .then(r => extractItems<Product>(r.data)),
  });

  const empMap: Record<string, string> = {};
  employees.forEach(e => { empMap[e.id] = e.name; });
  const prodMap: Record<string, string> = {};
  products.forEach(p => { prodMap[p.id] = `${p.code} · ${p.name}`; });

  const createMut = useMutation({
    mutationFn: (v: any) => api.post('/retail-commission-rates', v),
    onSuccess: () => {
      message.success('已新增');
      setModalOpen(false); form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['retail-commission-rates'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '新增失败'),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: any }) =>
      api.put(`/retail-commission-rates/${id}`, body),
    onSuccess: () => {
      message.success('已更新');
      setModalOpen(false); setEditing(null); form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['retail-commission-rates'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '更新失败'),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.delete(`/retail-commission-rates/${id}`),
    onSuccess: () => {
      message.success('已删除');
      queryClient.invalidateQueries({ queryKey: ['retail-commission-rates'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '删除失败'),
  });

  const columns: ColumnsType<Rate> = [
    {
      title: '店员', dataIndex: 'employee_id', width: 140,
      render: (id: string) => empMap[id] || id.slice(0, 8),
    },
    {
      title: '商品', dataIndex: 'product_id',
      render: (id: string) => prodMap[id] || id.slice(0, 8),
    },
    {
      title: '利润提成率', dataIndex: 'rate_on_profit', width: 120, align: 'right' as const,
      render: (v: string) => `${(Number(v) * 100).toFixed(2)}%`,
    },
    { title: '备注', dataIndex: 'notes', ellipsis: true },
    {
      title: '操作', key: 'act', width: 140,
      render: (_, r) => (
        <Space>
          <a onClick={() => {
            setEditing(r);
            form.setFieldsValue({
              rate_on_profit: Number(r.rate_on_profit) * 100,
              notes: r.notes,
            });
            setModalOpen(true);
          }}>编辑</a>
          <Popconfirm title="删除这条提成率配置？" onConfirm={() => deleteMut.mutate(r.id)}>
            <a style={{ color: '#ff4d4f' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>门店提成率（每员工 × 每商品）</Title>
        <Space>
          <Select
            placeholder="按店员筛选"
            style={{ width: 200 }}
            options={cashiers.map(e => ({ value: e.id, label: e.name }))}
            value={filterEmployee}
            onChange={setFilterEmployee}
            allowClear
          />
          <Button type="primary" icon={<PlusOutlined />}
            onClick={() => { setEditing(null); form.resetFields(); setModalOpen(true); }}>
            新增
          </Button>
        </Space>
      </div>

      <Table
        columns={columns}
        dataSource={rates}
        rowKey="id"
        loading={isLoading}
        size="middle"
        pagination={{ pageSize: 20 }}
      />

      <Modal
        title={editing ? '编辑提成率' : '新增提成率'}
        open={modalOpen}
        onCancel={() => { setModalOpen(false); setEditing(null); form.resetFields(); }}
        onOk={() => form.validateFields().then((v: any) => {
          const body = {
            ...v,
            rate_on_profit: Number(v.rate_on_profit) / 100,
          };
          if (editing) updateMut.mutate({ id: editing.id, body });
          else createMut.mutate(body);
        })}
        confirmLoading={createMut.isPending || updateMut.isPending}
        width={520}
      >
        <Form form={form} layout="vertical" preserve={false}>
          {!editing && (
            <>
              <Form.Item name="employee_id" label="店员"
                rules={[{ required: true, message: '必选店员' }]}
                extra="只显示已绑定门店的员工">
                <Select
                  showSearch
                  optionFilterProp="label"
                  options={cashiers.map(e => ({ value: e.id, label: e.name }))}
                />
              </Form.Item>
              <Form.Item name="product_id" label="商品"
                rules={[{ required: true }]}>
                <Select
                  showSearch
                  optionFilterProp="label"
                  options={products.map(p => ({
                    value: p.id, label: `${p.code} · ${p.name}`,
                  }))}
                />
              </Form.Item>
            </>
          )}
          <Form.Item name="rate_on_profit" label="提成率（%）"
            rules={[{ required: true, type: 'number', min: 0, max: 100 }]}
            extra="例：15 表示按每瓶利润的 15% 给店员">
            <InputNumber min={0} max={100} precision={2} style={{ width: '100%' }} suffix="%" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
