import { useState } from 'react';
import { Button, DatePicker, Form, Input, InputNumber, message, Modal, Select, Table } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

interface PaymentItem {
  id: string;
  payment_no: string;
  payee: string;
  amount: number;
  payment_type: string;
  payment_method: string;
  account_id: string | null;
  payment_date: string | null;
  notes: string | null;
  created_at: string;
}

interface PaymentFormValues {
  payee: string;
  amount: number;
  payment_type: string;
  payment_method: string;
  account_id: string;
  payment_date: any;
  notes: string;
}

function PaymentList() {
  const queryClient = useQueryClient();
  const { brandId } = useBrandFilter();
  const [form] = Form.useForm<PaymentFormValues>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<PaymentItem | null>(null);

  const { data = [], isLoading } = useQuery({
    queryKey: ['payments', brandId],
    queryFn: async () => { const { data } = await api.get('/payments'); return data; },
  });

  const { data: accounts = [] } = useQuery<{id: string; name: string; account_type: string; balance: number}[]>({
    queryKey: ['accounts-select', brandId],
    queryFn: () => api.get('/accounts', { params }).then(r => r.data),
  });

  const createMutation = useMutation({
    mutationFn: async (values: PaymentFormValues) => {
      const payload = { ...values, payment_date: values.payment_date?.format('YYYY-MM-DD') ?? null };
      const { data } = await api.post('/payments', payload);
      return data;
    },
    onSuccess: () => {
      message.success('创建成功');
      setModalOpen(false);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['payments'] });
    },
    onError: (err: any) => {
      message.error(err?.response?.data?.detail ?? '创建失败');
    },
  });

  const editMutation = useMutation({
    mutationFn: async (values: PaymentFormValues) => {
      const payload = { ...values, payment_date: values.payment_date?.format('YYYY-MM-DD') ?? null };
      const { data } = await api.put(`/payments/${editingRecord!.id}`, payload);
      return data;
    },
    onSuccess: () => {
      message.success('更新成功');
      setModalOpen(false);
      setEditingRecord(null);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['payments'] });
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

  const handleEdit = (record: PaymentItem) => {
    setEditingRecord(record);
    setModalOpen(true);
    form.setFieldsValue({
      payee: record.payee,
      amount: record.amount,
      payment_type: record.payment_type,
      payment_method: record.payment_method,
      account_id: record.account_id ?? '',
      payment_date: record.payment_date ? dayjs(record.payment_date) : null,
      notes: record.notes ?? '',
    });
  };

  const columns: ColumnsType<PaymentItem> = [
    { title: '付款编号', dataIndex: 'payment_no', width: 180 },
    { title: '收款方', dataIndex: 'payee', width: 140 },
    { title: '金额', dataIndex: 'amount', width: 100, align: 'right', render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '类型', dataIndex: 'payment_type', width: 80 },
    { title: '支付方式', dataIndex: 'payment_method', width: 100 },
    { title: '付款日期', dataIndex: 'payment_date', width: 120 },
    { title: '操作', key: 'action', width: 120, render: (_, record) => <><a onClick={() => handleEdit(record)}>编辑</a></> },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>付款管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingRecord(null); setModalOpen(true); }}>新建付款</Button>
      </div>
      <Table<PaymentItem> columns={columns} dataSource={data} rowKey="id" loading={isLoading} pagination={{ pageSize: 20, showSizeChanger: true }} />

      <Modal
        title={editingRecord ? '编辑付款' : '新建付款'}
        open={modalOpen}
        onOk={handleOk}
        onCancel={handleCancel}
        confirmLoading={createMutation.isPending || editMutation.isPending}
        okText="确认"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item name="payee" label="收款方" rules={[{ required: true, message: '请输入收款方' }]}>
            <Input placeholder="请输入收款方" />
          </Form.Item>
          <Form.Item name="amount" label="金额" rules={[{ required: true, message: '请输入金额' }]}>
            <InputNumber style={{ width: '100%' }} min={0.01} precision={2} prefix="¥" placeholder="请输入金额" />
          </Form.Item>
          <Form.Item name="payment_type" label="付款类型" rules={[{ required: true, message: '请选择付款类型' }]}>
            <Select placeholder="请选择付款类型">
              <Select.Option value="purchase">采购</Select.Option>
              <Select.Option value="expense">费用</Select.Option>
              <Select.Option value="refund">退款</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="payment_method" label="支付方式" rules={[{ required: true, message: '请选择支付方式' }]}>
            <Select placeholder="请选择支付方式">
              <Select.Option value="cash">现金</Select.Option>
              <Select.Option value="bank">银行转账</Select.Option>
              <Select.Option value="wechat">微信</Select.Option>
              <Select.Option value="alipay">支付宝</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="account_id" label="付款账户" rules={[{ required: true }]}>
            <Select
              showSearch
              placeholder="请选择账户"
              optionFilterProp="label"
              options={accounts.map(a => ({ value: a.id, label: `${a.name}（¥${Number(a.balance).toLocaleString()}）` }))}
              allowClear
            />
          </Form.Item>
          <Form.Item name="payment_date" label="付款日期">
            <DatePicker style={{ width: '100%' }} placeholder="请选择付款日期" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={3} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default PaymentList;
