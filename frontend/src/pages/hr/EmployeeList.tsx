import { useState } from 'react';
import { Button, Card, Checkbox, Col, DatePicker, Form, Input, InputNumber, message, Modal, Row, Select, Space, Table, Tag, Typography } from 'antd';
import { DownloadOutlined, PlusOutlined, UserAddOutlined, BankOutlined } from '@ant-design/icons';
import { exportExcel } from '../../utils/exportExcel';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api, { extractItems } from '../../api/client';

const { Text } = Typography;

interface EmployeeItem {
  id: string; employee_no: string; name: string;
  position: string | null;
  phone: string | null;
  status: string;
  hire_date: string | null;
  social_security?: number;
  company_social_security?: number;
  expected_manufacturer_subsidy?: number;
}

interface UserAccount { id: string; username: string; employee_id: string | null; is_active: boolean; roles: string[] }
interface BrandPosition {
  id: string; employee_id: string; brand_id: string; brand_name?: string;
  position_code: string; position_name?: string;
  commission_rate: number | null;
  manufacturer_subsidy: number;
  is_primary: boolean;
}
interface Position { code: string; name: string }
interface Brand { id: string; name: string }

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  active: { color: 'green', label: '在职' },
  on_leave: { color: 'orange', label: '休假' },
  left: { color: 'default', label: '离职' },
};

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员', boss: '老板', finance: '财务', salesman: '业务员',
  warehouse: '仓管', purchase: '采购', hr: '人事', sales_manager: '业务经理', mfr_staff: '厂家人员',
};

