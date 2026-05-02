/**
 * C 端用户列表（消费者）
 *
 * 筛选：状态 Tab / 推荐人 / 关键词（昵称手机用户名）
 * 操作：详情（弹抽屉）/ 换绑推荐人 / 启用 / 禁用
 */
import { useState } from 'react';
import {
  Button, Input, message, Modal, Select, Space, Table, Tabs, Tag, Tooltip, Typography,
} from 'antd';
import {
  StopOutlined, UnlockOutlined, SwapOutlined, EyeOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';
import ConsumerDetail from './ConsumerDetail';

const { Title } = Typography;

const STATUS: Record<string, { text: string; color: string }> = {
  active: { text: '正常', color: 'green' },
  disabled: { text: '已禁用', color: 'red' },
  inactive_archived: { text: '已归档', color: 'default' },
};

interface Consumer {
  id: string;
  username: string;
  nickname?: string;
  phone?: string;
  user_type: string;
  status: string;
  referrer_salesman_id?: string;
  referrer_nickname?: string;
  referrer_phone?: string;
  order_count: number;
  total_gmv: string;
  last_order_at?: string;
  archived_at?: string;
  created_at: string;
}

export default function ConsumerList() {
  const queryClient = useQueryClient();
  const [statusTab, setStatusTab] = useState('all');
  const [keyword, setKeyword] = useState('');
  const [referrerId, setReferrerId] = useState<string | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [rebindTarget, setRebindTarget] = useState<Consumer | null>(null);
  const [rebindNewId, setRebindNewId] = useState<string | undefined>();
  const [rebindReason, setRebindReason] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['mall-admin-consumers', statusTab, keyword, referrerId, page, pageSize],
    queryFn: () => api.get('/mall/admin/users', {
      params: {
        user_type: 'consumer',
        status: statusTab === 'all' ? undefined : statusTab,
        keyword: keyword || undefined,
        referrer_id: referrerId,
        skip: (page - 1) * pageSize,
        limit: pageSize,
      },
    }).then(r => r.data),
    refetchInterval: 30000,
  });
  const rows: Consumer[] = data?.records || [];
  const total: number = data?.total || 0;

  // 业务员下拉（换绑 + 筛选用）
  const { data: salesmenData } = useQuery({
    queryKey: ['mall-admin-users-salesmen'],
    queryFn: () => api.get('/mall/admin/users/_helpers/salesmen').then(r => r.data),
  });
  const salesmen = salesmenData?.records || [];

  const disableMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.post(`/mall/admin/users/${id}/disable`, { reason }),
    onSuccess: () => {
      message.success('已禁用（用户所有 token 失效）');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-consumers'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  const reactivateMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.post(`/mall/admin/users/${id}/reactivate`, { reason }),
    onSuccess: () => {
      message.success('已启用（last_order_at 已重置，有新的 3 个月观察期）');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-consumers'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  const rebindMut = useMutation({
    mutationFn: ({ id, new_referrer_id, reason }: any) =>
      api.put(`/mall/admin/users/${id}/referrer`, { new_referrer_id, reason }),
    onSuccess: () => {
      message.success('推荐人已更新');
      setRebindTarget(null);
      setRebindNewId(undefined);
      setRebindReason('');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-consumers'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  const columns: ColumnsType<Consumer> = [
    {
      title: '用户',
      key: 'user',
      width: 200,
      fixed: 'left' as const,
      render: (_, r) => (
        <div>
          <a onClick={() => setDetailId(r.id)} style={{ fontWeight: 500 }}>
            {r.nickname || r.username || '-'}
          </a>
          {r.phone && <div style={{ color: '#999', fontSize: 12 }}>{r.phone}</div>}
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => {
        const m = STATUS[v];
        return m ? <Tag color={m.color}>{m.text}</Tag> : v;
      },
    },
    {
      title: '推荐人',
      key: 'referrer',
      width: 140,
      render: (_, r) => r.referrer_nickname ? (
        <div>
          <div>{r.referrer_nickname}</div>
          {r.referrer_phone && <div style={{ color: '#999', fontSize: 12 }}>{r.referrer_phone}</div>}
        </div>
      ) : <Tag color="red">未绑定</Tag>,
    },
    {
      title: '订单',
      dataIndex: 'order_count',
      width: 80,
      align: 'right' as const,
      sorter: (a, b) => a.order_count - b.order_count,
      render: (v: number) => v > 0 ? <strong>{v}</strong> : <span style={{ color: '#ccc' }}>0</span>,
    },
    {
      title: '累计实收',
      dataIndex: 'total_gmv',
      width: 120,
      align: 'right' as const,
      sorter: (a, b) => Number(a.total_gmv) - Number(b.total_gmv),
      render: (v: string) => Number(v) > 0 ? `¥${Number(v).toLocaleString()}` : '-',
    },
    {
      title: '最近下单',
      dataIndex: 'last_order_at',
      width: 120,
      render: (v?: string) => v ? dayjs(v).format('MM-DD HH:mm') : <span style={{ color: '#ccc' }}>无</span>,
    },
    {
      title: '注册时间',
      dataIndex: 'created_at',
      width: 120,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD'),
    },
    {
      title: '归档时间',
      dataIndex: 'archived_at',
      width: 120,
      render: (v?: string) => v ? dayjs(v).format('YYYY-MM-DD') : '-',
    },
    {
      title: '操作',
      key: 'act',
      width: 220,
      fixed: 'right' as const,
      render: (_, r) => (
        <Space>
          <Tooltip title="详情">
            <Button size="small" icon={<EyeOutlined />} onClick={() => setDetailId(r.id)} />
          </Tooltip>
          <Tooltip title="换绑推荐人">
            <Button size="small" icon={<SwapOutlined />}
              onClick={() => {
                setRebindTarget(r);
                setRebindNewId(r.referrer_salesman_id);
                setRebindReason('');
              }}
            />
          </Tooltip>
          {r.status === 'active' ? (
            <Tooltip title="禁用">
              <Button size="small" danger icon={<StopOutlined />}
                onClick={() => {
                  let reason = '';
                  Modal.confirm({
                    title: `禁用 ${r.nickname || r.username}`,
                    content: (
                      <div>
                        <div style={{ marginBottom: 8, color: '#ff4d4f' }}>
                          用户所有 token 立即失效，无法登录
                        </div>
                        <Input.TextArea rows={2} placeholder="原因（必填，记审计）"
                          onChange={e => { reason = e.target.value; }}
                        />
                      </div>
                    ),
                    onOk: () => {
                      if (!reason.trim()) { message.warning('请填写原因'); return Promise.reject(); }
                      return disableMut.mutateAsync({ id: r.id, reason });
                    },
                  });
                }}
              />
            </Tooltip>
          ) : (
            <Tooltip title="启用">
              <Button size="small" type="primary" icon={<UnlockOutlined />}
                onClick={() => {
                  let reason = '';
                  Modal.confirm({
                    title: `启用 ${r.nickname || r.username}`,
                    content: (
                      <div>
                        <div style={{ marginBottom: 8 }}>
                          启用后：状态 → active，last_order_at 重置为 now（给新的 3 个月观察期，不立即再次归档）
                        </div>
                        <Input.TextArea rows={2} placeholder="原因（必填，记审计）"
                          onChange={e => { reason = e.target.value; }}
                        />
                      </div>
                    ),
                    onOk: () => {
                      if (!reason.trim()) { message.warning('请填写原因'); return Promise.reject(); }
                      return reactivateMut.mutateAsync({ id: r.id, reason });
                    },
                  });
                }}
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
      <Title level={4}>C 端用户（消费者）</Title>

      <Tabs
        activeKey={statusTab}
        onChange={(k) => { setStatusTab(k); setPage(1); }}
        items={TABS.map(t => ({ key: t.key, label: t.label }))}
      />

      <Space style={{ marginBottom: 16, flexWrap: 'wrap' }}>
        <Input.Search
          placeholder="昵称 / 手机 / 账号"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          onSearch={() => setPage(1)}
          allowClear
          style={{ width: 240 }}
        />
        <Select
          placeholder="按推荐人筛选"
          allowClear
          value={referrerId}
          onChange={(v) => { setReferrerId(v); setPage(1); }}
          showSearch
          style={{ width: 220 }}
          options={salesmen.map((s: any) => ({
            value: s.id,
            label: `${s.nickname || s.username}${s.phone ? ` · ${s.phone}` : ''}`,
          }))}
          filterOption={(input, option) =>
            (option?.label as string).toLowerCase().includes(input.toLowerCase())
          }
        />
      </Space>

      <Table
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={isLoading}
        size="middle"
        scroll={{ x: 1400 }}
        pagination={{
          current: page, pageSize, total,
          showTotal: t => `共 ${t} 人`,
          onChange: (p, s) => { setPage(p); setPageSize(s || 20); },
          pageSizeOptions: ['20', '50', '100'],
          showSizeChanger: true,
        }}
      />

      {detailId && (
        <ConsumerDetail
          userId={detailId}
          open={!!detailId}
          onClose={() => setDetailId(null)}
        />
      )}

      {/* 换绑推荐人 Modal */}
      <Modal
        title={`换绑推荐人 - ${rebindTarget?.nickname || rebindTarget?.username || ''}`}
        open={!!rebindTarget}
        onCancel={() => { setRebindTarget(null); setRebindNewId(undefined); setRebindReason(''); }}
        onOk={() => {
          if (!rebindTarget) return;
          if (!rebindReason.trim()) { message.warning('必须填原因'); return; }
          rebindMut.mutate({
            id: rebindTarget.id,
            new_referrer_id: rebindNewId || null,
            reason: rebindReason,
          });
        }}
        confirmLoading={rebindMut.isPending}
      >
        {rebindTarget && (
          <div>
            <div style={{ marginBottom: 12, color: '#666' }}>
              当前推荐人：<strong>{rebindTarget.referrer_nickname || '无'}</strong>
            </div>
            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4 }}>新推荐人（留空 = 解绑）：</div>
              <Select
                allowClear
                showSearch
                placeholder="选择业务员"
                value={rebindNewId}
                onChange={setRebindNewId}
                style={{ width: '100%' }}
                options={salesmen.map((s: any) => ({
                  value: s.id,
                  label: `${s.nickname || s.username}${s.phone ? ` · ${s.phone}` : ''}`,
                }))}
                filterOption={(input, option) =>
                  (option?.label as string).toLowerCase().includes(input.toLowerCase())
                }
              />
            </div>
            <div>
              <div style={{ marginBottom: 4 }}>原因（必填）：</div>
              <Input.TextArea
                rows={3}
                placeholder="例：原业务员离职；客户主动要求换人；客户投诉处理"
                value={rebindReason}
                onChange={e => setRebindReason(e.target.value)}
              />
            </div>
            <div style={{ marginTop: 12, fontSize: 12, color: '#ff4d4f' }}>
              换绑不影响历史订单的归属；仅影响后续新订单的默认分配
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
