/**
 * 仓库调拨 - 新建
 *
 * 业务规则（前端提示，后端强校验）：
 *   - 品牌主仓（warehouse_type=main AND brand 非空）不出现在 source/dest 下拉
 *   - 同品牌 ERP 内部调拨 → 免审，创建后直接显示"免审执行"按钮
 *   - 跨品牌 / ERP↔mall → 提交审批
 */
import { useMemo, useRef, useState } from 'react';
import {
  Alert, Button, Card, Input, message, Modal, Select, Space,
  Table, Tag, Typography,
} from 'antd';
import { BarcodeOutlined, DeleteOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import api, { extractItems } from '../../api/client';

const { Title } = Typography;

interface ERPWarehouse {
  id: string;
  name: string;
  code: string;
  warehouse_type: string;
  brand_id?: string;
  brand?: { id: string; name: string };
  is_active: boolean;
}

interface MallWarehouse {
  id: string;
  name: string;
  code: string;
  is_active: boolean;
}

interface ScanRow {
  key: string;
  barcode: string;
  time: string;
}

export default function TransferCreate() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const inputRef = useRef<any>(null);

  const [sourceSide, setSourceSide] = useState<'erp' | 'mall'>('erp');
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [destSide, setDestSide] = useState<'erp' | 'mall'>('erp');
  const [destId, setDestId] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [scanned, setScanned] = useState<ScanRow[]>([]);

  const { data: erpWhs = [] } = useQuery<ERPWarehouse[]>({
    queryKey: ['warehouses-all'],
    queryFn: () => api.get('/inventory/warehouses').then(r => extractItems<ERPWarehouse>(r.data)),
  });
  const { data: mallWhs = [] } = useQuery<MallWarehouse[]>({
    queryKey: ['mall-admin-warehouses-for-transfer'],
    queryFn: () => api.get('/mall/admin/warehouses')
      .then(r => r.data?.records || r.data?.items || []),
  });

  // 过滤品牌主仓（出入都禁）
  const transferableErp = useMemo(
    () => erpWhs.filter(w =>
      w.is_active && !(w.warehouse_type === 'main' && w.brand_id)
    ),
    [erpWhs]
  );
  const activeMall = useMemo(() => mallWhs.filter(w => w.is_active), [mallWhs]);

  const srcOptions = sourceSide === 'erp'
    ? transferableErp.map(w => ({
        value: w.id,
        label: `${w.name} [${w.code}]${w.brand ? ' · ' + w.brand.name : ''} (${w.warehouse_type})`,
      }))
    : activeMall.map(w => ({
        value: w.id,
        label: `${w.name} [${w.code}]`,
      }));
  const dstOptions = destSide === 'erp'
    ? transferableErp
        .filter(w => !(sourceSide === 'erp' && w.id === sourceId))
        .map(w => ({
          value: w.id,
          label: `${w.name} [${w.code}]${w.brand ? ' · ' + w.brand.name : ''} (${w.warehouse_type})`,
        }))
    : activeMall
        .filter(w => !(sourceSide === 'mall' && w.id === sourceId))
        .map(w => ({
          value: w.id,
          label: `${w.name} [${w.code}]`,
        }));

  // 审批判定（和后端逻辑一致，仅提示用）
  const approvalHint = useMemo(() => {
    if (!sourceId || !destId) return null;
    if (sourceSide === 'erp' && destSide === 'erp') {
      const src = erpWhs.find(w => w.id === sourceId);
      const dst = erpWhs.find(w => w.id === destId);
      if (src?.brand_id && dst?.brand_id && src.brand_id === dst.brand_id) {
        return { requires: false, text: '同品牌 ERP 内部调拨 → 免审，创建后可直接执行' };
      }
      return { requires: true, text: '跨品牌 ERP 调拨 → 需审批' };
    }
    return { requires: true, text: '涉商城仓 / 跨端调拨 → 需审批' };
  }, [sourceSide, sourceId, destSide, destId, erpWhs]);

  const handleScan = (value: string) => {
    const code = value.trim();
    if (!code) return;
    if (!sourceId || !destId) {
      message.warning('请先选择源仓和目标仓');
      return;
    }
    setScanned(prev => {
      if (prev.find(c => c.barcode === code)) {
        message.warning(`条码 ${code} 已扫过`);
        return prev;
      }
      return [...prev, {
        key: code, barcode: code,
        time: new Date().toLocaleTimeString('zh-CN'),
      }];
    });
  };

  const createMut = useMutation({
    mutationFn: () => api.post('/transfers', {
      source_side: sourceSide,
      source_warehouse_id: sourceId,
      dest_side: destSide,
      dest_warehouse_id: destId,
      barcodes: scanned.map(s => s.barcode),
      reason: reason || null,
    }).then(r => r.data),
    onSuccess: (res: any) => {
      message.success(`调拨单 ${res.transfer_no} 已创建${res.requires_approval ? '，请提交审批' : '（免审）'}`);
      queryClient.invalidateQueries({ queryKey: ['wh-transfers'] });
      navigate('/inventory/transfers');
    },
    onError: (e: any) => {
      const detail = e?.response?.data?.detail ?? e?.message ?? '创建失败';
      message.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    },
  });

  const columns: ColumnsType<ScanRow> = [
    { title: '#', key: 'idx', width: 50, render: (_, __, i) => i + 1 },
    { title: '条码', dataIndex: 'barcode', width: 280 },
    { title: '扫码时间', dataIndex: 'time', width: 120 },
    {
      title: '', key: 'del', width: 50,
      render: (_, r) => (
        <a style={{ color: '#ff4d4f' }}
          onClick={() => setScanned(p => p.filter(c => c.barcode !== r.barcode))}
        ><DeleteOutlined /></a>
      ),
    },
  ];

  const canSubmit = sourceId && destId && scanned.length > 0;

  return (
    <>
      <Title level={4}><BarcodeOutlined /> 新建调拨单</Title>

      <Alert
        type="info"
        message="品牌主仓（主仓 + 绑定品牌）不参与调拨"
        description="品牌主仓只能通过采购单入库 / 销售订单出库。其他仓和商城仓都能互相调拨。"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Card size="small" title="源仓 + 目标仓" style={{ marginBottom: 16 }}>
        <Space size="large" wrap>
          <Space>
            <span>源端：</span>
            <Select
              value={sourceSide}
              onChange={(v) => { setSourceSide(v); setSourceId(null); setScanned([]); }}
              style={{ width: 120 }}
              options={[
                { value: 'erp', label: 'ERP 仓' },
                { value: 'mall', label: '商城仓' },
              ]}
            />
            <Select
              placeholder="选择源仓"
              showSearch
              optionFilterProp="label"
              style={{ width: 320 }}
              value={sourceId}
              onChange={(v) => { setSourceId(v); setScanned([]); }}
              options={srcOptions}
              allowClear
            />
          </Space>
          <Space>
            <span>目标端：</span>
            <Select
              value={destSide}
              onChange={(v) => { setDestSide(v); setDestId(null); }}
              style={{ width: 120 }}
              options={[
                { value: 'erp', label: 'ERP 仓' },
                { value: 'mall', label: '商城仓' },
              ]}
            />
            <Select
              placeholder="选择目标仓"
              showSearch
              optionFilterProp="label"
              style={{ width: 320 }}
              value={destId}
              onChange={setDestId}
              options={dstOptions}
              allowClear
            />
          </Space>
        </Space>
        {approvalHint && (
          <div style={{ marginTop: 12 }}>
            <Tag color={approvalHint.requires ? 'orange' : 'green'}>
              {approvalHint.text}
            </Tag>
          </div>
        )}
        <div style={{ marginTop: 12 }}>
          <Input.TextArea
            placeholder="备注（可选）"
            rows={2}
            value={reason}
            onChange={e => setReason(e.target.value)}
            maxLength={1000}
            showCount
          />
        </div>
      </Card>

      <Card size="small" title={`扫码（已扫 ${scanned.length} 瓶）`}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Input
            ref={inputRef}
            placeholder="扫码枪扫描 / 手动输入后回车"
            style={{ width: 400 }}
            onPressEnter={(e) => {
              handleScan((e.target as HTMLInputElement).value);
              (e.target as HTMLInputElement).value = '';
            }}
            autoFocus
            prefix={<BarcodeOutlined />}
            disabled={!sourceId || !destId}
          />
          <Space>
            <Button
              onClick={() => setScanned([])}
              disabled={scanned.length === 0}
            >清空</Button>
            <Button
              type="primary"
              disabled={!canSubmit}
              loading={createMut.isPending}
              onClick={() => Modal.confirm({
                title: '创建调拨单',
                content: `${scanned.length} 瓶条码将从源仓调往目标仓。${approvalHint?.requires ? '需审批后才能执行。' : '免审，创建后可直接执行。'}`,
                onOk: () => createMut.mutateAsync(),
              })}
            >创建</Button>
          </Space>
        </Space>
      </Card>

      <div style={{ marginTop: 16 }}>
        <Table
          columns={columns}
          dataSource={scanned}
          rowKey="key"
          size="small"
          pagination={false}
          scroll={{ y: 400 }}
        />
      </div>
    </>
  );
}