function EmployeeList() {
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [accountForm] = Form.useForm();
  const [bpForm] = Form.useForm();

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<EmployeeItem | null>(null);
  const [accountEmp, setAccountEmp] = useState<EmployeeItem | null>(null);
  const [bpEmp, setBpEmp] = useState<EmployeeItem | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const { data: empResp, isLoading } = useQuery<{ items: EmployeeItem[]; total: number }>({
    queryKey: ['employees', page, pageSize],
    queryFn: () => api.get('/hr/employees', { params: { skip: (page - 1) * pageSize, limit: pageSize } }).then(r => r.data),
  });
  const employees = empResp?.items ?? [];
  const empTotal = empResp?.total ?? 0;
  const { data: users = [] } = useQuery<UserAccount[]>({
    queryKey: ['users-for-emp'],
    queryFn: () => api.get('/auth/users').then(r => extractItems<UserAccount>(r.data)),
  });
  const { data: brands = [] } = useQuery<Brand[]>({
    queryKey: ['brands-select'],
    queryFn: () => api.get('/products/brands').then(r => extractItems<Brand>(r.data)),
  });
  const { data: positions = [] } = useQuery<Position[]>({
    queryKey: ['positions'],
    queryFn: () => api.get('/payroll/positions').then(r => extractItems<Position>(r.data)),
  });

  const { data: empBPs = [] } = useQuery<BrandPosition[]>({
    queryKey: ['emp-bps', bpEmp?.id],
    queryFn: () => api.get(`/payroll/employees/${bpEmp!.id}/brand-positions`).then(r => extractItems<BrandPosition>(r.data)),
    enabled: !!bpEmp,
  });

  const userByEmp: Record<string, UserAccount> = {};
  users.forEach(u => { if (u.employee_id) userByEmp[u.employee_id] = u; });

  // 员工 → 品牌岗位数量统计
  const [bpCounts, setBpCounts] = useState<Record<string, { count: number; primary?: string; positions: string[] }>>({});
  useQuery({
    queryKey: ['all-emp-bps', employees.length],
    queryFn: async () => {
      const result: Record<string, { count: number; primary?: string; positions: string[] }> = {};
      await Promise.all(employees.map(async (e) => {
        try {
          const { data } = await api.get<BrandPosition[]>(`/payroll/employees/${e.id}/brand-positions`);
          const primary = data.find(x => x.is_primary);
          result[e.id] = {
            count: data.length,
            primary: primary?.brand_name,
            positions: [...new Set(data.map(x => x.position_name || x.position_code))],
          };
        } catch {}
      }));
      setBpCounts(result);
      return result;
    },
    enabled: employees.length > 0,
  });

  const createEmp = useMutation({
    mutationFn: async (values: any) => {
      const payload = { ...values, hire_date: values.hire_date?.format('YYYY-MM-DD') ?? null };
      ['create_account','account_username','account_password','account_roles','first_brand','first_position','first_subsidy'].forEach(k => delete payload[k]);
      const { data: emp } = await api.post('/hr/employees', payload);
      // 创建账号
      if (values.create_account && values.account_username && values.account_password) {
        await api.post('/auth/users', {
          username: values.account_username,
          password: values.account_password,
          employee_id: emp.id,
          role_codes: values.account_roles || [],
        });
      }
      // 绑定首个品牌×岗位
      if (values.first_brand && values.first_position) {
        await api.post(`/payroll/employees/${emp.id}/brand-positions`, {
          brand_id: values.first_brand,
          position_code: values.first_position,
          manufacturer_subsidy: values.first_subsidy || 0,
          is_primary: true,
        });
      }
      return emp;
    },
    onSuccess: () => {
      message.success('员工已创建');
      setModalOpen(false); form.resetFields();
      qc.invalidateQueries({ queryKey: ['employees'] });
      qc.invalidateQueries({ queryKey: ['users-for-emp'] });
      qc.invalidateQueries({ queryKey: ['all-emp-bps'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  const updateEmp = useMutation({
    mutationFn: async (values: any) => {
      const payload = { ...values, hire_date: values.hire_date?.format('YYYY-MM-DD') ?? null };
      ['create_account','account_username','account_password','account_roles','first_brand','first_position','first_subsidy'].forEach(k => delete payload[k]);
      const { data } = await api.put(`/hr/employees/${editing!.id}`, payload);
      return data;
    },
    onSuccess: () => {
      message.success('已更新');
      setModalOpen(false); setEditing(null); form.resetFields();
      qc.invalidateQueries({ queryKey: ['employees'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '更新失败'),
  });

  const createAccountMut = useMutation({
    mutationFn: (v: any) => api.post('/auth/users', {
      username: v.username, password: v.password,
      employee_id: accountEmp!.id, role_codes: v.role_codes || [],
    }),
    onSuccess: () => {
      message.success(`已为 ${accountEmp!.name} 创建账号`);
      setAccountEmp(null); accountForm.resetFields();
      qc.invalidateQueries({ queryKey: ['users-for-emp'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  const addBpMut = useMutation({
    mutationFn: (v: any) => api.post(`/payroll/employees/${bpEmp!.id}/brand-positions`, v),
    onSuccess: () => {
      message.success('已添加');
      bpForm.resetFields();
      qc.invalidateQueries({ queryKey: ['emp-bps'] });
      qc.invalidateQueries({ queryKey: ['all-emp-bps'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '添加失败'),
  });
  const delBpMut = useMutation({
    mutationFn: (id: string) => api.delete(`/payroll/brand-positions/${id}`),
    onSuccess: () => {
      message.success('已移除');
      qc.invalidateQueries({ queryKey: ['emp-bps'] });
      qc.invalidateQueries({ queryKey: ['all-emp-bps'] });
    },
  });
  const setPrimaryBpMut = useMutation({
    mutationFn: (id: string) => api.put(`/payroll/brand-positions/${id}`, { is_primary: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['emp-bps'] });
      qc.invalidateQueries({ queryKey: ['all-emp-bps'] });
    },
  });

  const openEdit = (r: EmployeeItem) => {
    setEditing(r);
    setModalOpen(true);
    form.setFieldsValue({
      employee_no: r.employee_no, name: r.name,
      position: r.position ?? '',
      phone: r.phone ?? '',
      hire_date: r.hire_date ? dayjs(r.hire_date) : null,
      status: r.status,
      social_security: r.social_security ?? 0,
      company_social_security: r.company_social_security ?? 0,
      expected_manufacturer_subsidy: r.expected_manufacturer_subsidy ?? 0,
    });
  };

  const watchCreateAccount = Form.useWatch('create_account', form);

  const columns: ColumnsType<EmployeeItem> = [
    { title: '工号', dataIndex: 'employee_no', width: 90 },
    { title: '姓名', dataIndex: 'name', width: 90,
      render: (v: string) => <Text strong>{v}</Text> },
    { title: '品牌×岗位', key: 'bp', width: 200,
      render: (_, r) => {
        const info = bpCounts[r.id];
        if (!info || info.count === 0) return <a onClick={() => setBpEmp(r)}>未配置 配置</a>;
        return (
          <Space size={2} wrap>
            {info.primary && <Tag color="blue">{info.primary}(主)</Tag>}
            <Text type="secondary" style={{ fontSize: 11 }}>{info.positions.join(' / ')}</Text>
            <a onClick={() => setBpEmp(r)}>{info.count > 1 ? `+${info.count - 1}` : '改'}</a>
          </Space>
        );
      }},
    { title: '社保代扣', key: 'salary', width: 110,
      render: (_, r) => (
        <div style={{ fontSize: 12 }}>
          {Number(r.social_security) > 0 ? <>个人 ¥{r.social_security}</> : <Text type="secondary">-</Text>}
          {Number(r.company_social_security) > 0 && <Text type="secondary" style={{ fontSize: 11, display: 'block' }}>公司 ¥{r.company_social_security}</Text>}
        </div>
      ) },
    { title: '登录账号', key: 'account', width: 160,
      render: (_, r) => {
        const u = userByEmp[r.id];
        if (!u) return <Button size="small" icon={<UserAddOutlined />} onClick={() => setAccountEmp(r)}>创建账号</Button>;
        return (
          <Space direction="vertical" size={0}>
            <Text code style={{ fontSize: 12 }}>{u.username}</Text>
            <Space size={2} wrap>
              {u.roles.map(role => <Tag key={role} color="purple" style={{ fontSize: 10, margin: 0 }}>{ROLE_LABEL[role] ?? role}</Tag>)}
            </Space>
            {!u.is_active && <Tag color="red" style={{ fontSize: 10 }}>已禁用</Tag>}
          </Space>
        );
      }},
    { title: '电话', dataIndex: 'phone', width: 110, render: (v: string) => v || '-' },
    { title: '状态', dataIndex: 'status', width: 70,
      render: (s: string) => { const info = STATUS_MAP[s] ?? { color: 'default', label: s }; return <Tag color={info.color}>{info.label}</Tag>; }},
    { title: '操作', key: 'action', width: 70, fixed: 'right' as const,
      render: (_, r) => <a onClick={() => openEdit(r)}>编辑</a> },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <h2 style={{ margin: 0 }}>员工管理</h2>
          <Text type="secondary">共 {empTotal} 人</Text>
        </Space>
        <Space>
          <Button icon={<DownloadOutlined />} onClick={() => {
            const rows = employees.map(e => {
              const u = userByEmp[e.id];
              const bp = bpCounts[e.id];
              return {
                '工号': e.employee_no,
                '姓名': e.name,
                '职务': e.position || '-',
                '电话': e.phone || '-',
                '入职日期': e.hire_date || '-',
                '状态': STATUS_MAP[e.status]?.label ?? e.status,
                '登录账号': u?.username || '-',
                '角色': u?.roles?.map(r => ROLE_LABEL[r] ?? r).join('、') || '-',
                '账号启用': u ? (u.is_active ? '是' : '否') : '-',
                '主属品牌': bp?.primary || '-',
                '岗位': bp?.positions?.join('、') || '-',
                '品牌数': bp?.count ?? 0,
                '社保代扣(个人)': Number(e.social_security ?? 0),
                '社保(公司)': Number(e.company_social_security ?? 0),
                '厂家补贴应得': Number(e.expected_manufacturer_subsidy ?? 0),
              };
            });
            exportExcel('员工花名册', '员工', rows, [
              { wch: 10 }, { wch: 10 }, { wch: 12 }, { wch: 14 }, { wch: 12 },
              { wch: 8 }, { wch: 14 }, { wch: 20 }, { wch: 10 },
              { wch: 12 }, { wch: 16 }, { wch: 8 }, { wch: 10 }, { wch: 10 }, { wch: 10 },
            ]);
          }}>导出花名册</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => {
            setEditing(null); form.resetFields();
            form.setFieldsValue({ status: 'active', social_security: 0, company_social_security: 0, expected_manufacturer_subsidy: 0 });
            setModalOpen(true);
          }}>新建员工</Button>
        </Space>
      </div>
      <Table<EmployeeItem> columns={columns} dataSource={employees} rowKey="id" loading={isLoading}
        pagination={{ current: page, pageSize, total: empTotal, showTotal: (t) => `共 ${t} 条`, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} scroll={{ x: 1300 }} />

      {/* 员工 Modal */}
      <Modal title={editing ? `编辑 ${editing.name}` : '新建员工'} open={modalOpen} width={720}
        onOk={() => form.validateFields().then(v => editing ? updateEmp.mutate(v) : createEmp.mutate(v))}
        onCancel={() => { setModalOpen(false); setEditing(null); form.resetFields(); }}
        confirmLoading={createEmp.isPending || updateEmp.isPending} okText="确认" destroyOnHidden>
        <Form form={form} layout="vertical">
          <Row gutter={12}>
            <Col span={8}><Form.Item name="employee_no" label="工号" rules={[{ required: true }]}><Input placeholder="EMP006" /></Form.Item></Col>
            <Col span={8}><Form.Item name="name" label="姓名" rules={[{ required: true }]}><Input placeholder="姓名" /></Form.Item></Col>
            <Col span={8}><Form.Item name="phone" label="电话"><Input placeholder="手机号" /></Form.Item></Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="position" label="职务（文字描述）"><Input placeholder="如：资深业务员" /></Form.Item></Col>
            <Col span={12}><Form.Item name="hire_date" label="入职日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <div style={{ padding: 8, background: '#fffbe6', borderRadius: 4, marginBottom: 12, fontSize: 12 }}>
            <Text type="secondary">固定底薪 / 浮动底薪 / 全勤奖全额由"主属品牌 × 岗位"的薪酬方案决定，请到"薪酬方案"页配置。</Text>
          </div>
          <Row gutter={12}>
            <Col span={8}><Form.Item name="social_security" label="社保代扣（个人）" tooltip="每月从工资中扣"><InputNumber min={0} style={{ width: '100%' }} addonBefore="¥" /></Form.Item></Col>
            <Col span={8}><Form.Item name="company_social_security" label="公司代缴社保" tooltip="不扣本人，计入公司成本"><InputNumber min={0} style={{ width: '100%' }} addonBefore="¥" /></Form.Item></Col>
            <Col span={8}><Form.Item name="expected_manufacturer_subsidy" label="厂家补贴应得（月）" tooltip="每月预期应收厂家补贴总额，用于对账"><InputNumber min={0} style={{ width: '100%' }} addonBefore="¥" /></Form.Item></Col>
          </Row>
          <Form.Item name="status" label="状态" rules={[{ required: true }]}>
            <Select options={[{ value: 'active', label: '在职' }, { value: 'on_leave', label: '休假' }, { value: 'left', label: '离职' }]} />
          </Form.Item>

          {!editing && (
            <div style={{ padding: 12, background: '#f0f9ff', borderRadius: 4, marginBottom: 12 }}>
              <Text strong>第一个品牌 × 岗位（可在保存后继续添加更多）</Text>
              <Row gutter={12} style={{ marginTop: 8 }}>
                <Col span={8}><Form.Item name="first_brand" label="品牌"><Select allowClear placeholder="归属品牌" options={brands.map(b => ({ value: b.id, label: b.name }))} /></Form.Item></Col>
                <Col span={8}><Form.Item name="first_position" label="岗位"><Select allowClear placeholder="岗位" options={positions.map(p => ({ value: p.code, label: p.name }))} /></Form.Item></Col>
                <Col span={8}><Form.Item name="first_subsidy" label="厂家补贴月额" tooltip="每月厂家补贴固定金额"><InputNumber min={0} style={{ width: '100%' }} addonBefore="¥" /></Form.Item></Col>
              </Row>
            </div>
          )}

          {!editing && (
            <>
              <Form.Item name="create_account" valuePropName="checked" style={{ marginBottom: 8 }}>
                <Checkbox>同时创建登录账号</Checkbox>
              </Form.Item>
              {watchCreateAccount && (
                <div style={{ padding: 12, background: '#f6f9ff', border: '1px dashed #adc6ff', borderRadius: 4 }}>
                  <Row gutter={12}>
                    <Col span={8}><Form.Item name="account_username" label="用户名" rules={[{ required: true }]}><Input /></Form.Item></Col>
                    <Col span={8}><Form.Item name="account_password" label="初始密码" rules={[{ required: true, min: 6 }]}><Input.Password /></Form.Item></Col>
                    <Col span={8}><Form.Item name="account_roles" label="角色"><Select mode="multiple" options={Object.entries(ROLE_LABEL).map(([v, l]) => ({ value: v, label: l }))} /></Form.Item></Col>
                  </Row>
                </div>
              )}
            </>
          )}
        </Form>
      </Modal>

      {/* 创建账号 Modal */}
      <Modal title={`创建登录账号 — ${accountEmp?.name ?? ''}`} open={!!accountEmp}
        onOk={() => accountForm.validateFields().then(v => createAccountMut.mutate(v))}
        onCancel={() => { setAccountEmp(null); accountForm.resetFields(); }}
        confirmLoading={createAccountMut.isPending} destroyOnHidden>
        <Form form={accountForm} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 6 }]}><Input.Password /></Form.Item>
          <Form.Item name="role_codes" label="角色（可多选）">
            <Select mode="multiple" options={Object.entries(ROLE_LABEL).map(([v, l]) => ({ value: v, label: l }))} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 品牌×岗位 管理 Modal */}
      <Modal title={<><BankOutlined /> 品牌 × 岗位 — {bpEmp?.name ?? ''}</>} open={!!bpEmp}
        onCancel={() => setBpEmp(null)} footer={null} width={700} destroyOnHidden>
        <Card size="small" title="当前已配置" style={{ marginBottom: 12 }}>
          {empBPs.length === 0 ? (
            <Text type="secondary">暂无配置</Text>
          ) : (
            <Table dataSource={empBPs} rowKey="id" size="small" pagination={false}
              columns={[
                { title: '品牌', dataIndex: 'brand_name', width: 110,
                  render: (v: string, r) => <>{v} {r.is_primary && <Tag color="blue">主</Tag>}</> },
                { title: '岗位', dataIndex: 'position_name', width: 100,
                  render: (v: string) => <Tag color="purple">{v}</Tag> },
                { title: '个性化提成率', dataIndex: 'commission_rate', width: 120,
                  render: (v: number | null) => v != null ? `${(v*100).toFixed(2)}%` : <Text type="secondary">品牌默认</Text> },
                { title: '厂家补贴', dataIndex: 'manufacturer_subsidy', width: 100,
                  render: (v: number) => v > 0 ? <Text strong style={{ color: '#52c41a' }}>¥{v}</Text> : '-' },
                { title: '操作', key: 'op', width: 140,
                  render: (_, r) => (
                    <Space size="small">
                      {!r.is_primary && <a onClick={() => setPrimaryBpMut.mutate(r.id)}>设为主</a>}
                      <a style={{ color: '#ff4d4f' }} onClick={() => Modal.confirm({ title: '确认移除?', onOk: () => delBpMut.mutate(r.id) })}>移除</a>
                    </Space>
                  ) },
              ]} />
          )}
        </Card>

        <Card size="small" title="添加品牌 × 岗位">
          <Form form={bpForm} layout="inline" onFinish={(v) => addBpMut.mutate({
            ...v, is_primary: empBPs.length === 0 ? true : (v.is_primary || false),
          })}>
            <Form.Item name="brand_id" rules={[{ required: true }]}>
              <Select placeholder="品牌" style={{ width: 130 }}
                options={brands.filter(b => !empBPs.some(bp => bp.brand_id === b.id)).map(b => ({ value: b.id, label: b.name }))} />
            </Form.Item>
            <Form.Item name="position_code" rules={[{ required: true }]}>
              <Select placeholder="岗位" style={{ width: 130 }}
                options={positions.map(p => ({ value: p.code, label: p.name }))} />
            </Form.Item>
            <Form.Item name="manufacturer_subsidy" initialValue={0}>
              <InputNumber min={0} addonBefore="补贴¥" style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="is_primary" valuePropName="checked">
              <Checkbox disabled={empBPs.length === 0}>设为主</Checkbox>
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={addBpMut.isPending}>添加</Button>
          </Form>
        </Card>
      </Modal>
    </>
  );
}

export default EmployeeList;
