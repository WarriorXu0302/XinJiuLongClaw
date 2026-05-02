/**
 * 邀请码查询
 *
 * 列表：码 / 状态 / 签发业务员 / 使用人 / 签发时间 / 过期时间
 * 统计：按业务员分组看近 7 天签发/使用/作废/使用率
 * 操作：作废异常码（仅 active 可作废）
 */
import { useState } from 'react';
import {
  Button, Card, Col, DatePicker, Input, InputNumber, message, Modal, Row, Select, Space,
  Statistic, Table, Tabs, Tag, Tooltip, Typography,
} from 'antd';
import { StopOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

const STATUS: Record<string, { text: string; color: string }> = {
  active: { text: '可用', color: 'green' },
  used: { text: '已使用', color: 'blue' },
  expired: { text: '已过期', color: 'default' },
  invalidated: { text: '已作废', color: 'red' },
};

interface Code {
  id: string;
  code: string;
  status: string;
  issuer?: { id: string; nickname?: string; phone?: string };
  used_by?: { id: string; nickname?: string; phone?: string };
  created_at: string;
  expires_at: string;
  used_at?: string;
  invalidated_at?: string;
  invalidated_reason?: string;
}

interface StatRow {
  issuer_id: string;
  issuer_nickname?: string;
  issuer_phone?: string;
  issued: number;
  used: number;
  invalidated: number;
  valid_issued: number;
  usage_rate: number;
}

export default function InviteCodeList() {
  const queryClient = useQueryClient();
  const [statusTab, setStatusTab] = useState('all');
  const [code, setCode] = useState('');
  const [issuerId, setIssuerId] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [statsDays, setStatsDays] = useState(7);

  const { data, isLoading } = useQuery({
    queryKey: ['mall-invite-codes', statusTab, code, issuerId, dateRange, page, pageSize],
    queryFn: () => api.get('/mall/admin/invite-codes', {
      params: {
        status: statusTab === 'all' ? undefined : statusTab,
        code: code || undefined,
        issuer_id: issuerId,
        date_from: dateRange?.[0].format('YYYY-MM-DD'),
        date_to: dateRange?.[1].format('YYYY-MM-DD'),
        skip: (page - 1) * pageSize,
        limit: pageSize,
      },
    }).then(r => r.data),
  });
  const rows: Code[] = data?.records || [];
  const total: number = data?.total || 0;

  const { data: statsData } = useQuery({
    queryKey: ['mall-invite-code-stats', statsDays],
    queryFn: () => api.get('/mall/admin/invite-codes/stats', { params: { days: statsDays } })
      .then(r => r.data),
  });
  const stats: StatRow[] = statsData?.records || [];

  // 业务员下拉（复用 users helper）
  const { data: salesmenData } = useQuery({
    queryKey: ['mall-admin-users-salesmen'],
    queryFn: () => api.get('/mall/admin/users/_helpers/salesmen').then(r => r.data),
  });
  const salesmen = salesmenData?.records || [];

  const invalidateMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.post(`/mall/admin/invite-codes/${id}/invalidate`, { reason }),
    onSuccess: () => {
      message.success('已作废');
      queryClient.invalidateQueries({ queryKey: ['mall-invite-codes'] });
      queryClient.invalidateQueries({ queryKey: ['mall-invite-code-stats'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  // 统计聚合
  const statsAgg = stats.reduce(
    (acc, r) => ({
      issued: acc.issued + r.issued,
      used: acc.used + r.used,
      invalidated: acc.invalidated + r.invalidated,
    }),
    { issued: 0, used: 0, invalidated: 0 }
  );
  const globalRate = statsAgg.issued > 0
    ? (statsAgg.used / statsAgg.issued * 100).toFixed(1)
    : '0';

  const columns: ColumnsType<Code> = [
    {
      title: '邀请码',
      dataIndex: 'code',
      width: 120,
      fixed: 'left' as const,
      render: (v) => <Text code copyable>{v}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v) => {
        const m = STATUS[v];
        return m ? <Tag color={m.color}>{m.text}</Tag> : v;
      },
    },
    {
      title: '签发业务员',
      key: 'issuer',
      width: 160,
      render: (_, r) => r.issuer ? (
        <div>
          <div>{r.issuer.nickname || '-'}</div>
          {r.issuer.phone && <div style={{ color: '#999', fontSize: 12 }}>{r.issuer.phone}</div>}
        </div>
      ) : '-',
    },
    {
      title: '使用者',
      key: 'used_by',
      width: 180,
      render: (_, r) => r.used_by ? (
        <div>
          <div>{r.used_by.nickname || '-'}</div>
          {r.used_by.phone && <div style={{ color: '#999', fontSize: 12 }}>{r.used_by.phone}</div>}
          {r.used_at && (
            <div style={{ color: '#999', fontSize: 12 }}>
              {dayjs(r.used_at).format('YYYY-MM-DD HH:mm')}
            </div>
          )}
        </div>
      ) : <span style={{ color: '#ccc' }}>-</span>,
    },
    {
      title: '签发时间',
      dataIndex: 'created_at',
      width: 150,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '过期时间',
      dataIndex: 'expires_at',
      width: 150,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '作废原因',
      dataIndex: 'invalidated_reason',
      ellipsis: true,
      render: (v) => v || <span style={{ color: '#ccc' }}>-</span>,
    },
    {
      title: '操作',
      key: 'act',
      width: 110,
      fixed: 'right' as const,
      render: (_, r) => r.status === 'active' ? (
        <Tooltip title="作废（立即失效）">
          <Button size="small" danger icon={<StopOutlined />}
            onClick={() => {
              let reason = '';
              Modal.confirm({
                title: `作废邀请码 ${r.code}`,
                content: (
                  <div>
                    <div style={{ marginBottom: 8, color: '#ff4d4f' }}>
                      作废后消费者无法用此码注册
                    </div>
                    <Input.TextArea rows={2} placeholder="原因（必填，记审计）"
                      onChange={e => { reason = e.target.value; }}
                    />
                  </div>
                ),
                onOk: () => {
                  if (!reason.trim()) { message.warning('请填写原因'); return Promise.reject(); }
                  return invalidateMut.mutateAsync({ id: r.id, reason });
                },
              });
            }}
          />
        </Tooltip>
      ) : null,
    },
  ];

  const TABS = [
    { key: 'all', label: '全部' },
    { key: 'active', label: '可用' },
    { key: 'used', label: '已使用' },
    { key: 'expired', label: '已过期' },
    { key: 'invalidated', label: '已作废' },
  ];

  return (
    <div>
      <Title level={4}>邀请码管理</Title>
      <div style={{ marginBottom: 16, color: '#666', fontSize: 13 }}>
        业务员每次生成的邀请码都会记录在这里（默认 2 小时有效，一次性消费）。
        运营可以监控签发异常（大量签发但转化率极低 → 可能刷码）、作废问题码、追溯消费者来源。
      </div>

      {/* 业务员签发统计 */}
      <Card size="small" style={{ marginBottom: 16 }}
        title={<>近 {statsDays} 天签发统计</>}
        extra={
          <InputNumber
            min={1} max={90}
            value={statsDays}
            onChange={(v) => setStatsDays(Number(v) || 7)}
            addonBefore="近"
            addonAfter="天"
            style={{ width: 160 }}
          />
        }
      >
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Statistic title="总签发" value={statsAgg.issued} />
          </Col>
          <Col span={6}>
            <Statistic title="已使用" value={statsAgg.used} valueStyle={{ color: '#52c41a' }} />
          </Col>
          <Col span={6}>
            <Statistic title="已作废" value={statsAgg.invalidated}
              valueStyle={{ color: statsAgg.invalidated > 0 ? '#ff4d4f' : undefined }} />
          </Col>
          <Col span={6}>
            <Statistic title="整体使用率" value={globalRate} suffix="%"
              valueStyle={{ color: Number(globalRate) >= 30 ? '#52c41a' : '#faad14' }} />
          </Col>
        </Row>
        <Table
          dataSource={stats}
          rowKey="issuer_id"
          size="small"
          pagination={false}
          columns={[
            {
              title: '业务员',
              key: 'sm',
              render: (_, r: StatRow) => (
                <div>
                  <div>{r.issuer_nickname || '-'}</div>
                  {r.issuer_phone && <div style={{ color: '#999', fontSize: 12 }}>{r.issuer_phone}</div>}
                </div>
              ),
            },
            { title: '签发', dataIndex: 'issued', width: 70, align: 'right' as const },
            { title: '作废', dataIndex: 'invalidated', width: 70, align: 'right' as const,
              render: (v: number) => v > 0 ? <Tag color="red">{v}</Tag> : v },
            { title: '有效', dataIndex: 'valid_issued', width: 70, align: 'right' as const,
              render: (v: number) => <strong>{v}</strong> },
            { title: '使用', dataIndex: 'used', width: 70, align: 'right' as const,
              render: (v: number) => <strong style={{ color: '#52c41a' }}>{v}</strong> },
            {
              title: '使用率',
              dataIndex: 'usage_rate',
              width: 100,
              align: 'right' as const,
              render: (v: number) => (
                <Tag color={v >= 30 ? 'green' : v >= 10 ? 'orange' : 'red'}>
                  {v}%
                </Tag>
              ),
            },
          ]}
        />
      </Card>

      <Tabs
        activeKey={statusTab}
        onChange={(k) => { setStatusTab(k); setPage(1); }}
        items={TABS.map(t => ({ key: t.key, label: t.label }))}
      />

      <Space style={{ marginBottom: 16, flexWrap: 'wrap' }}>
        <Input.Search
          placeholder="精确查码（8 位大写）"
          value={code}
          onChange={e => setCode(e.target.value.toUpperCase())}
          onSearch={() => setPage(1)}
          allowClear
          style={{ width: 200 }}
        />
        <Select
          placeholder="按业务员筛选"
          allowClear
          value={issuerId}
          onChange={(v) => { setIssuerId(v); setPage(1); }}
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
        <RangePicker
          value={dateRange as any}
          onChange={(v) => { setDateRange(v as any); setPage(1); }}
        />
      </Space>

      <Table
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={isLoading}
        size="middle"
        scroll={{ x: 1200 }}
        pagination={{
          current: page, pageSize, total,
          showTotal: t => `共 ${t} 条`,
          onChange: (p, s) => { setPage(p); setPageSize(s || 50); },
          pageSizeOptions: ['20', '50', '100'],
          showSizeChanger: true,
        }}
      />
    </div>
  );
}
