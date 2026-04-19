import { useState } from 'react';
import { Button, DatePicker, Form, Input, InputNumber, message, Modal, Select, Table } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

interface ReceiptItem {
  id: string;
  receipt_no: string;
  customer_id: string | null;
  order_id: string | null;
  account_id: string | null;
  amount: number;
  payment_method: string;
  receipt_date: string | null;
  notes: string | null;
  created_at: string;
  customer?: { id: string; name: string };
  order?: { id: string; order_no: string };
  account?: { id: string; name: string };
}

interface ReceiptCreateForm {
  customer_id: string;
  order_id: string;
  account_id: string;
  amount: number;
  payment_method: string;
  receipt_date: any;
  notes: string;
}

function ReceiptList() {
  const queryClient = useQueryClient();
  const { brandId, params } = useBrandFilter();
  const [form] = Form.useForm<ReceiptCreateForm>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<ReceiptItem | null>(null);

  const { data = [], isLoading } = useQuery({
    queryKey: ['receipts', brandId],
    queryFn: async () => { const { data } = await api.get('/receipts'); return data; },
  });

  const { data: customers = [] } = useQuery<{id: string; name: string}[]>({
    queryKey: ['customers-select', brandId],
    queryFn: () => api.get('/customers', { params }).then(r => r.data),
  });

  const { data: orders = [] } = useQuery<{id: string; order_no: string}[]>({
    queryKey: ['orders-select'],
    queryFn: () => api.get('/orders').then(r => r.data),
  });

  const createMutation = useMutation({
    mutationFn: async (values: ReceiptCreateForm) => {
      const payload = {
        ...values,
        receipt_date: values.receipt_date?.format('YYYY-MM-DD') ?? null,
      };
      const { data } = await api.post('/receipts', payload);
      return data;
    },
    onSuccess: () => {
      message.success('创建成功');
      setModalOpen(false);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['receipts'] });
    },
    onError: (err: any) => {
      message.error(err?.response?.data?.detail ?? '创建失败');
    },
  });

  const editMutation = useMutation({
    mutationFn: async (values: ReceiptCreateForm) => {
      const payload = {
        ...values,
        receipt_date: values.receipt_date?.format('YYYY-MM-DD') ?? null,
      };
      const { data } = await api.put(`/receipts/${editingRecord!.id}`, payload);
      return data;
    },
    onSuccess: () => {
      message.success('更新成功');
      setModalOpen(false);
      setEditingRecord(null);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['receipts'] });
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

  const handleEdit = (record: ReceiptItem) => {
    setEditingRecord(record);
    setModalOpen(true);
    form.setFieldsValue({
      customer_id: record.customer_id ?? '',
      order_id: record.order_id ?? '',
      account_id: record.account_id ?? '',
      amount: record.amount,
      payment_method: record.payment_method,
      receipt_date: record.receipt_date ? dayjs(record.receipt_date) : null,
      notes: record.notes ?? '',
    });
  };

  const columns: ColumnsType<ReceiptItem> = [
    { title: '收款编号', dataIndex: 'receipt_no', width: 180 },
    { title: '客户', dataIndex: 'customer_id', width: 120, render: (_, record) => record.customer?.name ?? '-' },
    { title: '订单', dataIndex: 'order_id', width: 140, render: (_, record) => record.order?.order_no ?? '-' },
    { title: '账户', dataIndex: 'account_id', width: 120, render: (_, record) => record.account?.name ?? '-' },
    { title: '金额', dataIndex: 'amount', width: 100, align: 'right', render: (v: number) => `¥${Number(v).toFixed(2)}` },
    { title: '支付方式', dataIndex: 'payment_method', width: 100 },
    { title: '收款日期', dataIndex: 'receipt_date', width: 120 },
    { title: '创建时间', dataIndex: 'created_at', width: 170, render: (v: string) => v?.replace('T', ' ').slice(0, 19) },
    { title: '操作', key: 'action', width: 120, render: (_, record) => <><a onClick={() => handleEdit(record)}>编辑</a></> },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>收款管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingRecord(null); setModalOpen(true); }}>新建收款</Button>
      </div>
      <Table<ReceiptItem> columns={columns} dataSource={data} rowKey="id" loading={isLoading} pagination={{ pageSize: 20, showSizeChanger: true }} />

      <Modal
        title={editingRecord ? '编辑收款' : '新建收款'}
        open={modalOpen}
        onOk={handleOk}
        onCancel={handleCancel}
        confirmLoading={createMutation.isPending || editMutation.isPending}
        okText="确认"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item name="customer_id" label="客户" rules={[{ required: true, message: '请选择客户' }]}>
            <Select
              showSearch
              placeholder="请选择客户"
              optionFilterProp="label"
              options={customers.map(c => ({ value: c.id, label: c.name }))}
              allowClear
            />
          </Form.Item>
          <Form.Item name="order_id" label="订单">
            <Select
              showSearch
              placeholder="请选择订单"
              optionFilterProp="label"
              options={orders.map(o => ({ value: o.id, label: o.order_no }))}
              allowClear
            />
          </Form.Item>
          <Form.Item label="收款账户">
            <div style={{ padding: '4px 11px', background: '#f0f9ff', border: '1px dashed #91caff', borderRadius: 4, fontSize: 13 }}>
              收款一律进<strong>公司总资金池</strong>（master 现金账户）
            </div>
          </Form.Item>
          <Form.Item name="amount" label="金额" rules={[{ required: true, message: '请输入金额' }]}>
            <InputNumber style={{ width: '100%' }} min={0.01} precision={2} prefix="¥" placeholder="请输入金额" />
          </Form.Item>
          <Form.Item name="payment_method" label="支付方式" rules={[{ required: true, message: '请选择支付方式' }]}>
            <Select placeholder="请选择支付方式">
              <Select.Option value="cash">现金</Select.Option>
              <Select.Option value="bank_transfer">银行转账</Select.Option>
              <Select.Option value="wechat">微信</Select.Option>
              <Select.Option value="alipay">支付宝</Select.Option>
              <Select.Option value="check">支票</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="receipt_date" label="收款日期">
            <DatePicker style={{ width: '100%' }} placeholder="请选择收款日期" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={3} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default ReceiptList;
