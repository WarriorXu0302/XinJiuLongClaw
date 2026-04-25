import { useState } from 'react';
import { Alert, Button, Card, InputNumber, message, Space, Table, Tag, Typography } from 'antd';
import { BellOutlined, WarningOutlined } from '@ant-design/icons';
import { useMutation, useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useBrandStore } from '../../stores/brandStore';

const { Title, Text } = Typography;

interface LowStockRow {
  product_id: string; product_name: string;
  warehouse_id: string; warehouse_name: string; warehouse_type: string;
  batch_no: string; bottles: number; cases: number; threshold_cases: number;
}

const whTypeLabel: Record<string, string> = {
  main: '主仓', backup: '备用仓', tasting: '品鉴物料仓',
  retail: '零售仓', wholesale: '批发仓', activity: '活动仓',
};

function LowStockAlert() {
  const brandId = useBrandStore(s => s.selectedBrandId);
  const [threshold, setThreshold] = useState(5);

  const { data = [], isLoading, refetch } = useQuery<LowStockRow[]>({
    queryKey: ['low-stock', brandId, threshold],
    queryFn: () => {
      const params: Record<string, string | number> = { threshold_cases: threshold };
      if (brandId) params.brand_id = brandId;
      return api.get('/inventory/low-stock', { params }).then(r => extractItems<LowStockRow>(r.data));
    },
  });

  const notifyMut = useMutation({
    mutationFn: () => api.post(`/inventory/low-stock/notify?threshold_cases=${threshold}`),
    onSuccess: (r: any) => message.success(r.data.detail),
  });

  const cols: ColumnsType<LowStockRow> = [
    { title: '仓库', dataIndex: 'warehouse_name', width: 140,
      render: (v: string, r) => <>{v} <Tag>{whTypeLabel[r.warehouse_type] ?? r.warehouse_type}</Tag></> },
    { title: '商品', dataIndex: 'product_name', width: 200 },
    { title: '批次', dataIndex: 'batch_no', width: 140 },
    { title: '余量', dataIndex: 'cases', width: 120,
      render: (v: number, r) => (
        <Space direction="vertical" size={0}>
          <Text strong style={{ color: v <= 1 ? '#ff4d4f' : '#fa8c16' }}>{v.toFixed(1)} 箱</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>{r.bottles} 瓶</Text>
        </Space>
      ) },
  ];

  return (
    <>
      <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}><WarningOutlined /> 低库存预警</Title>
        <Space>
          <Text>预警阈值</Text>
          <InputNumber min={1} max={100} value={threshold} onChange={v => setThreshold(v ?? 5)} suffix="箱" style={{ width: 120 }} />
          <Button onClick={() => refetch()}>刷新</Button>
          <Button type="primary" danger icon={<BellOutlined />} loading={notifyMut.isPending}
            disabled={data.length === 0} onClick={() => notifyMut.mutate()}>
            推送给仓管/管理员
          </Button>
        </Space>
      </Space>

      {data.length === 0 ? (
        <Alert type="success" title="所有库存充足，无低库存 SKU" />
      ) : (
        <>
          <Alert type="warning" style={{ marginBottom: 12 }}
            title={`发现 ${data.length} 个 SKU 低于 ${threshold} 箱`} />
          <Table<LowStockRow> columns={cols} dataSource={data}
            rowKey={r => `${r.warehouse_id}-${r.product_id}-${r.batch_no}`}
            loading={isLoading} size="small" pagination={{ pageSize: 30 }} />
        </>
      )}
    </>
  );
}

export default LowStockAlert;
