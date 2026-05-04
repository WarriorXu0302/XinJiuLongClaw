import { useState } from 'react';
import { Button, Card, Col, Descriptions, Divider, Form, Input, InputNumber, message, Modal, Row, Select, Space, Table, Tag, Typography, Upload } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

const { Text } = Typography;

interface Case {
  id: string; case_no: string; case_type: string; direction: string;
  barcode?: string; batch_no?: string; product_id?: string;
  quantity: number; quantity_unit: string;
  purchase_price: number; resell_price: number;
  penalty_amount: number; transfer_amount: number;
  rebate_loss: number; reward_amount: number;
  profit_loss: number; no_rebate: boolean;
  counterparty?: string; found_location?: string;
  status: string; notes?: string; created_at: string;
  product?: { name: string };
}

const TYPE_LABEL: Record<string, string> = {
  outflow_malicious: 'A1 恶意窜货→备用库', outflow_nonmalicious: 'A2 非恶意→主仓',
  outflow_transfer: 'A3 被转码', inflow_resell: 'B1 加价回售', inflow_transfer: 'B2 转码入库',
};
const TYPE_COLOR: Record<string, string> = {
  outflow_malicious: 'red', outflow_nonmalicious: 'orange', outflow_transfer: 'volcano',
  inflow_resell: 'green', inflow_transfer: 'blue',
};
const STATUS_MAP: Record<string, { color: string; label: string }> = {
  pending: { color: 'orange', label: '待处理' }, approved: { color: 'blue', label: '已审批' },
  processing: { color: 'cyan', label: '处理中' }, settled: { color: 'green', label: '已结算' },
  closed: { color: 'default', label: '已归档' },
  confirmed: { color: 'blue', label: '已确认' }, recovered: { color: 'cyan', label: '已回收' },
  penalty_processed: { color: 'green', label: '已处罚' },
};

