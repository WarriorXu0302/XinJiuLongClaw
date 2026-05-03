/**
 * 商城业务员管理
 *
 * 列表 + 新建 Modal + 编辑 Modal + 重置密码 Modal + 禁用/启用
 */
import { useState } from 'react';
import {
  Button, Form, Input, message, Modal, Select, Space, Switch, Table, Tabs, Tag, Tooltip, Typography,
} from 'antd';
import { PlusOutlined, KeyOutlined, EditOutlined, StopOutlined, UnlockOutlined, SwapOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title } = Typography;

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  active: { text: '正常', color: 'green' },
  disabled: { text: '已禁用', color: 'red' },
  inactive_archived: { text: '已归档', color: 'default' },
};

interface Salesman {
  id: string;
  username: string;
  nickname?: string;
  phone?: string;
  status: string;
  linked_employee_id?: string;
  assigned_brand_id?: string;
  assigned_store_id?: string;
  is_accepting_orders: boolean;
  must_change_password: boolean;
  created_at: string;
  employee?: { id: string; name: string; status: string };
  brand?: { id: string; name: string };
}

interface StoreWarehouse {
  id: string; code: string; name: string;
  warehouse_type: string; is_active: boolean;
}

export default function SalesmanList() {
  const queryClient = useQueryClient();
  const [statusTab, setStatusTab] = useState<string>('all');
  const [keyword, setKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Salesman | null>(null);
  const [resetTarget, setResetTarget] = useState<Salesman | null>(null);
  const [rebindTarget, setRebindTarget] = useState<Salesman | null>(null);
  const [createdInfo, setCreatedInfo] = useState<{ username: string; password: string } | null>(null);

  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [resetForm] = Form.useForm();
  const [rebindForm] = Form.useForm();

  const { data, isLoading } = useQuery({
    queryKey: ['mall-admin-salesmen', statusTab, keyword, page, pageSize],
    queryFn: () => api.get('/mall/admin/salesmen', {
      params: {
        status: statusTab === 'all' ? undefined : statusTab,
        keyword: keyword || undefined,
        skip: (page - 1) * pageSize,
        limit: pageSize,
      },
    }).then(r => r.data),
  });
  const rows: Salesman[] = data?.records || [];
  const total: number = data?.total || 0;

  const { data: employeeData } = useQuery({
    queryKey: ['mall-admin-bindable-employees'],
    queryFn: () => api.get('/mall/admin/salesmen/_helpers/employees').then(r => r.data),
    enabled: createOpen || !!rebindTarget,
  });
  const { data: brandData } = useQuery({
    queryKey: ['mall-admin-brands'],
    queryFn: () => api.get('/mall/admin/salesmen/_helpers/brands').then(r => r.data),
    enabled: createOpen || !!editTarget,
  });
  // 门店仓（warehouse_type=store）—— 店员可选归属门店
  const { data: storeData = [] } = useQuery<StoreWarehouse[]>({
    queryKey: ['warehouses-for-salesman-store'],
    queryFn: async () => {
      const r = await api.get('/warehouses');
      const items = (r.data?.items || r.data || []) as StoreWarehouse[];
      return items.filter(w => w.warehouse_type === 'store' && w.is_active);
    },
    enabled: createOpen || !!editTarget,
  });
  const storeNameById: Record<string, string> = {};
  storeData.forEach(w => { storeNameById[w.id] = w.name; });

  const createMut = useMutation({
    mutationFn: (body: any) => api.post('/mall/admin/salesmen', body).then(r => r.data),
    onSuccess: (res, variables: any) => {
      message.success('创建成功');
      setCreateOpen(false);
      createForm.resetFields();
      setCreatedInfo({ username: res.username, password: variables.password });
      queryClient.invalidateQueries({ queryKey: ['mall-admin-salesmen'] });
      queryClient.invalidateQueries({ queryKey: ['mall-admin-bindable-employees'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: any }) =>
      api.put(`/mall/admin/salesmen/${id}`, body),
    onSuccess: () => {
      message.success('已更新');
      setEditTarget(null);
      queryClient.invalidateQueries({ queryKey: ['mall-admin-salesmen'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '更新失败'),
  });

  const disableMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.post(`/mall/admin/salesmen/${id}/disable`, { reason }),
    onSuccess: () => {
      message.success('已禁用（该业务员所有 token 已失效）');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-salesmen'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '禁用失败'),
  });

  const enableMut = useMutation({
    mutationFn: (id: string) => api.post(`/mall/admin/salesmen/${id}/enable`, {}),
    onSuccess: () => {
      message.success('已启用');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-salesmen'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '启用失败'),
  });

  const resetPwdMut = useMutation({
    mutationFn: ({ id, new_password }: { id: string; new_password: string }) =>
      api.put(`/mall/admin/salesmen/${id}/reset-password`, { new_password }),
    onSuccess: (_, variables) => {
      message.success('已重置密码（新密码请告知业务员）');
      setResetTarget(null);
      setCreatedInfo({ username: resetTarget!.username, password: variables.new_password });
      resetForm.resetFields();
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '重置失败'),
  });

  const toggleAcceptingMut = useMutation({
    mutationFn: ({ id, value }: { id: string; value: boolean }) =>
      api.put(`/mall/admin/salesmen/${id}`, { is_accepting_orders: value }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mall-admin-salesmen'] });
    },
  });

  const rebindMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: any }) =>
      api.put(`/mall/admin/salesmen/${id}/rebind-employee`, body).then(r => r.data),
    onSuccess: () => {
      message.success('换绑成功，该业务员 token 已失效需重新登录');
      setRebindTarget(null);
      rebindForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['mall-admin-salesmen'] });
      queryClient.invalidateQueries({ queryKey: ['mall-admin-bindable-employees'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '换绑失败'),
  });

  const columns: ColumnsType<Salesman> = [
    {
      title: '账号',
      dataIndex: 'username',
      width: 140,
      render: (v, r) => (
        <div>
          <strong>{v}</strong>
          {r.must_change_password && <Tag color="orange" style={{ marginLeft: 6 }}>未改密</Tag>}
        </div>
      ),
    },
    { title: '昵称', dataIndex: 'nickname', width: 120 },
    { title: '手机', dataIndex: 'phone', width: 130 },
    {
      title: '关联员工',
      key: 'emp',
      width: 140,
      render: (_, r) => r.employee ? (
        <div>
          <div>{r.employee.name}</div>
          <Tag color={r.employee.status === 'active' ? 'green' : 'red'} style={{ fontSize: 11 }}>
            {r.employee.status === 'active' ? '在职' : '离职'}
          </Tag>
        </div>
      ) : <Tag color="red">未绑定</Tag>,
    },
    {
      title: '主属品牌',
      key: 'brand',
      width: 100,
      render: (_, r) => r.brand ? <Tag color="blue">{r.brand.name}</Tag> : '-',
    },
    {
      title: '归属门店',
      dataIndex: 'assigned_store_id',
      width: 140,
      render: (v: string | undefined) => v ? <Tag color="gold">{storeNameById[v] || v.slice(0, 8)}</Tag> : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => {
        const m = STATUS_LABEL[v];
        return m ? <Tag color={m.color}>{m.text}</Tag> : v;
      },
    },
    {
      title: '接单开关',
      dataIndex: 'is_accepting_orders',
      width: 100,
      render: (v: boolean, r) => (
        <Switch
          checked={v}
          disabled={r.status !== 'active'}
          onChange={(checked) => toggleAcceptingMut.mutate({ id: r.id, value: checked })}
        />
      ),
    },
    {
      title: '注册时间',
      dataIndex: 'created_at',
      width: 150,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'act',
      width: 260,
      fixed: 'right' as const,
      render: (_, r) => (
        <Space>
          <Tooltip title="编辑">
            <Button size="small" icon={<EditOutlined />}
              onClick={() => {
                setEditTarget(r);
                editForm.setFieldsValue({
                  nickname: r.nickname,
                  phone: r.phone,
                  assigned_brand_id: r.assigned_brand_id,
                  assigned_store_id: r.assigned_store_id,
                });
              }}
            />
          </Tooltip>
          <Tooltip title="重置密码">
            <Button size="small" icon={<KeyOutlined />}
              onClick={() => { setResetTarget(r); resetForm.resetFields(); }}
            />
          </Tooltip>
          <Tooltip title="换绑 ERP 员工">
            <Button size="small" icon={<SwapOutlined />}
              onClick={() => { setRebindTarget(r); rebindForm.resetFields(); }}
            />
          </Tooltip>
          {r.status === 'active' ? (
            <Tooltip title="禁用（立即踢下线）">
              <Button size="small" danger icon={<StopOutlined />}
                onClick={() => {
                  let reason = '';
                  Modal.confirm({
                    title: `禁用 ${r.nickname || r.username}`,
                    content: (
                      <div>
                        <div style={{ marginBottom: 8, color: '#ff4d4f' }}>
                          禁用后该业务员所有在途 token 立即失效，无法登录
                        </div>
                        <Input.TextArea rows={2} placeholder="原因（记入审计，可选）"
                          onChange={e => { reason = e.target.value; }} />
                      </div>
                    ),
                    onOk: () => disableMut.mutateAsync({ id: r.id, reason }),
                  });
                }}
              />
            </Tooltip>
          ) : (
            <Tooltip title="启用">
              <Button size="small" type="primary" icon={<UnlockOutlined />}
                onClick={() => Modal.confirm({
                  title: `启用 ${r.nickname || r.username}？`,
                  onOk: () => enableMut.mutateAsync(r.id),
                })}
              />
            </Tooltip>
          )}
        </Space>
      ),
    },
  ];

  const TABS = [
    { key: 'all', label: '全部' },
    { key: 'active', label: '正常' },
    { key: 'disabled', label: '已禁用' },
    { key: 'inactive_archived', label: '已归档' },
  ];

  return (
    <div>
      <Title level={4}>商城业务员</Title>

      <Tabs
        activeKey={statusTab}
        onChange={(k) => { setStatusTab(k); setPage(1); }}
        items={TABS.map(t => ({ key: t.key, label: t.label }))}
      />

      <Space style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="昵称 / 手机 / 账号"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          onSearch={() => setPage(1)}
          allowClear
          style={{ width: 240 }}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={() => {
          createForm.resetFields();
          setCreateOpen(true);
        }}>新建业务员</Button>
      </Space>

      <Table
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={isLoading}
        size="middle"
        scroll={{ x: 1300 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showTotal: t => `共 ${t} 人`,
          onChange: (p, s) => { setPage(p); setPageSize(s || 20); },
          pageSizeOptions: ['20', '50', '100'],
          showSizeChanger: true,
        }}
      />

      {/* 新建 */}
      <Modal
        title="新建业务员"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => {
          createForm.validateFields().then((values: any) => {
            createMut.mutate(values);
          });
        }}
        confirmLoading={createMut.isPending}
        width={520}
      >
        <Form form={createForm} layout="vertical" preserve={false}>
          <Form.Item name="linked_employee_id" label="关联 ERP 员工（必填）"
            rules={[{ required: true, message: '请选择员工' }]}
            extra="业务员必须绑定到 ERP 在职员工（唯一）"
          >
            <Select
              showSearch
              placeholder="搜索员工姓名"
              options={(employeeData?.records || []).map((e: any) => ({
                value: e.id,
                label: `${e.name}${e.phone ? ` · ${e.phone}` : ''}`,
              }))}
              filterOption={(input, option) =>
                (option?.label as string).toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
          <Form.Item name="username" label="登录账号（必填）"
            rules={[
              { required: true, min: 3, max: 50, message: '3-50 字符' },
              { pattern: /^[a-zA-Z0-9_]+$/, message: '仅英文/数字/下划线' },
            ]}
          >
            <Input placeholder="如 zhangsan" />
          </Form.Item>
          <Form.Item name="password" label="初始密码（必填）"
            rules={[{ required: true, min: 6, message: '至少 6 位' }]}
            extra="业务员首次登录后会被强制修改"
          >
            <Input.Password placeholder="建议 8 位以上" />
          </Form.Item>
          <Form.Item name="nickname" label="昵称（可选，留空用员工姓名）">
            <Input />
          </Form.Item>
          <Form.Item name="phone" label="手机（可选）">
            <Input />
          </Form.Item>
          <Form.Item name="assigned_brand_id" label="主属品牌（可选）"
            extra="影响提成率查询顺序"
          >
            <Select
              allowClear
              placeholder="选择品牌"
              options={(brandData?.records || []).map((b: any) => ({
                value: b.id, label: b.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="assigned_store_id" label="归属门店（店员必填，否则留空）"
            extra="专卖店店员填；小程序端据此显示「门店收银」入口"
          >
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="非店员留空"
              options={storeData.map(w => ({
                value: w.id, label: `${w.name} [${w.code}]`,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑 */}
      <Modal
        title={`编辑业务员 ${editTarget?.nickname || editTarget?.username || ''}`}
        open={!!editTarget}
        onCancel={() => setEditTarget(null)}
        onOk={() => {
          if (!editTarget) return;
          editForm.validateFields().then((values: any) => {
            updateMut.mutate({ id: editTarget.id, body: values });
          });
        }}
        confirmLoading={updateMut.isPending}
        width={480}
      >
        <Form form={editForm} layout="vertical" preserve={false}>
          <Form.Item name="nickname" label="昵称">
            <Input />
          </Form.Item>
          <Form.Item name="phone" label="手机">
            <Input />
          </Form.Item>
          <Form.Item name="assigned_brand_id" label="主属品牌">
            <Select
              allowClear
              placeholder="选择品牌"
              options={(brandData?.records || []).map((b: any) => ({
                value: b.id, label: b.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="assigned_store_id" label="归属门店"
            extra="切换此字段会同步更新 Employee.assigned_store_id"
          >
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="非店员留空"
              options={storeData.map(w => ({
                value: w.id, label: `${w.name} [${w.code}]`,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 换绑 ERP 员工 */}
      <Modal
        title={`换绑 ERP 员工 - ${rebindTarget?.nickname || rebindTarget?.username || ''}`}
        open={!!rebindTarget}
        onCancel={() => setRebindTarget(null)}
        onOk={() => {
          if (!rebindTarget) return;
          rebindForm.validateFields().then((v: any) => {
            rebindMut.mutate({ id: rebindTarget.id, body: v });
          });
        }}
        confirmLoading={rebindMut.isPending}
        width={560}
      >
        <div style={{ background: '#fffbe6', padding: 12, borderRadius: 4, marginBottom: 16, fontSize: 13 }}>
          <div><strong>当前绑定：</strong>{rebindTarget?.employee?.name ?? '未绑定'}</div>
          <div style={{ marginTop: 4, color: '#8c8c8c' }}>
            换绑条件：该业务员无在途订单（后端会校验）；换绑后其 token 立即失效，必须重新登录。
          </div>
        </div>
        <Form form={rebindForm} layout="vertical" preserve={false}>
          <Form.Item
            name="new_employee_id"
            label="新 ERP 员工（必填）"
            rules={[{ required: true, message: '请选择员工' }]}
          >
            <Select
              showSearch
              placeholder="搜索员工姓名"
              options={(employeeData?.records || [])
                .filter((e: any) => e.id !== rebindTarget?.linked_employee_id)
                .map((e: any) => ({
                  value: e.id,
                  label: `${e.name}${e.phone ? ` · ${e.phone}` : ''}`,
                }))}
              filterOption={(input, option) =>
                (option?.label as string).toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
          <Form.Item
            name="reason"
            label="换绑原因（必填，记入审计）"
            rules={[{ required: true, min: 1, max: 500 }]}
          >
            <Input.TextArea rows={3} placeholder="如：建号时选错员工、业务员调岗合并档案等" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 重置密码 */}
      <Modal
        title={`重置密码 - ${resetTarget?.nickname || resetTarget?.username || ''}`}
        open={!!resetTarget}
        onCancel={() => setResetTarget(null)}
        onOk={() => {
          if (!resetTarget) return;
          resetForm.validateFields().then((v: any) => {
            resetPwdMut.mutate({ id: resetTarget.id, new_password: v.new_password });
          });
        }}
        confirmLoading={resetPwdMut.isPending}
        width={480}
      >
        <Form form={resetForm} layout="vertical" preserve={false}>
          <Form.Item name="new_password" label="新密码"
            rules={[{ required: true, min: 6, message: '至少 6 位' }]}
            extra="重置后该业务员所有在途 token 立即失效，首次登录需修改"
          >
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>

      {/* 创建/重置成功后展示账号密码（供 HR 复制给业务员）*/}
      <Modal
        title="账号信息"
        open={!!createdInfo}
        onCancel={() => setCreatedInfo(null)}
        footer={[<Button key="ok" type="primary" onClick={() => setCreatedInfo(null)}>我已记录</Button>]}
      >
        <div style={{ padding: '16px 0' }}>
          <p>请将以下信息告知业务员，首次登录会强制修改密码：</p>
          <div style={{ background: '#fffbe6', padding: 16, borderRadius: 4, fontSize: 16 }}>
            <div>账号：<strong>{createdInfo?.username}</strong></div>
            <div style={{ marginTop: 8 }}>密码：<strong>{createdInfo?.password}</strong></div>
          </div>
          <p style={{ marginTop: 12, color: '#ff4d4f', fontSize: 12 }}>
            关闭此窗口后将无法再次查看密码
          </p>
        </div>
      </Modal>
    </div>
  );
}
