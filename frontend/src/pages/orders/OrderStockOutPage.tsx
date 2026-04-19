import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Alert, Button, Card, Descriptions, Input, InputNumber, message, Modal, Progress, Select, Space, Tag, Typography } from 'antd';
import { BarcodeOutlined, CheckCircleOutlined, ArrowLeftOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../../api/client';

const { Title, Text } = Typography;

interface OrderItem { id: string; product_id: string; quantity: number; quantity_unit?: string; unit_price: string; product?: { name: string; bottles_per_case?: number } }
interface OrderDetail {
  id: string; order_no: string; status: string; warehouse_id?: string; brand_id?: string;
  customer?: { name: string }; salesman?: { name: string };
  items: OrderItem[];
}
interface Warehouse { id: string; name: string; warehouse_type: string; brand_id?: string }

interface ScanRecord { barcode: string; product_id: string; product_name: string; order_item_id: string; time: string }

function OrderStockOutPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [barcodeInput, setBarcodeInput] = useState('');
  const [scanRecords, setScanRecords] = useState<ScanRecord[]>([]);
  const [manualMode, setManualMode] = useState(false);
  const [manualItemId, setManualItemId] = useState<string | null>(null);
  const [manualQty, setManualQty] = useState(1);
  const [scanError, setScanError] = useState('');
  const [selectedWarehouseId, setSelectedWarehouseId] = useState<string>('');

  const { data: order, isLoading, isError } = useQuery<OrderDetail>({
    queryKey: ['order-stockout', orderId],
    queryFn: () => api.get(`/orders/${orderId}`).then(r => r.data),
    enabled: !!orderId,
  });

  // Fetch warehouses for this order's brand
  const { data: warehouses = [] } = useQuery<Warehouse[]>({
    queryKey: ['warehouses-stockout', order?.brand_id],
    queryFn: () => api.get('/inventory/warehouses', { params: { brand_id: order?.brand_id } }).then(r => r.data),
    enabled: !!order?.brand_id,
  });

  // Auto-select: order.warehouse_id > brand main warehouse
  useEffect(() => {
    if (selectedWarehouseId) return; // already selected
    if (order?.warehouse_id) { setSelectedWarehouseId(order.warehouse_id); return; }
    const mainWh = warehouses.find(w => w.warehouse_type === 'main');
    if (mainWh) setSelectedWarehouseId(mainWh.id);
  }, [order, warehouses, selectedWarehouseId]);

  // 每个订单项需要扫码的箱数（若以箱为单位则=quantity，以瓶则=quantity/bpc向上取整）
  // 约定：一个条码=一箱
  const casesNeeded = (it: OrderItem): number => {
    const bpc = it.product?.bottles_per_case && it.product.bottles_per_case > 1 ? it.product.bottles_per_case : 1;
    return it.quantity_unit === '箱' ? it.quantity : Math.ceil(it.quantity / bpc);
  };
  const bottlesPerScan = (it: OrderItem): number => {
    return it.product?.bottles_per_case && it.product.bottles_per_case > 1 ? it.product.bottles_per_case : 1;
  };

  // Count scanned per order_item
  const scannedPerItem: Record<string, number> = {};
  for (const rec of scanRecords) {
    scannedPerItem[rec.order_item_id] = (scannedPerItem[rec.order_item_id] || 0) + 1;
  }

  const allDone = order?.items.every(it => (scannedPerItem[it.id] || 0) >= casesNeeded(it)) ?? false;

  const stockOutMut = useMutation({
    mutationFn: async (params: { order_item_id: string; product_id: string; required_quantity: number; warehouse_id: string; barcode?: string }) => {
      const { data } = await api.post('/inventory/stock-out', params);
      return data;
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? '出库失败';
      setScanError(msg);
      message.error(msg);
    },
  });

  const shipMut = useMutation({
    mutationFn: () => api.post(`/orders/${orderId}/ship`),
    onSuccess: () => {
      message.success('出库成功！订单已发货');
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      navigate('/orders');
    },
    onError: (err: any) => message.error(err?.response?.data?.detail ?? '发货失败'),
  });

  const handleScan = async (barcode: string) => {
    if (!barcode.trim() || !order) return;
    if (!selectedWarehouseId) { message.warning('请先选择出库仓库'); return; }
    setScanError('');
    setBarcodeInput('');

    try {
      // Trace barcode to get product_id
      const { data: trace } = await api.get(`/inventory/barcode-trace/${barcode.trim()}`);
      const productId = trace.product_id;

      // Find matching order item — 按需要的箱数比较已扫箱数
      const matchItem = order.items.find(it => it.product_id === productId && (scannedPerItem[it.id] || 0) < casesNeeded(it));
      if (!matchItem) {
        setScanError(`条码 ${barcode} 对应商品不在本订单中或已扫完`);
        return;
      }

      // Execute stock-out — 每扫一箱扣减 bpc 瓶
      await stockOutMut.mutateAsync({
        order_item_id: matchItem.id,
        product_id: productId,
        required_quantity: bottlesPerScan(matchItem),
        warehouse_id: selectedWarehouseId,
        barcode: barcode.trim(),
      });

      setScanRecords(prev => [...prev, {
        barcode: barcode.trim(),
        product_id: productId,
        product_name: trace.product_name || matchItem.product?.name || '未知',
        order_item_id: matchItem.id,
        time: new Date().toLocaleTimeString('zh-CN'),
      }]);
      message.success(`已扫: ${trace.product_name || '商品'}`);
    } catch (err: any) {
      if (!scanError) setScanError(err?.response?.data?.detail ?? '扫码失败');
    }
  };

  const handleManualOut = async () => {
    if (!manualItemId || !order) return;
    const item = order.items.find(it => it.id === manualItemId);
    if (!item) return;
    const bpc = bottlesPerScan(item);

    try {
      // manualQty 单位=箱，换算成瓶数扣库存
      await stockOutMut.mutateAsync({
        order_item_id: item.id,
        product_id: item.product_id,
        required_quantity: manualQty * bpc,
        warehouse_id: selectedWarehouseId,
      });

      for (let i = 0; i < manualQty; i++) {
        setScanRecords(prev => [...prev, {
          barcode: `MANUAL-${Date.now()}-${i}`,
          product_id: item.product_id,
          product_name: item.product?.name || '未知',
          order_item_id: item.id,
          time: new Date().toLocaleTimeString('zh-CN'),
        }]);
      }
      message.success(`手动出库 ${manualQty} 箱（${manualQty * bpc}瓶）`);
      setManualItemId(null);
      setManualQty(1);
    } catch { /* handled by mutation */ }
  };

  if (!orderId) return <div style={{ padding: 24 }}><Alert type="error" title="缺少订单ID" showIcon /><Button style={{ marginTop: 16 }} onClick={() => navigate('/orders')}>返回</Button></div>;
  if (isError) return <div style={{ padding: 24 }}><Alert type="error" title="加载订单失败" showIcon /><Button style={{ marginTop: 16 }} onClick={() => navigate('/orders')}>返回</Button></div>;
  if (isLoading || !order) return <div style={{ padding: 24 }}>加载中...</div>;
  if (order.status !== 'approved') return (
    <div style={{ padding: 24 }}>
      <Alert type="warning" title={`订单状态为 "${order.status}"，只有已审批的订单才能扫码出库`} showIcon />
      <Button style={{ marginTop: 16 }} onClick={() => navigate('/orders')}>返回订单列表</Button>
    </div>
  );

  return (
    <div style={{ maxWidth: 700, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/orders')}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>扫码出库</Title>
      </Space>

      {/* 订单信息 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="订单号">{order.order_no}</Descriptions.Item>
          <Descriptions.Item label="客户">{order.customer?.name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="出库仓库" span={2}>
            <Select
              value={selectedWarehouseId || undefined}
              onChange={v => setSelectedWarehouseId(v)}
              placeholder="选择出库仓库"
              style={{ width: 200 }}
              options={warehouses.filter(w => w.warehouse_type === 'main' || w.warehouse_type === 'backup').map(w => ({ value: w.id, label: w.name }))}
            />
            {!selectedWarehouseId && <Text type="danger" style={{ marginLeft: 8 }}>请先选择仓库</Text>}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 扫码输入 */}
      <div style={{ marginBottom: 16 }}>
        <Input
          size="large"
          prefix={<BarcodeOutlined style={{ fontSize: 20 }} />}
          placeholder="扫描条码或输入条码后回车"
          autoFocus
          value={barcodeInput}
          onChange={e => setBarcodeInput(e.target.value)}
          onPressEnter={() => handleScan(barcodeInput)}
          style={{ fontSize: 18 }}
        />
        {scanError && <Alert type="error" title={scanError} style={{ marginTop: 8 }} closable onClose={() => setScanError('')} />}
        <div style={{ marginTop: 8, textAlign: 'right' }}>
          <Button size="small" type="link" onClick={() => setManualMode(!manualMode)}>
            {manualMode ? '关闭手动模式' : '手动输入条码'}
          </Button>
        </div>
      </div>

      {/* 出库进度（以箱为单位） */}
      <Card title="出库进度（按箱）" size="small" style={{ marginBottom: 16 }}>
        {order.items.map(item => {
          const scanned = scannedPerItem[item.id] || 0;
          const need = casesNeeded(item);
          const pct = Math.min(100, Math.round(scanned / need * 100));
          const done = scanned >= need;
          return (
            <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid #f5f5f5' }}>
              <div style={{ flex: 1 }}>
                <Text strong>{item.product?.name || item.product_id.slice(0, 8)}</Text>
                <div style={{ fontSize: 12, color: '#888' }}>单价 ¥{Number(item.unit_price).toLocaleString()}/瓶 · 订单 {item.quantity}{item.quantity_unit || '瓶'}</div>
              </div>
              <div style={{ width: 100 }}><Progress percent={pct} size="small" status={done ? 'success' : 'active'} /></div>
              <Tag color={done ? 'green' : 'orange'}>{scanned}/{need} 箱</Tag>
              {manualMode && !done && (
                <Button size="small" onClick={() => { setManualItemId(item.id); setManualQty(need - scanned); }}>手动</Button>
              )}
            </div>
          );
        })}
      </Card>

      {/* 已扫记录 */}
      {scanRecords.length > 0 && (
        <Card title={`已扫条码 (${scanRecords.length})`} size="small" style={{ marginBottom: 16, maxHeight: 200, overflow: 'auto' }}>
          {scanRecords.map((rec, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 12, borderBottom: '1px solid #fafafa' }}>
              <span>{rec.product_name}</span>
              <span style={{ color: '#999' }}>{rec.barcode.startsWith('MANUAL') ? '手动' : rec.barcode} · {rec.time}</span>
            </div>
          ))}
        </Card>
      )}

      {/* 确认出库 */}
      <Button
        type="primary"
        size="large"
        block
        icon={<CheckCircleOutlined />}
        disabled={!allDone || !selectedWarehouseId}
        loading={shipMut.isPending}
        onClick={() => shipMut.mutate()}
        style={{ height: 48, fontSize: 16 }}
      >
        {allDone ? '确认出库' : `还需扫码 (${order.items.reduce((s, it) => s + Math.max(0, casesNeeded(it) - (scannedPerItem[it.id] || 0)), 0)} 箱)`}
      </Button>

      {/* 手动出库弹窗 */}
      <Modal title="手动出库" open={!!manualItemId} onOk={handleManualOut} onCancel={() => setManualItemId(null)}
        okText="确认出库" confirmLoading={stockOutMut.isPending}>
        <div style={{ marginBottom: 8 }}>
          <Text>商品: {order.items.find(it => it.id === manualItemId)?.product?.name}</Text>
        </div>
        <Space>
          <InputNumber value={manualQty} onChange={v => setManualQty(v ?? 1)} min={1}
            max={(() => { const it = order.items.find(i => i.id === manualItemId); return it ? casesNeeded(it) - (scannedPerItem[it.id] || 0) : 1; })()}
            style={{ width: 200 }} />
          <span>箱</span>
        </Space>
      </Modal>
    </div>
  );
}

export default OrderStockOutPage;
