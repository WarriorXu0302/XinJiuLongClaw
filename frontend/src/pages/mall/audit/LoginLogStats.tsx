/**
 * 登录频率统计
 *
 * 识别扒价机器人 / 盗号行为：
 *  - active_logins（password + wechat 真实手工登录）异常高 → 疑似机器人
 *  - distinct_ips 异常多（>5）→ 多设备 / 账号共享 / 盗号
 *  - refresh 不看阈值（小程序 token 过期会自动 refresh，高也正常）
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card, InputNumber, Radio, Space, Table, Tabs, Tag, Tooltip, Typography,
} from 'antd';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title, Text } = Typography;

interface UserSummary {
  id: string;
  nickname?: string;
  username?: string;
  phone?: string;
  user_type: string;
  status: string;
}

interface StatRow {
  user: UserSummary | null;
  total_logins: number;
  active_logins: number;
  password_count: number;
  wechat_count: number;
  refresh_count: number;
  distinct_ips: number;
  last_login_at: string;
}

const USER_TYPE: Record<string, { text: string; color: string }> = {
  consumer: { text: 'C 端', color: 'blue' },
  salesman: { text: '业务员', color: 'orange' },
};

interface IpStatRow {
  ip_address: string;
  accounts: number;
  total_logins: number;
  active_logins: number;
  last_login_at: string;
}

interface IpUserRow {
  user: UserSummary | null;
  total_logins: number;
  active_logins: number;
  last_login_at: string;
}

function UserStats({ days, topN, minCount, orderBy }: {
  days: number; topN: number; minCount: number; orderBy: 'active' | 'total';
}) {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ['mall-login-stats', days, topN, minCount, orderBy],
    queryFn: () => api.get('/mall/admin/login-logs/stats', {
      params: { days, top_n: topN, min_count: minCount, order_by: orderBy },
    }).then(r => r.data),
  });
  const rows: StatRow[] = data?.records || [];
  const dailyAvgThreshold = 30;
  const ipThreshold = 5;

  const columns: ColumnsType<StatRow> = [
    { title: '排名', key: 'rank', width: 60, render: (_, __, i) => i + 1 },
    {
      title: '用户', key: 'user', width: 240,
      render: (_, r) => r.user ? (
        <div>
          <div>
            <a onClick={() => navigate(`/mall/consumers`)}>{r.user.nickname || r.user.username || '-'}</a>
            <Tag color={USER_TYPE[r.user.user_type]?.color} style={{ marginLeft: 8 }}>
              {USER_TYPE[r.user.user_type]?.text || r.user.user_type}
            </Tag>
            {r.user.status !== 'active' && (
              <Tag color="red" style={{ marginLeft: 4 }}>{r.user.status}</Tag>
            )}
          </div>
          {r.user.phone && <div style={{ color: '#999', fontSize: 12 }}>{r.user.phone}</div>}
        </div>
      ) : <Text type="secondary">-</Text>,
    },
    {
      title: (
        <Tooltip title="password + wechat，去掉 refresh 自动刷新。识别扒价用这个。">
          <span style={{ borderBottom: '1px dashed #999' }}>真实登录 ⓘ</span>
        </Tooltip>
      ),
      dataIndex: 'active_logins', width: 120, align: 'right' as const,
      sorter: (a, b) => a.active_logins - b.active_logins,
      render: (v: number) => {
        const avg = v / days;
        const high = avg > dailyAvgThreshold;
        return (
          <div>
            <strong style={{ color: high ? '#ff4d4f' : undefined, fontSize: 15 }}>{v}</strong>
            <div style={{ color: '#999', fontSize: 11 }}>日均 {avg.toFixed(1)}</div>
          </div>
        );
      },
    },
    { title: '账密', dataIndex: 'password_count', width: 70, align: 'right' as const,
      render: (v: number) => <span style={{ color: '#999' }}>{v}</span> },
    { title: '微信', dataIndex: 'wechat_count', width: 70, align: 'right' as const,
      render: (v: number) => <span style={{ color: '#999' }}>{v}</span> },
    {
      title: (
        <Tooltip title="小程序 token 自动续期。不代表用户行为，仅参考。">
          <span style={{ borderBottom: '1px dashed #999' }}>刷新 ⓘ</span>
        </Tooltip>
      ),
      dataIndex: 'refresh_count', width: 90, align: 'right' as const,
      render: (v: number) => <span style={{ color: '#ccc' }}>{v}</span>,
    },
    { title: '总计', dataIndex: 'total_logins', width: 80, align: 'right' as const,
      render: (v: number) => <span style={{ color: '#999' }}>{v}</span> },
    {
      title: (
        <Tooltip title="登录使用过的不同 IP 数。生产环境 >5 可疑（盗号/账号共享）。">
          <span style={{ borderBottom: '1px dashed #999' }}>IP 数 ⓘ</span>
        </Tooltip>
      ),
      dataIndex: 'distinct_ips', width: 90, align: 'right' as const,
      sorter: (a, b) => a.distinct_ips - b.distinct_ips,
      render: (v: number) => v > ipThreshold ? <Tag color="red">{v}</Tag> : <strong>{v}</strong>,
    },
    { title: '最近登录', dataIndex: 'last_login_at', width: 160,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm') },
  ];

  return (
    <Table
      columns={columns}
      dataSource={rows}
      rowKey={(r) => r.user?.id || String(Math.random())}
      loading={isLoading}
      size="middle"
      scroll={{ x: 1100 }}
      pagination={false}
    />
  );
}

function IpStats({ days, topN, minAccounts }: { days: number; topN: number; minAccounts: number }) {
  const [drillIp, setDrillIp] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['mall-login-ip-stats', days, topN, minAccounts],
    queryFn: () => api.get('/mall/admin/login-logs/ip-stats', {
      params: { days, top_n: topN, min_accounts: minAccounts },
    }).then(r => r.data),
  });
  const rows: IpStatRow[] = data?.records || [];

  const { data: drillData, isLoading: drillLoading } = useQuery({
    queryKey: ['mall-login-ip-users', drillIp, days],
    queryFn: () => api.get(`/mall/admin/login-logs/ip-stats/${encodeURIComponent(drillIp!)}/users`, {
      params: { days },
    }).then(r => r.data),
    enabled: !!drillIp,
  });
  const drillRows: IpUserRow[] = drillData?.records || [];

  const columns: ColumnsType<IpStatRow> = [
    { title: '排名', key: 'rank', width: 60, render: (_, __, i) => i + 1 },
    { title: 'IP', dataIndex: 'ip_address', width: 160,
      render: (v) => <Text copyable style={{ fontSize: 13 }}>{v}</Text> },
    {
      title: (
        <Tooltip title="登录过该 IP 的不同账号数。>=3 可疑（账号农场/撞号）。">
          <span style={{ borderBottom: '1px dashed #999' }}>账号数 ⓘ</span>
        </Tooltip>
      ),
      dataIndex: 'accounts', width: 100, align: 'right' as const,
      render: (v: number) => v >= 5 ? <Tag color="red">{v}</Tag> : v >= 3 ? <Tag color="orange">{v}</Tag> : v,
    },
    { title: '真实登录', dataIndex: 'active_logins', width: 100, align: 'right' as const },
    { title: '总计', dataIndex: 'total_logins', width: 80, align: 'right' as const,
      render: (v: number) => <span style={{ color: '#999' }}>{v}</span> },
    { title: '最近登录', dataIndex: 'last_login_at', width: 160,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm') },
    { title: '', key: 'act', width: 70, fixed: 'right' as const,
      render: (_, r) => <a onClick={() => setDrillIp(r.ip_address)}>查看账号</a> },
  ];

  return (
    <>
      <Table
        columns={columns}
        dataSource={rows}
        rowKey="ip_address"
        loading={isLoading}
        size="middle"
        pagination={false}
      />
      {drillIp && (
        <Card
          size="small"
          title={<>IP <Text code>{drillIp}</Text> 登录过的账号（{days} 天内）</>}
          extra={<a onClick={() => setDrillIp(null)}>关闭</a>}
          style={{ marginTop: 16 }}
        >
          <Table
            size="small"
            loading={drillLoading}
            dataSource={drillRows}
            rowKey={(r) => r.user?.id || String(Math.random())}
            pagination={false}
            columns={[
              {
                title: '用户', key: 'user', width: 240,
                render: (_, r) => r.user ? (
                  <div>
                    {r.user.nickname || r.user.username}
                    <Tag color={USER_TYPE[r.user.user_type]?.color} style={{ marginLeft: 8 }}>
                      {USER_TYPE[r.user.user_type]?.text}
                    </Tag>
                    {r.user.phone && <span style={{ marginLeft: 8, color: '#999' }}>{r.user.phone}</span>}
                  </div>
                ) : '-',
              },
              { title: '真实登录', dataIndex: 'active_logins', width: 100, align: 'right' as const },
              { title: '总计', dataIndex: 'total_logins', width: 80, align: 'right' as const },
              { title: '最近登录', dataIndex: 'last_login_at', width: 160,
                render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm') },
            ]}
          />
        </Card>
      )}
    </>
  );
}

export default function LoginLogStats() {
  const [tab, setTab] = useState<'user' | 'ip'>('user');
  const [days, setDays] = useState(7);
  const [topN, setTopN] = useState(100);
  const [minCount, setMinCount] = useState(0);
  const [orderBy, setOrderBy] = useState<'active' | 'total'>('active');
  const [minAccounts, setMinAccounts] = useState(2);

  return (
    <div>
      <Title level={4}>登录频率统计</Title>
      <div style={{ marginBottom: 16, color: '#666', fontSize: 13 }}>
        按 <strong>用户</strong> 聚合识别扒价机器人 / 盗号，按 <strong>IP</strong> 聚合识别账号农场 / 撞号攻击。
        「真实登录」= 账密 + 微信，不含小程序 token 自动 refresh。
      </div>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <InputNumber
            min={1} max={90}
            value={days}
            onChange={(v) => setDays(Number(v) || 7)}
            addonBefore="近"
            addonAfter="天"
            style={{ width: 160 }}
          />
          <InputNumber
            min={10} max={500}
            value={topN}
            onChange={(v) => setTopN(Number(v) || 100)}
            addonBefore="Top"
            addonAfter="名"
            style={{ width: 160 }}
          />
          {tab === 'user' && (
            <>
              <InputNumber
                min={0}
                value={minCount}
                onChange={(v) => setMinCount(Number(v) || 0)}
                addonBefore="真实登录 ≥"
                style={{ width: 200 }}
              />
              <Radio.Group
                value={orderBy}
                onChange={(e) => setOrderBy(e.target.value)}
                options={[
                  { value: 'active', label: '按真实登录' },
                  { value: 'total', label: '按总计' },
                ]}
                optionType="button"
              />
            </>
          )}
          {tab === 'ip' && (
            <InputNumber
              min={1}
              value={minAccounts}
              onChange={(v) => setMinAccounts(Number(v) || 2)}
              addonBefore="账号数 ≥"
              style={{ width: 180 }}
            />
          )}
        </Space>
      </Card>

      <Tabs
        activeKey={tab}
        onChange={(k) => setTab(k as 'user' | 'ip')}
        items={[
          {
            key: 'user',
            label: '按用户聚合',
            children: <UserStats days={days} topN={topN} minCount={minCount} orderBy={orderBy} />,
          },
          {
            key: 'ip',
            label: '按 IP 聚合',
            children: <IpStats days={days} topN={topN} minAccounts={minAccounts} />,
          },
        ]}
      />
    </div>
  );
}
