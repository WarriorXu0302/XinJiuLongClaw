import { useState } from 'react';
import { Button, Card, Form, Input, InputNumber, message, Modal, Select, Space, Table, Tag, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

const { Title, Text } = Typography;

interface StockFlowItem {
  id: string; flow_no: string; product_id: string; product?: { name: string };
  warehouse_id: string; warehouse?: { name: string }; batch_no: string;
  flow_type: string; quantity: number; cost_price?: number; notes?: string; created_at: string;
}

const flowColor: Record<string, string> = { inbound: 'green', outbound: 'red', transfer_in: 'blue', transfer_out: 'orange' };
const flowLabel: Record<string, string> = { inbound: '入库', outbound: '出库', transfer_in: '调入', transfer_out: '调出' };

function WholesaleWarehouseManage() {
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();
  const { brandId, params } = useBrandFilter();

  const { data: warehouses = [] } = useQuery<{ id: string; name: string; warehouse_type: string }[]>({
    queryKey: ['warehouses-all', brandId],
    queryFn: () => api.get('/inventory/warehouses', { params }).then(r => extractItems<{ id: string; name: string; warehouse_type: string }>(r.data)),
  });

  const wholesaleWarehouses = warehouses.filter(w => w.warehouse_type === 'wholesale');

  const { data: products = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ['products-select', brandId],
    queryFn: () => api.get('/products', { params }).then(r => extractItems<{ id: string; name: string }>(r.data)),
  });

  const { data: flows = [] } = useQuery<StockFlowItem[]>({
    queryKey: ['wholesale-wh-flows', brandId],
    queryFn: () => api.get('/inventory/stock-flow', { params }).then(r => extractItems<StockFlowItem>(r.data)),
  });

  const wholesaleWhIds = new Set(wholesaleWarehouses.map(w => w.id));
  const filteredFlows = flows.filter(f => wholesaleWhIds.has(f.warehouse_id));

  const outboundMutation = useMutation({
    mutationFn: async (values: any) => {
      const { data } = await api.post('/inventory/direct-outbound', {
        product_id: values.product_id, warehouse_id: values.warehouse_id,
        quantity: values.quantity, notes: values.notes,
      });
      return data;
    },
    onSuccess: () => {
      message.success('出库成功');
      setModalOpen(false); form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['wholesale-wh-flows'] });
      queryClient.invalidateQueries({ queryKey: ['inventory-value'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '出库失败'),
  });

  const columns: ColumnsType<StockFlowItem> = [
    { title: '流水号', dataIndex: 'flow_no', width: 170 },
    { title: '类型', dataIndex: 'flow_type', width: 80, render: (v: string) => <Tag color={flowColor[v] ?? 'default'}>{flowLabel[v] ?? v}</Tag> },
    { title: '仓库', key: 'wh', width: 140, render: (_, r) => r.warehouse?.name ?? r.warehouse_id?.slice(0, 8) },
    { title: '商品', key: 'prod', width: 160, render: (_, r) => r.product?.name ?? r.product_id?.slice(0, 8) },
    { title: '批次', dataIndex: 'batch_no', width: 120 },
    { title: '数量', dataIndex: 'quantity', width: 80, align: 'right' },
    { title: '成本', dataIndex: 'cost_price', width: 100, align: 'right', render: (v: number | null) => v != null ? `¥${Number(v).toFixed(2)}` : '-' },
    { title: '备注', dataIndex: 'notes', width: 150, ellipsis: true },
    { title: '时间', dataIndex: 'created_at', width: 150, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
  ];

  return (
    <>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>批发仓库管理</Title>
          <Text type="secondary">批发仓库的出入库管理</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setModalOpen(true); }}>直接出库</Button>
      </Space>

      <Space style={{ marginBottom: 16 }} wrap>
        {wholesaleWarehouses.map(w => (
          <Card key={w.id} size="small" style={{ width: 200 }}>
            <Tag color="cyan">批发仓</Tag>
            <div style={{ marginTop: 4, fontWeight: 600 }}>{w.name}</div>
          </Card>
        ))}
      </Space>

      <Table<StockFlowItem> columns={columns} dataSource={filteredFlows} rowKey="id" size="small" pagination={{ pageSize: 20 }} />

      <Modal title="批发仓库 — 直接出库" open={modalOpen}
        onOk={() => form.validateFields().then(v => outboundMutation.mutate(v))}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        confirmLoading={outboundMutation.isPending} okText="确认出库">
        <Form form={form} layout="vertical">
          <Form.Item name="warehouse_id" label="出库仓库" rules={[{ required: true }]}>
            <Select placeholder="选择批发仓库"
              options={wholesaleWarehouses.map(w => ({ value: w.id, label: w.name }))} />
          </Form.Item>
          <Form.Item name="product_id" label="商品" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" placeholder="选择商品"
              options={products.map(p => ({ value: p.id, label: p.name }))} />
          </Form.Item>
          <Form.Item name="quantity" label="数量" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} min={1} max={9999} precision={0} />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="出库说明" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default WholesaleWarehouseManage;
