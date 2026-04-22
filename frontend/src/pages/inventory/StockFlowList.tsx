import { useState } from 'react';
import { Table, Tag } from 'antd';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

interface StockFlowItem {
  id: string;
  flow_no: string;
  product_id: string;
  warehouse_id: string;
  batch_no: string;
  flow_type: string;
  quantity: number;
  cost_price: number | null;
  created_at: string;
}

const columns: ColumnsType<StockFlowItem> = [
  { title: '流水号', dataIndex: 'flow_no', width: 180 },
  { title: '批次号', dataIndex: 'batch_no', width: 140 },
  { title: '类型', dataIndex: 'flow_type', width: 80, render: (t: string) => {
    const map: Record<string, { color: string; text: string }> = {
      inbound: { color: 'green', text: '入库' }, outbound: { color: 'red', text: '出库' },
      in: { color: 'green', text: '入库' }, out: { color: 'red', text: '出库' },
    };
    const m = map[t] ?? { color: 'blue', text: t };
    return <Tag color={m.color}>{m.text}</Tag>;
  }},
  { title: '数量', dataIndex: 'quantity', width: 80, align: 'right' },
  { title: '成本单价', dataIndex: 'cost_price', width: 100, align: 'right', render: (v: number | null) => v != null ? `¥${Number(v).toFixed(2)}` : '-' },
  { title: '时间', dataIndex: 'created_at', width: 170, render: (v: string) => v?.replace('T', ' ').slice(0, 19) },
];

function StockFlowList() {
  const { brandId, params } = useBrandFilter();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const { data, isLoading } = useQuery<{ items: StockFlowItem[]; total: number }>({
    queryKey: ['stock-flow', brandId, page, pageSize],
    queryFn: async () => { const { data } = await api.get('/inventory/stock-flow', { params: { ...params, skip: (page - 1) * pageSize, limit: pageSize } }); return data; },
  });

  return (
    <>
      <h2>出入库记录</h2>
      <Table<StockFlowItem> columns={columns} dataSource={data?.items ?? []} rowKey="id" loading={isLoading} style={{ marginTop: 16 }}
        pagination={{ current: page, pageSize, total: data?.total ?? 0, showTotal: t => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} />
    </>
  );
}

export default StockFlowList;
