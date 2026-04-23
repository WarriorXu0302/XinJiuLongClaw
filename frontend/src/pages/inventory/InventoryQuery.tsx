import { useState } from 'react';
import { Button, Card, Col, Collapse, Row, Segmented, Space, Statistic, Table, Tabs, Tag, Typography } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { exportExcel } from '../../utils/exportExcel';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useBrandStore } from '../../stores/brandStore';

const { Title, Text } = Typography;

interface InvRow { brand_id: string; warehouse_name: string; warehouse_id: string; warehouse_type: string; product_name: string; product_id: string; bottles_per_case: number; batch_no: string; quantity: number; cost_price: number; total_value: number; }
interface StockFlowRow { id: string; flow_no: string; flow_type: string; quantity: number; cost_price?: number; batch_no: string; reference_no?: string; notes?: string; created_at: string; product?: { name: string; bottles_per_case?: number }; warehouse?: { name: string; warehouse_type?: string }; }

const fmtQty = (bottles: number, bpc: number) => {
  const b = bpc && bpc > 1 ? bpc : 1;
  if (b === 1) return `${bottles}瓶`;
  const cases = Math.floor(bottles / b);
  const rem = bottles % b;
  if (cases === 0) return `${rem}瓶`;
  if (rem === 0) return `${cases}箱`;
  return `${cases}箱${rem}瓶`;
};
interface Warehouse { id: string; name: string; warehouse_type: string; }

const whTypeLabel: Record<string, string> = { main: '主仓', backup: '备用仓', tasting: '品鉴物料仓', retail: '零售仓', wholesale: '批发仓', activity: '活动仓' };
const whTypeColor: Record<string, string> = { main: 'blue', backup: 'orange', tasting: 'purple', retail: 'green', wholesale: 'cyan', activity: 'magenta' };

const typeOrder = ['main', 'backup', 'tasting', 'retail', 'wholesale', 'activity'];

