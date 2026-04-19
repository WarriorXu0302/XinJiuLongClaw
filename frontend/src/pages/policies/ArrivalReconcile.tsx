import { useState } from 'react';
import { Button, Card, Checkbox, Divider, Form, Input, InputNumber, message, Modal, Select, Space, Table, Tag, Typography, Upload } from 'antd';
import { PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';
import type { PolicyRequest, RequestItem } from './policyTypes';
import { BENEFIT_LABEL } from './policyTypes';

const { Text } = Typography;

const FLOW_TYPE_LABEL: Record<string, { label: string; color: string }> = {
  arrival: { label: '到账', color: 'green' },
  reward: { label: '奖励', color: 'gold' },
  deduction: { label: '扣款/罚款', color: 'red' },
  payment: { label: '支付货款', color: 'orange' },
  adjustment: { label: '调整', color: 'blue' },
};

function ArrivalReconcile() {
  const queryClient = useQueryClient();
  const { brandId, params } = useBrandFilter();
  // 导入匹配
  const [matchOpen, setMatchOpen] = useState(false);
  const [matched, setMatched] = useState<any[]>([]);
  const [salaryMatched, setSalaryMatched] = useState<any[]>([]);
  const [unmatched, setUnmatched] = useState<any[]>([]);
  // 手动入账
  const [manualOpen, setManualOpen] = useState(false);
  const [manualForm] = Form.useForm();
  const [selectedItems, setSelectedItems] = useState<string[]>([]);

  // 等待到账的政策项
  const { data = [], isLoading } = useQuery<PolicyRequest[]>({
    queryKey: ['policy-requests-reconcile', brandId],
    queryFn: () => api.get('/policies/requests', { params: { ...params, has_items: true, status: 'approved', limit: 200 } }).then(r => r.data),
  });
  const waitingItems = data.flatMap(r => (r.request_items ?? []).filter(i => i.fulfill_status === 'applied').map(i => ({
    ...i, _customer: r.customer?.name ?? r.order?.customer?.name ?? '-', _orderNo: r.order?.order_no ?? '-', _requestId: r.id, _source: r.request_source,
  })));

  // F类账户流水（从accounts fund-flows拉取）
  const { data: accounts = [] } = useQuery<any[]>({
    queryKey: ['accounts-select', brandId],
    queryFn: () => api.get('/accounts', { params }).then(r => r.data),
  });
  const fClassAcc = accounts.find((a: any) => a.account_type === 'f_class' && a.level === 'project');

  const { data: fFlows = [] } = useQuery<any[]>({
    queryKey: ['f-class-flows', fClassAcc?.id],
    queryFn: () => api.get('/accounts/fund-flows', { params: { account_id: fClassAcc?.id, limit: 50 } }).then(r => r.data),
    enabled: !!fClassAcc,
  });

  // 导入Excel匹配（政策 + 工资补贴 一次提交）
  const confirmArrivalMut = useMutation({
    mutationFn: async (payload: { items: any[]; salary_items: any[] }) => (await api.post('/policies/requests/confirm-arrival', {
      items: payload.items.map(m => ({ item_id: m.item_id, arrived_amount: m.income, billcode: m.billcode })),
      salary_items: payload.salary_items.map(s => ({ brand_id: s.brand_id, period: s.period, arrived_amount: s.income, billcode: s.billcode })),
    })).data,
    onSuccess: (res) => {
      message.success(res.detail);
      setMatchOpen(false); setMatched([]); setSalaryMatched([]); setUnmatched([]);
      queryClient.invalidateQueries({ queryKey: ['policy-requests-reconcile'] });
      queryClient.invalidateQueries({ queryKey: ['f-class-flows'] });
      queryClient.invalidateQueries({ queryKey: ['subsidies'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  // 手动确认到账（单个）
  const manualArrivalMut = useMutation({
    mutationFn: async (item: any) => (await api.post('/policies/requests/confirm-arrival', {
      items: [{ item_id: item.id, arrived_amount: item.total_value, billcode: null }],
      salary_items: [],
    })).data,
    onSuccess: () => { message.success('已确认到账'); queryClient.invalidateQueries({ queryKey: ['policy-requests-reconcile'] }); },
  });

  // 手动入账（正/负）→ 直接操作F类账户
  const manualEntryMut = useMutation({
    mutationFn: async (values: any) => {
      if (!fClassAcc) throw new Error('该品牌没有F类账户');
      const amount = values.amount;
      const flowType = amount >= 0 ? 'credit' : 'debit';
      const absAmount = Math.abs(amount);
      // 记录F类账户流水
      await api.post('/accounts/fund-flows', {
        account_id: fClassAcc.id,
        flow_type: flowType,
        amount: absAmount,
        related_type: values.entry_type,
        notes: values.notes || `${FLOW_TYPE_LABEL[values.entry_type]?.label ?? values.entry_type}: ${values.notes ?? ''}`,
      });
      // 如果关联了等待到账的政策项，批量确认到账
      if (selectedItems.length > 0 && amount > 0) {
        const items = selectedItems.map(id => {
          const item = waitingItems.find(i => i.id === id);
          return { item_id: id, arrived_amount: item?.total_value ?? 0, billcode: null };
        });
        await api.post('/policies/requests/confirm-arrival', { items, salary_items: [] });
      }
      return { amount };
    },
    onSuccess: () => {
      message.success('入账成功');
      setManualOpen(false); manualForm.resetFields(); setSelectedItems([]);
      queryClient.invalidateQueries({ queryKey: ['f-class-flows'] });
      queryClient.invalidateQueries({ queryKey: ['policy-requests-reconcile'] });
      queryClient.invalidateQueries({ queryKey: ['accounts-select'] });
    },
    onError: (e: any) => message.error(e?.message || e?.response?.data?.detail || '操作失败'),
  });

  const handleUploadExcel = async (file: File) => {
    if (!brandId) { message.warning('请先选择品牌'); return; }
    const formData = new FormData(); formData.append('file', file);
    try {
      const { data } = await api.post(`/policies/requests/match-arrival?brand_id=${brandId}`, formData, { headers: { 'Content-Type': 'multipart/form-data' } });
      setMatched(data.matched ?? []);
      setSalaryMatched(data.salary_matched ?? []);
      setUnmatched(data.unmatched ?? []);
      setMatchOpen(true);
      const totalMatch = (data.matched?.length ?? 0) + (data.salary_matched?.length ?? 0);
      if (totalMatch === 0) message.info(`共${data.total_rows}行，无匹配项`);
    } catch (e: any) { message.error(e?.response?.data?.detail ?? '解析失败'); }
  };

  const waitingCols: ColumnsType<any> = [
    { title: '来源', dataIndex: '_source', width: 60, render: (v: string) => <Tag color={v === 'f_class' ? 'purple' : 'blue'}>{v === 'f_class' ? 'F类' : '订单'}</Tag> },
    { title: '客户/说明', dataIndex: '_customer', width: 100 },
    { title: '类型', dataIndex: 'benefit_type', width: 80, render: (v: string) => <Tag>{BENEFIT_LABEL[v] ?? v}</Tag> },
    { title: '名称', dataIndex: 'name', width: 100 },
    { title: '方案号', dataIndex: 'scheme_no', width: 130, render: (v: string) => v || <Text type="warning">无</Text> },
    { title: '申请金额', dataIndex: 'standard_total', width: 80, align: 'right', render: (v: number) => `¥${(v ?? 0).toLocaleString()}` },
    { title: '操作', key: 'action', width: 100, render: (_, item) => (
      <Button size="small" onClick={() => Modal.confirm({ title: '确认到账', content: `"${item.name}" ¥${item.total_value.toLocaleString()} 确认厂家已到账？`, onOk: () => manualArrivalMut.mutate(item) })}>确认到账</Button>
    ) },
  ];

  const flowCols: ColumnsType<any> = [
    { title: '流水号', dataIndex: 'flow_no', width: 140 },
    { title: '类型', dataIndex: 'flow_type', width: 60, render: (v: string) => v === 'credit' ? <Tag color="green">入</Tag> : <Tag color="red">出</Tag> },
    { title: '金额', dataIndex: 'amount', width: 90, align: 'right', render: (v: number, r: any) => <Text style={{ color: r.flow_type === 'credit' ? '#52c41a' : '#ff4d4f' }}>{r.flow_type === 'credit' ? '+' : '-'}¥{Number(v).toLocaleString()}</Text> },
    { title: '余额', dataIndex: 'balance_after', width: 90, align: 'right', render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '来源', dataIndex: 'related_type', width: 80, render: (v: string) => FLOW_TYPE_LABEL[v]?.label ?? v ?? '-' },
    { title: '备注', dataIndex: 'notes', width: 200, ellipsis: true },
    { title: '时间', dataIndex: 'created_at', width: 120, render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>到账对账</h2>
        <Space>
          <Upload accept=".xls,.xlsx" showUploadList={false} beforeUpload={(file) => { handleUploadExcel(file); return false; }}>
            <Button icon={<UploadOutlined />} disabled={!brandId}>导入厂家到账</Button>
          </Upload>
          <Button type="primary" icon={<PlusOutlined />} disabled={!brandId} onClick={() => { manualForm.resetFields(); setSelectedItems([]); setManualOpen(true); }}>手动入账</Button>
        </Space>
      </div>

      {/* F类账户概览 */}
      {fClassAcc && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space size={32}>
            <div><Text type="secondary">F类账户</Text> <Text strong style={{ fontSize: 18, color: '#1890ff' }}>¥{Number(fClassAcc.balance).toLocaleString()}</Text></div>
            <div><Text type="secondary">等待到账</Text> <Text strong style={{ fontSize: 18, color: '#fa8c16' }}>{waitingItems.length}项 ¥{waitingItems.reduce((s, i) => s + i.total_value, 0).toLocaleString()}</Text></div>
          </Space>
        </Card>
      )}

      {/* 等待到账列表 */}
      <h4>等待到账 ({waitingItems.length})</h4>
      <Table columns={waitingCols} dataSource={waitingItems} rowKey="id" size="small" loading={isLoading}
        pagination={waitingItems.length > 10 ? { pageSize: 10 } : false} style={{ marginBottom: 24 }} />

      {/* F类账户流水 */}
      {fClassAcc && (
        <>
          <h4>F类账户流水</h4>
          <Table columns={flowCols} dataSource={fFlows} rowKey="id" size="small" pagination={{ pageSize: 10 }} />
        </>
      )}

      {!brandId && <Card style={{ textAlign: 'center', padding: 32 }}><Text type="secondary">请先选择品牌</Text></Card>}

      {/* 导入匹配弹窗 */}
      <Modal title="厂家到账匹配" open={matchOpen} width={780}
        onOk={() => {
          const total = matched.length + salaryMatched.length;
          if (total === 0) { message.warning('没有匹配项'); return; }
          confirmArrivalMut.mutate({ items: matched, salary_items: salaryMatched });
        }}
        onCancel={() => { setMatchOpen(false); setMatched([]); setSalaryMatched([]); setUnmatched([]); }}
        confirmLoading={confirmArrivalMut.isPending}
        okText={`确认到账 (政策 ${matched.length} / 工资补贴 ${salaryMatched.length})`} destroyOnHidden>
        {matched.length > 0 && (
          <>
            <h4 style={{ color: '#52c41a' }}>政策到账 ({matched.length})</h4>
            <Table size="small" pagination={false} rowKey="item_id" dataSource={matched} columns={[
              { title: '政策项', dataIndex: 'item_name', width: 100 },
              { title: '方案号', dataIndex: 'scheme_no', width: 140 },
              { title: '单据号', dataIndex: 'billcode', width: 140 },
              { title: '到账金额', dataIndex: 'income', width: 100, align: 'right', render: (v: number) => <Text style={{ color: '#52c41a' }}>¥{v.toLocaleString()}</Text> },
            ]} />
          </>
        )}
        {salaryMatched.length > 0 && (
          <>
            <h4 style={{ color: '#722ed1', marginTop: 12 }}>工资补贴到账 ({salaryMatched.length})</h4>
            <Table size="small" pagination={false} rowKey={(r) => `${r.brand_id}|${r.period}`} dataSource={salaryMatched} columns={[
              { title: '周期', dataIndex: 'period', width: 100 },
              { title: '应收合计', dataIndex: 'expected_amount', width: 120, align: 'right', render: (v: number) => `¥${v.toLocaleString()}` },
              { title: '到账金额', dataIndex: 'income', width: 120, align: 'right', render: (v: number) => <Text style={{ color: '#722ed1' }}>¥{v.toLocaleString()}</Text> },
              { title: '单据号', dataIndex: 'billcode', width: 140 },
              { title: '摘要', dataIndex: 'memo', ellipsis: true },
            ]} />
          </>
        )}
        {unmatched.length > 0 && (
          <>
            <h4 style={{ color: '#999', marginTop: 12 }}>未匹配 ({unmatched.length})</h4>
            <Table size="small" pagination={false} rowKey="billcode" dataSource={unmatched} columns={[
              { title: '单据号', dataIndex: 'billcode', width: 140 },
              { title: '方案号', dataIndex: 'pronumber', width: 140 },
              { title: '摘要', dataIndex: 'memo', width: 200, ellipsis: true },
              { title: '金额', dataIndex: 'income', width: 100, align: 'right', render: (v: number) => `¥${v.toLocaleString()}` },
            ]} />
          </>
        )}
      </Modal>

      {/* 手动入账弹窗 */}
      <Modal title="手动入账/扣款" open={manualOpen} width={600}
        onOk={() => manualForm.validateFields().then(v => manualEntryMut.mutate(v))}
        onCancel={() => { setManualOpen(false); manualForm.resetFields(); setSelectedItems([]); }}
        confirmLoading={manualEntryMut.isPending} okText="确认" destroyOnHidden>
        <Form form={manualForm} layout="vertical" initialValues={{ entry_type: 'arrival' }}>
          <Form.Item name="entry_type" label="类型" rules={[{ required: true }]}>
            <Select options={[
              { value: 'arrival', label: '到账（正数入账）' },
              { value: 'reward', label: '奖励（正数入账，可划拨利润）' },
              { value: 'deduction', label: '扣款/罚款（负数，算亏损）' },
              { value: 'payment', label: '支付货款（负数）' },
              { value: 'adjustment', label: '调整（正负均可）' },
            ]} />
          </Form.Item>
          <Form.Item name="amount" label="金额（正数=入账，负数=扣款）" rules={[{ required: true }]}
            extra="到账/奖励填正数，扣款/罚款/支付货款填负数">
            <InputNumber style={{ width: '100%' }} precision={2} prefix="¥" />
          </Form.Item>
          <Form.Item name="notes" label="备注说明" rules={[{ required: true }]}>
            <Input.TextArea rows={2} placeholder="如：2025年Q1青花郎奖励 / 窜货罚款 / 支付货款PO-xxx" />
          </Form.Item>

          {/* 关联等待到账的政策项（可选） */}
          {waitingItems.length > 0 && (
            <>
              <Divider>关联政策项（可选 — 勾选后自动确认到账）</Divider>
              <div style={{ maxHeight: 200, overflow: 'auto' }}>
                {waitingItems.map(item => (
                  <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', borderBottom: '1px solid #f5f5f5' }}>
                    <Checkbox checked={selectedItems.includes(item.id)} onChange={e => {
                      if (e.target.checked) setSelectedItems(p => [...p, item.id]);
                      else setSelectedItems(p => p.filter(id => id !== item.id));
                    }} />
                    <Tag>{BENEFIT_LABEL[item.benefit_type] ?? item.benefit_type}</Tag>
                    <span style={{ flex: 1 }}>{item.name}</span>
                    <Text type="secondary">¥{item.total_value.toLocaleString()}</Text>
                  </div>
                ))}
              </div>
            </>
          )}
        </Form>
      </Modal>
    </>
  );
}

export default ArrivalReconcile;
