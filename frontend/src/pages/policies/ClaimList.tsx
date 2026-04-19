import { useState } from 'react';
import { Button, Checkbox, Form, Input, InputNumber, message, Modal, Select, Table, Tag, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

const { Text } = Typography;

interface PolicyClaim {
  id: string; claim_no: string; manufacturer_id: string | null; brand_id: string | null;
  claim_batch_period: string; claim_amount: number; approved_total_amount: number;
  settled_amount: number; unsettled_amount: number; status: string; created_at: string;
}

interface Settlement { id: string; settlement_no: string; settlement_amount: number; unsettled_amount: number; }

interface RequestItem {
  id: string; name: string; benefit_type: string; quantity: number; quantity_unit?: string;
  total_value: number; fulfill_status: string; settled_amount: number; _requestId: string;
}

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  draft: { color: 'default', label: '草稿' }, submitted: { color: 'blue', label: '已提交' },
  partially_settled: { color: 'orange', label: '部分核销' }, settled: { color: 'green', label: '已核销' },
  rejected: { color: 'red', label: '已驳回' },
};

function ClaimList() {
  const queryClient = useQueryClient();
  const { brandId, params } = useBrandFilter();
  const [allocForm] = Form.useForm();
  const [allocOpen, setAllocOpen] = useState(false);
  const [activeClaim, setActiveClaim] = useState<PolicyClaim | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [selectedItems, setSelectedItems] = useState<string[]>([]);

  const { data: claims = [], isLoading } = useQuery<PolicyClaim[]>({
    queryKey: ['policy-claims', brandId],
    queryFn: () => api.get('/policies/claims', { params }).then(r => r.data),
  });

  const { data: settlements = [] } = useQuery<Settlement[]>({
    queryKey: ['settlements'],
    queryFn: () => api.get('/manufacturer-settlements').then(r => r.data),
    enabled: allocOpen,
  });

  // Fetch approved policy requests with fulfilled items for creating new claims
  const { data: policyRequests = [] } = useQuery<any[]>({
    queryKey: ['policy-requests-for-claim', brandId],
    queryFn: () => api.get('/policies/requests', { params: { ...params, status: 'approved', has_items: true, limit: 200 } }).then(r => r.data),
    enabled: createOpen,
  });

  // Flatten fulfilled items that haven't been fully settled
  const claimableItems: RequestItem[] = policyRequests
    .filter((pr: any) => pr.status === 'approved' && pr.request_items?.length > 0)
    .flatMap((pr: any) => pr.request_items
      .filter((ri: any) => (ri.fulfill_status === 'fulfilled' || ri.fulfill_status === 'applied') && ri.settled_amount < ri.total_value)
      .map((ri: any) => ({ ...ri, _requestId: pr.id }))
    );

  const { data: suppliers = [] } = useQuery<any[]>({
    queryKey: ['suppliers-select'],
    queryFn: () => api.get('/suppliers', { params: { type: 'manufacturer' } }).then(r => r.data),
    enabled: createOpen,
  });

  const allocMutation = useMutation({
    mutationFn: (values: any) => api.post(`/manufacturer-settlements/${values.settlement_id}/allocation-confirm`, {
      claim_id: values.claim_id, allocated_amount: values.allocated_amount, confirmed_by: 'current_user',
    }),
    onSuccess: () => { message.success('核销分配成功'); setAllocOpen(false); allocForm.resetFields(); queryClient.invalidateQueries({ queryKey: ['policy-claims'] }); },
    onError: (err: any) => message.error(err?.response?.data?.detail ?? '核销分配失败'),
  });

  const createClaimMutation = useMutation({
    mutationFn: async (values: any) => {
      const items = claimableItems.filter(i => selectedItems.includes(i.id)).map(i => ({
        source_request_item_id: i.id,
        declared_amount: i.total_value - i.settled_amount,
      }));
      const { data } = await api.post('/policies/claims', {
        manufacturer_id: values.manufacturer_id || null,
        brand_id: brandId || null,
        claim_batch_period: values.claim_batch_period,
        notes: values.notes,
        items,
      });
      return data;
    },
    onSuccess: () => {
      message.success('申报单已创建');
      setCreateOpen(false); createForm.resetFields(); setSelectedItems([]);
      queryClient.invalidateQueries({ queryKey: ['policy-claims'] });
    },
    onError: (err: any) => message.error(err?.response?.data?.detail ?? '创建失败'),
  });

  const claimColumns: ColumnsType<PolicyClaim> = [
    { title: '申报编号', dataIndex: 'claim_no', width: 180 },
    { title: '申报期', dataIndex: 'claim_batch_period', width: 100 },
    { title: '申报金额', dataIndex: 'claim_amount', width: 110, align: 'right', render: (v: number) => `¥${Number(v).toFixed(2)}` },
    { title: '已核销', dataIndex: 'settled_amount', width: 110, align: 'right', render: (v: number) => `¥${Number(v).toFixed(2)}` },
    { title: '未核销', dataIndex: 'unsettled_amount', width: 110, align: 'right', render: (v: number) => <span style={{ color: v > 0 ? '#faad14' : undefined }}>¥{Number(v).toFixed(2)}</span> },
    { title: '状态', dataIndex: 'status', width: 90, render: (s: string) => { const info = STATUS_MAP[s] ?? { color: 'default', label: s }; return <Tag color={info.color}>{info.label}</Tag>; } },
    { title: '时间', dataIndex: 'created_at', width: 160, render: (v: string) => v?.replace('T', ' ').slice(0, 19) },
    { title: '操作', key: 'action', width: 100, render: (_, record) => (
      <Button type="link" size="small" disabled={record.unsettled_amount <= 0} onClick={() => { setActiveClaim(record); setAllocOpen(true); }}>核销分配</Button>
    ) },
  ];

  const selectedTotal = claimableItems.filter(i => selectedItems.includes(i.id)).reduce((s, i) => s + (i.total_value - i.settled_amount), 0);

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>兑付申报</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setCreateOpen(true); setSelectedItems([]); createForm.resetFields(); }}>新建申报</Button>
      </div>

      <Table<PolicyClaim> columns={claimColumns} dataSource={claims} rowKey="id" loading={isLoading} pagination={{ pageSize: 20 }} />

      {/* 核销分配弹窗 */}
      <Modal title={`核销分配 — ${activeClaim?.claim_no ?? ''}`} open={allocOpen}
        onOk={() => allocForm.validateFields().then(v => allocMutation.mutate({ ...v, claim_id: activeClaim!.id }))}
        onCancel={() => { setAllocOpen(false); allocForm.resetFields(); }}
        confirmLoading={allocMutation.isPending} okText="确认分配">
        {activeClaim && <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>申报金额 ¥{Number(activeClaim.claim_amount).toFixed(2)}，未核销 ¥{Number(activeClaim.unsettled_amount).toFixed(2)}</Text>}
        <Form form={allocForm} layout="vertical">
          <Form.Item name="settlement_id" label="选择到账记录" rules={[{ required: true }]}>
            <Select placeholder="选择厂家到账单" showSearch optionFilterProp="label"
              options={settlements.filter(s => s.unsettled_amount > 0).map(s => ({ value: s.id, label: `${s.settlement_no}（余 ¥${Number(s.unsettled_amount).toFixed(2)}）` }))} />
          </Form.Item>
          <Form.Item name="allocated_amount" label="分配金额" rules={[{ required: true }, { type: 'number', min: 0.01, message: '金额必须大于0' }]}>
            <InputNumber style={{ width: '100%' }} precision={2} min={0.01} max={activeClaim?.unsettled_amount} prefix="¥" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新建申报弹窗 */}
      <Modal title="新建兑付申报" open={createOpen} width={700}
        onOk={() => createForm.validateFields().then(v => createClaimMutation.mutate(v))}
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); setSelectedItems([]); }}
        confirmLoading={createClaimMutation.isPending} okText={`提交申报（¥${selectedTotal.toFixed(2)}）`}>
        <Form form={createForm} layout="vertical">
          <Form.Item name="claim_batch_period" label="申报期" rules={[{ required: true, message: '如 2026-04' }]}>
            <Input placeholder="2026-04" />
          </Form.Item>
          <Form.Item name="manufacturer_id" label="厂家">
            <Select allowClear showSearch optionFilterProp="label" placeholder="选择厂家"
              options={suppliers.map((s: any) => ({ value: s.id, label: s.name }))} />
          </Form.Item>
          <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>

        <Text strong style={{ display: 'block', marginBottom: 8 }}>选择已兑付的政策项：</Text>
        {claimableItems.length === 0 ? (
          <Text type="secondary">暂无可申报的已兑付政策项</Text>
        ) : (
          <div style={{ maxHeight: 300, overflow: 'auto' }}>
            {claimableItems.map(item => (
              <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', borderBottom: '1px solid #f0f0f0' }}>
                <Checkbox checked={selectedItems.includes(item.id)} onChange={(e) => {
                  setSelectedItems(prev => e.target.checked ? [...prev, item.id] : prev.filter(id => id !== item.id));
                }} />
                <Tag>{item.benefit_type}</Tag>
                <span style={{ flex: 1 }}>{item.name} ×{item.quantity}{item.quantity_unit || '次'}</span>
                <Text>¥{(item.total_value - item.settled_amount).toFixed(2)}</Text>
                <Tag color={item.fulfill_status === 'fulfilled' ? 'green' : 'blue'}>{item.fulfill_status === 'fulfilled' ? '已兑付' : '已申请'}</Tag>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </>
  );
}

export default ClaimList;
