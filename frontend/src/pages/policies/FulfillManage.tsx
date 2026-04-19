import { useState } from 'react';
import { Button, Card, Image, message, Modal, Space, Table, Tag, Typography, Upload } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';
import { useAuthStore } from '../../stores/authStore';
import type { PolicyRequest, RequestItem } from './policyTypes';
import { BENEFIT_LABEL, PAYER_LABEL } from './policyTypes';

const { Text } = Typography;

const STATUS_LABEL: Record<string, string> = { arrived: '待兑付', fulfilled: '待确认', settled: '已归档' };
const STATUS_COLOR: Record<string, string> = { arrived: 'blue', fulfilled: 'green', settled: 'cyan' };

function FulfillManage() {
  const queryClient = useQueryClient();
  const { brandId, params } = useBrandFilter();
  const roles = useAuthStore((s) => s.roles) ?? [];
  const canConfirm = roles.some(r => ['admin', 'boss', 'finance'].includes(r));
  const [voucherOpen, setVoucherOpen] = useState(false);
  const [voucherItem, setVoucherItem] = useState<RequestItem | null>(null);
  const [voucherRequestId, setVoucherRequestId] = useState('');
  const [voucherUrls, setVoucherUrls] = useState<string[]>([]);
  const [previewItem, setPreviewItem] = useState<RequestItem | null>(null);

  const { data = [], isLoading } = useQuery<PolicyRequest[]>({
    queryKey: ['policy-requests-fulfill', brandId],
    queryFn: () => api.get('/policies/requests', { params: { ...params, has_items: true, status: 'approved', limit: 200 } }).then(r => r.data),
  });

  // 只取有 arrived/fulfilled/settled 项的
  const relevantStatuses = ['arrived', 'fulfilled', 'settled'];
  const requests = data.filter(r => r.request_items?.some(i => relevantStatuses.includes(i.fulfill_status)));

  const tableData = requests.flatMap(r =>
    (r.request_items ?? []).filter(i => relevantStatuses.includes(i.fulfill_status)).map(i => ({
      ...i,
      _customer: r.customer?.name ?? r.order?.customer?.name ?? '-',
      _orderNo: r.order?.order_no ?? '-',
      _requestId: r.id,
    }))
  );

  const countArrived = tableData.filter(i => i.fulfill_status === 'arrived').length;
  const countFulfilled = tableData.filter(i => i.fulfill_status === 'fulfilled').length;
  const countSettled = tableData.filter(i => i.fulfill_status === 'settled').length;

  const submitVoucherMut = useMutation({
    mutationFn: async () => {
      return (await api.post(`/policies/requests/${voucherRequestId}/submit-voucher`, {
        item_id: voucherItem!.id, voucher_urls: voucherUrls,
      })).data;
    },
    onSuccess: () => { message.success('凭证已提交，等待财务确认'); setVoucherOpen(false); setVoucherUrls([]); queryClient.invalidateQueries({ queryKey: ['policy-requests-fulfill'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '提交失败'),
  });

  const confirmMut = useMutation({
    mutationFn: async ({ requestId, itemId }: { requestId: string; itemId: string }) => {
      return (await api.post(`/policies/requests/${requestId}/confirm-fulfill`, { item_id: itemId })).data;
    },
    onSuccess: () => { message.success('已确认归档'); queryClient.invalidateQueries({ queryKey: ['policy-requests-fulfill'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '确认失败'),
  });

  type TableItem = RequestItem & { _customer: string; _orderNo: string; _requestId: string };

  const columns: ColumnsType<TableItem> = [
    { title: '客户', dataIndex: '_customer', width: 90 },
    { title: '订单', dataIndex: '_orderNo', width: 130, ellipsis: true },
    { title: '类型', dataIndex: 'benefit_type', width: 80, render: (v: string) => <Tag>{BENEFIT_LABEL[v] ?? v}</Tag> },
    { title: '名称', dataIndex: 'name', width: 100 },
    { title: '到账金额', dataIndex: 'arrival_amount', width: 90, align: 'right', render: (v: number) => v > 0 ? <Text style={{ color: '#52c41a' }}>¥{v.toLocaleString()}</Text> : '-' },
    { title: '实际花费', dataIndex: 'actual_cost', width: 80, align: 'right', render: (v: number) => v > 0 ? `¥${v.toLocaleString()}` : '-' },
    { title: '盈亏', dataIndex: 'profit_loss', width: 75, align: 'right', render: (v: number) => v !== 0 ? <Text style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f' }}>{v >= 0 ? '+' : ''}¥{v.toLocaleString()}</Text> : '-' },
    { title: '垫付方', dataIndex: 'advance_payer_type', width: 60, render: (v: string) => PAYER_LABEL[v] ?? '-' },
    { title: '凭证', key: 'voucher', width: 60, render: (_, r) => r.voucher_urls?.length ? <a onClick={() => setPreviewItem(r)}>查看</a> : '-' },
    { title: '状态', dataIndex: 'fulfill_status', width: 70, render: (v: string) => <Tag color={STATUS_COLOR[v]}>{STATUS_LABEL[v] ?? v}</Tag> },
    { title: '操作', key: 'action', width: 130, render: (_, item) => (
      <Space size="small">
        {item.fulfill_status === 'arrived' && (
          <Button size="small" type="primary" onClick={() => { setVoucherItem(item); setVoucherRequestId(item._requestId); setVoucherUrls([]); setVoucherOpen(true); }}>
            兑付(上传凭证)
          </Button>
        )}
        {item.fulfill_status === 'fulfilled' && canConfirm && (
          <Button size="small" style={{ color: '#52c41a', borderColor: '#52c41a' }}
            onClick={() => confirmMut.mutate({ requestId: item._requestId, itemId: item.id })}>财务确认</Button>
        )}
        {item.fulfill_status === 'fulfilled' && !canConfirm && <Text type="secondary">待财务确认</Text>}
        {item.fulfill_status === 'settled' && <Tag color="cyan">已归档</Tag>}
      </Space>
    ) },
  ];

  return (
    <>
      <h2 style={{ marginBottom: 16 }}>兑付管理</h2>

      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <Card size="small" style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ color: '#888', fontSize: 12 }}>待兑付</div>
          <div style={{ fontSize: 20, fontWeight: 600, color: '#1890ff' }}>{countArrived}</div>
        </Card>
        <Card size="small" style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ color: '#888', fontSize: 12 }}>待财务确认</div>
          <div style={{ fontSize: 20, fontWeight: 600, color: '#52c41a' }}>{countFulfilled}</div>
        </Card>
        <Card size="small" style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ color: '#888', fontSize: 12 }}>已归档</div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>{countSettled}</div>
        </Card>
      </div>

      {tableData.length === 0 && !isLoading ? (
        <Card style={{ textAlign: 'center', padding: 32 }}>
          <Text type="secondary">{brandId ? '暂无待兑付项，到账对账后这里会自动显示' : '请先选择品牌'}</Text>
        </Card>
      ) : (
        <Table columns={columns} dataSource={tableData} rowKey="id" size="middle" loading={isLoading} pagination={{ pageSize: 20 }} />
      )}

      {/* 上传凭证弹窗 */}
      <Modal title={`兑付凭证 — ${voucherItem ? BENEFIT_LABEL[voucherItem.benefit_type] ?? voucherItem.name : ''}`}
        open={voucherOpen}
        onOk={() => { if (voucherUrls.length === 0) { message.warning('请上传至少一张凭证'); return; } submitVoucherMut.mutate(); }}
        onCancel={() => { setVoucherOpen(false); setVoucherUrls([]); }}
        confirmLoading={submitVoucherMut.isPending} okText="提交凭证" destroyOnHidden>
        {voucherItem && (
          <div style={{ marginBottom: 12, padding: 10, background: '#f6ffed', borderRadius: 6, fontSize: 13 }}>
            到账: <Text strong style={{ color: '#52c41a' }}>¥{(voucherItem.arrival_amount ?? 0).toLocaleString()}</Text>
            &nbsp;· 垫付方: <Text strong>{PAYER_LABEL[voucherItem.advance_payer_type ?? ''] ?? '未指定'}</Text>
            &nbsp;· 兑付给垫付方，提供凭证
          </div>
        )}
        <Upload listType="picture-card" accept=".jpg,.jpeg,.png,.webp" multiple
          customRequest={async ({ file, onSuccess, onError }: any) => {
            const fd = new FormData(); fd.append('file', file);
            try { const { data } = await api.post('/uploads', fd, { headers: { 'Content-Type': 'multipart/form-data' } }); setVoucherUrls(prev => [...prev, data.url]); onSuccess(data); }
            catch (e) { onError(e); }
          }}>
          <div><PlusOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>上传凭证</div></div>
        </Upload>
        <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>转账截图、收据照片等</div>
      </Modal>

      {/* 凭证预览弹窗 */}
      <Modal title="兑付凭证" open={!!previewItem} onCancel={() => setPreviewItem(null)} footer={null}>
        {previewItem?.voucher_urls && (
          <Image.PreviewGroup>
            <Space wrap>{previewItem.voucher_urls.map((url, i) => <Image key={i} src={url} width={120} style={{ borderRadius: 4 }} />)}</Space>
          </Image.PreviewGroup>
        )}
      </Modal>
    </>
  );
}

export default FulfillManage;
