import { useState } from 'react';
import { Button, Card, Col, Form, Input, InputNumber, message, Modal, Progress, Row, Select, Space, Table, Tag, Typography, Upload } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

const { Text } = Typography;

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  pending: { color: 'orange', label: '待审批' }, approved: { color: 'blue', label: '待出库' },
  applied: { color: 'cyan', label: '待物流' }, fulfilled: { color: 'green', label: '待归档' },
  settled: { color: 'default', label: '已归档' }, rejected: { color: 'red', label: '已驳回' },
};

function PaymentProgress() {
  const queryClient = useQueryClient();
  const { brandId, params } = useBrandFilter();
  const [shareOpen, setShareOpen] = useState(false);
  const [shareForm] = Form.useForm();
  const [voucherUrls, setVoucherUrls] = useState<string[]>([]);
  // 出库弹窗
  const [outboundOpen, setOutboundOpen] = useState(false);
  const [outboundRecord, setOutboundRecord] = useState<any>(null);
  const [barcodeInput, setBarcodeInput] = useState('');
  // 物流弹窗
  const [logisticsOpen, setLogisticsOpen] = useState(false);
  const [logisticsRecord, setLogisticsRecord] = useState<any>(null);
  const [logisticsForm] = Form.useForm();
  const [logisticsUrls, setLogisticsUrls] = useState<string[]>([]);

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['share-records'] });
    queryClient.invalidateQueries({ queryKey: ['ptm-flows'] });
    queryClient.invalidateQueries({ queryKey: ['accounts-select'] });
  };

  const { data: accounts = [] } = useQuery<any[]>({
    queryKey: ['accounts-select', brandId],
    queryFn: () => api.get('/accounts', { params }).then(r => extractItems(r.data)),
  });
  const ptmAcc = accounts.find((a: any) => a.account_type === 'payment_to_mfr');

  const { data: flows = [] } = useQuery<any[]>({
    queryKey: ['ptm-flows', ptmAcc?.id],
    queryFn: () => api.get('/accounts/fund-flows', { params: { account_id: ptmAcc?.id, limit: 100 } }).then(r => extractItems(r.data)),
    enabled: !!ptmAcc,
  });

  const { data: shares = [] } = useQuery<any[]>({
    queryKey: ['share-records', brandId],
    queryFn: () => api.get('/expense-claims', { params: { claim_type: 'share_out', brand_id: brandId, limit: 50 } }).then(r => extractItems(r.data)),
    enabled: !!brandId,
  });

  const { data: products = [] } = useQuery<any[]>({
    queryKey: ['products-select', brandId],
    queryFn: () => api.get('/products', { params: brandId ? params : { limit: 200 } }).then(r => extractItems(r.data)),
  });

  const { data: warehouses = [] } = useQuery<any[]>({
    queryKey: ['warehouses-select', brandId],
    queryFn: () => api.get('/inventory/warehouses', { params }).then(r => extractItems(r.data)),
    enabled: !!brandId,
  });
  const mainWh = warehouses.find((w: any) => w.warehouse_type === 'main');

  const storageKey = `ptm_target_${brandId}_${new Date().getFullYear()}`;
  const [target, setTarget] = useState<number>(() => Number(localStorage.getItem(storageKey) || 0));
  const [editTarget, setEditTarget] = useState(false);
  const [tempTarget, setTempTarget] = useState(target);
  const saveTarget = () => { localStorage.setItem(storageKey, String(tempTarget)); setTarget(tempTarget); setEditTarget(false); };

  const completed = ptmAcc ? Number(ptmAcc.balance) : 0;
  const pct = target > 0 ? Math.min(100, Math.round(Math.max(0, completed) / target * 100)) : 0;
  const remaining = target - completed;

  // 创建分货单
  const createShareMut = useMutation({
    mutationFn: async (values: any) => {
      return (await api.post('/expense-claims', {
        claim_type: 'share_out', brand_id: brandId,
        title: `分货给 ${values.counterparty}`,
        // description存商品和数量信息
        description: JSON.stringify({ product_id: values.product_id, quantity: values.quantity, quantity_unit: values.quantity_unit }),
        amount: values.amount,
        voucher_urls: voucherUrls.length > 0 ? voucherUrls : null,
        notes: values.counterparty,
      })).data;
    },
    onSuccess: () => { message.success('分货单已创建，请到审批中心审批'); setShareOpen(false); shareForm.resetFields(); setVoucherUrls([]); invalidateAll(); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  // 出库
  const outboundMut = useMutation({
    mutationFn: async () => {
      if (!outboundRecord || !mainWh) throw new Error('缺少信息');
      if (!barcodeInput.trim()) throw new Error('请扫描条码，用于货品追溯');
      let desc: any = {};
      try { desc = JSON.parse(outboundRecord.description || '{}'); } catch {}
      const productId = desc.product_id;
      const qty = desc.quantity || 1;
      if (!productId) throw new Error('分货单缺少商品信息');
      // 直接从主仓出库
      await api.post('/inventory/direct-outbound', {
        product_id: productId, warehouse_id: mainWh.id,
        quantity: qty, notes: `分货出库: ${outboundRecord.title}`,
        barcode: barcodeInput || undefined,
      });
      // 更新分货状态
      await api.post(`/expense-claims/${outboundRecord.id}/apply`, {});
    },
    onSuccess: () => { message.success('出库成功'); setOutboundOpen(false); setBarcodeInput(''); invalidateAll(); },
    onError: (e: any) => message.error(e?.message || e?.response?.data?.detail || '出库失败'),
  });

  // 上传物流
  const logisticsMut = useMutation({
    mutationFn: async () => {
      await api.post(`/expense-claims/${logisticsRecord.id}/fulfill`, {
        receipt_urls: logisticsUrls.length > 0 ? logisticsUrls : null,
      });
    },
    onSuccess: () => { message.success('物流信息已上传'); setLogisticsOpen(false); setLogisticsUrls([]); invalidateAll(); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '操作失败'),
  });

  // 归档
  const archiveMut = useMutation({
    mutationFn: (id: string) => api.post(`/expense-claims/${id}/settle`),
    onSuccess: () => { message.success('已归档'); invalidateAll(); },
  });

  // 解析分货单里的商品信息
  const parseDesc = (desc: string) => {
    try { const d = JSON.parse(desc || '{}'); const p = products.find((pp: any) => pp.id === d.product_id); return `${p?.name ?? '商品'} ×${d.quantity ?? 0}${d.quantity_unit ?? '瓶'}`; } catch { return '-'; }
  };

  const flowCols: ColumnsType<any> = [
    { title: '流水号', dataIndex: 'flow_no', width: 120 },
    { title: '', dataIndex: 'flow_type', width: 35, render: (v: string) => v === 'credit' ? <Tag color="green">+</Tag> : <Tag color="red">-</Tag> },
    { title: '金额', dataIndex: 'amount', width: 90, align: 'right', render: (v: number, r: any) => <Text style={{ color: r.flow_type === 'credit' ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>{r.flow_type === 'credit' ? '+' : '-'}¥{Number(v).toLocaleString()}</Text> },
    { title: '余额', dataIndex: 'balance_after', width: 90, align: 'right', render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '来源', dataIndex: 'related_type', width: 80, render: (v: string) => ({ purchase_payment: '采购', transfer_deduction: '被转码', transfer_credit: '转码入库', share_out: '分货', share_out_income: '分货收入' })[v] ?? v ?? '-' },
    { title: '备注', dataIndex: 'notes', width: 160, ellipsis: true },
    { title: '时间', dataIndex: 'created_at', width: 100, render: (v: string) => v ? new Date(v).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }) : '-' },
  ];

  const shareCols: ColumnsType<any> = [
    { title: '编号', dataIndex: 'claim_no', width: 110 },
    { title: '对方', dataIndex: 'notes', width: 90 },
    { title: '商品', key: 'product', width: 120, render: (_, r) => parseDesc(r.description) },
    { title: '金额', dataIndex: 'amount', width: 80, align: 'right', render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '状态', dataIndex: 'status', width: 70, render: (v: string) => { const m = STATUS_MAP[v]; return m ? <Tag color={m.color}>{m.label}</Tag> : <Tag>{v}</Tag>; } },
    { title: '操作', key: 'act', width: 110, render: (_, r) => (
      <Space size="small">
        {r.status === 'pending' && <Tag color="orange">审批中心</Tag>}
        {r.status === 'approved' && <a onClick={() => { setOutboundRecord(r); setBarcodeInput(''); setOutboundOpen(true); }}>扫码出库</a>}
        {r.status === 'applied' && <a onClick={() => { setLogisticsRecord(r); setLogisticsUrls([]); setLogisticsOpen(true); }}>上传物流</a>}
        {r.status === 'fulfilled' && <a onClick={() => archiveMut.mutate(r.id)}>归档</a>}
        {r.status === 'settled' && <Tag>已归档</Tag>}
      </Space>
    ) },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>回款进度</h2>
        <Button type="primary" icon={<PlusOutlined />} disabled={!brandId} onClick={() => { shareForm.resetFields(); setVoucherUrls([]); setShareOpen(true); }}>录入分货</Button>
      </div>

      {!brandId ? <Card style={{ textAlign: 'center', padding: 32 }}><Text type="secondary">请先选择品牌</Text></Card> : (
        <>
          <Card style={{ marginBottom: 16 }}>
            <Row gutter={24} align="middle">
              <Col span={6} style={{ textAlign: 'center' }}>
                <div style={{ color: '#888', fontSize: 12 }}>年度任务</div>
                {editTarget ? (
                  <Space><InputNumber value={tempTarget} onChange={v => setTempTarget(v ?? 0)} min={0} style={{ width: 130 }} prefix="¥" /><Button size="small" type="primary" onClick={saveTarget}>保存</Button></Space>
                ) : (
                  <div><Text strong style={{ fontSize: 20 }}>¥{target.toLocaleString()}</Text><a style={{ marginLeft: 8, fontSize: 12 }} onClick={() => { setTempTarget(target); setEditTarget(true); }}>改</a></div>
                )}
              </Col>
              <Col span={6} style={{ textAlign: 'center' }}><div style={{ color: '#888', fontSize: 12 }}>已完成</div><Text strong style={{ fontSize: 20, color: completed >= 0 ? '#1890ff' : '#ff4d4f' }}>¥{completed.toLocaleString()}</Text></Col>
              <Col span={6} style={{ textAlign: 'center' }}><div style={{ color: '#888', fontSize: 12 }}>剩余</div><Text strong style={{ fontSize: 20, color: remaining > 0 ? '#fa8c16' : '#52c41a' }}>¥{remaining.toLocaleString()}</Text></Col>
              <Col span={6} style={{ textAlign: 'center' }}><Progress type="circle" percent={pct} size={80} strokeColor={pct >= 100 ? '#52c41a' : '#1890ff'} /></Col>
            </Row>
          </Card>

          {shares.length > 0 && (<><h4>分货记录</h4><Table columns={shareCols} dataSource={shares} rowKey="id" size="small" pagination={false} style={{ marginBottom: 16 }} /></>)}

          <h4>回款明细</h4>
          <Table columns={flowCols} dataSource={flows} rowKey="id" size="small" pagination={{ pageSize: 15 }} />
        </>
      )}

      {/* 新建分货 */}
      <Modal title="录入分货" open={shareOpen} width={500}
        onOk={() => shareForm.validateFields().then(v => createShareMut.mutate(v))}
        onCancel={() => { setShareOpen(false); shareForm.resetFields(); setVoucherUrls([]); }}
        confirmLoading={createShareMut.isPending} okText="提交" destroyOnHidden>
        <Form form={shareForm} layout="vertical">
          <Form.Item name="counterparty" label="对方经销商" rules={[{ required: true }]}><Input placeholder="经销商名称" /></Form.Item>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="product_id" label="商品" rules={[{ required: true }]}>
              <Select showSearch optionFilterProp="label" options={products.map((p: any) => ({ value: p.id, label: `${p.name} (${p.bottles_per_case ?? 6}瓶/箱)` }))} />
            </Form.Item></Col>
            <Col span={6}><Form.Item name="quantity" label="数量" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} min={1} /></Form.Item></Col>
            <Col span={6}><Form.Item name="quantity_unit" label="单位" initialValue="箱"><Select options={[{ value: '箱', label: '箱' }, { value: '瓶', label: '瓶' }]} /></Form.Item></Col>
          </Row>
          <Form.Item name="amount" label="分货金额" rules={[{ required: true }]} extra="对方打给我们的金额">
            <InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" />
          </Form.Item>
          <Form.Item label="对方付款凭证" required>
            <Upload listType="picture-card" accept=".jpg,.jpeg,.png,.webp" multiple
              customRequest={async ({ file, onSuccess, onError }: any) => {
                const fd = new FormData(); fd.append('file', file);
                try { const { data } = await api.post('/uploads', fd); setVoucherUrls(p => [...p, data.url]); onSuccess(data); } catch (e) { onError(e); }
              }}><div><PlusOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>上传</div></div></Upload>
          </Form.Item>
          <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      {/* 扫码出库弹窗 */}
      <Modal title={`扫码出库 — ${outboundRecord?.title ?? ''}`} open={outboundOpen}
        onOk={() => outboundMut.mutate()} onCancel={() => setOutboundOpen(false)}
        confirmLoading={outboundMut.isPending} okText="确认出库" destroyOnHidden>
        {outboundRecord && (
          <div style={{ marginBottom: 12, padding: 10, background: '#f0f5ff', borderRadius: 6, fontSize: 13 }}>
            商品: <Text strong>{parseDesc(outboundRecord.description)}</Text>
            &nbsp;· 出库仓库: <Text strong>{mainWh?.name ?? '主仓'}</Text>
          </div>
        )}
        <Input size="large" placeholder="扫描条码后回车" value={barcodeInput}
          onChange={e => setBarcodeInput(e.target.value)} onPressEnter={() => { if (!barcodeInput.trim()) { message.warning('请扫描条码'); return; } outboundMut.mutate(); }} autoFocus
          prefix={<span>📦</span>} />
        {!barcodeInput.trim() && <div style={{ color: '#ff4d4f', fontSize: 12, marginTop: 4 }}>请扫描条码，用于货品追溯</div>}
      </Modal>

      {/* 上传物流弹窗 */}
      <Modal title={`上传物流信息 — ${logisticsRecord?.title ?? ''}`} open={logisticsOpen}
        onOk={() => { if (!logisticsUrls.length) { message.warning('请上传物流单据'); return; } logisticsMut.mutate(); }}
        onCancel={() => { setLogisticsOpen(false); setLogisticsUrls([]); }}
        confirmLoading={logisticsMut.isPending} okText="提交" destroyOnHidden>
        <Upload listType="picture-card" accept=".jpg,.jpeg,.png,.webp" multiple
          customRequest={async ({ file, onSuccess, onError }: any) => {
            const fd = new FormData(); fd.append('file', file);
            try { const { data } = await api.post('/uploads', fd); setLogisticsUrls(p => [...p, data.url]); onSuccess(data); } catch (e) { onError(e); }
          }}><div><PlusOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>物流单据</div></div></Upload>
        <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>上传快递单/物流回执照片</div>
      </Modal>
    </>
  );
}

export default PaymentProgress;
