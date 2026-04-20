import { useState } from 'react';
import { Button, Form, Input, message, Modal, Select, Space, Switch, Table, Tag } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';

interface UserItem {
  id: string; username: string; employee_id?: string; employee_name?: string;
  is_active: boolean; is_superuser: boolean; roles: string[]; created_at?: string;
}
interface RoleItem { id: string; code: string; name: string }

const ROLE_COLORS: Record<string, string> = {
  admin: 'red', boss: 'gold', finance: 'green', salesman: 'blue',
  warehouse: 'cyan', hr: 'purple', purchase: 'orange', manufacturer_staff: 'default',
};
const ROLE_LABELS: Record<string, string> = {
  admin: '管理员', boss: '老板', finance: '财务', salesman: '业务员',
  warehouse: '仓库', hr: '人事', purchase: '采购', manufacturer_staff: '厂家',
};

const ROLE_DESCRIPTIONS: Record<string, string> = {
  admin: '超级管理员，全系统可见 + 可操作',
  boss: '老板，全系统可见，资金调拨批准',
  finance: '财务，全品牌账/订单/审批；看不到总资金池和工资明细',
  hr: '人事，员工/工资/补贴/考勤/绩效',
  salesman: '业务员，只看自己订单/回款/客户/政策申请',
  sales_manager: '业务经理，看所属品牌全部业务数据',
  warehouse: '库管，授权仓库的出入库/采购收货',
  purchase: '采购，采购单/供应商/商品',
  manufacturer_staff: '厂家对接人，受限视图',
};

