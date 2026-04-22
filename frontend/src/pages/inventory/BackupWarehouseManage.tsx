import { Card, Space, Table, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
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

function BackupWarehouseManage() {
  const { brandId, params } = useBrandFilter();

  const { data: warehouses = [] } = useQuery<{ id: string; name: string; warehouse_type: string }[]>({
    queryKey: ['warehouses-all', brandId],
    queryFn: () => api.get('/inventory/warehouses', { params }).then(r => extractItems<{ id: string; name: string; warehouse_type: string }>(r.data)),
  });

  const backupWarehouses = warehouses.filter(w => w.warehouse_type === 'backup');

  const { data: flows = [] } = useQuery<StockFlowItem[]>({
    queryKey: ['backup-wh-flows', brandId],
    queryFn: () => api.get('/inventory/stock-flow', { params }).then(r => extractItems<StockFlowItem>(r.data)),
  });

  const backupWhIds = new Set(backupWarehouses.map(w => w.id));
  const filteredFlows = flows.filter(f => backupWhIds.has(f.warehouse_id));

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
      <Space style={{ marginBottom: 16 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>备用仓</Title>
          <Text type="secondary">入库走采购订单，出库走销售订单</Text>
        </div>
      </Space>

      <Space style={{ marginBottom: 16 }} wrap>
        {backupWarehouses.map(w => (
          <Card key={w.id} size="small" style={{ width: 200 }}>
            <Tag color="orange">备用仓</Tag>
            <div style={{ marginTop: 4, fontWeight: 600 }}>{w.name}</div>
          </Card>
        ))}
      </Space>

      <Table<StockFlowItem> columns={columns} dataSource={filteredFlows} rowKey="id" size="small" pagination={{ pageSize: 20 }} />
    </>
  );
}

export default BackupWarehouseManage;
