import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Alert, Button, Card, Descriptions, Input, message, Select, Space, Table, Tag, Typography, Upload,
} from 'antd';
import { BarcodeOutlined, DeleteOutlined, UploadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import * as XLSX from 'xlsx';

const { Title, Text } = Typography;

interface POItem {
  id: string;
  product_id: string;
  product?: { name: string; bottles_per_case?: number };
  quantity: number;
  quantity_unit?: string;
  unit_price: string;
}

interface PurchaseOrder {
  id: string;
  po_no: string;
  supplier?: { name: string };
  warehouse_id?: string;
  warehouse?: { name: string };
  target_warehouse_type?: 'erp_warehouse' | 'mall_warehouse';
  mall_warehouse_id?: string;
  total_amount: string;
  status: string;
  items: POItem[];
}

interface ScannedCode {
  key: string;
  barcode: string;
  item_id: string;       // 绑定到哪个 PO item
  count: number;
  time: string;
}

/**
 * 采购收货扫码页
 *
 * ERP 仓 + mall 仓**都**要扫码（白酒业务硬要求：每瓶厂家防伪码）。
 *
 * mall 仓收货差异：
 *   - 需要按 PO item 分组扫码：先选当前扫的 item，再扫该 item 应收瓶数
 *   - 每个 item 扫码数必须精确等于 quantity × bottles_per_case
 *   - 提交时 barcodes_by_item = [{item_id, barcodes: [...]}]
 *   - 后端全局 UNIQUE + 本次内去重
 */
function ReceiveScanPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const preselectedPoId = searchParams.get('po_id');
  const inputRef = useRef<any>(null);
  const [selectedPO, setSelectedPO] = useState<PurchaseOrder | null>(null);
  const [batchNo, setBatchNo] = useState('');
  const [scannedCodes, setScannedCodes] = useState<ScannedCode[]>([]);
  const [currentItemId, setCurrentItemId] = useState<string | null>(null);

  // 拉取待收货的采购单（paid / shipped 状态）
  const { data: poList = [] } = useQuery<PurchaseOrder[]>({
    queryKey: ['po-for-receive'],
    queryFn: () => api.get('/purchase-orders').then(r => extractItems<PurchaseOrder>(r.data)),
  });

  const receivablePOs = poList.filter(po => ['pending', 'approved', 'paid', 'shipped'].includes(po.status));
  const isMallTarget = selectedPO?.target_warehouse_type === 'mall_warehouse';

  // 预选采购单
  useEffect(() => {
    if (preselectedPoId && poList.length > 0 && !selectedPO) {
      const po = poList.find(p => p.id === preselectedPoId);
      if (po) {
        setSelectedPO(po);
        if (!batchNo) setBatchNo(`PO-${new Date().toISOString().slice(0, 10)}`);
        if (po.items.length > 0) setCurrentItemId(po.items[0].id);
      }
    }
  }, [preselectedPoId, poList, selectedPO, batchNo]);

  // 每个 item 应入瓶数
  const bottlesByItem = useMemo(() => {
    const m: Record<string, number> = {};
    (selectedPO?.items ?? []).forEach(it => {
      const bpc = it.quantity_unit === '箱' ? (it.product?.bottles_per_case ?? 1) : 1;
      m[it.id] = it.quantity * bpc;
    });
    return m;
  }, [selectedPO]);

  const scannedByItem = useMemo(() => {
    const m: Record<string, number> = {};
    for (const c of scannedCodes) {
      m[c.item_id] = (m[c.item_id] ?? 0) + 1;
    }
    return m;
  }, [scannedCodes]);

  // 扫码：绑定到当前 item_id + 全局去重
  const handleScan = (value: string) => {
    const code = value.trim();
    if (!code) return;
    if (!currentItemId) {
      message.warning('请先选择要扫码的商品条目');
      return;
    }
    // 校验当前 item 是否已满
    const expected = bottlesByItem[currentItemId] ?? 0;
    const got = scannedByItem[currentItemId] ?? 0;
    if (got >= expected) {
      message.warning(`当前商品已扫满 ${expected} 瓶`);
      return;
    }
    setScannedCodes(prev => {
      const existing = prev.find(c => c.barcode === code);
      if (existing) {
        message.warning(`条码 ${code} 已扫过（${existing.count + 1} 次），自动忽略重复`);
        return prev.map(c => c.barcode === code ? { ...c, count: c.count + 1 } : c);
      }
      return [...prev, {
        key: code, barcode: code, item_id: currentItemId,
        count: 1, time: new Date().toLocaleTimeString('zh-CN'),
      }];
    });
  };

  const handleExcelImport = (file: File) => {
    if (!currentItemId) {
      message.warning('请先选择要导入条码的商品条目');
      return false;
    }
    const expected = bottlesByItem[currentItemId] ?? 0;
    const got = scannedByItem[currentItemId] ?? 0;
    const remaining = expected - got;

    const reader = new FileReader();
    reader.onload = (e) => {
      const data = e.target?.result;
      const workbook = XLSX.read(data, { type: 'binary' });
      const sheet = workbook.Sheets[workbook.SheetNames[0]];
      const rows = XLSX.utils.sheet_to_json<Record<string, string>>(sheet, { header: 'A' });
      let imported = 0;
      const newCodes = [...scannedCodes];
      const seen = new Set(newCodes.map(c => c.barcode));
      for (const row of rows) {
        if (imported >= remaining) break;
        const code = String(row.A || row.B || Object.values(row)[0] || '').trim();
        if (!code || seen.has(code)) continue;
        newCodes.push({
          key: code, barcode: code, item_id: currentItemId,
          count: 1, time: 'Excel',
        });
        seen.add(code);
        imported++;
      }
      setScannedCodes(newCodes);
      message.success(`导入 ${imported} 个条码到当前商品（剩余配额 ${remaining - imported}）`);
    };
    reader.readAsBinaryString(file);
    return false;
  };

  // 提交收货
  const receiveMutation = useMutation({
    mutationFn: async () => {
      if (!selectedPO) throw new Error('请选择采购单');
      if (!batchNo.trim()) throw new Error('请输入批次号');

      // 按 item 分组条码
      const barcodes_by_item = selectedPO.items.map(it => ({
        item_id: it.id,
        barcodes: scannedCodes.filter(c => c.item_id === it.id).map(c => c.barcode),
      }));

      // 每个 item 必须扫满
      for (const it of selectedPO.items) {
        const expected = bottlesByItem[it.id] ?? 0;
        const got = barcodes_by_item.find(b => b.item_id === it.id)?.barcodes.length ?? 0;
        if (got !== expected) {
          const name = it.product?.name ?? it.product_id.slice(0, 8);
          throw new Error(`商品 ${name} 应扫 ${expected} 瓶，已扫 ${got} 瓶`);
        }
      }

      await api.post(`/purchase-orders/${selectedPO.id}/receive`, {
        batch_no: batchNo,
        // 仅 mall 仓必填；ERP 仓沿用老流程（条码单独走 /inventory/barcodes/batch-import）
        ...(isMallTarget ? { barcodes_by_item } : {}),
      });

      // ERP 仓：条码走原有 batch-import 路径
      if (!isMallTarget && scannedCodes.length > 0 && selectedPO.items.length > 0) {
        // ERP 端的 batch-import 当前按 product_id 单体提交，保留原行为
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
      message.success(
        `采购单 ${selectedPO!.po_no} 收货完成，${scannedCodes.length} 瓶已入库并生成条码`
      );
      setScannedCodes([]);
      setSelectedPO(null);
      setBatchNo('');
      setCurrentItemId(null);
      queryClient.invalidateQueries({ queryKey: ['po-for-receive'] });
      queryClient.invalidateQueries({ queryKey: ['purchase-orders'] });
      queryClient.invalidateQueries({ queryKey: ['inventory-value'] });
      queryClient.invalidateQueries({ queryKey: ['stock-flows'] });
      navigate('/purchase/orders');
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ')
        : (detail || err?.message || '收货失败');
      message.error(`收货失败: ${msg}`);
      console.error('Receive error:', err?.response?.data || err);
    },
  });

  const columns: ColumnsType<ScannedCode> = [
    { title: '#', key: 'idx', width: 50, render: (_, __, i) => i + 1 },
    { title: '条码', dataIndex: 'barcode', width: 260 },
    {
      title: '所属商品',
      dataIndex: 'item_id',
      width: 200,
      render: (id: string) => {
        const it = selectedPO?.items.find(i => i.id === id);
        return it?.product?.name ?? id.slice(0, 8);
      },
    },
    {
      title: '状态',
      dataIndex: 'count',
      width: 90,
      align: 'center',
      render: (v: number) => v > 1 ? <Tag color="orange">{v}次重复</Tag> : <Tag color="green">OK</Tag>,
    },
    { title: '时间', dataIndex: 'time', width: 100 },
    {
      title: '',
      key: 'del',
      width: 40,
      render: (_, r) => (
        <a style={{ color: '#ff4d4f' }} onClick={() => setScannedCodes(p => p.filter(c => c.barcode !== r.barcode))}>
          <DeleteOutlined />
        </a>
      ),
    },
  ];

  // 所有 item 是否都扫满
  const allItemsFilled = selectedPO
    ? selectedPO.items.every(it => (scannedByItem[it.id] ?? 0) === (bottlesByItem[it.id] ?? 0))
    : false;

  return (
    <>
      <Title level={4}><BarcodeOutlined /> 采购收货扫码</Title>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <span>采购单：</span>
          <Select
            showSearch
            placeholder="选择待收货的采购单"
            optionFilterProp="label"
            options={receivablePOs.map(po => ({
              value: po.id,
              label: `${po.target_warehouse_type === 'mall_warehouse' ? '[商城] ' : ''}${po.po_no} | ${po.supplier?.name ?? ''} | ¥${Number(po.total_amount).toFixed(0)}`,
            }))}
            style={{ width: 420 }}
            onChange={(id) => {
              const po = poList.find(p => p.id === id) ?? null;
              setSelectedPO(po);
              setScannedCodes([]);
              setCurrentItemId(po?.items[0]?.id ?? null);
            }}
            allowClear
            onClear={() => { setSelectedPO(null); setCurrentItemId(null); }}
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

      {selectedPO && (
        <Card size="small" style={{ marginBottom: 16 }}>
          {isMallTarget && (
            <Alert
              type="info"
              showIcon
              message="本采购单入商城仓"
              description="按 PO item 分组扫码，每瓶必须是厂家防伪码（全局唯一）。扫满所有 item 后提交。"
              style={{ marginBottom: 12 }}
            />
          )}
          <Descriptions column={3} size="small">
            <Descriptions.Item label="采购单号">{selectedPO.po_no}</Descriptions.Item>
            <Descriptions.Item label="供应商">{selectedPO.supplier?.name ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="目标仓库">
              {isMallTarget ? (
                <><Tag color="gold">商城仓</Tag>{selectedPO.mall_warehouse_id?.slice(0, 8)}...</>
              ) : (
                <><Tag>ERP</Tag>{selectedPO.warehouse?.name ?? selectedPO.warehouse_id ?? '-'}</>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="总金额">¥{Number(selectedPO.total_amount).toFixed(2)}</Descriptions.Item>
            <Descriptions.Item label="状态"><Tag color="blue">{selectedPO.status}</Tag></Descriptions.Item>
          </Descriptions>

          {/* 每个 item 的扫码进度 */}
          <div style={{ marginTop: 12 }}>
            <Text strong>商品扫码进度（点击选中当前扫码目标）：</Text>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
              {selectedPO.items.map(it => {
                const expected = bottlesByItem[it.id] ?? 0;
                const got = scannedByItem[it.id] ?? 0;
                const done = got === expected;
                const active = currentItemId === it.id;
                return (
                  <Tag
                    key={it.id}
                    color={done ? 'green' : (active ? 'gold' : 'default')}
                    style={{
                      cursor: 'pointer',
                      fontSize: 13,
                      padding: '4px 10px',
                      border: active ? '2px solid #1677ff' : undefined,
                    }}
                    onClick={() => {
                      setCurrentItemId(it.id);
                      setTimeout(() => inputRef.current?.focus(), 50);
                    }}
                  >
                    {it.product?.name ?? it.product_id.slice(0, 8)}
                    {'  '}
                    <span style={{ fontWeight: 600 }}>{got}/{expected}</span>
                  </Tag>
                );
              })}
            </div>
          </div>
        </Card>
      )}

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space>
            <Input
              ref={inputRef}
              placeholder="扫码枪扫描 / 手动输入后回车"
              style={{ width: 350 }}
              onPressEnter={(e) => {
                handleScan((e.target as HTMLInputElement).value);
                (e.target as HTMLInputElement).value = '';
              }}
              autoFocus
              prefix={<BarcodeOutlined />}
              disabled={!selectedPO || !currentItemId}
            />
            <Upload
              beforeUpload={handleExcelImport}
              accept=".xlsx,.xls,.csv"
              showUploadList={false}
              disabled={!selectedPO || !currentItemId}
            >
              <Button icon={<UploadOutlined />} disabled={!selectedPO || !currentItemId}>Excel 导入</Button>
            </Upload>
          </Space>
          <Space>
            <Text>已扫 <strong>{scannedCodes.length}</strong> 瓶（全局去重）</Text>
            <Button onClick={() => setScannedCodes([])} disabled={scannedCodes.length === 0}>清空</Button>
            <Button
              type="primary"
              disabled={!selectedPO || !batchNo.trim() || !allItemsFilled}
              loading={receiveMutation.isPending}
              onClick={() => receiveMutation.mutate()}
            >
              {allItemsFilled ? '确认收货入库' : '扫满后提交'}
            </Button>
          </Space>
        </Space>
      </Card>

      {!selectedPO && (
        <Alert type="info" message="请先选择一个已付款/已发货的采购单，再扫码收货" showIcon style={{ marginBottom: 16 }} />
      )}

      <Table<ScannedCode>
        columns={columns}
        dataSource={scannedCodes}
        rowKey="key"
        size="small"
        pagination={false}
        scroll={{ y: 400 }}
      />
    </>
  );
}

export default ReceiveScanPage;