function UserList() {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<UserItem | null>(null);
  const [resetPwdUser, setResetPwdUser] = useState<UserItem | null>(null);
  const [newPassword, setNewPassword] = useState('');

  const { data: users = [], isLoading } = useQuery<UserItem[]>({
    queryKey: ['users'],
    queryFn: () => api.get('/auth/users').then(r => r.data),
  });

  const { data: roles = [] } = useQuery<RoleItem[]>({
    queryKey: ['roles'],
    queryFn: () => api.get('/auth/roles').then(r => r.data),
  });

  const { data: employees = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ['employees-select'],
    queryFn: () => api.get('/hr/employees').then(r => r.data),
  });

  const createMut = useMutation({
    mutationFn: (values: any) => api.post('/auth/users', values),
    onSuccess: () => { message.success('用户创建成功'); queryClient.invalidateQueries({ queryKey: ['users'] }); setModalOpen(false); form.resetFields(); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, ...values }: any) => api.put(`/auth/users/${id}`, values),
    onSuccess: () => { message.success('更新成功'); queryClient.invalidateQueries({ queryKey: ['users'] }); setModalOpen(false); setEditingUser(null); form.resetFields(); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '更新失败'),
  });

  const setRolesMut = useMutation({
    mutationFn: ({ userId, role_codes }: { userId: string; role_codes: string[] }) =>
      api.put(`/auth/users/${userId}/roles`, { role_codes }),
    onSuccess: () => { message.success('角色已更新'); queryClient.invalidateQueries({ queryKey: ['users'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '更新角色失败'),
  });

  const resetPwdMut = useMutation({
    mutationFn: ({ userId, new_password }: { userId: string; new_password: string }) =>
      api.post(`/auth/users/${userId}/reset-password`, { new_password }),
    onSuccess: () => { message.success('密码已重置'); setResetPwdUser(null); setNewPassword(''); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '重置失败'),
  });

  const handleOk = () => {
    form.validateFields().then(values => {
      if (editingUser) {
        const { password, role_codes, ...rest } = values;
        updateMut.mutate({ id: editingUser.id, ...rest });
        if (role_codes) setRolesMut.mutate({ userId: editingUser.id, role_codes });
      } else {
        createMut.mutate(values);
      }
    });
  };

  const handleEdit = (record: UserItem) => {
    setEditingUser(record);
    form.setFieldsValue({
      username: record.username,
      employee_id: record.employee_id,
      is_active: record.is_active,
      role_codes: record.roles,
    });
    setModalOpen(true);
  };

  const columns: ColumnsType<UserItem> = [
    { title: '用户名', dataIndex: 'username', width: 120 },
    { title: '关联员工', dataIndex: 'employee_name', width: 100, render: (v: string) => v ?? <Tag>未关联</Tag> },
    {
      title: '角色', dataIndex: 'roles', width: 200,
      render: (roles: string[]) => roles.map(r => (
        <Tag key={r} color={ROLE_COLORS[r] || 'default'}>{ROLE_LABELS[r] || r}</Tag>
      )),
    },
    {
      title: '状态', dataIndex: 'is_active', width: 80,
      render: (v: boolean) => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v: string) => v?.slice(0, 19).replace('T', ' ') },
    {
      title: '操作', key: 'action', width: 160,
      render: (_, record) => (
        <Space>
          <a onClick={() => handleEdit(record)}>编辑</a>
          <a style={{ color: '#fa8c16' }} onClick={() => setResetPwdUser(record)}>重置密码</a>
        </Space>
      ),
    },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>用户管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingUser(null); form.resetFields(); form.setFieldsValue({ is_active: true }); setModalOpen(true); }}>新建用户</Button>
      </div>

      <Table<UserItem> columns={columns} dataSource={users} rowKey="id" loading={isLoading} pagination={{ pageSize: 20 }} />

      {/* 新建/编辑弹窗 */}
      <Modal title={editingUser ? '编辑用户' : '新建用户'} open={modalOpen}
        onOk={handleOk} onCancel={() => { setModalOpen(false); setEditingUser(null); form.resetFields(); }}
        confirmLoading={createMut.isPending || updateMut.isPending} okText="确认" cancelText="取消" destroyOnHidden>
        <Form form={form} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input placeholder="登录用户名" />
          </Form.Item>
          {!editingUser && (
            <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password placeholder="初始密码" />
            </Form.Item>
          )}
          <Form.Item name="employee_id" label="关联员工">
            <Select allowClear showSearch optionFilterProp="label" placeholder="选择员工（可不关联）"
              options={employees.map((e: any) => ({ value: e.id, label: e.name }))} />
          </Form.Item>
          <Form.Item
            name="role_codes"
            label="角色（权限）"
            rules={[{ required: true, message: '至少选择一个角色，否则该账号无权访问任何功能' }]}
            tooltip="同一账号可指定多个角色，权限并集。admin 拥有一切权限。"
          >
            <Select
              mode="multiple"
              placeholder="为该账号分配角色"
              optionLabelProp="label"
              options={roles.map(r => ({
                value: r.code,
                label: ROLE_LABELS[r.code] || r.name,
                optionLabel: (
                  <div>
                    <Tag color={ROLE_COLORS[r.code] || 'default'}>{ROLE_LABELS[r.code] || r.name}</Tag>
                    <span style={{ fontSize: 12, color: '#666', marginLeft: 8 }}>
                      {ROLE_DESCRIPTIONS[r.code] || ''}
                    </span>
                  </div>
                ),
              }))}
              optionRender={(opt) => (opt.data as any).optionLabel}
            />
          </Form.Item>
          {editingUser && (
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="停用" />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 重置密码弹窗 */}
      <Modal title={`重置密码 — ${resetPwdUser?.username}`} open={!!resetPwdUser}
        onOk={() => { if (resetPwdUser && newPassword) resetPwdMut.mutate({ userId: resetPwdUser.id, new_password: newPassword }); }}
        onCancel={() => { setResetPwdUser(null); setNewPassword(''); }}
        confirmLoading={resetPwdMut.isPending} okText="确认重置" okButtonProps={{ danger: true }}>
        <Input.Password placeholder="输入新密码" value={newPassword} onChange={e => setNewPassword(e.target.value)} />
      </Modal>
    </>
  );
}

export default UserList;
