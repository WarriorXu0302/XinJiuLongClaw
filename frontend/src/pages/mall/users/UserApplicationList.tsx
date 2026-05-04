/**
 * 商城用户注册审批列表
 *
 * Tab：待审批 / 已通过 / 已驳回 / 全部
 * 详情抽屉：营业执照大图 + 资料 + 通过/驳回按钮
 */
import { useState } from 'react';
import {
  Button, Drawer, Empty, Image, Input, message, Modal, Space, Table, Tabs, Tag, Typography,
} from 'antd';
import { CheckOutlined, EyeOutlined, StopOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title } = Typography;

const STATUS: Record<string, { text: string; color: string }> = {
  pending: { text: '待审批', color: 'orange' },
  approved: { text: '已通过', color: 'green' },
  rejected: { text: '已驳回', color: 'red' },
};

interface Application {
  id: string;
  application_status: string;
  username?: string;
  nickname?: string;
  real_name?: string;
  contact_phone?: string;
  delivery_address?: string;
  business_license_url?: string;
  rejection_reason?: string;
  approved_at?: string;
  approved_by_employee_id?: string;
  referrer_salesman?: { id: string; nickname?: string; phone?: string };
  created_at: string;
}

export default function UserApplicationList() {
  const queryClient = useQueryClient();
  const [statusTab, setStatusTab] = useState<string>('pending');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [detail, setDetail] = useState<Application | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['mall-admin-user-applications', statusTab, page, pageSize],
    queryFn: () => api.get('/mall/admin/user-applications', {
      params: {
        status: statusTab === 'all' ? undefined : statusTab,
        skip: (page - 1) * pageSize,
        limit: pageSize,
      },
    }).then(r => r.data),
    refetchInterval: 15000,
  });
  const rows: Application[] = data?.records || [];
  const total: number = data?.total || 0;

  const approveMut = useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) =>
      api.post(`/mall/admin/user-applications/${id}/approve`, { note }),
    onSuccess: () => {
      message.success('已通过审批，用户可登录');
      setDetail(null);
      queryClient.invalidateQueries({ queryKey: ['mall-admin-user-applications'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '审批失败'),
  });

  const rejectMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.post(`/mall/admin/user-applications/${id}/reject`, { reason }),
    onSuccess: () => {
      message.success('已驳回，邀请码已自动作废');
      setDetail(null);
      queryClient.invalidateQueries({ queryKey: ['mall-admin-user-applications'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '驳回失败'),
  });

  const columns: ColumnsType<Application> = [
    {
      title: '姓名/账号', key: 'name', width: 160,
      render: (_, r) => (
        <div>
          <div><strong>{r.real_name || r.nickname || '-'}</strong></div>
          {r.username && <div style={{ color: '#999', fontSize: 12 }}>账号 {r.username}</div>}
        </div>
      ),
    },
    { title: '联系电话', dataIndex: 'contact_phone', width: 140 },
    { title: '配送地址', dataIndex: 'delivery_address', ellipsis: true },
    {
      title: '推荐业务员', key: 'ref', width: 150,
      render: (_, r) => r.referrer_salesman ? (
        <div>
          <div>{r.referrer_salesman.nickname || '-'}</div>
          {r.referrer_salesman.phone && (
            <div style={{ color: '#999', fontSize: 12 }}>{r.referrer_salesman.phone}</div>
          )}
        </div>
      ) : '-',
    },
    {
      title: '状态', dataIndex: 'application_status', width: 100,
      render: (v: string) => <Tag color={STATUS[v]?.color}>{STATUS[v]?.text || v}</Tag>,
    },
    {
      title: '提交时间', dataIndex: 'created_at', width: 160,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作', key: 'act', width: 100, fixed: 'right' as const,
      render: (_, r) => (
        <Button size="small" icon={<EyeOutlined />} onClick={() => setDetail(r)}>
          查看
        </Button>
      ),
    },
  ];

  const TABS = [
    { key: 'pending', label: '待审批' },
    { key: 'approved', label: '已通过' },
    { key: 'rejected', label: '已驳回' },
    { key: 'all', label: '全部' },
  ];

  return (
    <div>
      <Title level={4}>商城注册审批</Title>
      <Tabs
        activeKey={statusTab}
        onChange={(k) => { setStatusTab(k); setPage(1); }}
        items={TABS.map(t => ({ key: t.key, label: t.label }))}
      />
      <Table
        dataSource={rows}
        rowKey="id"
        columns={columns}
        loading={isLoading}
        pagination={{
          current: page,
          pageSize,
          total,
          onChange: (p, s) => { setPage(p); setPageSize(s); },
          showSizeChanger: true,
        }}
        scroll={{ x: 1100 }}
        locale={{ emptyText: <Empty description="暂无申请" /> }}
      />

      {/* 详情抽屉 */}
      <Drawer
        title="注册申请详情"
        open={!!detail}
        onClose={() => setDetail(null)}
        size={720}
      >
        {detail && (
          <div>
            <Space orientation="vertical" size="large" style={{ width: '100%' }}>
              <div>
                <strong>状态：</strong>
                <Tag color={STATUS[detail.application_status]?.color}>
                  {STATUS[detail.application_status]?.text}
                </Tag>
              </div>

              <div>
                <strong>真实姓名：</strong>{detail.real_name || '-'}
              </div>
              <div>
                <strong>联系电话：</strong>{detail.contact_phone || '-'}
              </div>
              <div>
                <strong>配送地址：</strong>{detail.delivery_address || '-'}
              </div>
              <div>
                <strong>账号：</strong>{detail.username || '（微信注册）'}
              </div>
              <div>
                <strong>推荐业务员：</strong>
                {detail.referrer_salesman ? (
                  <span>
                    {detail.referrer_salesman.nickname}
                    {detail.referrer_salesman.phone && ` · ${detail.referrer_salesman.phone}`}
                  </span>
                ) : '-'}
              </div>
              <div>
                <strong>提交时间：</strong>
                {dayjs(detail.created_at).format('YYYY-MM-DD HH:mm:ss')}
              </div>

              <div>
                <strong>营业执照：</strong>
                {detail.business_license_url ? (
                  <div style={{ marginTop: 8 }}>
                    <Image src={detail.business_license_url} width={360} />
                  </div>
                ) : <span style={{ color: '#999' }}> 未上传</span>}
              </div>

              {detail.application_status === 'rejected' && detail.rejection_reason && (
                <div style={{ background: '#fff1f0', padding: 12, borderRadius: 4 }}>
                  <strong>驳回原因：</strong>{detail.rejection_reason}
                </div>
              )}

              {detail.application_status === 'approved' && detail.approved_at && (
                <div style={{ color: '#52c41a' }}>
                  <strong>通过时间：</strong>
                  {dayjs(detail.approved_at).format('YYYY-MM-DD HH:mm:ss')}
                </div>
              )}

              {detail.application_status === 'pending' && (
                <Space style={{ marginTop: 24 }}>
                  <Button
                    type="primary"
                    icon={<CheckOutlined />}
                    loading={approveMut.isPending}
                    onClick={() => Modal.confirm({
                      title: `通过 ${detail.real_name} 的注册申请？`,
                      content: '通过后用户可立即登录使用',
                      onOk: () => approveMut.mutateAsync({ id: detail.id }),
                    })}
                  >
                    通过
                  </Button>
                  <Button
                    danger
                    icon={<StopOutlined />}
                    loading={rejectMut.isPending}
                    onClick={() => {
                      let reason = '';
                      Modal.confirm({
                        title: `驳回 ${detail.real_name} 的注册申请？`,
                        content: (
                          <div>
                            <div style={{ color: '#ff4d4f', marginBottom: 8 }}>
                              驳回后邀请码将自动作废，用户需重新向业务员索取新码。
                            </div>
                            <Input.TextArea
                              rows={3}
                              placeholder="驳回原因（必填，会通知用户）"
                              onChange={e => { reason = e.target.value; }}
                            />
                          </div>
                        ),
                        onOk: () => {
                          if (!reason.trim()) {
                            message.warning('请填写驳回原因');
                            return Promise.reject();
                          }
                          return rejectMut.mutateAsync({ id: detail.id, reason });
                        },
                      });
                    }}
                  >
                    驳回
                  </Button>
                </Space>
              )}
            </Space>
          </div>
        )}
      </Drawer>
    </div>
  );
}
