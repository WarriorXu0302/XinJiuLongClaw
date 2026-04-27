import { useState } from 'react';
import {
  Button, Form, InputNumber, message, Modal, Select, Space, Table, Tag, Typography, Alert, Switch,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';

const { Title, Text } = Typography;

interface Rule {
  id: string;
  brand_id: string;
  min_rate: number;
  max_rate: number | null;
  mode: 'linear' | 'fixed';
  fixed_value: number | null;
  effective_from: string;
  effective_to: string | null;
  notes?: string | null;
  created_at: string;
}

interface Brand { id: string; name: string }

const formatRange = (r: Rule) => {
  const lo = `${(r.min_rate * 100).toFixed(0)}%`;
  const hi = r.max_rate === null ? '+∞' : `${(r.max_rate * 100).toFixed(0)}%`;
  return `[${lo}, ${hi})`;
};

const formatMode = (r: Rule) => {
  if (r.mode === 'linear') return <Tag color="blue">按完成率线性</Tag>;
  return <Tag color="purple">固定 {((r.fixed_value ?? 0) * 100).toFixed(0)}%</Tag>;
};

function KpiRulesList() {
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Rule | null>(null);
  const [brandFilter, setBrandFilter] = useState<string | undefined>(undefined);
  const [includeHistory, setIncludeHistory] = useState(false);

  const { data: brands = [] } = useQuery<Brand[]>({
    queryKey: ['brands-select'],
    queryFn: () => api.get('/products/brands').then(r => extractItems<Brand>(r.data)),
  });

  const { data: rules = [], isLoading } = useQuery<Rule[]>({
    queryKey: ['kpi-rules', brandFilter, includeHistory],
    queryFn: () => api.get('/payroll/kpi-coefficient-rules', {
      params: {
        brand_id: brandFilter,
        include_history: includeHistory,
      },
    }).then(r => r.data),
  });

  const createMut = useMutation({
    mutationFn: (v: any) => api.post('/payroll/kpi-coefficient-rules', v),
    onSuccess: () => {
      message.success('已新增规则');
      setOpen(false); setEditing(null); form.resetFields();
      qc.invalidateQueries({ queryKey: ['kpi-rules'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '保存失败'),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, v }: { id: string; v: any }) => api.put(`/payroll/kpi-coefficient-rules/${id}`, v),
    onSuccess: () => {
      message.success('已更新（旧版已归档）');
      setOpen(false); setEditing(null); form.resetFields();
      qc.invalidateQueries({ queryKey: ['kpi-rules'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '更新失败'),
  });

  const delMut = useMutation({
    mutationFn: (id: string) => api.delete(`/payroll/kpi-coefficient-rules/${id}`),
    onSuccess: () => {
      message.success('已停用（保留历史）');
      qc.invalidateQueries({ queryKey: ['kpi-rules'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '删除失败'),
  });

  const openNew = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      brand_id: brandFilter,
      min_rate: 50,
      max_rate: null,
      mode: 'linear',
      fixed_value: null,
    });
    setOpen(true);
  };

  const openEdit = (r: Rule) => {
    setEditing(r);
    form.setFieldsValue({
      brand_id: r.brand_id,
      min_rate: r.min_rate * 100,
      max_rate: r.max_rate === null ? null : r.max_rate * 100,
      mode: r.mode,
      fixed_value: r.fixed_value === null ? null : r.fixed_value * 100,
      notes: r.notes,
    });
    setOpen(true);
  };

  const watchMode = Form.useWatch('mode', form);

  const submit = () => form.validateFields().then(v => {
    const payload: any = {
      min_rate: v.min_rate / 100,
      max_rate: v.max_rate === null || v.max_rate === undefined ? null : v.max_rate / 100,
      mode: v.mode,
      fixed_value: v.mode === 'fixed' ? (v.fixed_value ?? 0) / 100 : null,
      notes: v.notes,
    };
    if (editing) {
      updateMut.mutate({ id: editing.id, v: payload });
    } else {
      payload.brand_id = v.brand_id;
      createMut.mutate(payload);
    }
  });

  const brandName = (id: string) => brands.find(b => b.id === id)?.name ?? id.slice(0, 8);
  const sortedRules = [...rules].sort((a, b) => {
    if (a.brand_id !== b.brand_id) return brandName(a.brand_id).localeCompare(brandName(b.brand_id));
    if (!!a.effective_to !== !!b.effective_to) return a.effective_to ? 1 : -1;
    return a.min_rate - b.min_rate;
  });

  const columns: ColumnsType<Rule> = [
    { title: '品牌', dataIndex: 'brand_id', width: 130,
      render: (id: string) => <Tag color="blue">{brandName(id)}</Tag> },
    { title: '完成率区间', width: 140, render: (_, r) => <Text strong>{formatRange(r)}</Text> },
    { title: '模式', width: 160, render: (_, r) => formatMode(r) },
    { title: '生效日期', dataIndex: 'effective_from', width: 110 },
    { title: '失效日期', dataIndex: 'effective_to', width: 130,
      render: (v: string | null) => v
        ? <Tag color="default">{v}</Tag>
        : <Tag color="green">当前有效</Tag> },
    { title: '备注', dataIndex: 'notes', ellipsis: true },
    { title: '操作', key: 'op', width: 130, fixed: 'right' as const,
      render: (_, r) => r.effective_to
        ? <Text type="secondary">（历史）</Text>
        : (
          <Space size="small">
            <a onClick={() => openEdit(r)}>编辑</a>
            <a style={{ color: '#ff4d4f' }} onClick={() => Modal.confirm({
              title: '确认停用该规则？',
              content: '停用后会记录失效日期，历史档案保留，但该规则不再用于未来工资单计算。',
              onOk: () => delMut.mutate(r.id),
            })}>停用</a>
          </Space>
        ) },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>KPI 系数规则</Title>
          <Text type="secondary">按品牌配置"完成率 → 提成系数"，影响工资单提成计算</Text>
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={openNew}>新增规则</Button>
      </div>

      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="规则说明"
        description={
          <div style={{ fontSize: 12 }}>
            <div>· 每条规则覆盖一个完成率区间 <Text code>[下限, 上限)</Text>（左闭右开，上限留空=+∞）</div>
            <div>· <Text code>按完成率线性</Text>：系数 = 完成率（例：完成 85% → 系数 0.85）</div>
            <div>· <Text code>固定值</Text>：区间内系数固定（例：完成 50~80% 固定 0.5）</div>
            <div>· 改规则 = 旧规则记录失效日 + 新规则记录生效日，<b>历史完整留存</b></div>
            <div>· 同一品牌同一时段内 <b>区间不可重叠</b>；若冲突请先"编辑"已有规则缩小区间</div>
          </div>
        }
      />

      <Space style={{ marginBottom: 12 }}>
        <Select
          placeholder="筛选品牌（不选=全部）" allowClear style={{ width: 200 }}
          value={brandFilter} onChange={setBrandFilter}
          options={brands.map(b => ({ value: b.id, label: b.name }))}
        />
        <Switch checked={includeHistory} onChange={setIncludeHistory} />
        <Text type="secondary">包含历史档案</Text>
      </Space>

      <Table<Rule> columns={columns} dataSource={sortedRules} rowKey="id" loading={isLoading}
        pagination={{ pageSize: 50, showTotal: t => `共 ${t} 条` }} size="middle" />

      <Modal title={editing ? '编辑 KPI 系数规则（会归档旧版本）' : '新增 KPI 系数规则'} open={open}
        onOk={submit} onCancel={() => { setOpen(false); setEditing(null); form.resetFields(); }}
        confirmLoading={createMut.isPending || updateMut.isPending} destroyOnHidden width={520}>
        <Form form={form} layout="vertical">
          <Form.Item name="brand_id" label="品牌" rules={[{ required: true, message: '请选择品牌' }]}>
            <Select placeholder="选择品牌" disabled={!!editing}
              options={brands.map(b => ({ value: b.id, label: b.name }))} />
          </Form.Item>
          <div style={{ padding: 8, background: '#f0f9ff', borderRadius: 4, marginBottom: 12, fontSize: 12 }}>
            <Text strong>完成率区间</Text>（百分比形式输入，例 50 = 50%）
          </div>
          <Space.Compact style={{ width: '100%' }}>
            <Form.Item name="min_rate" label="下限（闭）" style={{ flex: 1 }}
              rules={[{ required: true, message: '必填' }]}>
              <InputNumber style={{ width: '100%' }} min={0} max={999} step={10} suffix="%" />
            </Form.Item>
            <Form.Item name="max_rate" label="上限（开，留空=+∞）" style={{ flex: 1, marginLeft: 12 }}>
              <InputNumber style={{ width: '100%' }} min={0} max={999} step={10} suffix="%" placeholder="留空" />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="mode" label="系数计算方式" rules={[{ required: true }]}>
            <Select options={[
              { value: 'linear', label: '按完成率线性（系数 = 完成率）' },
              { value: 'fixed', label: '区间内固定值' },
            ]} />
          </Form.Item>
          {watchMode === 'fixed' && (
            <Form.Item name="fixed_value" label="固定系数（%）"
              rules={[{ required: true, message: 'fixed 模式必填' }]}
              tooltip="例：80 代表系数 0.8；区间内无论完成率多少都按此系数算提成">
              <InputNumber style={{ width: '100%' }} min={0} max={999} step={5} suffix="%" />
            </Form.Item>
          )}
          <Form.Item name="notes" label="备注（可选）">
            <InputNumber style={{ display: 'none' }} />
            <input
              type="text"
              className="ant-input"
              maxLength={200}
              placeholder="说明这条规则的业务背景，便于将来查历史"
              onChange={e => form.setFieldValue('notes', e.target.value)}
              defaultValue={editing?.notes ?? ''}
              style={{ width: '100%', padding: '4px 11px', border: '1px solid #d9d9d9', borderRadius: 6 }}
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default KpiRulesList;
