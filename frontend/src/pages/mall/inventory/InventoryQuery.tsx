/**
 * 商城库存查询
 *
 * 按仓库筛选，展示 SKU、批次、数量、加权平均成本
 * 低库存（quantity <= 10）标红
 */
import { useState } from 'react';
import { Card, Select, Space, Table, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api from '../../../api/client';

const { Title } = Typography;

interface InventoryRow {
  id: string;
  warehouse_id: string;
  warehouse_name?: string;
  sku_id: number;
  sku_name?: string;  // 规格（spec）
  product_id?: number;
  product_name?: string;
  quantity: number;
  avg_cost_price?: string;
  updated_at?: string;
}

export default function InventoryQuery() {
  const [warehouseId, setWarehouseId] = useState<string | undefined>(undefined);
  const [lowStockOnly, setLowStockOnly] = useState(false);

  const { data: warehousesResp } = useQuery<any>({
    queryKey: ['mall-warehouses-all'],
    queryFn: () => api.get('/mall/admin/warehouses').then(r => r.data),
  });
  const warehouses: any[] = warehousesResp?.records || [];

  const { data, isLoading } = useQuery<{ records: InventoryRow[]; total: number }>({
    queryKey: ['mall-inventory', warehouseId, lowStockOnly],
    queryFn: () => api.get('/mall/admin/inventory', {
      params: {
        warehouse_id: warehouseId,
        low_stock: lowStockOnly ? true : undefined,
        limit: 500,
      },
    }).then(r => r.data),
  });
  const rows = data?.records || [];

  const columns: ColumnsType<InventoryRow> = [
    {
      title: '仓库', key: 'wh', width: 160,
      render: (_, r) => r.warehouse_name || <code>{r.warehouse_id?.slice(0, 8)}...</code>,
    },
    {
      title: 'SKU', key: 'sku',
      render: (_, r) => (
        <div>
          <strong>{r.product_name || '-'}</strong>
          {r.sku_name && <div style={{ color: '#999', fontSize: 12 }}>{r.sku_name}</div>}
        </div>
      ),
    },
    {
      title: '数量', dataIndex: 'quantity', width: 100, align: 'right' as const,
      render: (v: number) => v <= 10
        ? <Tag color="volcano">{v} 瓶</Tag>
        : <span><strong>{v}</strong> 瓶</span>,
      sorter: (a, b) => a.quantity - b.quantity,
    },
    {
      title: '加权平均成本', dataIndex: 'avg_cost_price', width: 140, align: 'right' as const,
      render: (v?: string) => v ? `¥${Number(v).toFixed(2)}` : '-',
    },
  ];

  return (
    <div>
      <Title level={4}>商城库存查询</Title>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <span>仓库：</span>
          <Select
            style={{ width: 220 }}
            placeholder="全部仓库"
            allowClear
            value={warehouseId}
            onChange={setWarehouseId}
            options={warehouses.map(w => ({
              value: w.id, label: `${w.code} · ${w.name}`,
            }))}
          />
          <Tag
            color={lowStockOnly ? 'volcano' : 'default'}
            style={{ cursor: 'pointer' }}
            onClick={() => setLowStockOnly(s => !s)}
          >
            {lowStockOnly ? '✓ ' : ''}仅低库存（≤ 10 瓶）
          </Tag>
        </Space>
      </Card>

      <Table
        dataSource={rows}
        rowKey="id"
        columns={columns}
        loading={isLoading}
        size="middle"
        pagination={{
          showTotal: (t) => `共 ${t} 条`,
          defaultPageSize: 50,
          showSizeChanger: true,
        }}
      />
    </div>
  );
}
