import { useState } from 'react';
import { Button, Card, Col, Form, Image, Input, InputNumber, message, Modal, Row, Select, Space, Table, Tag, Tooltip, Typography, Upload } from 'antd';
import { CloseCircleOutlined, DollarOutlined, DownloadOutlined, SendOutlined, ThunderboltOutlined, UploadOutlined } from '@ant-design/icons';
import * as XLSX from 'xlsx';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import { Link } from 'react-router-dom';
import api, { extractItems } from '../../api/client';
import { useAuthStore } from '../../stores/authStore';

const { Title, Text } = Typography;

interface SalaryRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  period: string;
  fixed_salary: number;
  variable_salary_total: number;
  commission_total: number;
  manager_share_total: number;
  attendance_bonus: number;
  bonus_other: number;
  manufacturer_subsidy_total: number;
  late_deduction: number;
  absence_deduction: number;
  fine_deduction: number;
  social_security: number;
  total_pay: number;
  actual_pay: number;
  status: string; // draft / pending_approval / approved / rejected / paid
  reject_reason?: string;
  work_days_month: number;
  work_days_actual: number;
  notes?: string;
  payment_voucher_urls?: string[];
  paid_at?: string;
  submitted_at?: string;
  approved_at?: string;
}

interface Account { id: string; code: string; name: string; level: string; account_type: string; balance: number }

function ym(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  pending_approval: { color: 'gold', text: '待审批' },
  approved: { color: 'blue', text: '已批准' },
  rejected: { color: 'red', text: '已驳回' },
  paid: { color: 'green', text: '已发放' },
};

