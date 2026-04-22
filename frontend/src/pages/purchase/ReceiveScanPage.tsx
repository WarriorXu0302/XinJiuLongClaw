import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Alert, Button, Card, Descriptions, Input, message, Select, Space, Table, Tag, Typography, Upload } from 'antd';
import { BarcodeOutlined, DeleteOutlined, UploadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import * as XLSX from 'xlsx';

const { Title, Text } = Typography;

interface PurchaseOrder {
  id: string;
  po_no: string;
  supplier?: { name: string };
  warehouse_id?: string;
  warehouse?: { name: string };
  total_amount: string;
  status: string;
  items: { product_id: string; product?: { name: string; bottles_per_case?: number }; quantity: number; quantity_unit?: string; unit_price: string }[];
}

interface ScannedCode {
  key: string;
  barcode: string;
  count: number;
  time: string;
}

function ReceiveScanPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const preselectedPoId = searchParams.get('po_id');
  const inputRef = useRef<any>(null);
  const [selectedPO, setSelectedPO] = useState<PurchaseOrder | null>(null);
  const [batchNo, setBatchNo] = useState('');
  const [scannedCodes, setScannedCodes] = useState<ScannedCode[]>([]);

  // 拉取待收货的采购单（paid / shipped 状态）
  const { data: poList = [] } = useQuery<PurchaseOrder[]>({
    queryKey: ['po-for-receive'],
    queryFn: () => api.get('/purchase-orders').then(r => extractItems<PurchaseOrder>(r.data)),
  });

  const receivablePOs = poList.filter(po => ['pending', 'approved', 'paid', 'shipped'].includes(po.status));

  // 预选采购单（从列表点击扫码入库时带 po_id）
  useEffect(() => {
    if (preselectedPoId && poList.length > 0 && !selectedPO) {
      const po = poList.find(p => p.id === preselectedPoId);
      if (po) {
        setSelectedPO(po);
        if (!batchNo) setBatchNo(`PO-${new Date().toISOString().slice(0, 10)}`);
      }
    }
  }, [preselectedPoId, poList, selectedPO, batchNo]);

  // 扫码：自动去重 + 计数
  const handleScan = (value: string) => {
    const code = value.trim();
    if (!code) return;
    setScannedCodes(prev => {
      const existing = prev.find(c => c.barcode === code);
      if (existing) {
        message.warning(`条码 ${code} 已扫过（第 ${existing.count + 1} 次）`);
        return prev.map(c => c.barcode === code ? { ...c, count: c.count + 1 } : c);
      }
      return [...prev, { key: code, barcode: code, count: 1, time: new Date().toLocaleTimeString('zh-CN') }];
    });
  };

  // Excel 导入
  const handleExcelImport = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const data = e.target?.result;
      const workbook = XLSX.read(data, { type: 'binary' });
      const sheet = workbook.Sheets[workbook.SheetNames[0]];
      const rows = XLSX.utils.sheet_to_json<Record<string, string>>(sheet, { header: 'A' });
      let imported = 0;
      const newCodes = [...scannedCodes];
      for (const row of rows) {
        const code = String(row.A || row.B || Object.values(row)[0] || '').trim();
        if (!code || newCodes.find(c => c.barcode === code)) continue;
        newCodes.push({ key: code, barcode: code, count: 1, time: 'Excel' });
        imported++;
      }
      setScannedCodes(newCodes);
      message.success(`导入 ${imported} 个条码，${rows.length - imported} 个重复跳过`);
    };
    reader.readAsBinaryString(file);
    return false;
  };

  // 提交收货：调用 receive 端点 + 条码绑定
  const receiveMutation = useMutation({
    mutationFn: async () => {
      if (!selectedPO) throw new Error('请选择采购单');
      if (!batchNo.trim()) throw new Error('请输入批次号');

      // 1. 调用采购单收货端点
      await api.post(`/purchase-orders/${selectedPO.id}/receive?batch_no=${encodeURIComponent(batchNo)}`);

      // 2. 如果有扫描条码，批量导入绑定
      if (scannedCodes.length > 0 && selectedPO.items.length > 0) {
        const productId = selectedPO.items[0].product_id;
        await api.post('/inventory/barcodes/batch-import', {
          product_id: productId,
          warehouse_id: selectedPO.warehouse_id,
          batch_no: batchNo,
          barcodes: scannedCodes.map(c => c.barcode),
        });
      }
    },
    onSuccess: () => {
      message.success(`采购单 ${selectedPO!.po_no} 收货完成，${scannedCodes.length} 个条码已绑定`);
      setScannedCodes([]);
      setSelectedPO(null);
      setBatchNo('');
      queryClient.invalidateQueries({ queryKey: ['po-for-receive'] });
      queryClient.invalidateQueries({ queryKey: ['purchase-orders'] });
      queryClient.invalidateQueries({ queryKey: ['inventory-value'] });
      queryClient.invalidateQueries({ queryKey: ['stock-flows'] });
      navigate('/purchase/orders');
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail;
      const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ') : (detail || err?.message || '收货失败');
      message.error(`收货失败: ${msg}`);
      console.error('Receive error:', err?.response?.data || err);
    },
  });

  const columns: ColumnsType<ScannedCode> = [
    { title: '#', key: 'idx', width: 50, render: (_, __, i) => i + 1 },
    { title: '条码', dataIndex: 'barcode', width: 280 },
    { title: '状态', dataIndex: 'count', width: 90, align: 'center', render: (v: number) => v > 1 ? <Tag color="orange">{v}次重复</Tag> : <Tag color="green">OK</Tag> },
    { title: '时间', dataIndex: 'time', width: 100 },
    { title: '', key: 'del', width: 40, render: (_, r) => <a style={{ color: '#ff4d4f' }} onClick={() => setScannedCodes(p => p.filter(c => c.barcode !== r.barcode))}><DeleteOutlined /></a> },
  ];

  const uniqueCount = new Set(scannedCodes.map(c => c.barcode)).size;

  return (
    <>
      <Title level={4}><BarcodeOutlined /> 采购收货扫码</Title>

      {/* 选择采购单 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <span>采购单：</span>
          <Select
            showSearch
            placeholder="选择待收货的采购单"
            optionFilterProp="label"
            options={receivablePOs.map(po => ({
              value: po.id,
              label: `${po.po_no} | ${po.supplier?.name ?? ''} | ¥${Number(po.total_amount).toFixed(0)}`,
            }))}
            style={{ width: 420 }}
            onChange={(id) => setSelectedPO(poList.find(p => p.id === id) ?? null)}
            allowClear
            onClear={() => setSelectedPO(null)}
          />
          <span>批次号：</span>
          <Input
            placeholder="如 2026-04-B1"
            style={{ width: 160 }}
            value={batchNo}
            onChange={e => setBatchNo(e.target.value)}
          />
        </Space>
      </Card>

      {/* 采购单信息 */}
      {selectedPO && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Descriptions column={3} size="small">
            <Descriptions.Item label="采购单号">{selectedPO.po_no}</Descriptions.Item>
            <Descriptions.Item label="供应商">{selectedPO.supplier?.name ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="目标仓库">{selectedPO.warehouse?.name ?? selectedPO.warehouse_id ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="总金额">¥{Number(selectedPO.total_amount).toFixed(2)}</Descriptions.Item>
            <Descriptions.Item label="状态"><Tag color="blue">{selectedPO.status}</Tag></Descriptions.Item>
            <Descriptions.Item label="商品明细">
              {selectedPO.items.map((it, i) => (
                <Tag key={i}>{it.product?.name ?? it.product_id.slice(0, 8)} ×{it.quantity}{it.quantity_unit || '箱'}</Tag>
              ))}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {/* 扫码区域 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space>
            <Input
              ref={inputRef}
              placeholder="扫码枪扫描 / 手动输入后回车"
              style={{ width: 350 }}
              onPressEnter={(e) => { handleScan((e.target as HTMLInputElement).value); (e.target as HTMLInputElement).value = ''; }}
              autoFocus
              prefix={<BarcodeOutlined />}
              disabled={!selectedPO}
            />
            <Upload beforeUpload={handleExcelImport} accept=".xlsx,.xls,.csv" showUploadList={false} disabled={!selectedPO}>
              <Button icon={<UploadOutlined />} disabled={!selectedPO}>Excel 导入</Button>
            </Upload>
          </Space>
          <Space>
            <Text>已扫 <strong>{scannedCodes.length}</strong> 个（去重 {uniqueCount}）</Text>
            <Button onClick={() => setScannedCodes([])} disabled={scannedCodes.length === 0}>清空</Button>
            <Button
              type="primary"
              disabled={!selectedPO || !batchNo.trim()}
              loading={receiveMutation.isPending}
              onClick={() => receiveMutation.mutate()}
            >
              确认收货入库
            </Button>
          </Space>
        </Space>
      </Card>

      {!selectedPO && (
        <Alert type="info" title="请先选择一个已付款/已发货的采购单，再扫码收货" showIcon style={{ marginBottom: 16 }} />
      )}

      <Table<ScannedCode> columns={columns} dataSource={scannedCodes} rowKey="key" size="small" pagination={false} scroll={{ y: 400 }} />
    </>
  );
}

export default ReceiveScanPage;
