import { useState } from 'react';
import { Button, Card, Col, Form, InputNumber, message, Modal, Progress, Row, Select, Space, Table, Tabs, Tag, Typography } from 'antd';
import { AimOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useIsAdmin, useHasRole } from '../../stores/authStore';

const { Title, Text } = Typography;

interface Target {
  id: string;
  target_level: string;
  target_year: number;
  target_month?: number;
  brand_id?: string;
  brand_name?: string;
  employee_id?: string;
  employee_name?: string;
  receipt_target: number;
  sales_target: number;
  bonus_at_100?: number;
  bonus_at_120?: number;
  bonus_metric?: string;
  actual_sales: number;
  actual_receipt: number;
  sales_completion: number;
  receipt_completion: number;
  status?: string;
  reject_reason?: string;
  submitted_at?: string;
  notes?: string;
}

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  approved: { color: 'green', text: '已生效' },
  pending_approval: { color: 'gold', text: '待审批' },
  rejected: { color: 'red', text: '已驳回' },
};

interface Brand { id: string; name: string }
interface Employee { id: string; name: string }

const ym = () => new Date().getFullYear();

function SalesTargetManage() {
  const qc = useQueryClient();
  const isAdmin = useIsAdmin();
  const isManager = useHasRole('sales_manager');
  const canSetCompanyBrand = isAdmin;

  const [year, setYear] = useState(ym());
  const [month, setMonth] = useState<number | undefined>();
  const [level, setLevel] = useState<string>(isAdmin ? 'company' : 'employee');
  const [form] = Form.useForm();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Target | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(30);

  const { data: rawTargets, isLoading } = useQuery<{ items: Target[]; total: number }>({
    queryKey: ['targets', year, month, level, page, pageSize],
    queryFn: () => {
      const params: Record<string, string | number> = { target_year: year, target_level: level, skip: (page - 1) * pageSize, limit: pageSize };
      if (month !== undefined) params.target_month = month;
      return api.get('/sales-targets', { params }).then(r => r.data);
    },
  });
  const targets = rawTargets?.items ?? [];
  const targetsTotal = rawTargets?.total ?? 0;

  const { data: brands = [] } = useQuery<Brand[]>({
    queryKey: ['brands-select'],
    queryFn: () => api.get('/products/brands').then(r => extractItems<Brand>(r.data)),
  });
  const { data: employees = [] } = useQuery<Employee[]>({
    queryKey: ['employees-all'],
    queryFn: () => api.get('/hr/employees').then(r => extractItems<Employee>(r.data)),
  });

  const saveMut = useMutation({
    mutationFn: (v: any) => api.post('/sales-targets', v),
    onSuccess: () => {
      message.success('已保存');
      setOpen(false); setEditing(null); form.resetFields();
      qc.invalidateQueries({ queryKey: ['targets'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '保存失败'),
  });

  const delMut = useMutation({
    mutationFn: (id: string) => api.delete(`/sales-targets/${id}`),
    onSuccess: () => { message.success('已删除'); qc.invalidateQueries({ queryKey: ['targets'] }); },
  });

  const openNew = () => {
    setEditing(null); form.resetFields();
    form.setFieldsValue({ target_level: level, target_year: year, target_month: month });
    setOpen(true);
  };
  const openEdit = (t: Target) => {
    setEditing(t);
    form.setFieldsValue({
      target_level: t.target_level, target_year: t.target_year, target_month: t.target_month,
      brand_id: t.brand_id, employee_id: t.employee_id,
      receipt_target: t.receipt_target, sales_target: t.sales_target,
      bonus_at_100: (t as any).bonus_at_100 || 0,
      bonus_at_120: (t as any).bonus_at_120 || 0,
      bonus_metric: (t as any).bonus_metric || 'receipt',
    });
    setOpen(true);
  };

  const submit = () => form.validateFields().then(v => saveMut.mutate({
    target_level: v.target_level,
    target_year: v.target_year,
    target_month: v.target_month || null,
    brand_id: v.brand_id || null,
    employee_id: v.employee_id || null,
    receipt_target: v.receipt_target || 0,
    sales_target: v.sales_target || 0,
    bonus_at_100: v.bonus_at_100 || 0,
    bonus_at_120: v.bonus_at_120 || 0,
    bonus_metric: v.bonus_metric || 'receipt',
  }));

  const watchLevel = Form.useWatch('target_level', form);

  // Summary
  const totalSalesTarget = targets.reduce((s, t) => s + t.sales_target, 0);
  const totalReceiptTarget = targets.reduce((s, t) => s + t.receipt_target, 0);
  const totalSales = targets.reduce((s, t) => s + t.actual_sales, 0);
  const totalReceipt = targets.reduce((s, t) => s + t.actual_receipt, 0);

  const columns: ColumnsType<Target> = [
    { title: '周期', key: 'period', width: 110,
      render: (_, r) => r.target_month ? `${r.target_year}-${String(r.target_month).padStart(2,'0')}` : `${r.target_year} 年度` },
    { title: level === 'brand' ? '品牌' : level === 'employee' ? '员工' : '范围',
      key: 'name', width: 140,
      render: (_, r) => {
        if (r.target_level === 'company') return <Tag color="gold">公司整体</Tag>;
        if (r.target_level === 'brand') return <Tag color="blue">{r.brand_name}</Tag>;
        return <Space size={4}><Tag color="purple">{r.employee_name}</Tag>{r.brand_name && <Tag>{r.brand_name}</Tag>}</Space>;
      }},
    { title: '销售目标', dataIndex: 'sales_target', width: 120, align: 'right' as const,
      render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '实际销售', dataIndex: 'actual_sales', width: 120, align: 'right' as const,
      render: (v: number) => <Text style={{ color: '#1890ff' }}>¥{v.toLocaleString()}</Text> },
    { title: '销售完成率', dataIndex: 'sales_completion', width: 140,
      render: (v: number) => {
        const pct = Math.round(v * 100);
        return <Progress percent={pct} size="small"
          status={pct >= 100 ? 'success' : pct >= 80 ? 'normal' : pct >= 50 ? 'active' : 'exception'} />;
      }},
    { title: '回款目标', dataIndex: 'receipt_target', width: 120, align: 'right' as const,
      render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '实际回款', dataIndex: 'actual_receipt', width: 120, align: 'right' as const,
      render: (v: number) => <Text style={{ color: '#52c41a' }}>¥{v.toLocaleString()}</Text> },
    { title: '回款完成率', dataIndex: 'receipt_completion', width: 140,
      render: (v: number) => {
        const pct = Math.round(v * 100);
        return <Progress percent={pct} size="small"
          status={pct >= 100 ? 'success' : pct >= 80 ? 'normal' : pct >= 50 ? 'active' : 'exception'} />;
      }},
    { title: '状态', dataIndex: 'status', width: 100,
      render: (v: string, r: Target) => {
        const tag = STATUS_TAG[v || 'approved'];
        const label = <Tag color={tag.color}>{tag.text}</Tag>;
        if (v === 'rejected' && r.reject_reason) {
          return <span title={r.reject_reason}>{label}<Text type="secondary" style={{ fontSize: 11, marginLeft: 4 }}>原因 …</Text></span>;
        }
        return label;
      } },
    { title: '操作', key: 'op', width: 120,
      render: (_, r) => (
        <Space size="small">
          {(isAdmin || (r.status !== 'approved' && isManager)) && <a onClick={() => openEdit(r)}>编辑</a>}
          {(isAdmin || (r.status !== 'approved' && isManager)) &&
            <a style={{ color: '#ff4d4f' }} onClick={() => Modal.confirm({
              title: '删除该目标?', onOk: () => delMut.mutate(r.id),
            })}>删除</a>}
        </Space>
      ) },
  ];

  return (
    <>
      <Title level={4}><AimOutlined /> 销售目标管理</Title>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <span>年份</span>
          <InputNumber value={year} onChange={v => { setYear(v || ym()); setPage(1); }} min={2020} max={2099} />
          <span>月份</span>
          <Select placeholder="全年" allowClear style={{ width: 120 }} value={month}
            onChange={(v) => { setMonth(v); setPage(1); }}
            options={Array.from({length: 12}, (_, i) => ({ value: i + 1, label: `${i + 1} 月` }))} />
          <Button type="primary" icon={<PlusOutlined />} onClick={openNew}>设置目标</Button>
        </Space>
      </Card>

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small"><Text type="secondary">销售目标合计</Text>
          <div style={{ fontSize: 18, fontWeight: 600 }}>¥{totalSalesTarget.toLocaleString()}</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">实际销售</Text>
          <div style={{ fontSize: 18, fontWeight: 600, color: '#1890ff' }}>¥{totalSales.toLocaleString()}</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">回款目标合计</Text>
          <div style={{ fontSize: 18, fontWeight: 600 }}>¥{totalReceiptTarget.toLocaleString()}</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">实际回款</Text>
          <div style={{ fontSize: 18, fontWeight: 600, color: '#52c41a' }}>¥{totalReceipt.toLocaleString()}</div></Card></Col>
      </Row>

      <Tabs activeKey={level} onChange={(v) => { setLevel(v); setPage(1); }} items={[
        ...(canSetCompanyBrand ? [
          { key: 'company', label: '公司整体' },
          { key: 'brand', label: '品牌目标' },
        ] : []),
        { key: 'employee', label: '员工目标' },
      ]} />

      <Table<Target> columns={columns} dataSource={targets} rowKey="id" loading={isLoading}
        pagination={{ current: page, pageSize, total: targetsTotal, showTotal: t => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} size="middle" />

      <Modal title={editing ? '编辑目标' : '设置目标'} open={open}
        onOk={submit} onCancel={() => { setOpen(false); setEditing(null); form.resetFields(); }}
        confirmLoading={saveMut.isPending} destroyOnHidden width={520}>
        {isManager && !isAdmin && (
          <div style={{ padding: 8, background: '#fffbe6', borderRadius: 4, marginBottom: 12, fontSize: 12 }}>
            <Text type="warning">业务经理给业务员下的目标需要老板审批后才生效</Text>
          </div>
        )}
        <Form form={form} layout="vertical">
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="target_level" label="层级" rules={[{ required: true }]}>
                <Select disabled={!!editing || !canSetCompanyBrand} options={canSetCompanyBrand ? [
                  { value: 'company', label: '公司' },
                  { value: 'brand', label: '品牌' },
                  { value: 'employee', label: '员工' },
                ] : [
                  { value: 'employee', label: '员工' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="target_year" label="年份" rules={[{ required: true }]}>
                <InputNumber style={{ width: '100%' }} min={2020} max={2099} disabled={!!editing} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="target_month" label="月份（空=年度目标）">
                <Select allowClear placeholder="年度目标" disabled={!!editing}
                  options={Array.from({length: 12}, (_, i) => ({ value: i + 1, label: `${i + 1} 月` }))} />
              </Form.Item>
            </Col>
          </Row>
          {watchLevel !== 'company' && (
            <Form.Item name="brand_id" label="品牌" rules={[{ required: true }]}>
              <Select disabled={!!editing} options={brands.map(b => ({ value: b.id, label: b.name }))} />
            </Form.Item>
          )}
          {watchLevel === 'employee' && (
            <Form.Item name="employee_id" label="员工" rules={[{ required: true }]}>
              <Select showSearch optionFilterProp="label" disabled={!!editing}
                options={employees.map(e => ({ value: e.id, label: e.name }))} />
            </Form.Item>
          )}
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="sales_target" label="销售目标金额" rules={[{ required: true }]}>
                <InputNumber style={{ width: '100%' }} min={0} step={10000} addonBefore="¥" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="receipt_target" label="回款目标金额" rules={[{ required: true }]}>
                <InputNumber style={{ width: '100%' }} min={0} step={10000} addonBefore="¥" />
              </Form.Item>
            </Col>
          </Row>

          <div style={{ padding: 12, background: '#fff7e6', borderRadius: 4, marginBottom: 8 }}>
            <div style={{ marginBottom: 6, fontWeight: 600 }}>达标奖金（可选，仅月度目标生效）</div>
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item name="bonus_metric" label="按哪个指标判达标" initialValue="receipt">
                  <Select options={[
                    { value: 'receipt', label: '按回款' },
                    { value: 'sales', label: '按销售' },
                  ]} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="bonus_at_100" label="完成 100% 奖" initialValue={0}>
                  <InputNumber style={{ width: '100%' }} min={0} step={100} addonBefore="¥" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="bonus_at_120" label="完成 120% 奖" initialValue={0}>
                  <InputNumber style={{ width: '100%' }} min={0} step={100} addonBefore="¥" />
                </Form.Item>
              </Col>
            </Row>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              工资单"一键生成"时自动判定；完成 120% 以上只发 120% 这一档（不叠加）
            </Typography.Text>
          </div>
        </Form>
      </Modal>
    </>
  );
}

export default SalesTargetManage;