function SalaryRecordList() {
  const qc = useQueryClient();
  const roles = useAuthStore(s => s.roles);
  const isBoss = roles.includes('boss') || roles.includes('admin');

  const [period, setPeriod] = useState(ym());
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(30);
  const [editOpen, setEditOpen] = useState<SalaryRecord | null>(null);
  const [payOpen, setPayOpen] = useState<SalaryRecord | null>(null);
  const [batchPayOpen, setBatchPayOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState<SalaryRecord | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [voucherUrls, setVoucherUrls] = useState<string[]>([]);
  const [batchVoucherUrls, setBatchVoucherUrls] = useState<string[]>([]);
  const [voucherView, setVoucherView] = useState<SalaryRecord | null>(null);
  const [form] = Form.useForm();
  const [payForm] = Form.useForm();
  const [batchForm] = Form.useForm();
  const [rejectForm] = Form.useForm();

  const { data: rawData, isLoading } = useQuery<{ items: SalaryRecord[]; total: number }>({
    queryKey: ['salary-records', period, page, pageSize],
    queryFn: () => api.get('/payroll/salary-records', { params: { period, skip: (page - 1) * pageSize, limit: pageSize } }).then(r => r.data),
  });
  const data = rawData?.items ?? [];
  const total = rawData?.total ?? 0;
  // 工资只能从品牌现金账户发
  const { data: accounts = [] } = useQuery<Account[]>({
    queryKey: ['accounts-master'],
    queryFn: () => api.get('/accounts').then(r => extractItems<Account>(r.data).filter((a) => a.level === 'project' && a.account_type === 'cash')),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, ...v }: any) => api.put(`/payroll/salary-records/${id}`, v),
    onSuccess: () => { message.success('已更新'); setEditOpen(null); qc.invalidateQueries({ queryKey: ['salary-records'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '更新失败'),
  });

  const submitMut = useMutation({
    mutationFn: (id: string) => api.post(`/payroll/salary-records/${id}/submit`),
    onSuccess: () => { message.success('已提交审批'); qc.invalidateQueries({ queryKey: ['salary-records'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '提交失败'),
  });

  const batchSubmitMut = useMutation({
    mutationFn: () => api.post('/payroll/salary-records/batch-submit', { salary_record_ids: selected }),
    onSuccess: (r: any) => {
      message.success(r.data.detail);
      setSelected([]);
      qc.invalidateQueries({ queryKey: ['salary-records'] });
    },
  });

  const approveMut = useMutation({
    mutationFn: ({ id, approved, reject_reason }: { id: string; approved: boolean; reject_reason?: string }) =>
      api.post(`/payroll/salary-records/${id}/approve`, { approved, reject_reason }),
    onSuccess: (r: any) => {
      message.success(r.data.detail);
      setRejectOpen(null); rejectForm.resetFields();
      qc.invalidateQueries({ queryKey: ['salary-records'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '操作失败'),
  });

  const payMut = useMutation({
    mutationFn: (v: any) => api.post(`/payroll/salary-records/${payOpen!.id}/pay`, {
      ...v, voucher_urls: voucherUrls,
    }),
    onSuccess: () => {
      message.success('工资已发放');
      setPayOpen(null); payForm.resetFields(); setVoucherUrls([]);
      qc.invalidateQueries({ queryKey: ['salary-records'] });
      qc.invalidateQueries({ queryKey: ['accounts-master'] });
    },
    onError: (e: any) => {
      const detail = e?.response?.data?.detail ?? '发放失败';
      if (String(detail).includes('余额不足')) {
        Modal.warning({
          title: '账户余额不足',
          content: <div><p>{detail}</p><p style={{ color: '#faad14' }}>请先从"资金调拨"页将公司总资金池拨款到品牌现金账户，再回来发放工资。</p></div>,
          okText: '去资金调拨',
          onOk: () => { window.location.href = '/finance/accounts'; },
        });
      } else { message.error(detail); }
    },
  });

  const delMut = useMutation({
    mutationFn: (id: string) => api.delete(`/payroll/salary-records/${id}`),
    onSuccess: () => { message.success('已删除'); qc.invalidateQueries({ queryKey: ['salary-records'] }); },
  });

  const exportExcel = () => {
    if (data.length === 0) { message.warning('无工资单可导出'); return; }
    const rows = data.map(r => ({
      '员工': r.employee_name,
      '周期': r.period,
      '固定底薪': Number(r.fixed_salary),
      '浮动底薪': Number(r.variable_salary_total),
      '销售提成': Number(r.commission_total),
      '管理提成': Number(r.manager_share_total),
      '厂家补贴': Number(r.manufacturer_subsidy_total),
      '全勤奖': Number(r.attendance_bonus),
      '其他奖金': Number(r.bonus_other),
      '迟到扣款': Number(r.late_deduction),
      '旷工扣款': Number(r.absence_deduction),
      '罚款': Number(r.fine_deduction),
      '社保代扣': Number(r.social_security),
      '应发合计': Number(r.total_pay),
      '实发': Number(r.actual_pay),
      '状态': STATUS_MAP[r.status]?.text ?? r.status,
      '应出勤': r.work_days_month,
      '实出勤': r.work_days_actual,
      '备注': r.notes || '',
    }));
    const ws = XLSX.utils.json_to_sheet(rows);
    ws['!cols'] = Array(19).fill({ wch: 10 });
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, `工资单-${period}`);
    XLSX.writeFile(wb, `工资单_${period}_${new Date().toISOString().slice(0, 10)}.xlsx`);
    message.success('已导出');
  };

  const batchPayMut = useMutation({
    mutationFn: (values: any) => api.post('/payroll/salary-records/batch-pay', {
      salary_record_ids: selected,
      payment_account_id: values.payment_account_id,
      voucher_urls: batchVoucherUrls,
    }),
    onSuccess: (r: any) => {
      message.success(r.data.detail);
      setSelected([]); setBatchPayOpen(false); batchForm.resetFields(); setBatchVoucherUrls([]);
      qc.invalidateQueries({ queryKey: ['salary-records'] });
      qc.invalidateQueries({ queryKey: ['accounts-master'] });
    },
    onError: (e: any) => {
      const detail = e?.response?.data?.detail ?? '批量发放失败';
      if (String(detail).includes('余额不足')) {
        Modal.warning({
          title: '账户余额不足',
          content: <div><p>{detail}</p><p style={{ color: '#faad14' }}>请先从"资金调拨"将公司总资金池拨款到品牌现金账户。</p></div>,
          okText: '去资金调拨',
          onOk: () => { window.location.href = '/finance/accounts'; },
        });
      } else { message.error(detail); }
    },
  });

  const generateMut = useMutation({
    mutationFn: (overwrite: boolean) => api.post('/payroll/salary-records/generate', { period, overwrite }),
    onSuccess: (r: any) => {
      const { generated = [], skipped = [] } = r.data || {};
      Modal.success({
        title: `工资单生成完成`,
        width: 600,
        content: (
          <div>
            <p>生成 <b>{generated.length}</b> 条，跳过 <b>{skipped.length}</b> 条</p>
            {generated.length > 0 && (
              <div style={{ fontSize: 12, maxHeight: 240, overflow: 'auto' }}>
                {generated.map((g: any) => (
                  <div key={g.employee_id}>
                    {g.name}: 提成¥{g.commission.toFixed(2)} · 管理¥{g.manager_share.toFixed(2)} · 厂家¥{g.subsidy.toFixed(2)} · 实发<b>¥{g.total_pay.toFixed(2)}</b> ({g.order_count}单)
                  </div>
                ))}
              </div>
            )}
            {skipped.length > 0 && (
              <div style={{ marginTop: 8, fontSize: 12, color: '#888' }}>
                跳过: {skipped.map((s: any) => `${s.name}(${s.reason})`).join('；')}
              </div>
            )}
          </div>
        ),
      });
      qc.invalidateQueries({ queryKey: ['salary-records'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '生成失败'),
  });

  const handleGenerate = () => {
    Modal.confirm({
      title: `一键生成 ${period} 工资单？`,
      content: (
        <div>
          <p>系统按下列规则自动计算（不能人工修改核心字段）：</p>
          <ul style={{ fontSize: 12 }}>
            <li>固定/浮动底薪：员工档案</li>
            <li>销售提成：已全额回款且未结算订单 × 品牌提成率 × KPI系数</li>
            <li>管理提成：业务经理拿下属业务员回款比例</li>
            <li>厂家补贴：员工×品牌</li>
            <li>全勤奖：员工档案全额 × 按请假天数梯度（0=100% / 1=80% / 2=60% / 3=40% / 4=20% / ≥5=0%；迟到/旷工=0）</li>
          </ul>
          <p style={{ color: '#fa8c16' }}>若已存在该期工资单，可选是否覆盖（仅未发放的会被覆盖）：</p>
        </div>
      ),
      okText: '生成(不覆盖已有)',
      cancelText: '取消',
      onOk: () => generateMut.mutate(false),
      footer: (_, { OkBtn, CancelBtn }) => (
        <>
          <CancelBtn />
          <Button danger onClick={() => { Modal.destroyAll(); generateMut.mutate(true); }}>覆盖已有(未发放)</Button>
          <OkBtn />
        </>
      ),
    });
  };

  const totalUnpaid = data.filter(r => r.status !== 'paid').reduce((s, r) => s + r.actual_pay, 0);
  const totalPaid = data.filter(r => r.status === 'paid').reduce((s, r) => s + r.actual_pay, 0);
  const pendingCount = data.filter(r => r.status === 'pending_approval').length;
  const approvedCount = data.filter(r => r.status === 'approved').length;

  const columns: ColumnsType<SalaryRecord> = [
    {
      title: '员工', dataIndex: 'employee_name', width: 100,
      render: (v: string, r) => <Link to={`/hr/salaries/${r.id}`}><Text strong>{v}</Text></Link>,
    },
    { title: '周期', dataIndex: 'period', width: 90 },
    {
      title: '固定底薪', dataIndex: 'fixed_salary', width: 90, align: 'right' as const,
      render: (v: number) => `¥${v.toLocaleString()}`,
    },
    {
      title: '浮动底薪', dataIndex: 'variable_salary_total', width: 90, align: 'right' as const,
      render: (v: number) => v > 0 ? `¥${v.toLocaleString()}` : <Text type="secondary">-</Text>,
    },
    {
      title: '销售提成', dataIndex: 'commission_total', width: 100, align: 'right' as const,
      render: (v: number) => v > 0 ? <Text style={{ color: '#1890ff' }}>¥{v.toLocaleString()}</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '管理提成', dataIndex: 'manager_share_total', width: 90, align: 'right' as const,
      render: (v: number) => v > 0 ? <Text style={{ color: '#fa8c16' }}>¥{v.toLocaleString()}</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '厂家补贴', dataIndex: 'manufacturer_subsidy_total', width: 90, align: 'right' as const,
      render: (v: number) => v > 0 ? <Text style={{ color: '#52c41a' }}>¥{v.toLocaleString()}</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '全勤奖', dataIndex: 'attendance_bonus', width: 80, align: 'right' as const,
      render: (v: number) => v > 0 ? `¥${v}` : '-',
    },
    {
      title: '扣款合计', key: 'ded', width: 100, align: 'right' as const,
      render: (_, r) => {
        const t = r.late_deduction + r.absence_deduction + r.fine_deduction + r.social_security;
        return t > 0 ? <Text type="danger">-¥{t.toLocaleString()}</Text> : <Text type="secondary">-</Text>;
      },
    },
    {
      title: '实发', dataIndex: 'actual_pay', width: 110, align: 'right' as const,
      render: (v: number) => <Text strong style={{ fontSize: 14, color: '#ff4d4f' }}>¥{v.toLocaleString()}</Text>,
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: string, r) => {
        const { color, text } = STATUS_MAP[v] ?? { color: 'default', text: v };
        if (v === 'rejected' && r.reject_reason) {
          return <Tooltip title={r.reject_reason}><Tag color={color}>{text}</Tag></Tooltip>;
        }
        return <Tag color={color}>{text}</Tag>;
      },
    },
    {
      title: '操作', key: 'op', width: 280, fixed: 'right' as const,
      render: (_, r) => (
        <Space size="small">
          <Link to={`/hr/salaries/${r.id}`}>详情</Link>
          {(r.status === 'draft' || r.status === 'rejected') && (
            <>
              <a onClick={() => { setEditOpen(r); form.setFieldsValue(r); }}>编辑</a>
              <a style={{ color: '#1890ff' }} onClick={() => Modal.confirm({
                title: '提交审批?', content: `将该工资单提交老板审批`, onOk: () => submitMut.mutate(r.id),
              })}>提交审批</a>
              <a style={{ color: '#ff4d4f' }} onClick={() => Modal.confirm({ title: '确认删除?', onOk: () => delMut.mutate(r.id) })}>删除</a>
            </>
          )}
          {r.status === 'pending_approval' && isBoss && (
            <>
              <a style={{ color: '#52c41a' }} onClick={() => Modal.confirm({
                title: `批准 ${r.employee_name} 的工资?`,
                content: `实发 ¥${r.actual_pay.toLocaleString()}`,
                onOk: () => approveMut.mutate({ id: r.id, approved: true }),
              })}>批准</a>
              <a style={{ color: '#ff4d4f' }} onClick={() => setRejectOpen(r)}>驳回</a>
            </>
          )}
          {r.status === 'approved' && (
            <a style={{ color: '#52c41a' }} onClick={() => setPayOpen(r)}>发放</a>
          )}
          {r.status === 'paid' && (r.payment_voucher_urls?.length ?? 0) > 0 && (
            <a onClick={() => setVoucherView(r)}>凭证({r.payment_voucher_urls!.length})</a>
          )}
        </Space>
      ),
    },
  ];

  // 选中项（仅允许 draft/rejected 批量提交，approved 批量发放）
  const selectedRecs = data.filter(r => selected.includes(r.id));
  const canBatchSubmit = selectedRecs.length > 0 && selectedRecs.every(r => r.status === 'draft' || r.status === 'rejected');
  const canBatchPay = selectedRecs.length > 0 && selectedRecs.every(r => r.status === 'approved');

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>月度工资</Title>
          <span>周期：</span>
          <Input style={{ width: 110 }} value={period} onChange={e => { setPeriod(e.target.value); setPage(1); }} placeholder="2026-04" />
        </Space>
        <Space>
          <Button icon={<ThunderboltOutlined />} type="primary" style={{ background: '#722ed1' }}
            loading={generateMut.isPending} onClick={handleGenerate}>一键生成本期</Button>
          <Button icon={<DownloadOutlined />} onClick={exportExcel}>导出 Excel</Button>
          <Button icon={<SendOutlined />} disabled={!canBatchSubmit}
            onClick={() => batchSubmitMut.mutate()}>
            批量提交审批 ({selectedRecs.filter(r => r.status === 'draft' || r.status === 'rejected').length})
          </Button>
          <Button type="primary" disabled={!canBatchPay} onClick={() => setBatchPayOpen(true)}>
            批量发放 ({selectedRecs.filter(r => r.status === 'approved').length})
          </Button>
        </Space>
      </div>

      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Text type="secondary">本期工资单</Text><div style={{ fontSize: 20, fontWeight: 600 }}>{data.length} 条</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">待审批</Text><div style={{ fontSize: 20, fontWeight: 600, color: '#faad14' }}>{pendingCount}</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">已批准待发</Text><div style={{ fontSize: 20, fontWeight: 600, color: '#1890ff' }}>{approvedCount}</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">已发放合计</Text><div style={{ fontSize: 20, fontWeight: 600, color: '#52c41a' }}>¥{totalPaid.toLocaleString()}</div></Card></Col>
      </Row>

      <div style={{ marginBottom: 8, fontSize: 12, color: '#999' }}>
        待发放合计 ¥{totalUnpaid.toLocaleString()}
      </div>

      <Table<SalaryRecord> columns={columns} dataSource={data} rowKey="id"
        loading={isLoading} size="small" scroll={{ x: 1400 }}
        pagination={{ current: page, pageSize, total, showTotal: t => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }}
        rowSelection={{
          selectedRowKeys: selected,
          onChange: (keys) => setSelected(keys as string[]),
          getCheckboxProps: (r) => ({ disabled: r.status === 'paid' }),
        }} />

      {/* 批量发放 */}
      <Modal title="批量发放工资" open={batchPayOpen}
        onOk={() => {
          if (batchVoucherUrls.length === 0) { message.warning('请上传转款凭证'); return; }
          batchForm.validateFields().then(v => batchPayMut.mutate(v));
        }}
        onCancel={() => { setBatchPayOpen(false); batchForm.resetFields(); setBatchVoucherUrls([]); }}
        confirmLoading={batchPayMut.isPending} okText="确认批量发放" destroyOnHidden>
        <div style={{ padding: 12, background: '#fff7e6', borderRadius: 4, marginBottom: 12 }}>
          本次将发放 <Text strong>{selectedRecs.filter(r => r.status === 'approved').length}</Text> 张工资单，合计 <Text strong style={{ color: '#ff4d4f' }}>
          ¥{selectedRecs.filter(r => r.status === 'approved').reduce((s, r) => s + r.actual_pay, 0).toLocaleString()}</Text>
          <br />
          <Text type="secondary">发放后系统自动生成对应厂家补贴应收记录，可在"厂家工资报账"页批量报账。</Text>
        </div>
        <Form form={batchForm} layout="vertical">
          <Form.Item name="payment_account_id" label="付款账户" rules={[{ required: true }]}>
            <Select placeholder="选择付款账户"
              options={accounts.map(a => ({ value: a.id, label: `${a.name} (¥${a.balance.toLocaleString()})` }))} />
          </Form.Item>
          <Form.Item label="转款凭证（银行回单/转账截图，必传）" required>
            <Upload listType="picture-card" accept=".jpg,.jpeg,.png,.webp" multiple
              fileList={batchVoucherUrls.map((url, i) => ({ uid: String(i), name: `凭证${i + 1}`, status: 'done', url }))}
              onRemove={(f) => setBatchVoucherUrls(p => p.filter(u => u !== f.url))}
              customRequest={async ({ file, onSuccess, onError }: any) => {
                const fd = new FormData(); fd.append('file', file);
                try {
                  const { data } = await api.post('/uploads', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
                  setBatchVoucherUrls(p => [...p, data.url]);
                  onSuccess(data);
                } catch (e) { onError(e); }
              }}>
              <div><UploadOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>上传</div></div>
            </Upload>
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑工资单（仅手工字段：罚款/其他奖金/实发覆盖/备注） */}
      <Modal title={<>编辑 - {editOpen?.employee_name} <Tag>仅可修改人工干预字段</Tag></>}
        open={!!editOpen} width={560}
        onOk={() => form.validateFields().then(v => updateMut.mutate({ id: editOpen!.id, ...v }))}
        onCancel={() => setEditOpen(null)}
        confirmLoading={updateMut.isPending} destroyOnHidden>
        <div style={{ padding: 8, background: '#fffbe6', borderRadius: 4, marginBottom: 12, fontSize: 12 }}>
          <Text type="secondary">底薪、提成、考核、补贴等由系统自动计算，不可修改。可调整的仅限罚款、其他奖金、实发覆盖与备注。</Text>
        </div>
        <Form form={form} layout="vertical">
          <Row gutter={12}>
            <Col span={12}><Form.Item name="fine_deduction" label="罚款"><InputNumber style={{ width: '100%' }} prefix="¥" /></Form.Item></Col>
            <Col span={12}><Form.Item name="bonus_other" label="其他奖金"><InputNumber style={{ width: '100%' }} prefix="¥" /></Form.Item></Col>
          </Row>
          <Form.Item name="actual_pay" label="实发金额（可手工覆盖）" tooltip="留空则按系统计算"><InputNumber style={{ width: '100%' }} prefix="¥" /></Form.Item>
          <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      {/* 驳回原因 */}
      <Modal title={<><CloseCircleOutlined style={{ color: '#ff4d4f' }} /> 驳回 - {rejectOpen?.employee_name}</>}
        open={!!rejectOpen}
        onOk={() => rejectForm.validateFields().then(v =>
          approveMut.mutate({ id: rejectOpen!.id, approved: false, reject_reason: v.reason })
        )}
        onCancel={() => { setRejectOpen(null); rejectForm.resetFields(); }}
        confirmLoading={approveMut.isPending} okButtonProps={{ danger: true }} okText="确认驳回" destroyOnHidden>
        <Form form={rejectForm} layout="vertical">
          <Form.Item name="reason" label="驳回原因" rules={[{ required: true, message: '请填写驳回原因' }]}>
            <Input.TextArea rows={3} placeholder="例如：考核数据有误，请重新核对" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 发放工资 */}
      <Modal title={<><DollarOutlined /> 发放工资 - {payOpen?.employee_name}</>} open={!!payOpen}
        onOk={() => {
          if (voucherUrls.length === 0) { message.warning('请上传转款凭证'); return; }
          payForm.validateFields().then(v => payMut.mutate(v));
        }}
        onCancel={() => { setPayOpen(null); payForm.resetFields(); setVoucherUrls([]); }}
        confirmLoading={payMut.isPending} okText="确认发放" destroyOnHidden>
        <div style={{ padding: 12, background: '#fff7e6', borderRadius: 4, marginBottom: 12 }}>
          应发 ¥{payOpen?.total_pay.toLocaleString()} · 实发 <Text strong style={{ fontSize: 16, color: '#ff4d4f' }}>¥{payOpen?.actual_pay.toLocaleString()}</Text>
          <br />
          <Text type="secondary">厂家补贴 ¥{payOpen?.manufacturer_subsidy_total.toLocaleString()}（独立挂"政策应收"，不并入员工实发）。</Text>
        </div>
        <Form form={payForm} layout="vertical">
          <Form.Item name="payment_account_id" label="付款账户（公司现金账户）" rules={[{ required: true }]}>
            <Select placeholder="选择付款账户"
              options={accounts.map(a => ({ value: a.id, label: `${a.name} (余额 ¥${a.balance.toLocaleString()})` }))} />
          </Form.Item>
          <Form.Item label="转款凭证（银行回单/转账截图，必传）" required>
            <Upload listType="picture-card" accept=".jpg,.jpeg,.png,.webp" multiple
              fileList={voucherUrls.map((url, i) => ({ uid: String(i), name: `凭证${i + 1}`, status: 'done', url }))}
              onRemove={(f) => setVoucherUrls(p => p.filter(u => u !== f.url))}
              customRequest={async ({ file, onSuccess, onError }: any) => {
                const fd = new FormData(); fd.append('file', file);
                try {
                  const { data } = await api.post('/uploads', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
                  setVoucherUrls(p => [...p, data.url]);
                  onSuccess(data);
                } catch (e) { onError(e); }
              }}>
              <div><UploadOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>上传</div></div>
            </Upload>
          </Form.Item>
        </Form>
      </Modal>

      {/* 查看凭证 */}
      <Modal title={`转款凭证 - ${voucherView?.employee_name} ${voucherView?.period}`}
        open={!!voucherView} footer={null}
        onCancel={() => setVoucherView(null)} width={700}>
        {voucherView?.payment_voucher_urls?.length ? (
          <Image.PreviewGroup>
            <Space wrap>
              {voucherView.payment_voucher_urls.map((u, i) => (
                <Image key={i} width={160} src={u} />
              ))}
            </Space>
          </Image.PreviewGroup>
        ) : <Text type="secondary">无凭证</Text>}
        {voucherView?.paid_at && (
          <div style={{ marginTop: 12 }}>
            <Text type="secondary">发放时间：{new Date(voucherView.paid_at).toLocaleString('zh-CN')}</Text>
          </div>
        )}
      </Modal>
    </>
  );
}

export default SalaryRecordList;
