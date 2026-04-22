import { useState } from 'react';
import { Button, Form, InputNumber, message, Modal, Select, Space, Table, Tag, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';

const { Title, Text } = Typography;

interface Scheme {
  id: string;
  brand_id: string | null;
  brand_name: string;
  position_code: string;
  position_name: string;
  commission_rate: number;
  manager_share_rate: number;
  fixed_salary: number;
  variable_salary_max: number;
  attendance_bonus_full: number;
  notes?: string;
}

interface Position { code: string; name: string }
interface Brand { id: string; name: string }

function SalarySchemeList() {
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Scheme | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const { data: rawData, isLoading } = useQuery<{ items: Scheme[]; total: number }>({
    queryKey: ['salary-schemes', page, pageSize],
    queryFn: () => api.get('/payroll/salary-schemes', { params: { skip: (page - 1) * pageSize, limit: pageSize } }).then(r => r.data),
  });
  const schemes = rawData?.items ?? [];
  const schemesTotal = rawData?.total ?? 0;
  const { data: positions = [] } = useQuery<Position[]>({
    queryKey: ['positions'],
    queryFn: () => api.get('/payroll/positions').then(r => extractItems<Position>(r.data)),
  });
  const { data: brands = [] } = useQuery<Brand[]>({
    queryKey: ['brands-select'],
    queryFn: () => api.get('/products/brands').then(r => extractItems<Brand>(r.data)),
  });

  const createMut = useMutation({
    mutationFn: (v: any) => api.post('/payroll/salary-schemes', v),
    onSuccess: () => {
      message.success('已保存');
      setOpen(false); setEditing(null); form.resetFields();
      qc.invalidateQueries({ queryKey: ['salary-schemes'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '保存失败'),
  });

  const delMut = useMutation({
    mutationFn: (id: string) => api.delete(`/payroll/salary-schemes/${id}`),
    onSuccess: () => { message.success('已删除'); qc.invalidateQueries({ queryKey: ['salary-schemes'] }); },
  });

  const openNew = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      commission_rate: 1, manager_share_rate: 0.3,
      fixed_salary: 3000, variable_salary_max: 1500, attendance_bonus_full: 200,
    });
    setOpen(true);
  };
  const openEdit = (s: Scheme) => {
    setEditing(s);
    form.setFieldsValue({
      brand_id: s.brand_id,
      position_code: s.position_code,
      commission_rate: s.commission_rate * 100, // 显示百分比
      manager_share_rate: s.manager_share_rate * 100,
      fixed_salary: s.fixed_salary,
      variable_salary_max: s.variable_salary_max,
      attendance_bonus_full: s.attendance_bonus_full,
    });
    setOpen(true);
  };

  const submit = () => form.validateFields().then(v => {
    createMut.mutate({
      brand_id: v.brand_id || null,
      position_code: v.position_code,
      commission_rate: (v.commission_rate || 0) / 100,
      manager_share_rate: (v.manager_share_rate || 0) / 100,
      fixed_salary: v.fixed_salary || 0,
      variable_salary_max: v.variable_salary_max || 0,
      attendance_bonus_full: v.attendance_bonus_full || 0,
    });
  });

  const watchPosition = Form.useWatch('position_code', form);
  const isManager = watchPosition === 'sales_manager';

  const columns: ColumnsType<Scheme> = [
    { title: '品牌', dataIndex: 'brand_name', width: 140,
      render: (v: string, r) => r.brand_id ? <Tag color="blue">{v}</Tag> : <Tag>公司通用</Tag> },
    { title: '岗位', dataIndex: 'position_name', width: 120,
      render: (v: string) => <Tag color="purple">{v}</Tag> },
    { title: '固定底薪', dataIndex: 'fixed_salary', width: 100, align: 'right' as const,
      render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '浮动底薪上限', dataIndex: 'variable_salary_max', width: 110, align: 'right' as const,
      render: (v: number) => `¥${Number(v).toLocaleString()}` },
    { title: '全勤奖', dataIndex: 'attendance_bonus_full', width: 90, align: 'right' as const,
      render: (v: number) => v > 0 ? `¥${Number(v).toLocaleString()}` : <Text type="secondary">-</Text> },
    { title: '销售提成率', dataIndex: 'commission_rate', width: 110, align: 'right' as const,
      render: (v: number) => v > 0 ? <Text strong>{(v*100).toFixed(2)}%</Text> : <Text type="secondary">-</Text> },
    { title: '管理提成率', dataIndex: 'manager_share_rate', width: 110, align: 'right' as const,
      render: (v: number) => v > 0 ? <Text strong style={{ color: '#fa8c16' }}>{(v*100).toFixed(2)}%</Text> : <Text type="secondary">-</Text> },
    { title: '操作', key: 'op', width: 120,
      render: (_, r) => (
        <Space size="small">
          <a onClick={() => openEdit(r)}>编辑</a>
          <a style={{ color: '#ff4d4f' }} onClick={() => Modal.confirm({
            title: '确认删除该方案?', onOk: () => delMut.mutate(r.id),
          })}>删除</a>
        </Space>
      ) },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>薪酬方案</Title>
          <Text type="secondary">共 {schemesTotal} 套（按"品牌 × 岗位"配置）</Text>
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={openNew}>新建方案</Button>
      </div>

      <Table<Scheme> columns={columns} dataSource={schemes} rowKey="id" loading={isLoading}
        pagination={{ current: page, pageSize, total: schemesTotal, showTotal: t => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} size="middle" />

      <Modal title={editing ? '编辑薪酬方案' : '新建薪酬方案'} open={open}
        onOk={submit} onCancel={() => { setOpen(false); setEditing(null); form.resetFields(); }}
        confirmLoading={createMut.isPending} destroyOnHidden width={500}>
        <Form form={form} layout="vertical">
          <Form.Item name="brand_id" label="品牌（不选=公司通用）">
            <Select allowClear placeholder="选择品牌，或留空代表公司通用" disabled={!!editing}
              options={brands.map(b => ({ value: b.id, label: b.name }))} />
          </Form.Item>
          <Form.Item name="position_code" label="岗位" rules={[{ required: true }]}>
            <Select placeholder="选择岗位" disabled={!!editing}
              options={positions.map(p => ({ value: p.code, label: p.name }))} />
          </Form.Item>
          <div style={{ padding: 8, background: '#f0f9ff', borderRadius: 4, marginBottom: 12, fontSize: 12 }}>
            <Text strong>底薪模板（主属该品牌×该岗位的员工按此模板发）</Text>
          </div>
          <Form.Item name="fixed_salary" label="固定底薪">
            <InputNumber style={{ width: '100%' }} min={0} step={100} addonBefore="¥" />
          </Form.Item>
          <Form.Item name="variable_salary_max" label="浮动底薪上限" tooltip="考核满分时发多少，实发=上限×考核完成率">
            <InputNumber style={{ width: '100%' }} min={0} step={100} addonBefore="¥" />
          </Form.Item>
          <Form.Item name="attendance_bonus_full" label="全勤奖全额" tooltip="无迟到/旷工且无请假时发全额；按请假天数 0/1/2/3/4/≥5 梯度扣减">
            <InputNumber style={{ width: '100%' }} min={0} step={50} addonBefore="¥" />
          </Form.Item>
          <div style={{ padding: 8, background: '#f0f9ff', borderRadius: 4, margin: '12px 0', fontSize: 12 }}>
            <Text strong>提成率（按销售品牌结算，不分主属兼职）</Text>
          </div>
          <Form.Item name="commission_rate" label="销售提成率（%）" tooltip="按回款金额计算，0 代表该岗位无提成（如财务）">
            <InputNumber style={{ width: '100%' }} min={0} max={100} step={0.1} addonAfter="%" precision={2} />
          </Form.Item>
          {isManager && (
            <Form.Item name="manager_share_rate" label="管理提成率（%）" tooltip="业务经理拿下属业务员回款的提成比例，一般 0.3%">
              <InputNumber style={{ width: '100%' }} min={0} max={100} step={0.1} addonAfter="%" precision={2} />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </>
  );
}

export default SalarySchemeList;