function InventoryQuery() {
  const brandId = useBrandStore(s => s.selectedBrandId);
  const params: Record<string, string> = {};
  if (brandId) params.brand_id = brandId;

  const [filterType, setFilterType] = useState<string>('all');
  const [filterWarehouseId, setFilterWarehouseId] = useState<string | null>(null);

  const { data = [], isLoading } = useQuery<InvRow[]>({
    queryKey: ['inventory-value', brandId],
    queryFn: () => api.get('/inventory/value-summary', { params }).then(r => extractItems<InvRow>(r.data)),
  });

  const { data: allWarehouses = [] } = useQuery<Warehouse[]>({
    queryKey: ['warehouses-all', brandId],
    queryFn: () => api.get('/inventory/warehouses', { params }).then(r => extractItems<Warehouse>(r.data)),
  });

  const { data: flows = [], isLoading: flowsLoading } = useQuery<StockFlowRow[]>({
    queryKey: ['stock-flows', brandId],
    queryFn: () => api.get('/inventory/stock-flow', { params: { ...params, limit: 200 } }).then(r => extractItems<StockFlowRow>(r.data)),
  });

  // Group warehouses by type
  const whByType: Record<string, Warehouse[]> = {};
  allWarehouses.forEach(w => {
    if (!whByType[w.warehouse_type]) whByType[w.warehouse_type] = [];
    whByType[w.warehouse_type].push(w);
  });

  // Stats per warehouse (convert bottles → cases for display aggregation)
  const whStats: Record<string, { cases: number; value: number }> = {};
  allWarehouses.forEach(w => { whStats[w.id] = { cases: 0, value: 0 }; });
  data.forEach(r => {
    if (!whStats[r.warehouse_id]) whStats[r.warehouse_id] = { cases: 0, value: 0 };
    const bpc = r.bottles_per_case && r.bottles_per_case > 1 ? r.bottles_per_case : 1;
    whStats[r.warehouse_id].cases += r.quantity / bpc;
    whStats[r.warehouse_id].value += r.total_value;
  });

  // Stats per type
  const typeStats: Record<string, { cases: number; value: number; count: number }> = {};
  typeOrder.forEach(t => { if (whByType[t]?.length) typeStats[t] = { cases: 0, value: 0, count: whByType[t].length }; });
  allWarehouses.forEach(w => {
    const s = whStats[w.id];
    if (typeStats[w.warehouse_type]) {
      typeStats[w.warehouse_type].cases += s.cases;
      typeStats[w.warehouse_type].value += s.value;
    }
  });

  const grandTotal = data.filter(r => r.warehouse_type !== 'tasting').reduce((s, r) => s + r.total_value, 0);
  const grandCases = data.reduce((s, r) => {
    const bpc = r.bottles_per_case && r.bottles_per_case > 1 ? r.bottles_per_case : 1;
    return s + r.quantity / bpc;
  }, 0);

  // Filter table data
  const filteredData = data.filter(r => {
    if (filterWarehouseId) return r.warehouse_id === filterWarehouseId;
    if (filterType !== 'all') return r.warehouse_type === filterType;
    return true;
  });

  const availableTypes = typeOrder.filter(t => whByType[t]?.length);

  const columns: ColumnsType<InvRow> = [
    { title: '仓库', dataIndex: 'warehouse_name', width: 150, render: (v: string, r) => <>{v} <Tag color={whTypeColor[r.warehouse_type] ?? 'default'}>{whTypeLabel[r.warehouse_type] ?? r.warehouse_type}</Tag></> },
    { title: '商品', dataIndex: 'product_name', width: 200 },
    { title: '批次', dataIndex: 'batch_no', width: 130 },
    { title: '数量', dataIndex: 'quantity', width: 100, align: 'right', render: (v: number, r) => fmtQty(v, r.bottles_per_case) },
    { title: '成本单价', dataIndex: 'cost_price', width: 110, align: 'right', render: (v: number, r) => r.warehouse_type === 'tasting' ? '-' : `¥${Number(v).toFixed(2)}/瓶` },
    { title: '库存价值', dataIndex: 'total_value', width: 120, align: 'right', render: (v: number, r) => r.warehouse_type === 'tasting' ? <Text type="secondary">待兑付</Text> : <strong>¥{Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</strong> },
  ];

  const collapseItems = availableTypes.map(type => {
    const ts = typeStats[type];
    const isTasting = type === 'tasting';
    return {
      key: type,
      label: (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Tag color={whTypeColor[type]} style={{ margin: 0 }}>{whTypeLabel[type]}</Tag>
          <Text type="secondary">{ts.count} 个仓库</Text>
          <Text type="secondary">·</Text>
          <Text>{ts.cases.toFixed(1)} 箱</Text>
          {!isTasting && <><Text type="secondary">·</Text><Text style={{ color: '#1890ff' }}>¥{ts.value.toLocaleString()}</Text></>}
          {isTasting && <Text type="secondary">（待兑付）</Text>}
        </div>
      ),
      children: (
        <Row gutter={12}>
          {(whByType[type] ?? []).map(w => {
            const s = whStats[w.id] ?? { cases: 0, value: 0 };
            const active = filterWarehouseId === w.id;
            return (
              <Col key={w.id} flex="180px" style={{ marginBottom: 8 }}>
                <Card size="small" hoverable
                  style={{ borderColor: active ? whTypeColor[type] : undefined, borderWidth: active ? 2 : 1 }}
                  onClick={() => { setFilterWarehouseId(active ? null : w.id); setFilterType('all'); }}>
                  <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{w.name}</div>
                  {isTasting ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>{s.cases.toFixed(1)} 箱</Text>
                  ) : (
                    <>
                      <div style={{ color: '#1890ff', fontWeight: 600 }}>¥{s.value.toLocaleString()}</div>
                      <Text type="secondary" style={{ fontSize: 12 }}>{s.cases.toFixed(1)} 箱</Text>
                    </>
                  )}
                </Card>
              </Col>
            );
          })}
        </Row>
      ),
    };
  });

  return (
    <>
      <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>库存查询</Title>
        <Space>
          <Button icon={<DownloadOutlined />} onClick={() => {
            const rows = data.map(r => ({
              '仓库': r.warehouse_name,
              '仓库类型': whTypeLabel[r.warehouse_type] ?? r.warehouse_type,
              '商品': r.product_name,
              '批次': r.batch_no,
              '数量(瓶)': r.quantity,
              '每箱瓶数': r.bottles_per_case || 1,
              '折合(箱)': +(r.quantity / (r.bottles_per_case || 1)).toFixed(2),
              '成本单价/瓶': Number(r.cost_price),
              '库存价值': Number(r.total_value),
            }));
            exportExcel('库存明细', '库存', rows, [
              { wch: 16 }, { wch: 12 }, { wch: 20 }, { wch: 16 }, { wch: 12 }, { wch: 10 }, { wch: 12 }, { wch: 14 }, { wch: 14 },
            ]);
          }}>导出 Excel</Button>
        </Space>
      </Space>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card size="small"><Statistic title="库存总价值" value={grandTotal} precision={2} prefix="¥" styles={{ content: { color: '#1890ff' } }} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="总库存量" value={grandCases} precision={1} suffix="箱" /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="仓库数" value={allWarehouses.length} suffix="个" /></Card></Col>
      </Row>

      <Collapse items={collapseItems} defaultActiveKey={['main']} style={{ marginBottom: 16 }} />

      <Tabs defaultActiveKey="inv" items={[
        {
          key: 'inv',
          label: '库存明细',
          children: (
            <>
              <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 12 }}>
                <Segmented
                  value={filterWarehouseId ? 'warehouse' : filterType}
                  onChange={(v) => { if (v === 'warehouse') return; setFilterType(v as string); setFilterWarehouseId(null); }}
                  options={[
                    { label: '全部', value: 'all' },
                    ...availableTypes.map(t => ({ label: whTypeLabel[t], value: t })),
                    ...(filterWarehouseId ? [{ label: allWarehouses.find(w => w.id === filterWarehouseId)?.name ?? '选中仓库', value: 'warehouse' as string }] : []),
                  ]}
                />
                {filterWarehouseId && <a onClick={() => { setFilterWarehouseId(null); setFilterType('all'); }}>清除筛选</a>}
              </div>
              <Table<InvRow>
                columns={columns}
                dataSource={filteredData}
                rowKey={(r) => `${r.product_id}-${r.warehouse_id}-${r.batch_no}`}
                loading={isLoading}
                size="small"
                pagination={{ pageSize: 50 }}
              />
            </>
          ),
        },
        {
          key: 'flow',
          label: '出入库流水',
          children: (
            <Table<StockFlowRow>
              dataSource={flows}
              rowKey="id"
              loading={flowsLoading}
              size="small"
              pagination={{ pageSize: 30 }}
              columns={[
                { title: '时间', dataIndex: 'created_at', width: 155, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
                { title: '仓库', key: 'wh', width: 150, render: (_, r) => r.warehouse ? <>{r.warehouse.name} <Tag color={whTypeColor[r.warehouse.warehouse_type || ''] ?? 'default'}>{whTypeLabel[r.warehouse.warehouse_type || ''] ?? r.warehouse.warehouse_type}</Tag></> : '-' },
                { title: '类型', dataIndex: 'flow_type', width: 75, render: (v: string) => {
                  const m: Record<string, {c: string; t: string}> = { inbound: {c:'green',t:'入库'}, outbound: {c:'red',t:'出库'}, in: {c:'green',t:'入库'}, out: {c:'red',t:'出库'} };
                  const r = m[v] ?? {c:'blue',t:v}; return <Tag color={r.c}>{r.t}</Tag>;
                }},
                { title: '商品', key: 'p', width: 160, render: (_, r) => r.product?.name ?? '-' },
                { title: '数量', key: 'qty', width: 120, align: 'right', render: (_, r) => fmtQty(r.quantity, r.product?.bottles_per_case ?? 1) },
                { title: '单价', dataIndex: 'cost_price', width: 100, align: 'right', render: (v: number) => v ? `¥${Number(v).toFixed(2)}/瓶` : '-' },
                { title: '批次', dataIndex: 'batch_no', width: 140 },
                { title: '关联单号', dataIndex: 'reference_no', width: 140 },
                { title: '备注', dataIndex: 'notes', ellipsis: true },
                { title: '流水号', dataIndex: 'flow_no', width: 180 },
              ]}
            />
          ),
        },
      ]} />
    </>
  );
}

export default InventoryQuery;
