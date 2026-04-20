import { useState } from 'react';
import { Button, DatePicker, Form, Input, InputNumber, message, Modal, Select, Space, Table, Tag, Upload } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

interface ExpenseItem {
  id: string;
  expense_no: string;
  amount: number;
  actual_cost: number;
  category_id: string | null;
  applicant_id: string | null;
  description: string | null;
  payment_date: string | null;
  status: string;
  created_at: string;
  applicant?: { id: string; name: string };
}

interface ExpenseFormValues {
  amount: number;
  category_id: string;
  applicant_id: string;
  description: string;
  payment_date: any;
  status: string;
}

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  pending: { color: 'orange', label: '待审批' }, approved: { color: 'blue', label: '已审批' },
  paid: { color: 'green', label: '已付款' }, rejected: { color: 'red', label: '已驳回' },
};

function ExpenseList() {
  const queryClient = useQueryClient();
  const { brandId, params } = useBrandFilter();
  const [form] = Form.useForm<ExpenseFormValues>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<ExpenseItem | null>(null);
  const [voucherUrls, setVoucherUrls] = useState<string[]>([]);
  // 付款弹窗
  const [payOpen, setPayOpen] = useState(false);
  const [payRecord, setPayRecord] = useState<ExpenseItem | null>(null);
  const [payAccountId, setPayAccountId] = useState('');
  const [payVoucherUrls, setPayVoucherUrls] = useState<string[]>([]);
  const [payReceiptUrls, setPayReceiptUrls] = useState<string[]>([]);

  const { data = [], isLoading } = useQuery({
    queryKey: ['expenses', brandId],
    queryFn: async () => { const { data } = await api.get('/expenses', { params: { ...params, limit: 100 } }); return data; },
  });

  const { data: employees = [] } = useQuery<{id: string; name: string}[]>({
    queryKey: ['employees-select-all'],
    queryFn: () => api.get('/hr/employees').then(r => r.data),
  });

  const { data: accounts = [] } = useQuery<any[]>({
    queryKey: ['accounts-for-pay'],
    queryFn: () => api.get('/accounts').then(r => r.data),
  });

  const payMutation = useMutation({
    mutationFn: async () => {
      if (!payAccountId) throw new Error('请选择付款账户');
      if (payVoucherUrls.length === 0) throw new Error('请上传付款凭证');
      // 先上传凭证到报销单
      await api.put(`/expenses/${payRecord!.id}`, { voucher_urls: [...(payRecord as any).voucher_urls ?? [], ...payVoucherUrls] });
      // 再付款
      await api.post(`/expenses/${payRecord!.id}/pay`, { payment_account_id: payAccountId });
    },
    onSuccess: () => {
      message.success('付款成功');
      setPayOpen(false);
      queryClient.invalidateQueries({ queryKey: ['expenses'] });
      queryClient.invalidateQueries({ queryKey: ['accounts-for-pay'] });
    },
    onError: (err: any) => message.error(err?.message || err?.response?.data?.detail || '付款失败'),
  });

  const createMutation = useMutation({
    mutationFn: async (values: ExpenseFormValues) => {
      const payload = { ...values, brand_id: brandId || null, payment_date: values.payment_date?.format('YYYY-MM-DD') ?? null, voucher_urls: voucherUrls.length > 0 ? voucherUrls : null };
      const { data } = await api.post('/expenses', payload);
      return data;
    },
    onSuccess: () => {
      message.success('报销已创建，请到审批中心审批');
      setModalOpen(false);
      form.resetFields();
      setVoucherUrls([]);
      queryClient.invalidateQueries({ queryKey: ['expenses'] });
    },
    onError: (err: any) => {
      message.error(err?.response?.data?.detail ?? '创建失败');
    },
  });

  const editMutation = useMutation({
    mutationFn: async (values: ExpenseFormValues) => {
      const payload = { ...values, payment_date: values.payment_date?.format('YYYY-MM-DD') ?? null };
      const { data } = await api.put(`/expenses/${editingRecord!.id}`, payload);
      return data;
    },
    onSuccess: () => {
      message.success('更新成功');
      setModalOpen(false);
      setEditingRecord(null);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['expenses'] });
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

  const handleEdit = (record: ExpenseItem) => {
    setEditingRecord(record);
    setModalOpen(true);
    form.setFieldsValue({
      amount: record.amount,
      category_id: record.category_id ?? '',
      applicant_id: record.applicant_id ?? '',
      description: record.description ?? '',
      payment_date: record.payment_date ? dayjs(record.payment_date) : null,
      status: record.status,
    });
  };

  const columns: ColumnsType<ExpenseItem> = [
    { title: '报销编号', dataIndex: 'expense_no', width: 140 },
    { title: '说明', dataIndex: 'description', width: 180, ellipsis: true },
    { title: '金额', dataIndex: 'amount', width: 90, align: 'right', render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '申请人', key: 'applicant', width: 80, render: (_, r) => r.applicant?.name ?? '-' },
    { title: '凭证', key: 'voucher', width: 50, render: (_, r: any) => r.voucher_urls?.length ? `${r.voucher_urls.length}张` : '-' },
    { title: '状态', dataIndex: 'status', width: 80, render: (s: string) => { const m = STATUS_MAP[s]; return m ? <Tag color={m.color}>{m.label}</Tag> : <Tag>{s}</Tag>; } },
    { title: '时间', dataIndex: 'created_at', width: 120, render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
    { title: '操作', key: 'action', width: 100, render: (_, record) => (
      <Space size="small">
        {record.status === 'pending' && <a onClick={() => handleEdit(record)}>编辑</a>}
        {record.status === 'pending' && <Tag color="orange">待审批</Tag>}
        {record.status === 'approved' && <a style={{ color: '#52c41a', fontWeight: 600 }} onClick={() => { setPayRecord(record); setPayVoucherUrls([]); setPayReceiptUrls([]); setPayAccountId(''); setPayOpen(true); }}>付款</a>}
        {record.status === 'paid' && <Tag color="green">已完成</Tag>}
        {record.status === 'rejected' && <Tag color="red">已驳回</Tag>}
      </Space>
    ) },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>报销管理</h2>
        <Button type="primary" icon={<PlusOutlined />} disabled={!brandId}
          onClick={() => { if (!brandId) { message.warning('请先在右上角选择品牌'); return; } setEditingRecord(null); setVoucherUrls([]); setModalOpen(true); }}>
          {brandId ? '新建报销' : '请先选择品牌'}
        </Button>
      </div>
      <Table<ExpenseItem> columns={columns} dataSource={data} rowKey="id" loading={isLoading} pagination={{ pageSize: 20, showSizeChanger: true }} />

      <Modal
        title={editingRecord ? '编辑报销' : '新建报销'}
        open={modalOpen}
        onOk={handleOk}
        onCancel={handleCancel}
        confirmLoading={createMutation.isPending || editMutation.isPending}
        okText="确认"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item name="description" label="报销说明" rules={[{ required: true, message: '请填写说明' }]}>
            <Input.TextArea rows={2} placeholder="如：办公用品采购、差旅费、场地费" />
          </Form.Item>
          <Form.Item name="amount" label="报销金额" rules={[{ required: true, message: '请输入金额' }]}>
            <InputNumber style={{ width: '100%' }} min={0.01} precision={2} prefix="¥" placeholder="0" />
          </Form.Item>
          <Form.Item name="applicant_id" label="申请人">
            <Select showSearch placeholder="选择申请人" optionFilterProp="label" allowClear
              options={employees.map(e => ({ value: e.id, label: e.name }))} />
          </Form.Item>
          <Form.Item name="payment_date" label="费用发生日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="付款凭证" extra="上传发票、收据、转账截图等">
            <Upload listType="picture-card" accept=".jpg,.jpeg,.png,.webp" multiple
              customRequest={async ({ file, onSuccess, onError }: any) => {
                const fd = new FormData(); fd.append('file', file);
                try { const { data } = await api.post('/uploads', fd, { headers: { 'Content-Type': 'multipart/form-data' } }); setVoucherUrls(p => [...p, data.url]); onSuccess(data); }
                catch (e) { onError(e); }
              }}>
              <div><PlusOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>上传凭证</div></div>
            </Upload>
          </Form.Item>
        </Form>
      </Modal>

      {/* 付款弹窗 */}
      <Modal title={`付款 — ${payRecord?.expense_no ?? ''} ¥${payRecord ? Number(payRecord.amount).toLocaleString() : 0}`}
        open={payOpen}
        onOk={() => payMutation.mutate()}
        onCancel={() => { setPayOpen(false); setPayVoucherUrls([]); setPayReceiptUrls([]); }}
        confirmLoading={payMutation.isPending} okText="确认付款" width={500} destroyOnHidden>
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>付款账户</div>
          <Select style={{ width: '100%' }} placeholder="选择付款账户" value={payAccountId || undefined} onChange={v => setPayAccountId(v)}
            options={accounts.filter((a: any) => a.level === 'master').map((a: any) => ({ value: a.id, label: `${a.name}（余额 ¥${Number(a.balance).toLocaleString()}）` }))} />
        </div>
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>付款凭证（必传）</div>
          <Upload listType="picture-card" accept=".jpg,.jpeg,.png,.webp" multiple
            customRequest={async ({ file, onSuccess, onError }: any) => {
              const fd = new FormData(); fd.append('file', file);
              try { const { data } = await api.post('/uploads', fd, { headers: { 'Content-Type': 'multipart/form-data' } }); setPayVoucherUrls(p => [...p, data.url]); onSuccess(data); } catch (e) { onError(e); }
            }}>
            <div><PlusOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>付款凭证</div></div>
          </Upload>
        </div>
        <div>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>签收单（可选）</div>
          <Upload listType="picture-card" accept=".jpg,.jpeg,.png,.webp" multiple
            customRequest={async ({ file, onSuccess, onError }: any) => {
              const fd = new FormData(); fd.append('file', file);
              try { const { data } = await api.post('/uploads', fd, { headers: { 'Content-Type': 'multipart/form-data' } }); setPayReceiptUrls(p => [...p, data.url]); onSuccess(data); } catch (e) { onError(e); }
            }}>
            <div><PlusOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>签收单</div></div>
          </Upload>
        </div>
      </Modal>
    </>
  );
}

export default ExpenseList;
