import { useState } from 'react';
import { Button, DatePicker, Form, Input, InputNumber, message, Modal, Select, Space, Table, Tag } from 'antd';
import { PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

interface SettlementItem {
  id: string;
  settlement_no: string;
  manufacturer_id: string | null;
  brand_id: string | null;
  settlement_amount: number;
  settled_amount: number;
  unsettled_amount: number;
  status: string;
  settlement_date: string | null;
  notes: string | null;
  created_at: string;
  manufacturer?: { id: string; name: string };
}

interface SettlementFormValues {
  manufacturer_id: string;
  brand_id: string;
  settlement_amount: number;
  settlement_date: any;
  notes: string;
}

function SettlementList() {
  const queryClient = useQueryClient();
  const { brandId, params } = useBrandFilter();
  const [form] = Form.useForm<SettlementFormValues>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<SettlementItem | null>(null);

  const { data = [], isLoading } = useQuery({
    queryKey: ['settlements', brandId],
    queryFn: async () => { const { data } = await api.get('/manufacturer-settlements', { params }); return data; },
  });

  const createMutation = useMutation({
    mutationFn: async (values: SettlementFormValues) => {
      const payload = { ...values, settlement_date: values.settlement_date?.format('YYYY-MM-DD') ?? null };
      const { data } = await api.post('/manufacturer-settlements', payload);
      return data;
    },
    onSuccess: () => {
      message.success('创建成功');
      setModalOpen(false);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['settlements'] });
    },
    onError: (err: any) => {
      message.error(err?.response?.data?.detail ?? '创建失败');
    },
  });

  const editMutation = useMutation({
    mutationFn: async (values: SettlementFormValues) => {
      const payload = { ...values, settlement_date: values.settlement_date?.format('YYYY-MM-DD') ?? null };
      const { data } = await api.put(`/manufacturer-settlements/${editingRecord!.id}`, payload);
      return data;
    },
    onSuccess: () => {
      message.success('更新成功');
      setModalOpen(false);
      setEditingRecord(null);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['settlements'] });
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

  const handleEdit = (record: SettlementItem) => {
    setEditingRecord(record);
    setModalOpen(true);
    form.setFieldsValue({
      manufacturer_id: record.manufacturer_id ?? '',
      brand_id: record.brand_id ?? '',
      settlement_amount: record.settlement_amount,
      settlement_date: record.settlement_date ? dayjs(record.settlement_date) : null,
      notes: record.notes ?? '',
    });
  };

  const columns: ColumnsType<SettlementItem> = [
    { title: '结算编号', dataIndex: 'settlement_no', width: 180 },
    { title: '厂家', dataIndex: 'manufacturer_id', width: 120, render: (_, record) => record.manufacturer?.name ?? record.manufacturer_id ?? '-' },
    { title: '到账金额', dataIndex: 'settlement_amount', width: 110, align: 'right', render: (v: number) => `¥${Number(v).toFixed(2)}` },
    { title: '已核销', dataIndex: 'settled_amount', width: 110, align: 'right', render: (v: number) => `¥${Number(v).toFixed(2)}` },
    { title: '未核销', dataIndex: 'unsettled_amount', width: 110, align: 'right', render: (v: number) => <span style={{ color: v > 0 ? '#faad14' : undefined }}>¥{Number(v).toFixed(2)}</span> },
    { title: '状态', dataIndex: 'status', width: 80, render: (s: string) => <Tag color={s === 'pending' ? 'orange' : 'green'}>{s}</Tag> },
    { title: '到账日期', dataIndex: 'settlement_date', width: 120 },
    { title: '操作', key: 'action', width: 160, render: (_, record) => <><a onClick={() => handleEdit(record)}>编辑</a><a style={{ marginLeft: 8 }}>核销分配</a></> },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>厂家核销</h2>
        <Space>
          <Button icon={<UploadOutlined />} onClick={() => {
            Modal.confirm({
              title: '导入厂家对账 Excel',
              content: (
                <div>
                  <p>将导入青花郎费用表数据。自动去重（已有单据号跳过）。</p>
                  <Select id="import-brand" placeholder="选择品牌" style={{ width: '100%' }}
                    options={[
                      { value: 'QHL', label: '青花郎' },
                      { value: 'WLY', label: '五粮液' },
                      { value: 'Z15', label: '珍十五' },
                    ]}
                    onChange={(v) => { (window as any).__importBrandCode = v; }}
                  />
                </div>
              ),
              onOk: async () => {
                const brandCode = (window as any).__importBrandCode;
                if (!brandCode) { message.warning('请选择品牌'); return Promise.reject(); }
                try {
                  // Get brand ID from code
                  const { data: products } = await api.get('/products', { params });
                  const brand = products.find((p: any) => p.brand?.code === brandCode)?.brand;
                  if (!brand) { message.error('品牌未找到'); return; }
                  const { data: result } = await api.post(`/manufacturer-settlements/import-excel?brand_id=${brand.id}`);
                  message.success(`导入完成：${result.imported_settlements} 条到账记录，${result.imported_usage_records} 条执行记录`);
                  queryClient.invalidateQueries({ queryKey: ['settlements'] });
                } catch (e: any) {
                  message.error(e?.response?.data?.detail ?? '导入失败');
                }
              },
            });
          }}>导入 Excel 对账</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingRecord(null); setModalOpen(true); }}>录入到账</Button>
        </Space>
      </div>
      <Table<SettlementItem> columns={columns} dataSource={data} rowKey="id" loading={isLoading} pagination={{ pageSize: 20, showSizeChanger: true }} />

      <Modal
        title={editingRecord ? '编辑结算' : '录入到账'}
        open={modalOpen}
        onOk={handleOk}
        onCancel={handleCancel}
        confirmLoading={createMutation.isPending || editMutation.isPending}
        okText="确认"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item name="manufacturer_id" label="厂家ID" rules={[{ required: true, message: '请输入厂家ID' }]}>
            <Input placeholder="请输入厂家ID" />
          </Form.Item>
          <Form.Item name="brand_id" label="品牌ID">
            <Input placeholder="请输入品牌ID" />
          </Form.Item>
          <Form.Item name="settlement_amount" label="到账金额" rules={[{ required: true, message: '请输入到账金额' }]}>
            <InputNumber style={{ width: '100%' }} min={0.01} precision={2} prefix="¥" placeholder="请输入到账金额" />
          </Form.Item>
          <Form.Item name="settlement_date" label="到账日期">
            <DatePicker style={{ width: '100%' }} placeholder="请选择到账日期" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={3} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default SettlementList;