function InspectionList() {
  const queryClient = useQueryClient();
  const { brandId, params } = useBrandFilter();
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const [detailRecord, setDetailRecord] = useState<Case | null>(null);
  const [dirFilter, setDirFilter] = useState<string | null>(null);
  // 执行弹窗
  const [execRecord, setExecRecord] = useState<Case | null>(null);
  const [payVouchers, setPayVouchers] = useState<string[]>([]);
  const [scanBarcode, setScanBarcode] = useState('');
  const [scannedCodes, setScannedCodes] = useState<string[]>([]);
  const [logisticsUrls, setLogisticsUrls] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data: listResp, isLoading } = useQuery<{ items: Case[]; total: number }>({
    queryKey: ['inspection-cases', brandId, page, pageSize],
    queryFn: () => api.get('/inspection-cases', { params: { ...params, skip: (page - 1) * pageSize, limit: pageSize } }).then(r => r.data),
  });
  const data = listResp?.items ?? [];
  const total = listResp?.total ?? 0;

  const { data: products = [] } = useQuery<any[]>({
    queryKey: ['products-select', brandId],
    queryFn: () => api.get('/products', { params: brandId ? params : { limit: 200 } }).then(r => extractItems(r.data)),
  });

  const { data: customers = [] } = useQuery<any[]>({
    queryKey: ['customers-select'],
    queryFn: () => api.get('/customers').then(r => extractItems(r.data)),
  });

  const { data: warehouses = [] } = useQuery<any[]>({
    queryKey: ['warehouses-select', brandId],
    queryFn: () => api.get('/inventory/warehouses', { params }).then(r => extractItems(r.data)),
    enabled: !!brandId,
  });

  // 拉当前品牌的政策模板（取 customer_unit_price 用于盈亏计算）
  const { data: policyTemplates = [] } = useQuery<any[]>({
    queryKey: ['policy-templates-brand', brandId],
    queryFn: () => api.get('/policy-templates/templates', { params: { brand_id: brandId, is_active: true } }).then(r => extractItems(r.data)),
    enabled: !!brandId,
  });
  const mainWh = warehouses.find((w: any) => w.warehouse_type === 'main');
  const backupWh = warehouses.find((w: any) => w.warehouse_type === 'backup');

  const watchDirection = Form.useWatch('direction', form) ?? 'outflow';
  const watchType = Form.useWatch('case_type', form) ?? '';
  const watchQty = Form.useWatch('quantity', form) ?? 0;
  const watchUnit = Form.useWatch('quantity_unit', form) ?? '瓶';
  const watchProductId = Form.useWatch('product_id', form);
  const watchPurchasePrice = Form.useWatch('purchase_price', form) ?? 0;
  const watchResellPrice = Form.useWatch('resell_price', form) ?? 0;
  const watchPenalty = Form.useWatch('penalty_amount', form) ?? 0;
  const watchReward = Form.useWatch('reward_amount', form) ?? 0;

  // 选了商品后拿到 bottles_per_case
  const selectedProduct = products.find((p: any) => p.id === watchProductId);
  const bpc = selectedProduct?.bottles_per_case ?? 6;
  // 换算成瓶数
  const bottleCount = watchUnit === '箱' ? watchQty * bpc : watchQty;
  // 从商品拿价格（如果有）
  const salePrice = selectedProduct?.sale_price ?? 885;
  // 到手价：从当前品牌的政策模板读 customer_unit_price（取第一个匹配的模板）
  const brandTemplate = policyTemplates.find((t: any) => t.customer_unit_price > 0);
  const dealPrice = brandTemplate?.customer_unit_price ?? salePrice;

  const calcProfitLoss = () => {
    switch (watchType) {
      case 'outflow_malicious': return -((watchPurchasePrice - dealPrice) * bottleCount + watchPenalty);
      case 'outflow_nonmalicious': return (salePrice - watchPurchasePrice) * bottleCount - watchPenalty;
      case 'outflow_transfer': return -(watchPenalty);
      case 'inflow_resell': return (watchResellPrice - watchPurchasePrice) * bottleCount + watchReward;
      case 'inflow_transfer': return (salePrice - watchPurchasePrice) * bottleCount + watchReward;
      default: return 0;
    }
  };
  const liveProfit = calcProfitLoss();

  const createMut = useMutation({
    mutationFn: async (values: any) => {
      // 瓶数（库存和金额核算基准单位）
      const bottles = values.quantity_unit === '箱' ? (values.quantity || 0) * bpc : (values.quantity || 0);
      return (await api.post('/inspection-cases', {
        ...values, brand_id: brandId,
        original_sale_price: salePrice,
        deal_unit_price: dealPrice,
        profit_loss: calcProfitLoss(),
        no_rebate: values.case_type === 'outflow_nonmalicious',
        transfer_amount: values.case_type === 'outflow_transfer' ? salePrice * bottles : 0,
      })).data;
    },
    onSuccess: () => { message.success('案件已创建'); setModalOpen(false); form.resetFields(); queryClient.invalidateQueries({ queryKey: ['inspection-cases'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  const invalidateAll = () => { queryClient.invalidateQueries({ queryKey: ['inspection-cases'] }); queryClient.invalidateQueries({ queryKey: ['accounts-all'] }); };

  // 执行：付款+入库/出库 由后端原子化处理
  const executeMut = useMutation({
    mutationFn: async () => {
      if (!execRecord) throw new Error('无案件');
      const t = execRecord.case_type;
      const needsScan = ['outflow_malicious', 'outflow_nonmalicious', 'inflow_transfer', 'inflow_resell'].includes(t);
      if (needsScan && scannedCodes.length === 0 && !scanBarcode.trim()) throw new Error('请至少扫描一个条码');
      await api.post(`/inspection-cases/${execRecord.id}/execute`, {
        barcode: scanBarcode || undefined,
        barcodes: scannedCodes.length > 0 ? scannedCodes : undefined,
        voucher_urls: payVouchers.length > 0 ? payVouchers : undefined,
      });
    },
    onSuccess: () => { message.success('执行完成'); setExecRecord(null); setPayVouchers([]); setScanBarcode(''); setScannedCodes([]); invalidateAll(); },
    onError: (e: any) => message.error(e?.response?.data?.detail || e?.message || '执行失败'),
  });

  // B1上传物流
  const logisticsMut = useMutation({
    mutationFn: async (id: string) => {
      await api.put(`/inspection-cases/${id}`, { status: 'settled', voucher_urls: logisticsUrls });
    },
    onSuccess: () => { message.success('物流已上传'); setLogisticsUrls([]); setExecRecord(null); invalidateAll(); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  const archiveMut = useMutation({
    mutationFn: (id: string) => api.put(`/inspection-cases/${id}`, { status: 'closed' }),
    onSuccess: () => { message.success('已归档'); setExecRecord(null); invalidateAll(); },
  });

  const filtered = dirFilter ? data.filter(c => c.direction === dirFilter) : data;

  const columns: ColumnsType<Case> = [
    { title: '案件号', dataIndex: 'case_no', width: 120, render: (v, r) => <a onClick={() => setDetailRecord(r)}>{v}</a> },
    { title: '方向', dataIndex: 'direction', width: 65, render: (v: string) => !v ? <Tag>-</Tag> : v === 'outflow' ? <Tag color="red">外流</Tag> : <Tag color="green">流入</Tag> },
    { title: '类型', dataIndex: 'case_type', width: 130, render: (v: string) => <Tag color={TYPE_COLOR[v]}>{TYPE_LABEL[v] ?? v}</Tag> },
    { title: '商品', key: 'product', width: 100, render: (_, r) => r.product?.name ?? '-' },
    { title: '数量', key: 'qty', width: 65, render: (_, r) => `${r.quantity}${r.quantity_unit}` },
    { title: '对方', dataIndex: 'counterparty', width: 80, ellipsis: true },
    { title: '盈亏', dataIndex: 'profit_loss', width: 90, align: 'right', render: (v: number) => { const n = Number(v || 0); return <Text style={{ color: n >= 0 ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>{n >= 0 ? '+' : ''}¥{n.toLocaleString()}</Text>; } },
    { title: '状态', dataIndex: 'status', width: 75, render: (v: string) => { const m = STATUS_MAP[v]; return m ? <Tag color={m.color}>{m.label}</Tag> : <Tag>{v}</Tag>; } },
    { title: '操作', key: 'action', width: 110, render: (_, r) => (
      <Space size="small">
        {r.status === 'pending' && <Tag color="orange">审批中心</Tag>}
        {r.status === 'approved' && <a onClick={() => { setExecRecord(r); setPayVouchers([]); setScanBarcode(''); }}>执行</a>}
        {r.status === 'processing' && r.case_type === 'inflow_resell' && (
          <a onClick={() => { setExecRecord(r); setLogisticsUrls([]); }}>上传物流</a>
        )}
        {r.status === 'processing' && r.case_type !== 'inflow_resell' && <a onClick={() => archiveMut.mutate(r.id)}>归档</a>}
        {r.status === 'settled' && <a onClick={() => archiveMut.mutate(r.id)}>归档</a>}
        {r.status === 'closed' && <Tag>已归档</Tag>}
      </Space>
    ) },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Space>
          <h2 style={{ margin: 0 }}>稽查案件</h2>
          <Select value={dirFilter} onChange={v => { setDirFilter(v); setPage(1); }} allowClear placeholder="全部" style={{ width: 120 }}
            options={[{ value: 'outflow', label: '我方外流' }, { value: 'inflow', label: '主动清理' }]} />
        </Space>
        <Button type="primary" icon={<PlusOutlined />} disabled={!brandId} onClick={() => { form.resetFields(); form.setFieldsValue({ direction: 'outflow', quantity_unit: '瓶' }); setModalOpen(true); }}>新建案件</Button>
      </div>

      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <Card size="small" style={{ flex: 1, textAlign: 'center' }}><div style={{ color: '#888', fontSize: 12 }}>总案件</div><div style={{ fontSize: 18, fontWeight: 600 }}>{data.length}</div></Card>
        <Card size="small" style={{ flex: 1, textAlign: 'center' }}><div style={{ color: '#888', fontSize: 12 }}>外流亏损</div><div style={{ fontSize: 18, fontWeight: 600, color: '#ff4d4f' }}>¥{Math.abs(data.filter(c => Number(c.profit_loss || 0) < 0).reduce((s, c) => s + Number(c.profit_loss || 0), 0)).toLocaleString()}</div></Card>
        <Card size="small" style={{ flex: 1, textAlign: 'center' }}><div style={{ color: '#888', fontSize: 12 }}>清理盈利</div><div style={{ fontSize: 18, fontWeight: 600, color: '#52c41a' }}>¥{data.filter(c => Number(c.profit_loss || 0) > 0).reduce((s, c) => s + Number(c.profit_loss || 0), 0).toLocaleString()}</div></Card>
      </div>

      <Table columns={columns} dataSource={filtered} rowKey="id" loading={isLoading} size="middle" scroll={{ x: 900 }} pagination={{ current: page, pageSize, total, showTotal: (t) => '共 ' + t + ' 条', showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} />

      {/* 新建案件 */}
      <Modal title="新建稽查案件" open={modalOpen} width={650}
        onOk={() => form.validateFields().then(v => createMut.mutate(v))}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        confirmLoading={createMut.isPending} okText="提交" destroyOnHidden>
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={12}><Form.Item name="direction" label="方向" rules={[{ required: true }]}>
              <Select onChange={() => form.setFieldValue('case_type', undefined)} options={[
                { value: 'outflow', label: '我方货物外流（被查）' }, { value: 'inflow', label: '别人货物流入（主动清理）' },
              ]} />
            </Form.Item></Col>
            <Col span={12}><Form.Item name="case_type" label="处理方式" rules={[{ required: true }]}>
              <Select options={watchDirection === 'outflow' ? [
                { value: 'outflow_malicious', label: 'A1 恶意→回收→备用库' },
                { value: 'outflow_nonmalicious', label: 'A2 非恶意→回收→主仓(不计回款)' },
                { value: 'outflow_transfer', label: 'A3 被转码' },
              ] : [
                { value: 'inflow_resell', label: 'B1 加价回售' },
                { value: 'inflow_transfer', label: 'B2 转码入库' },
              ]} />
            </Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="product_id" label="商品" rules={[{ required: true }]}>
              <Select showSearch optionFilterProp="label" options={products.map((p: any) => ({ value: p.id, label: p.name }))} />
            </Form.Item></Col>
            <Col span={6}><Form.Item name="quantity" label="数量" rules={[{ required: true }]}
              extra={watchUnit === '箱' && watchQty > 0 ? `= ${bottleCount}瓶 (${bpc}瓶/箱)` : undefined}>
              <InputNumber style={{ width: '100%' }} min={1} /></Form.Item></Col>
            <Col span={6}><Form.Item name="quantity_unit" label="单位"><Select options={[{ value: '瓶', label: '瓶' }, { value: '箱', label: '箱' }]} /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="counterparty" label="对方"><Input placeholder="窜货方/被清理方" /></Form.Item></Col>
            <Col span={12}><Form.Item name="original_customer_id" label="原始客户">
              <Select allowClear showSearch optionFilterProp="label" placeholder="外流时选"
                options={customers.map((c: any) => ({ value: c.id, label: c.name }))} />
            </Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="barcode" label="条码"><Input /></Form.Item></Col>
            <Col span={8}><Form.Item name="batch_no" label="批次"><Input /></Form.Item></Col>
            <Col span={8}><Form.Item name="found_location" label="发现地点"><Input /></Form.Item></Col>
          </Row>
          <Divider>价格与损益</Divider>
          <Row gutter={16}>
            {['outflow_malicious', 'outflow_nonmalicious'].includes(watchType) && (
              <Col span={8}><Form.Item name="purchase_price" label="回收价/瓶" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} prefix="¥" min={0} precision={2} /></Form.Item></Col>
            )}
            {watchType === 'outflow_transfer' && (
              <Col span={16}><div style={{ padding: 8, background: '#fff1f0', borderRadius: 6, marginBottom: 12 }}>转码金额: <Text strong style={{ color: '#ff4d4f' }}>¥{(salePrice * bottleCount).toLocaleString()}</Text> ({salePrice}/瓶 × {bottleCount}瓶)</div></Col>
            )}
            {watchType === 'inflow_resell' && (<>
              <Col span={6}><Form.Item name="purchase_price" label="买入价/瓶" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} prefix="¥" min={0} precision={2} /></Form.Item></Col>
              <Col span={6}><Form.Item name="resell_price" label="回售价/瓶" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} prefix="¥" min={0} precision={2} /></Form.Item></Col>
            </>)}
            {watchType === 'inflow_transfer' && (
              <Col span={8}><Form.Item name="purchase_price" label="买入价/瓶" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} prefix="¥" min={0} precision={2} /></Form.Item></Col>
            )}
            {watchDirection === 'outflow' && <Col span={8}><Form.Item name="penalty_amount" label="厂家罚款"><InputNumber style={{ width: '100%' }} prefix="¥" min={0} precision={2} /></Form.Item></Col>}
            {watchDirection === 'inflow' && <Col span={8}><Form.Item name="reward_amount" label="厂家奖励"><InputNumber style={{ width: '100%' }} prefix="¥" min={0} precision={2} /></Form.Item></Col>}
          </Row>
          <div style={{ padding: 12, background: liveProfit >= 0 ? '#f6ffed' : '#fff1f0', borderRadius: 8, textAlign: 'center', marginBottom: 12 }}>
            <span style={{ color: '#888', fontSize: 12 }}>预估盈亏</span>
            <div style={{ fontSize: 22, fontWeight: 700, color: liveProfit >= 0 ? '#52c41a' : '#ff4d4f' }}>{liveProfit >= 0 ? '+' : ''}¥{liveProfit.toLocaleString()}</div>
          </div>
          <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      {/* 详情 */}
      <Modal title={`案件 ${detailRecord?.case_no ?? ''}`} open={!!detailRecord} onCancel={() => setDetailRecord(null)} footer={null} width={600}>
        {detailRecord && (
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="方向"><Tag color={detailRecord.direction === 'outflow' ? 'red' : 'green'}>{detailRecord.direction === 'outflow' ? '我方外流' : '主动清理'}</Tag></Descriptions.Item>
            <Descriptions.Item label="类型"><Tag color={TYPE_COLOR[detailRecord.case_type]}>{TYPE_LABEL[detailRecord.case_type]}</Tag></Descriptions.Item>
            <Descriptions.Item label="商品">{detailRecord.product?.name ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="数量">{detailRecord.quantity}{detailRecord.quantity_unit}</Descriptions.Item>
            <Descriptions.Item label="对方">{detailRecord.counterparty ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="地点">{detailRecord.found_location ?? '-'}</Descriptions.Item>
            {detailRecord.purchase_price > 0 && <Descriptions.Item label="回收/买入价">¥{detailRecord.purchase_price}/瓶</Descriptions.Item>}
            {detailRecord.resell_price > 0 && <Descriptions.Item label="回售价">¥{detailRecord.resell_price}/瓶</Descriptions.Item>}
            {detailRecord.transfer_amount > 0 && <Descriptions.Item label="转码金额">¥{detailRecord.transfer_amount.toLocaleString()}</Descriptions.Item>}
            {detailRecord.penalty_amount > 0 && <Descriptions.Item label="罚款"><Text type="danger">¥{detailRecord.penalty_amount.toLocaleString()}</Text></Descriptions.Item>}
            {detailRecord.reward_amount > 0 && <Descriptions.Item label="奖励"><Text type="success">¥{detailRecord.reward_amount.toLocaleString()}</Text></Descriptions.Item>}
            <Descriptions.Item label="盈亏" span={2}>
              <Text strong style={{ fontSize: 16, color: detailRecord.profit_loss >= 0 ? '#52c41a' : '#ff4d4f' }}>
                {(detailRecord.profit_loss || 0) >= 0 ? '+' : ''}¥{Number(detailRecord.profit_loss || 0).toLocaleString()}
              </Text>
              {detailRecord.no_rebate && <Tag color="orange" style={{ marginLeft: 8 }}>不计回款</Tag>}
            </Descriptions.Item>
            {detailRecord.notes && <Descriptions.Item label="备注" span={2}>{detailRecord.notes}</Descriptions.Item>}
          </Descriptions>
        )}
      </Modal>

      {/* 执行弹窗 */}
      <Modal title={`执行 — ${execRecord?.case_no ?? ''}`} open={!!execRecord && execRecord.status === 'approved'} width={550}
        onOk={() => executeMut.mutate()} onCancel={() => setExecRecord(null)}
        confirmLoading={executeMut.isPending} okText="确认执行" destroyOnHidden>
        {execRecord && (() => {
          const t = execRecord.case_type;
          const qty = execRecord.quantity;
          const u = execRecord.quantity_unit;
          const needsPay = ['outflow_malicious', 'outflow_nonmalicious', 'outflow_transfer', 'inflow_transfer'].includes(t);
          const needsInbound = ['outflow_malicious', 'outflow_nonmalicious', 'inflow_transfer'].includes(t);
          const needsOutbound = t === 'inflow_resell';
          const needsReceive = t === 'inflow_resell';
          return (
            <>
              <div style={{ marginBottom: 12, padding: 10, background: '#f0f5ff', borderRadius: 6, fontSize: 13 }}>
                <Tag color={TYPE_COLOR[t]}>{TYPE_LABEL[t]}</Tag>
                商品: <Text strong>{execRecord.product?.name ?? '-'}</Text> ×{qty}{u}
                &nbsp;· 盈亏: <Text strong style={{ color: (execRecord.profit_loss || 0) >= 0 ? '#52c41a' : '#ff4d4f' }}>¥{Number(execRecord.profit_loss || 0).toLocaleString()}</Text>
              </div>

              {needsPay && (
                <div style={{ marginBottom: 12 }}>
                  <Text strong>💰 {t === 'outflow_transfer' ? `罚款 ¥${execRecord.penalty_amount}` : `付款 ¥${(execRecord.purchase_price * qty).toLocaleString()} (${execRecord.purchase_price}/瓶×${qty})`} → 从品牌现金账户扣款</Text>
                </div>
              )}
              {needsReceive && (
                <div style={{ marginBottom: 12 }}>
                  <Text strong style={{ color: '#52c41a' }}>💰 收款 ¥{(execRecord.resell_price * qty).toLocaleString()} → 品牌现金账户入账</Text>
                </div>
              )}
              {needsInbound && (
                <div style={{ marginBottom: 12 }}>
                  <Text strong>📦 入库 → {t === 'outflow_malicious' ? backupWh?.name ?? '备用库' : mainWh?.name ?? '主仓'}</Text>
                  {t === 'outflow_nonmalicious' && <Tag color="orange" style={{ marginLeft: 8 }}>不计回款</Tag>}
                </div>
              )}
              {needsInbound && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ marginBottom: 8 }}><Text strong style={{ color: '#ff4d4f' }}>📱 扫码入库（必须）</Text></div>
                  <Input placeholder="扫描条码后回车" value={scanBarcode}
                    onChange={e => setScanBarcode(e.target.value)}
                    onPressEnter={() => { if (scanBarcode.trim()) { setScannedCodes(p => p.includes(scanBarcode.trim()) ? p : [...p, scanBarcode.trim()]); setScanBarcode(''); } }}
                    autoFocus />
                  {scannedCodes.length > 0 && (
                    <div style={{ marginTop: 6, fontSize: 12, color: '#52c41a' }}>
                      已扫 {scannedCodes.length} 个：{scannedCodes.slice(-5).join('、')}{scannedCodes.length > 5 ? '...' : ''}
                      <a style={{ marginLeft: 8, color: '#ff4d4f' }} onClick={() => setScannedCodes([])}>清空</a>
                    </div>
                  )}
                  {scannedCodes.length === 0 && <div style={{ color: '#ff4d4f', fontSize: 12, marginTop: 4 }}>请至少扫描一个条码，用于后期货品追溯</div>}
                </div>
              )}
              {needsOutbound && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ marginBottom: 8 }}><Text strong style={{ color: '#ff4d4f' }}>📦 扫码出库（必须） → {backupWh?.name ?? '备用库'}</Text></div>
                  <Input placeholder="扫描条码后回车" value={scanBarcode}
                    onChange={e => setScanBarcode(e.target.value)}
                    onPressEnter={() => { if (scanBarcode.trim()) { setScannedCodes(p => p.includes(scanBarcode.trim()) ? p : [...p, scanBarcode.trim()]); setScanBarcode(''); } }}
                    autoFocus />
                  {scannedCodes.length > 0 && <div style={{ marginTop: 6, fontSize: 12, color: '#52c41a' }}>已扫 {scannedCodes.length} 个</div>}
                  {scannedCodes.length === 0 && <div style={{ color: '#ff4d4f', fontSize: 12, marginTop: 4 }}>请至少扫描一个条码</div>}
                </div>
              )}

              <div style={{ marginBottom: 8 }}><Text strong>📎 付款/操作凭证</Text></div>
              <Upload listType="picture-card" accept=".jpg,.jpeg,.png,.webp" multiple
                customRequest={async ({ file, onSuccess, onError }: any) => {
                  const fd = new FormData(); fd.append('file', file);
                  try { const { data } = await api.post('/uploads', fd); setPayVouchers(p => [...p, data.url]); onSuccess(data); } catch (e) { onError(e); }
                }}><div><PlusOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>凭证</div></div></Upload>
            </>
          );
        })()}
      </Modal>

      {/* B1上传物流弹窗 */}
      <Modal title={`上传物流 — ${execRecord?.case_no ?? ''}`} open={!!execRecord && execRecord.status === 'processing'}
        onOk={() => { if (!logisticsUrls.length) { message.warning('请上传物流单据'); return; } logisticsMut.mutate(execRecord!.id); }}
        onCancel={() => setExecRecord(null)} okText="提交" destroyOnHidden>
        <Upload listType="picture-card" accept=".jpg,.jpeg,.png,.webp" multiple
          customRequest={async ({ file, onSuccess, onError }: any) => {
            const fd = new FormData(); fd.append('file', file);
            try { const { data } = await api.post('/uploads', fd); setLogisticsUrls(p => [...p, data.url]); onSuccess(data); } catch (e) { onError(e); }
          }}><div><PlusOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>物流单据</div></div></Upload>
      </Modal>
    </>
  );
}

export default InspectionList;
