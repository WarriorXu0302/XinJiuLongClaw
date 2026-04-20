import { useState } from 'react';
import { Button, Descriptions, Empty, Form, Image, message, Modal, Select, Space, Tabs, Table, Tag, Typography, Upload } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, DollarOutlined, UploadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

const { Title } = Typography;

interface Expense { id: string; expense_no: string; amount: string; description?: string; applicant?: { name: string }; status: string; created_at: string; }
interface PaymentRequest { id: string; request_no: string; amount: string; payee_type?: string; payee_employee?: { name: string }; payee_customer?: { name: string }; payee_other_name?: string; status: string; created_at: string; payable_account_id?: string; }
interface Account { id: string; name: string; account_type: string; balance: number; brand_name?: string; }

function FinanceApproval() {
  const queryClient = useQueryClient();
  const [payExpenseId, setPayExpenseId] = useState<string | null>(null);
  const [payForm] = Form.useForm();
  const [payPR, setPayPR] = useState<any | null>(null);  // 当前要兑付的 PaymentRequest
  const [prPayAccount, setPrPayAccount] = useState<string | undefined>();
  const [prVoucherUrls, setPrVoucherUrls] = useState<string[]>([]);
  const [prSignedUrls, setPrSignedUrls] = useState<string[]>([]);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailData, setDetailData] = useState<any>(null);
  const [detailTitle, setDetailTitle] = useState('');
  const showDetail = (title: string, data: any) => { setDetailTitle(title); setDetailData(data); setDetailOpen(true); };

  const { brandId, params } = useBrandFilter();

  // Pending purchase orders
  const { data: pendingPOs = [] } = useQuery<any[]>({
    queryKey: ['pending-pos', brandId],
    queryFn: () => api.get('/purchase-orders', { params: { ...params, status: undefined } }).then(r => r.data.filter((po: any) => po.status === 'pending')),
    refetchInterval: 5000,
  });
  const approvePOMut = useMutation({
    mutationFn: (id: string) => api.post(`/purchase-orders/${id}/approve`),
    onSuccess: (res) => { message.success(res.data.message); invalidate(); queryClient.invalidateQueries({ queryKey: ['pending-pos'] }); queryClient.invalidateQueries({ queryKey: ['account-summary'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '审批失败'),
  });
  const rejectPOMut = useMutation({
    mutationFn: (id: string) => api.post(`/purchase-orders/${id}/reject`),
    onSuccess: () => { message.success('已驳回'); queryClient.invalidateQueries({ queryKey: ['pending-pos'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '驳回失败'),
  });

  // Pending transfers
  // Pending financing repayments
  const { data: pendingFinancing = [] } = useQuery<any[]>({
    queryKey: ['pending-financing-repayments'],
    queryFn: () => api.get('/financing-orders/pending-repayments').then(r => r.data),
    refetchInterval: 5000,
  });
  const approveFinancingMut = useMutation({
    mutationFn: (id: string) => api.post(`/financing-orders/repayments/${id}/approve`),
    onSuccess: (res) => {
      const d = res.data;
      if (d.status === 'rejected') { message.warning(d.message); } else { message.success(d.message); }
      invalidate(); queryClient.invalidateQueries({ queryKey: ['pending-financing-repayments'] }); queryClient.invalidateQueries({ queryKey: ['account-summary'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '审批失败'),
  });
  const rejectFinancingMut = useMutation({
    mutationFn: (id: string) => api.post(`/financing-orders/repayments/${id}/reject`),
    onSuccess: () => { message.success('已驳回'); queryClient.invalidateQueries({ queryKey: ['pending-financing-repayments'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '驳回失败'),
  });

  const { data: pendingTransfers = [] } = useQuery<any[]>({
    queryKey: ['pending-transfers'],
    queryFn: () => api.get('/accounts/pending-transfers').then(r => r.data),
    refetchInterval: 5000,
  });
  const approveTransferMut = useMutation({
    mutationFn: (id: string) => api.post(`/accounts/transfers/${id}/approve`),
    onSuccess: (res) => { message.success(res.data.message); invalidate(); queryClient.invalidateQueries({ queryKey: ['pending-transfers'] }); queryClient.invalidateQueries({ queryKey: ['account-summary'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '审批失败'),
  });
  const rejectTransferMut = useMutation({
    mutationFn: (id: string) => api.post(`/accounts/transfers/${id}/reject`),
    onSuccess: () => { message.success('已驳回'); queryClient.invalidateQueries({ queryKey: ['pending-transfers'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '驳回失败'),
  });

  const { data: expenses = [], isLoading: expLoading } = useQuery<Expense[]>({
    queryKey: ['expenses-approval', brandId],
    queryFn: () => api.get('/expenses', { params: { ...params, limit: 100 } }).then(r => r.data),
    refetchInterval: 5000,
  });
  const { data: paymentRequests = [], isLoading: prLoading } = useQuery<PaymentRequest[]>({
    queryKey: ['payment-requests-approval', brandId],
    queryFn: () => api.get('/payment-requests', { params }).then(r => r.data),
    refetchInterval: 5000,
  });
  const { data: accounts = [] } = useQuery<Account[]>({
    queryKey: ['accounts-select', brandId],
    queryFn: () => api.get('/accounts', { params }).then(r => r.data),
  });

  // Pending inspection cases
  const { data: pendingCases = [] } = useQuery<any[]>({
    queryKey: ['pending-inspection-cases', brandId],
    queryFn: () => api.get('/inspection-cases', { params: { ...params, status: 'pending' } }).then(r => r.data),
    refetchInterval: 5000,
  });
  const approveCaseMut = useMutation({
    mutationFn: (id: string) => api.put(`/inspection-cases/${id}`, { status: 'approved' }),
    onSuccess: () => { message.success('已审批'); queryClient.invalidateQueries({ queryKey: ['pending-inspection-cases'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '审批失败'),
  });
  // Pending share-out claims
  const { data: pendingShares = [] } = useQuery<any[]>({
    queryKey: ['pending-shares'],
    queryFn: () => api.get('/expense-claims', { params: { claim_type: 'share_out', status: 'pending', limit: 50 } }).then(r => r.data),
    refetchInterval: 5000,
  });
  const approveShareMut = useMutation({
    mutationFn: (id: string) => api.post(`/expense-claims/${id}/approve`),
    onSuccess: () => { message.success('分货已审批'); queryClient.invalidateQueries({ queryKey: ['pending-shares'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '审批失败'),
  });
  const rejectShareMut = useMutation({
    mutationFn: (id: string) => api.post(`/expense-claims/${id}/reject`),
    onSuccess: () => { message.success('已驳回'); queryClient.invalidateQueries({ queryKey: ['pending-shares'] }); },
  });

  const rejectCaseMut = useMutation({
    mutationFn: (id: string) => api.put(`/inspection-cases/${id}`, { status: 'closed' }),
    onSuccess: () => { message.success('已驳回'); queryClient.invalidateQueries({ queryKey: ['pending-inspection-cases'] }); },
  });

  // Pending salary approvals
  const { data: pendingSalaries = [] } = useQuery<any[]>({
    queryKey: ['pending-salaries'],
    queryFn: () => api.get('/payroll/salary-records', { params: { status: 'pending_approval' } }).then(r => r.data),
    refetchInterval: 5000,
  });
  const approveSalaryMut = useMutation({
    mutationFn: ({ id, approved, reject_reason }: { id: string; approved: boolean; reject_reason?: string }) =>
      api.post(`/payroll/salary-records/${id}/approve`, { approved, reject_reason }),
    onSuccess: (r: any) => { message.success(r.data.detail); queryClient.invalidateQueries({ queryKey: ['pending-salaries'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '操作失败'),
  });

  // Pending sales target approvals
  const { data: pendingTargets = [] } = useQuery<any[]>({
    queryKey: ['pending-targets'],
    queryFn: () => api.get('/sales-targets', { params: { status: 'pending_approval' } }).then(r => r.data),
    refetchInterval: 5000,
  });

  // Orders pending 确认收款（delivered + 全款才出现）
  const { data: deliveredOrders = [] } = useQuery<any[]>({
    queryKey: ['pending-confirm-payment', brandId],
    queryFn: () => api.get('/orders', {
      params: { ...params, status: 'delivered', payment_status: 'fully_paid', limit: 200 },
    }).then(r => r.data),
    refetchInterval: 5000,
  });
  const confirmOrderPayMut = useMutation({
    mutationFn: (id: string) => api.post(`/orders/${id}/confirm-payment`),
    onSuccess: () => {
      message.success('已确认收款');
      queryClient.invalidateQueries({ queryKey: ['pending-confirm-payment'] });
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });
  // Pending leave requests
  const { data: pendingLeaves = [] } = useQuery<any[]>({
    queryKey: ['pending-leaves'],
    queryFn: () => api.get('/attendance/leave-requests', { params: { status: 'pending' } }).then(r => r.data),
    refetchInterval: 5000,
  });
  const approveLeaveMut = useMutation({
    mutationFn: ({ id, approved, reason }: { id: string; approved: boolean; reason?: string }) =>
      api.post(`/attendance/leave-requests/${id}/approve`, { approved, reject_reason: reason }),
    onSuccess: () => { message.success('已处理'); queryClient.invalidateQueries({ queryKey: ['pending-leaves'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '操作失败'),
  });

  const approveTargetMut = useMutation({
    mutationFn: ({ id, approved, reject_reason }: { id: string; approved: boolean; reject_reason?: string }) =>
      api.post(`/sales-targets/${id}/approve`, { approved, reject_reason }),
    onSuccess: () => { message.success('操作成功'); queryClient.invalidateQueries({ queryKey: ['pending-targets'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '操作失败'),
  });

  const pendingExpenses = expenses.filter(e => e.status === 'pending');
  const approvedExpenses = expenses.filter(e => e.status === 'approved');
  const pendingPRs = paymentRequests.filter(p => p.status === 'pending');
  const approvedPRs = paymentRequests.filter(p => p.status === 'approved');

  const invalidate = () => { queryClient.invalidateQueries({ queryKey: ['expenses-approval'] }); queryClient.invalidateQueries({ queryKey: ['payment-requests-approval'] }); queryClient.invalidateQueries({ queryKey: ['account-summary'] }); };

  const approveExpMut = useMutation({ mutationFn: (id: string) => api.post(`/expenses/${id}/approve`), onSuccess: () => { message.success('审批通过'); invalidate(); }, onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败') });
  const rejectExpMut = useMutation({ mutationFn: (id: string) => api.post(`/expenses/${id}/reject`), onSuccess: () => { message.success('已驳回'); invalidate(); }, onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败') });
  const payExpMut = useMutation({
    mutationFn: ({ id, payment_account_id }: { id: string; payment_account_id: string }) =>
      api.post(`/expenses/${id}/pay`, { payment_account_id }),
    onSuccess: () => { message.success('付款成功'); setPayExpenseId(null); payForm.resetFields(); invalidate(); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '付款失败'),
  });
  const approvePRMut = useMutation({ mutationFn: (id: string) => api.put(`/payment-requests/${id}`, { status: 'approved' }), onSuccess: () => { message.success('审批通过'); invalidate(); }, onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败') });
  const confirmPayMut = useMutation({
    mutationFn: ({ id, payment_account_id, payment_voucher_urls, signed_photo_urls }: any) =>
      api.post(`/payment-requests/${id}/confirm-payment`, {
        payment_account_id, payment_voucher_urls, signed_photo_urls,
      }),
    onSuccess: () => {
      message.success('已确认付款');
      setPayPR(null); setPrVoucherUrls([]); setPrSignedUrls([]); setPrPayAccount(undefined);
      invalidate();
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  const projectAccounts = accounts.filter((a: any) => a.level === 'project');

  // 报销列 — 待审批（只审批，付款在报销管理页）
  const pendingExpCols: ColumnsType<Expense> = [
    { title: '编号', dataIndex: 'expense_no', width: 150 },
    { title: '申请人', key: 'app', width: 80, render: (_, r) => r.applicant?.name ?? '-' },
    { title: '金额', dataIndex: 'amount', width: 100, align: 'right', render: (v: string) => `¥${Number(v).toFixed(0)}` },
    { title: '说明', dataIndex: 'description', width: 200, ellipsis: true },
    { title: '时间', dataIndex: 'created_at', width: 140, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
    { title: '操作', key: 'act', width: 200, render: (_, r) => (
      <Space>
        <a onClick={() => showDetail(`报销 ${r.expense_no}`, r)}>查看</a>
        <Button size="small" type="primary" icon={<CheckCircleOutlined />} onClick={() => approveExpMut.mutate(r.id)}>通过</Button>
        <Button size="small" danger icon={<CloseCircleOutlined />} onClick={() => rejectExpMut.mutate(r.id)}>驳回</Button>
      </Space>
    )},
  ];

  // 垫付返还列
  const prCols: ColumnsType<PaymentRequest> = [
    { title: '编号', dataIndex: 'request_no', width: 150 },
    { title: '收款人', key: 'payee', width: 100, render: (_, r) => r.payee_employee?.name ?? r.payee_customer?.name ?? '-' },
    { title: '类型', dataIndex: 'payee_type', width: 70, render: (v: string) => <Tag>{v === 'employee' ? '员工' : v === 'customer' ? '客户' : v}</Tag> },
    { title: '金额', dataIndex: 'amount', width: 100, align: 'right', render: (v: string) => `¥${Number(v).toFixed(2)}` },
    { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => <Tag color={v === 'approved' ? 'blue' : v === 'paid' ? 'green' : 'orange'}>{v}</Tag> },
    { title: '操作', key: 'act', width: 170, render: (_, r) => (
      <Space>
        <a onClick={() => showDetail(`垫付返还 ${r.request_no}`, r)}>查看</a>
        {r.status === 'pending' && <Button size="small" type="primary" onClick={() => approvePRMut.mutate(r.id)}>审批</Button>}
        {r.status === 'approved' && <Button size="small" type="primary" style={{ background: '#52c41a' }} onClick={() => {
          setPayPR(r);
          setPrPayAccount(r.payable_account_id);
          setPrVoucherUrls([]);
          setPrSignedUrls([]);
        }}>确认付款</Button>}
      </Space>
    )},
  ];

  return (
    <>
      <Title level={4}>财务审批</Title>

      <Tabs items={[
        {
          key: 'po',
          label: <span>采购审批 <Tag color="red">{pendingPOs.length}</Tag></span>,
          children: pendingPOs.length === 0 ? <Empty description="暂无待审采购单" /> :
            <Table
              columns={[
                { title: '采购单号', dataIndex: 'po_no', width: 150 },
                { title: '供应商', key: 'sup', width: 120, render: (_: any, r: any) => r.supplier?.name ?? '-' },
                { title: '商品', key: 'items', width: 180, ellipsis: true, render: (_: any, r: any) => r.items?.map((it: any) => `${it.product?.name ?? ''} ×${it.quantity}${it.quantity_unit || '箱'}`).join(', ') || '-' },
                { title: '总额', dataIndex: 'total_amount', width: 100, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString()}` },
                { title: '现金', dataIndex: 'cash_amount', width: 90, align: 'right' as const, render: (v: number) => Number(v) > 0 ? `¥${Number(v).toLocaleString()}` : '-' },
                { title: 'F类', dataIndex: 'f_class_amount', width: 90, align: 'right' as const, render: (v: number) => Number(v) > 0 ? `¥${Number(v).toLocaleString()}` : '-' },
                { title: '凭证', dataIndex: 'voucher_url', width: 60, render: (v: string) => v ? <a onClick={() => Modal.info({ title: '付款凭证', width: 500, content: <img src={v} alt="凭证" style={{ maxWidth: '100%' }} /> })}>查看</a> : '-' },
                { title: '操作', key: 'act', width: 150, render: (_: any, r: any) => (
                  <Space>
                    <a onClick={() => showDetail(`采购单 ${r.po_no}`, r)}>查看</a>
                    <Button size="small" type="primary" onClick={() => Modal.confirm({
                      title: '审批采购单', width: 500,
                      content: (<div>
                        <p>单号：{r.po_no} | 总额：¥{Number(r.total_amount).toLocaleString()}</p>
                        <p>现金：¥{Number(r.cash_amount).toLocaleString()} | F类：¥{Number(r.f_class_amount).toLocaleString()}</p>
                        {r.voucher_url && <img src={r.voucher_url} alt="凭证" style={{ maxWidth: '100%', maxHeight: 300, marginTop: 8, border: '1px solid #d9d9d9', borderRadius: 4 }} />}
                        <p style={{ marginTop: 12, color: '#ff4d4f' }}>确认审批并从账户扣款？</p>
                      </div>),
                      onOk: () => approvePOMut.mutate(r.id),
                    })}>通过</Button>
                    <Button size="small" danger onClick={() => rejectPOMut.mutate(r.id)}>驳回</Button>
                  </Space>
                )},
              ] as any}
              dataSource={pendingPOs} rowKey="id" size="middle" pagination={false}
            />,
        },
        {
          key: 'exp-pending',
          label: <span>报销待审 <Tag color="red">{pendingExpenses.length}</Tag></span>,
          children: pendingExpenses.length === 0 ? <Empty description="暂无待审报销" /> :
            <Table columns={pendingExpCols} dataSource={pendingExpenses} rowKey="id" size="middle" pagination={false} />,
        },
        {
          key: 'pr',
          label: <span>垫付返还 <Tag color="red">{pendingPRs.length + approvedPRs.length}</Tag></span>,
          children: (pendingPRs.length + approvedPRs.length) === 0 ? <Empty description="暂无待处理" /> :
            <Table columns={prCols} dataSource={[...pendingPRs, ...approvedPRs]} rowKey="id" size="middle" pagination={false} />,
        },
        {
          key: 'transfer',
          label: <span>拨款审批 <Tag color="red">{pendingTransfers.length}</Tag></span>,
          children: pendingTransfers.length === 0 ? <Empty description="暂无待审拨款" /> :
            <Table
              columns={[
                { title: '流水号', dataIndex: 'flow_no', width: 150 },
                { title: '转出', dataIndex: 'from_account', width: 120 },
                { title: '转入', dataIndex: 'to_account', width: 140 },
                { title: '品牌', dataIndex: 'to_brand', width: 80, render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-' },
                { title: '金额', dataIndex: 'amount', width: 110, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString()}` },
                { title: '备注', dataIndex: 'notes', width: 200, ellipsis: true },
                { title: '操作', key: 'act', width: 190, render: (_: any, r: any) => (
                  <Space>
                    <a onClick={() => showDetail(`拨款 ${r.flow_no}`, r)}>查看</a>
                    <Button size="small" type="primary" onClick={() => approveTransferMut.mutate(r.id)}>通过</Button>
                    <Button size="small" danger onClick={() => rejectTransferMut.mutate(r.id)}>驳回</Button>
                  </Space>
                )},
              ] as any}
              dataSource={pendingTransfers}
              rowKey="id"
              size="middle"
              pagination={false}
            />,
        },
        {
          key: 'financing',
          label: <span>融资还款 <Tag color="red">{pendingFinancing.length}</Tag></span>,
          children: pendingFinancing.length === 0 ? <Empty description="暂无待审融资还款" /> :
            <Table
              columns={[
                { title: '还款单号', dataIndex: 'repayment_no', width: 150 },
                { title: '类型', dataIndex: 'repayment_type', width: 80, render: (v: string) => <Tag color={v === 'return_warehouse' ? 'volcano' : 'blue'}>{v === 'return_warehouse' ? '退仓' : '还款'}</Tag> },
                { title: '还款本金', dataIndex: 'principal_amount', width: 110, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString()}` },
                { title: '利息', dataIndex: 'interest_amount', width: 100, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString()}` },
                { title: '天数', dataIndex: 'interest_days', width: 60 },
                { title: '现金扣款', key: 'cash', width: 120, align: 'right' as const, render: (_: any, r: any) => {
                  const cash = r.repayment_type === 'return_warehouse' ? Number(r.interest_amount) : Number(r.principal_amount) + Number(r.interest_amount);
                  return <span style={{ color: '#ff4d4f', fontWeight: 600 }}>¥{cash.toLocaleString()}</span>;
                }},
                { title: '备注', dataIndex: 'notes', width: 200, ellipsis: true },
                { title: '操作', key: 'act', width: 170, render: (_: any, r: any) => (
                  <Space>
                    <a onClick={() => showDetail(`融资还款 ${r.repayment_no}`, r)}>查看</a>
                    <Button size="small" type="primary" onClick={() => Modal.confirm({
                      title: '审批融资还款',
                      content: <div>
                        <p>单号：{r.repayment_no} | 本金：¥{Number(r.principal_amount).toLocaleString()}</p>
                        <p>利息：¥{Number(r.interest_amount).toLocaleString()}（{r.interest_days}天）</p>
                        <p style={{ color: '#ff4d4f' }}>审批通过后从品牌现金账户扣款，余额不足自动驳回</p>
                      </div>,
                      onOk: () => approveFinancingMut.mutate(r.id),
                    })}>通过</Button>
                    <Button size="small" danger onClick={() => rejectFinancingMut.mutate(r.id)}>驳回</Button>
                  </Space>
                )},
              ] as any}
              dataSource={pendingFinancing}
              rowKey="id"
              size="middle"
              pagination={false}
            />,
        },
        {
          key: 'share',
          label: <span>分货审批 <Tag color="red">{pendingShares.length}</Tag></span>,
          children: pendingShares.length === 0 ? <Empty description="暂无待审分货" /> :
            <Table
              columns={[
                { title: '编号', dataIndex: 'claim_no', width: 120 },
                { title: '对方', dataIndex: 'notes', width: 120 },
                { title: '金额', dataIndex: 'amount', width: 100, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString()}` },
                { title: '凭证', key: 'v', width: 60, render: (_: any, r: any) => r.voucher_urls?.length ? `${r.voucher_urls.length}张` : '-' },
                { title: '说明', dataIndex: 'title', width: 160 },
                { title: '操作', key: 'act', width: 170, render: (_: any, r: any) => (
                  <Space>
                    <a onClick={() => showDetail(`分货 ${r.claim_no}`, r)}>查看</a>
                    <Button size="small" type="primary" onClick={() => approveShareMut.mutate(r.id)}>通过</Button>
                    <Button size="small" danger onClick={() => rejectShareMut.mutate(r.id)}>驳回</Button>
                  </Space>
                )},
              ] as any}
              dataSource={pendingShares} rowKey="id" size="middle" pagination={false}
            />,
        },
        {
          key: 'leave',
          label: <span>请假审批 <Tag color="red">{pendingLeaves.length}</Tag></span>,
          children: pendingLeaves.length === 0 ? <Empty description="暂无待审请假" /> :
            <Table
              columns={[
                { title: '单号', dataIndex: 'request_no', width: 160 },
                { title: '员工', dataIndex: 'employee_name', width: 100 },
                { title: '类型', dataIndex: 'leave_type', width: 90,
                  render: (v: string) => {
                    const m: Record<string, string> = { sick: '病假', personal: '事假', annual: '年假', overtime_off: '调休', other: '其他' };
                    return <Tag>{m[v] ?? v}</Tag>;
                  }},
                { title: '起止', key: 'range', width: 200,
                  render: (_: any, r: any) => `${r.start_date} ~ ${r.end_date}` },
                { title: '天数', dataIndex: 'total_days', width: 70 },
                { title: '原因', dataIndex: 'reason', ellipsis: true },
                { title: '操作', key: 'act', width: 200, render: (_: any, r: any) => (
                  <Space>
                    <Button size="small" type="primary" icon={<CheckCircleOutlined />}
                      onClick={() => approveLeaveMut.mutate({ id: r.id, approved: true })}>批准</Button>
                    <Button size="small" danger icon={<CloseCircleOutlined />}
                      onClick={() => {
                        let reason = '';
                        Modal.confirm({
                          title: `驳回 ${r.employee_name} 请假`,
                          content: <textarea rows={2} style={{ width: '100%', border: '1px solid #d9d9d9', borderRadius: 4, padding: 6 }}
                            onChange={e => { reason = e.target.value; }} placeholder="驳回原因" />,
                          onOk: () => {
                            if (!reason.trim()) { message.warning('请填写原因'); return Promise.reject(); }
                            return approveLeaveMut.mutateAsync({ id: r.id, approved: false, reason });
                          },
                        });
                      }}>驳回</Button>
                  </Space>
                )},
              ] as any}
              dataSource={pendingLeaves} rowKey="id" size="middle" pagination={false}
            />,
        },
        {
          key: 'confirm-payment',
          label: <span>确认收款 <Tag color="red">{deliveredOrders.length}</Tag></span>,
          children: deliveredOrders.length === 0 ? <Empty description="暂无待确认收款订单" /> :
            <Table
              columns={[
                { title: '订单号', dataIndex: 'order_no', width: 180 },
                { title: '客户', key: 'cust', width: 100, render: (_: any, r: any) => r.customer?.name ?? '-' },
                { title: '业务员', key: 'sale', width: 100, render: (_: any, r: any) => r.salesman?.name ?? '-' },
                { title: '结算模式', dataIndex: 'settlement_mode', width: 110,
                  render: (v: string) => {
                    const map: Record<string, {c: string; t: string}> = {
                      customer_pay: { c: 'blue', t: '客户付款' },
                      employee_pay: { c: 'orange', t: '业务垫付' },
                      company_pay: { c: 'purple', t: '公司垫付' },
                    };
                    const m = map[v] ?? { c: 'default', t: v };
                    return <Tag color={m.c}>{m.t}</Tag>;
                  }},
                { title: '应收', dataIndex: 'customer_paid_amount', width: 110, align: 'right' as const,
                  render: (v: string, r: any) => `¥${Number(v ?? r.total_amount).toLocaleString()}` },
                { title: '付款状态', dataIndex: 'payment_status', width: 100,
                  render: (v: string) => {
                    const map: Record<string, {c: string; t: string}> = {
                      fully_paid: { c: 'green', t: '已全款' },
                      partially_paid: { c: 'orange', t: '部分付款' },
                      unpaid: { c: 'red', t: '未收款' },
                    };
                    const m = map[v] ?? { c: 'default', t: v };
                    return <Tag color={m.c}>{m.t}</Tag>;
                  }},
                { title: '凭证', dataIndex: 'payment_voucher_urls', width: 100,
                  render: (urls: string[]) => urls?.length ? (
                    <Typography.Link onClick={() => Modal.info({
                      title: '付款凭证', width: 600,
                      content: <Image.PreviewGroup><Space wrap>{urls.map((u, i) => <Image key={i} src={u} width={100} />)}</Space></Image.PreviewGroup>,
                    })}>{urls.length} 张</Typography.Link>
                  ) : <Typography.Text type="secondary">无</Typography.Text>},
                { title: '操作', key: 'act', width: 180, render: (_: any, r: any) => (
                  <Space>
                    <a onClick={() => {
                      const mode: Record<string, string> = { customer_pay: '客户付款', employee_pay: '业务垫付', company_pay: '公司垫付' };
                      Modal.info({
                        title: `订单 ${r.order_no}`,
                        width: 520,
                        content: (
                          <Descriptions column={2} size="small" bordered style={{ marginTop: 12 }}>
                            <Descriptions.Item label="客户">{r.customer?.name ?? '-'}</Descriptions.Item>
                            <Descriptions.Item label="业务员">{r.salesman?.name ?? '-'}</Descriptions.Item>
                            <Descriptions.Item label="结算模式"><Tag color="blue">{mode[r.settlement_mode] ?? r.settlement_mode}</Tag></Descriptions.Item>
                            <Descriptions.Item label="付款状态"><Tag color={r.payment_status === 'fully_paid' ? 'green' : 'orange'}>{r.payment_status === 'fully_paid' ? '已全款' : r.payment_status}</Tag></Descriptions.Item>
                            <Descriptions.Item label="订单总额">¥{Number(r.total_amount).toLocaleString()}</Descriptions.Item>
                            <Descriptions.Item label="应收">¥{Number(r.customer_paid_amount ?? r.total_amount).toLocaleString()}</Descriptions.Item>
                            {r.deal_amount && <Descriptions.Item label="客户到手价">¥{Number(r.deal_amount).toLocaleString()}</Descriptions.Item>}
                            {r.policy_gap > 0 && <Descriptions.Item label="政策差额"><Typography.Text type="warning">¥{Number(r.policy_gap).toLocaleString()}</Typography.Text></Descriptions.Item>}
                            {r.items?.length > 0 && (
                              <Descriptions.Item label="商品" span={2}>
                                {r.items.map((it: any, i: number) => <Tag key={i}>{it.product?.name ?? '商品'} ×{it.quantity}{it.quantity_unit || '箱'}</Tag>)}
                              </Descriptions.Item>
                            )}
                          </Descriptions>
                        ),
                      });
                    }}>详情</a>
                    <Button size="small" type="primary"
                      disabled={r.payment_status !== 'fully_paid'}
                      onClick={() => Modal.confirm({
                        title: `确认收款 - ${r.order_no}?`,
                        content: `订单应收 ¥${Number(r.customer_paid_amount ?? r.total_amount).toLocaleString()}，确认钱已到账？确认后将流转到"政策兑付"阶段。`,
                        onOk: () => confirmOrderPayMut.mutate(r.id),
                      })}>
                      {r.payment_status === 'fully_paid' ? '确认收款' : '未全款'}
                    </Button>
                  </Space>
                )},
              ] as any}
              dataSource={deliveredOrders} rowKey="id" size="middle" pagination={false}
            />,
        },
        {
          key: 'target',
          label: <span>销售目标审批 <Tag color="red">{pendingTargets.length}</Tag></span>,
          children: pendingTargets.length === 0 ? <Empty description="暂无待审销售目标" /> :
            <Table
              columns={[
                { title: '员工', dataIndex: 'employee_name', width: 100 },
                { title: '品牌', dataIndex: 'brand_name', width: 100, render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-' },
                { title: '周期', key: 'period', width: 100,
                  render: (_: any, r: any) => r.target_month ? `${r.target_year}-${String(r.target_month).padStart(2,'0')}` : `${r.target_year}年` },
                { title: '销售目标', dataIndex: 'sales_target', width: 120, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString()}` },
                { title: '回款目标', dataIndex: 'receipt_target', width: 120, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString()}` },
                { title: '达标奖', key: 'bonus', width: 140, align: 'right' as const,
                  render: (_: any, r: any) => `100% ¥${Number(r.bonus_at_100 || 0).toLocaleString()} / 120% ¥${Number(r.bonus_at_120 || 0).toLocaleString()}` },
                { title: '提交时间', dataIndex: 'submitted_at', width: 150,
                  render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
                { title: '操作', key: 'act', width: 200, render: (_: any, r: any) => (
                  <Space>
                    <Button size="small" type="primary" icon={<CheckCircleOutlined />}
                      onClick={() => Modal.confirm({
                        title: `批准 ${r.employee_name} ${r.target_year}-${String(r.target_month).padStart(2,'0')} 目标？`,
                        content: `销售 ¥${Number(r.sales_target).toLocaleString()} / 回款 ¥${Number(r.receipt_target).toLocaleString()}`,
                        onOk: () => approveTargetMut.mutate({ id: r.id, approved: true }),
                      })}>通过</Button>
                    <Button size="small" danger icon={<CloseCircleOutlined />}
                      onClick={() => {
                        let reason = '';
                        Modal.confirm({
                          title: `驳回 ${r.employee_name} 目标`,
                          content: (
                            <textarea rows={3} style={{ width: '100%', border: '1px solid #d9d9d9', borderRadius: 4, padding: 6 }}
                              onChange={e => { reason = e.target.value; }} placeholder="驳回原因（必填）" />
                          ),
                          onOk: () => {
                            if (!reason.trim()) { message.warning('请填写驳回原因'); return Promise.reject(); }
                            return approveTargetMut.mutateAsync({ id: r.id, approved: false, reject_reason: reason });
                          },
                        });
                      }}>驳回</Button>
                  </Space>
                ) },
              ] as any}
              dataSource={pendingTargets} rowKey="id" size="middle" pagination={false}
            />,
        },
        {
          key: 'salary',
          label: <span>工资审批 <Tag color="red">{pendingSalaries.length}</Tag></span>,
          children: pendingSalaries.length === 0 ? <Empty description="暂无待审工资单" /> :
            <Table
              columns={[
                { title: '员工', dataIndex: 'employee_name', width: 100 },
                { title: '周期', dataIndex: 'period', width: 90 },
                { title: '固定底薪', dataIndex: 'fixed_salary', width: 100, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString()}` },
                { title: '销售提成', dataIndex: 'commission_total', width: 100, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString()}` },
                { title: '管理提成', dataIndex: 'manager_share_total', width: 100, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString()}` },
                { title: '厂家补贴', dataIndex: 'manufacturer_subsidy_total', width: 100, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString()}` },
                { title: '全勤奖', dataIndex: 'attendance_bonus', width: 80, align: 'right' as const, render: (v: number) => `¥${Number(v).toLocaleString()}` },
                { title: '扣款合计', key: 'ded', width: 100, align: 'right' as const,
                  render: (_: any, r: any) => {
                    const t = Number(r.late_deduction) + Number(r.absence_deduction) + Number(r.fine_deduction) + Number(r.social_security);
                    return t > 0 ? <span style={{ color: '#ff4d4f' }}>-¥{t.toLocaleString()}</span> : '-';
                  } },
                { title: '实发', dataIndex: 'actual_pay', width: 110, align: 'right' as const,
                  render: (v: number) => <span style={{ color: '#ff4d4f', fontWeight: 600 }}>¥{Number(v).toLocaleString()}</span> },
                { title: '操作', key: 'act', width: 220, render: (_: any, r: any) => (
                  <Space>
                    <a href={`/hr/salaries/${r.id}`} target="_blank" rel="noreferrer">详情</a>
                    <Button size="small" type="primary" icon={<CheckCircleOutlined />}
                      onClick={() => Modal.confirm({
                        title: `批准 ${r.employee_name} 的 ${r.period} 工资?`,
                        content: `实发 ¥${Number(r.actual_pay).toLocaleString()}`,
                        onOk: () => approveSalaryMut.mutate({ id: r.id, approved: true }),
                      })}>通过</Button>
                    <Button size="small" danger icon={<CloseCircleOutlined />}
                      onClick={() => {
                        let reason = '';
                        Modal.confirm({
                          title: `驳回 ${r.employee_name} ${r.period}`,
                          content: (
                            <Form layout="vertical">
                              <Form.Item label="驳回原因" required>
                                <textarea rows={3} style={{ width: '100%', border: '1px solid #d9d9d9', borderRadius: 4, padding: 6 }}
                                  onChange={e => { reason = e.target.value; }} />
                              </Form.Item>
                            </Form>
                          ),
                          onOk: () => {
                            if (!reason.trim()) { message.warning('请填写驳回原因'); return Promise.reject(); }
                            return approveSalaryMut.mutateAsync({ id: r.id, approved: false, reject_reason: reason });
                          },
                        });
                      }}>驳回</Button>
                  </Space>
                ) },
              ] as any}
              dataSource={pendingSalaries} rowKey="id" size="middle" pagination={false}
            />,
        },
        {
          key: 'inspection',
          label: <span>稽查案件 <Tag color="red">{pendingCases.length}</Tag></span>,
          children: pendingCases.length === 0 ? <Empty description="暂无待审稽查案件" /> :
            <Table
              columns={[
                { title: '案件号', dataIndex: 'case_no', width: 120 },
                { title: '方向', dataIndex: 'direction', width: 65, render: (v: string) => v === 'outflow' ? <Tag color="red">外流</Tag> : <Tag color="green">流入</Tag> },
                { title: '类型', dataIndex: 'case_type', width: 140, render: (v: string) => {
                  const m: Record<string, string> = { outflow_malicious: 'A1 恶意→备用库', outflow_nonmalicious: 'A2 非恶意→主仓', outflow_transfer: 'A3 被转码', inflow_resell: 'B1 加价回售', inflow_transfer: 'B2 转码入库' };
                  return <Tag color={v?.startsWith('outflow') ? 'red' : 'green'}>{m[v] ?? v}</Tag>;
                }},
                { title: '商品', key: 'product', width: 100, render: (_: any, r: any) => r.product?.name ?? '-' },
                { title: '数量', key: 'qty', width: 70, render: (_: any, r: any) => `${r.quantity ?? 0}${r.quantity_unit ?? '瓶'}` },
                { title: '回收/买入价', key: 'price', width: 90, align: 'right' as const, render: (_: any, r: any) => r.purchase_price > 0 ? `¥${Number(r.purchase_price).toLocaleString()}/瓶` : '-' },
                { title: '罚款/奖励', key: 'penalty', width: 90, align: 'right' as const, render: (_: any, r: any) => {
                  if (r.penalty_amount > 0) return <span style={{ color: '#ff4d4f' }}>罚¥{Number(r.penalty_amount).toLocaleString()}</span>;
                  if (r.reward_amount > 0) return <span style={{ color: '#52c41a' }}>奖¥{Number(r.reward_amount).toLocaleString()}</span>;
                  return '-';
                }},
                { title: '盈亏', dataIndex: 'profit_loss', width: 90, align: 'right' as const, render: (v: number) => { const n = Number(v || 0); return <span style={{ color: n >= 0 ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>{n >= 0 ? '+' : ''}¥{n.toLocaleString()}</span>; }},
                { title: '操作', key: 'act', width: 170, render: (_: any, r: any) => (
                  <Space>
                    <a onClick={() => showDetail(`稽查 ${r.case_no}`, r)}>查看</a>
                    <Button size="small" type="primary" onClick={() => approveCaseMut.mutate(r.id)}>通过</Button>
                    <Button size="small" danger onClick={() => rejectCaseMut.mutate(r.id)}>驳回</Button>
                  </Space>
                )},
              ] as any}
              dataSource={pendingCases} rowKey="id" size="middle" pagination={false}
            />,
        },
      ]} />

      {/* 通用详情弹窗 */}
      <Modal title={detailTitle} open={detailOpen} onCancel={() => setDetailOpen(false)} footer={null} width={650}>
        {detailData && (() => {
          const d = detailData;
          const isPO = !!d.po_no;
          const isExpense = !!d.expense_no;
          const isShare = d.claim_type === 'share_out';
          const isCase = !!d.case_no;
          const TYPE_LABEL: Record<string, string> = { outflow_malicious: 'A1 恶意→备用库', outflow_nonmalicious: 'A2 非恶意→主仓', outflow_transfer: 'A3 被转码', inflow_resell: 'B1 加价回售', inflow_transfer: 'B2 转码入库' };
          return (
            <>
              {/* 采购单详情 */}
              {isPO && (
                <>
                  <Descriptions column={3} size="small" bordered style={{ marginBottom: 12 }}>
                    <Descriptions.Item label="采购单号"><Typography.Text copyable>{d.po_no}</Typography.Text></Descriptions.Item>
                    <Descriptions.Item label="供应商">{d.supplier?.name ?? '-'}</Descriptions.Item>
                    <Descriptions.Item label="品牌">{d.brand_name ?? '-'}</Descriptions.Item>
                    <Descriptions.Item label="总额"><Typography.Text strong>¥{Number(d.total_amount).toLocaleString()}</Typography.Text></Descriptions.Item>
                    <Descriptions.Item label="现金付款">{Number(d.cash_amount) > 0 ? `¥${Number(d.cash_amount).toLocaleString()}` : '-'}</Descriptions.Item>
                    <Descriptions.Item label="F类付款">{Number(d.f_class_amount) > 0 ? `¥${Number(d.f_class_amount).toLocaleString()}` : '-'}</Descriptions.Item>
                    {Number(d.financing_amount) > 0 && <Descriptions.Item label="融资">¥{Number(d.financing_amount).toLocaleString()}</Descriptions.Item>}
                    {d.expected_date && <Descriptions.Item label="预计到货">{d.expected_date}</Descriptions.Item>}
                    {d.notes && <Descriptions.Item label="备注" span={3}>{d.notes}</Descriptions.Item>}
                  </Descriptions>
                  {d.items?.length > 0 && (
                    <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                      <thead><tr style={{ background: '#fafafa' }}><th style={{ padding: '5px 8px', textAlign: 'left' }}>商品</th><th style={{ padding: '5px 8px', width: 80 }}>数量</th><th style={{ padding: '5px 8px', width: 90, textAlign: 'right' }}>单价</th><th style={{ padding: '5px 8px', width: 90, textAlign: 'right' }}>小计</th></tr></thead>
                      <tbody>{d.items.map((it: any, i: number) => (
                        <tr key={i} style={{ borderBottom: '1px solid #f0f0f0' }}>
                          <td style={{ padding: '5px 8px' }}>{it.product?.name ?? it.product_name ?? '-'}</td>
                          <td style={{ padding: '5px 8px' }}>{it.quantity}{it.quantity_unit || '箱'}</td>
                          <td style={{ padding: '5px 8px', textAlign: 'right' }}>¥{Number(it.unit_price).toLocaleString()}</td>
                          <td style={{ padding: '5px 8px', textAlign: 'right', fontWeight: 600 }}>¥{(Number(it.unit_price) * it.quantity).toLocaleString()}</td>
                        </tr>
                      ))}</tbody>
                    </table>
                  )}
                  {d.voucher_url && <div style={{ marginTop: 12 }}><Typography.Text type="secondary">凭证：</Typography.Text><Image src={d.voucher_url} width={120} style={{ borderRadius: 4 }} /></div>}
                </>
              )}

              {/* 报销详情 */}
              {isExpense && (
                <Descriptions column={2} size="small" bordered>
                  <Descriptions.Item label="报销编号">{d.expense_no}</Descriptions.Item>
                  <Descriptions.Item label="申请人">{d.applicant?.name ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="金额"><Typography.Text strong>¥{Number(d.amount).toLocaleString()}</Typography.Text></Descriptions.Item>
                  <Descriptions.Item label="状态"><Tag>{d.status}</Tag></Descriptions.Item>
                  <Descriptions.Item label="说明" span={2}>{d.description ?? '-'}</Descriptions.Item>
                  {d.payment_date && <Descriptions.Item label="费用日期">{d.payment_date}</Descriptions.Item>}
                  {d.voucher_urls?.length > 0 && (
                    <Descriptions.Item label="凭证" span={2}>
                      <Image.PreviewGroup><Space wrap>{d.voucher_urls.map((url: string, i: number) => <Image key={i} src={url} width={60} height={60} style={{ objectFit: 'cover', borderRadius: 4 }} />)}</Space></Image.PreviewGroup>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              )}

              {/* 分货详情 */}
              {isShare && (
                <Descriptions column={2} size="small" bordered>
                  <Descriptions.Item label="编号">{d.claim_no}</Descriptions.Item>
                  <Descriptions.Item label="对方经销商">{d.notes ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="标题" span={2}>{d.title}</Descriptions.Item>
                  <Descriptions.Item label="金额"><Typography.Text strong>¥{Number(d.amount).toLocaleString()}</Typography.Text></Descriptions.Item>
                  <Descriptions.Item label="申请人">{d.applicant_name ?? '-'}</Descriptions.Item>
                  {d.description && <Descriptions.Item label="商品信息" span={2}>{(() => { try { const p = JSON.parse(d.description); return `${p.product_id?.slice(0,8) ?? ''} ×${p.quantity ?? 0}${p.quantity_unit ?? ''}`; } catch { return d.description; } })()}</Descriptions.Item>}
                  {d.voucher_urls?.length > 0 && (
                    <Descriptions.Item label="付款凭证" span={2}>
                      <Image.PreviewGroup><Space wrap>{d.voucher_urls.map((url: string, i: number) => <Image key={i} src={url} width={60} height={60} style={{ objectFit: 'cover', borderRadius: 4 }} />)}</Space></Image.PreviewGroup>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              )}

              {/* 稽查案件详情 */}
              {isCase && (
                <Descriptions column={2} size="small" bordered>
                  <Descriptions.Item label="案件号">{d.case_no}</Descriptions.Item>
                  <Descriptions.Item label="方向">{d.direction === 'outflow' ? <Tag color="red">我方外流</Tag> : <Tag color="green">主动清理</Tag>}</Descriptions.Item>
                  <Descriptions.Item label="类型" span={2}><Tag color={d.direction === 'outflow' ? 'red' : 'green'}>{TYPE_LABEL[d.case_type] ?? d.case_type}</Tag></Descriptions.Item>
                  <Descriptions.Item label="商品">{d.product?.name ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="数量">{d.quantity}{d.quantity_unit}</Descriptions.Item>
                  <Descriptions.Item label="对方">{d.counterparty ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="发现地点">{d.found_location ?? '-'}</Descriptions.Item>
                  {d.purchase_price > 0 && <Descriptions.Item label="回收/买入价">¥{d.purchase_price}/瓶</Descriptions.Item>}
                  {d.resell_price > 0 && <Descriptions.Item label="回售价">¥{d.resell_price}/瓶</Descriptions.Item>}
                  {d.transfer_amount > 0 && <Descriptions.Item label="转码金额"><Typography.Text type="danger">¥{Number(d.transfer_amount).toLocaleString()}</Typography.Text></Descriptions.Item>}
                  {d.penalty_amount > 0 && <Descriptions.Item label="罚款"><Typography.Text type="danger">¥{Number(d.penalty_amount).toLocaleString()}</Typography.Text></Descriptions.Item>}
                  {d.reward_amount > 0 && <Descriptions.Item label="奖励"><Typography.Text type="success">¥{Number(d.reward_amount).toLocaleString()}</Typography.Text></Descriptions.Item>}
                  <Descriptions.Item label="盈亏" span={2}>
                    <Typography.Text strong style={{ fontSize: 16, color: (d.profit_loss ?? 0) >= 0 ? '#52c41a' : '#ff4d4f' }}>
                      {(d.profit_loss ?? 0) >= 0 ? '+' : ''}¥{Number(d.profit_loss ?? 0).toLocaleString()}
                    </Typography.Text>
                    {d.no_rebate && <Tag color="orange" style={{ marginLeft: 8 }}>不计回款</Tag>}
                  </Descriptions.Item>
                  {d.barcode && <Descriptions.Item label="条码">{d.barcode}</Descriptions.Item>}
                  {d.batch_no && <Descriptions.Item label="批次">{d.batch_no}</Descriptions.Item>}
                  {d.notes && <Descriptions.Item label="备注" span={2}>{d.notes}</Descriptions.Item>}
                </Descriptions>
              )}

              {/* 拨款详情 */}
              {!isPO && !isExpense && !isShare && !isCase && d.flow_no && (
                <Descriptions column={2} size="small" bordered>
                  <Descriptions.Item label="流水号">{d.flow_no}</Descriptions.Item>
                  <Descriptions.Item label="类型">{d.flow_type === 'credit' ? '入账' : d.flow_type === 'transfer_pending' ? '待审批拨款' : '出账'}</Descriptions.Item>
                  <Descriptions.Item label="转出账户">{d.from_account ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="转入账户">{d.to_account ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="金额"><Typography.Text strong>¥{Number(d.amount || 0).toLocaleString()}</Typography.Text></Descriptions.Item>
                  {d.to_brand && <Descriptions.Item label="品牌"><Tag color="blue">{d.to_brand}</Tag></Descriptions.Item>}
                  {d.notes && <Descriptions.Item label="备注" span={2}>{d.notes}</Descriptions.Item>}
                </Descriptions>
              )}

              {/* 融资还款详情 */}
              {!isPO && !isExpense && !isShare && !isCase && d.repayment_no && (
                <Descriptions column={2} size="small" bordered>
                  <Descriptions.Item label="还款单号">{d.repayment_no}</Descriptions.Item>
                  <Descriptions.Item label="类型"><Tag color={d.repayment_type === 'return_warehouse' ? 'volcano' : 'blue'}>{d.repayment_type === 'return_warehouse' ? '退仓' : '还款'}</Tag></Descriptions.Item>
                  <Descriptions.Item label="还款本金">¥{Number(d.principal_amount || 0).toLocaleString()}</Descriptions.Item>
                  <Descriptions.Item label="利息">¥{Number(d.interest_amount || 0).toLocaleString()}</Descriptions.Item>
                  <Descriptions.Item label="天数">{d.interest_days ?? '-'}</Descriptions.Item>
                  {d.notes && <Descriptions.Item label="备注" span={2}>{d.notes}</Descriptions.Item>}
                </Descriptions>
              )}

              {/* 垫付返还详情 */}
              {!isPO && !isExpense && !isShare && !isCase && d.request_no && (
                <Descriptions column={2} size="small" bordered>
                  <Descriptions.Item label="编号">{d.request_no}</Descriptions.Item>
                  <Descriptions.Item label="收款人">{d.payee_employee?.name ?? d.payee_customer?.name ?? d.payee_other_name ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="类型"><Tag>{d.payee_type === 'employee' ? '员工' : d.payee_type === 'customer' ? '客户' : d.payee_type}</Tag></Descriptions.Item>
                  <Descriptions.Item label="金额"><Typography.Text strong>¥{Number(d.amount || 0).toLocaleString()}</Typography.Text></Descriptions.Item>
                  <Descriptions.Item label="状态"><Tag color={d.status === 'paid' ? 'green' : d.status === 'approved' ? 'blue' : 'orange'}>{d.status}</Tag></Descriptions.Item>
                  {d.paid_at && <Descriptions.Item label="付款时间">{new Date(d.paid_at).toLocaleString('zh-CN')}</Descriptions.Item>}
                </Descriptions>
              )}
            </>
          );
        })()}
      </Modal>

      {/* 垫付返还确认付款 */}
      <Modal title={`确认付款 ${payPR?.request_no ?? ''}`} open={!!payPR} width={600}
        onCancel={() => { setPayPR(null); setPrVoucherUrls([]); setPrSignedUrls([]); }}
        onOk={() => {
          if (prVoucherUrls.length === 0 && prSignedUrls.length === 0) {
            message.warning('请上传转款凭证或签收照片（至少一种）');
            return;
          }
          if (!prPayAccount) { message.warning('请选择品牌现金账户'); return; }
          confirmPayMut.mutate({
            id: payPR.id,
            payment_account_id: prPayAccount,
            payment_voucher_urls: prVoucherUrls,
            signed_photo_urls: prSignedUrls,
          });
        }}
        confirmLoading={confirmPayMut.isPending} okText="确认付款" destroyOnHidden>
        {payPR && (
          <>
            <div style={{ padding: 12, background: '#fff7e6', borderRadius: 4, marginBottom: 12 }}>
              收款人：<Typography.Text strong>{payPR.payee_employee?.name ?? payPR.payee_customer?.name ?? payPR.payee_other_name ?? '-'}</Typography.Text>
              {' '}·{' '}金额 <Typography.Text strong style={{ color: '#ff4d4f' }}>¥{Number(payPR.amount).toLocaleString()}</Typography.Text>
              <br />
              <Typography.Text type="secondary">付款从<strong>品牌现金账户</strong>扣（F 类账户专款订货，不能用于兑付）</Typography.Text>
            </div>

            <Form layout="vertical">
              <Form.Item label="付款账户（品牌现金）" required>
                <Select
                  placeholder="选择品牌现金账户"
                  value={prPayAccount}
                  onChange={setPrPayAccount}
                  options={accounts
                    .filter((a: any) => a.account_type === 'cash' && a.level === 'project')
                    .map((a: any) => ({ value: a.id, label: `${a.name} (余额 ¥${Number(a.balance).toLocaleString()})` }))}
                />
              </Form.Item>

              <Form.Item label="转款凭证（银行回单/转账截图）">
                <Upload listType="picture-card" accept=".jpg,.jpeg,.png,.webp" multiple
                  fileList={prVoucherUrls.map((url, i) => ({ uid: String(i), name: `凭证${i+1}`, status: 'done' as const, url }))}
                  onRemove={(f) => setPrVoucherUrls(p => p.filter(u => u !== f.url))}
                  customRequest={async ({ file, onSuccess, onError }: any) => {
                    const fd = new FormData(); fd.append('file', file);
                    try {
                      const { data } = await api.post('/uploads', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
                      setPrVoucherUrls(p => [...p, data.url]);
                      onSuccess(data);
                    } catch (e) { onError(e); }
                  }}>
                  <div><UploadOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>上传</div></div>
                </Upload>
              </Form.Item>

              <Form.Item label="签收照片（收款人签字 / 现金签收）">
                <Upload listType="picture-card" accept=".jpg,.jpeg,.png,.webp" multiple
                  fileList={prSignedUrls.map((url, i) => ({ uid: String(i), name: `签收${i+1}`, status: 'done' as const, url }))}
                  onRemove={(f) => setPrSignedUrls(p => p.filter(u => u !== f.url))}
                  customRequest={async ({ file, onSuccess, onError }: any) => {
                    const fd = new FormData(); fd.append('file', file);
                    try {
                      const { data } = await api.post('/uploads', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
                      setPrSignedUrls(p => [...p, data.url]);
                      onSuccess(data);
                    } catch (e) { onError(e); }
                  }}>
                  <div><UploadOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>上传</div></div>
                </Upload>
              </Form.Item>
            </Form>
          </>
        )}
      </Modal>
    </>
  );
}

export default FinanceApproval;