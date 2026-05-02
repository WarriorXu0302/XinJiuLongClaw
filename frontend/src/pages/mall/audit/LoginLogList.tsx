/**
 * 商城登录日志
 *
 * 列：时间 / 用户 / 登录方式 / 客户端 / IP / UA / device_info
 * 过滤：用户类型 / 登录方式 / 客户端 / IP / 日期
 * 用途：追溯登录异常（异地/多账号/机器人扒价）
 */
import { useState } from 'react';
import {
  Button, Card, DatePicker, Drawer, Input, message, Select, Space, Table, Tag, Typography,
} from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title, Text, Paragraph } = Typography;
const { RangePicker } = DatePicker;

interface UserSummary {
  id: string;
  nickname?: string;
  username?: string;
  phone?: string;
  user_type: string;
  status: string;
}

interface LoginRow {
  id: number;
  user: UserSummary | null;
  login_method: string;
  client_app: string;
  ip_address: string | null;
  user_agent: string | null;
  device_info: Record<string, unknown> | null;
  session_id: string | null;
  login_at: string;
}

const METHOD: Record<string, { text: string; color: string }> = {
  password: { text: '账密', color: 'blue' },
  wechat: { text: '微信', color: 'green' },
  refresh: { text: '刷新', color: 'default' },
};

const CLIENT: Record<string, string> = {
  mp_weixin: '微信小程序',
  h5: 'H5',
  app_android: 'Android',
  app_ios: 'iOS',
};

const USER_TYPE: Record<string, { text: string; color: string }> = {
  consumer: { text: 'C 端', color: 'blue' },
  salesman: { text: '业务员', color: 'orange' },
};

export default function LoginLogList() {
  const [userType, setUserType] = useState<string | undefined>();
  const [loginMethod, setLoginMethod] = useState<string | undefined>();
  const [clientApp, setClientApp] = useState<string | undefined>();
  const [ip, setIp] = useState('');
  const [userKeyword, setUserKeyword] = useState('');
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [detail, setDetail] = useState<LoginRow | null>(null);
  const [exporting, setExporting] = useState(false);

  const exportCsv = async () => {
    setExporting(true);
    try {
      const res = await api.get('/mall/admin/login-logs/export', {
        params: {
          user_type: userType,
          login_method: loginMethod,
          client_app: clientApp,
          ip: ip || undefined,
          user_keyword: userKeyword || undefined,
          date_from: dateRange?.[0].format('YYYY-MM-DD'),
          date_to: dateRange?.[1].format('YYYY-MM-DD'),
        },
        responseType: 'blob',
      });
      const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `mall_login_logs_${dayjs().format('YYYYMMDD_HHmmss')}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      message.error(e?.response?.data?.detail ?? '导出失败');
    } finally {
      setExporting(false);
    }
  };

  const { data, isLoading } = useQuery({
    queryKey: ['mall-login-logs', userType, loginMethod, clientApp, ip, userKeyword, dateRange, page, pageSize],
    queryFn: () => api.get('/mall/admin/login-logs', {
      params: {
        user_type: userType,
        login_method: loginMethod,
        client_app: clientApp,
        ip: ip || undefined,
        user_keyword: userKeyword || undefined,
        date_from: dateRange?.[0].format('YYYY-MM-DD'),
        date_to: dateRange?.[1].format('YYYY-MM-DD'),
        skip: (page - 1) * pageSize,
        limit: pageSize,
      },
    }).then(r => r.data),
  });
  const rows: LoginRow[] = data?.records || [];
  const total: number = data?.total || 0;

  const columns: ColumnsType<LoginRow> = [
    {
      title: '时间',
      dataIndex: 'login_at',
      width: 160,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '用户',
      key: 'user',
      width: 220,
      render: (_, r) => r.user ? (
        <div>
          <div>
            {r.user.nickname || r.user.username || '-'}
            <Tag color={USER_TYPE[r.user.user_type]?.color} style={{ marginLeft: 8 }}>
              {USER_TYPE[r.user.user_type]?.text || r.user.user_type}
            </Tag>
            {r.user.status !== 'active' && (
              <Tag color="red" style={{ marginLeft: 4 }}>{r.user.status}</Tag>
            )}
          </div>
          {r.user.phone && (
            <div style={{ color: '#999', fontSize: 12 }}>{r.user.phone}</div>
          )}
        </div>
      ) : <Text type="secondary">-</Text>,
    },
    {
      title: '方式',
      dataIndex: 'login_method',
      width: 80,
      render: (v) => {
        const m = METHOD[v];
        return m ? <Tag color={m.color}>{m.text}</Tag> : v;
      },
    },
    {
      title: '客户端',
      dataIndex: 'client_app',
      width: 120,
      render: (v) => CLIENT[v] || v,
    },
    {
      title: 'IP',
      dataIndex: 'ip_address',
      width: 140,
      render: (v) => v ? <Text copyable style={{ fontSize: 12 }}>{v}</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: 'User-Agent',
      dataIndex: 'user_agent',
      ellipsis: true,
      render: (v) => v
        ? <Text ellipsis style={{ maxWidth: 320, color: '#666', fontSize: 12 }}>{v}</Text>
        : <Text type="secondary">-</Text>,
    },
    {
      title: '',
      key: 'act',
      width: 70,
      fixed: 'right' as const,
      render: (_, r) => r.device_info || r.user_agent ? (
        <a onClick={() => setDetail(r)}>详情</a>
      ) : null,
    },
  ];

  return (
    <div>
      <Title level={4}>商城登录日志</Title>
      <div style={{ marginBottom: 16, color: '#666', fontSize: 13 }}>
        C 端用户 + 业务员每次登录/刷新都会记一条。默认保留 90 天。
        识别异常行为（同 IP 多账号 / 异地登录 / 频繁 refresh）用{' '}
        <a href="/mall/audit/login-stats">登录频率统计</a>。
      </div>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            placeholder="用户类型"
            allowClear
            value={userType}
            onChange={(v) => { setUserType(v); setPage(1); }}
            style={{ width: 120 }}
            options={[
              { value: 'consumer', label: 'C 端' },
              { value: 'salesman', label: '业务员' },
            ]}
          />
          <Select
            placeholder="登录方式"
            allowClear
            value={loginMethod}
            onChange={(v) => { setLoginMethod(v); setPage(1); }}
            style={{ width: 120 }}
            options={[
              { value: 'password', label: '账密' },
              { value: 'wechat', label: '微信' },
              { value: 'refresh', label: '刷新' },
            ]}
          />
          <Select
            placeholder="客户端"
            allowClear
            value={clientApp}
            onChange={(v) => { setClientApp(v); setPage(1); }}
            style={{ width: 140 }}
            options={[
              { value: 'mp_weixin', label: '微信小程序' },
              { value: 'h5', label: 'H5' },
              { value: 'app_android', label: 'Android' },
              { value: 'app_ios', label: 'iOS' },
            ]}
          />
          <Input
            placeholder="IP 精确匹配"
            value={ip}
            onChange={e => setIp(e.target.value)}
            onPressEnter={() => setPage(1)}
            allowClear
            style={{ width: 160 }}
          />
          <Input.Search
            placeholder="昵称/用户名/手机号"
            value={userKeyword}
            onChange={e => setUserKeyword(e.target.value)}
            onSearch={() => setPage(1)}
            allowClear
            style={{ width: 220 }}
          />
          <RangePicker
            value={dateRange as any}
            onChange={(v) => { setDateRange(v as any); setPage(1); }}
          />
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={exportCsv}>
            导出 CSV
          </Button>
        </Space>
      </Card>

      <Table
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={isLoading}
        size="middle"
        scroll={{ x: 1100 }}
        pagination={{
          current: page, pageSize, total,
          showTotal: t => `共 ${t} 条`,
          onChange: (p, s) => { setPage(p); setPageSize(s || 50); },
          pageSizeOptions: ['20', '50', '100', '200'],
          showSizeChanger: true,
        }}
      />

      <Drawer
        title="登录详情"
        open={!!detail}
        onClose={() => setDetail(null)}
        width={640}
      >
        {detail && (
          <div>
            <Paragraph>
              <Text strong>时间：</Text>{dayjs(detail.login_at).format('YYYY-MM-DD HH:mm:ss')}
            </Paragraph>
            <Paragraph>
              <Text strong>用户：</Text>
              {detail.user ? (
                <>
                  {detail.user.nickname || detail.user.username}
                  <Tag color={USER_TYPE[detail.user.user_type]?.color} style={{ marginLeft: 8 }}>
                    {USER_TYPE[detail.user.user_type]?.text}
                  </Tag>
                  {detail.user.phone && (
                    <Text type="secondary" style={{ marginLeft: 8 }}>{detail.user.phone}</Text>
                  )}
                </>
              ) : <Text type="secondary">-</Text>}
            </Paragraph>
            <Paragraph>
              <Text strong>方式：</Text>
              <Tag color={METHOD[detail.login_method]?.color}>
                {METHOD[detail.login_method]?.text || detail.login_method}
              </Tag>
              <Text style={{ marginLeft: 8 }}>{CLIENT[detail.client_app] || detail.client_app}</Text>
            </Paragraph>
            <Paragraph>
              <Text strong>IP：</Text>{detail.ip_address || <Text type="secondary">-</Text>}
            </Paragraph>
            <Paragraph>
              <Text strong>User-Agent：</Text>
              <div style={{ wordBreak: 'break-all', color: '#666', fontSize: 12 }}>
                {detail.user_agent || '-'}
              </div>
            </Paragraph>
            {detail.session_id && (
              <Paragraph>
                <Text strong>Session：</Text>
                <Text code style={{ fontSize: 12 }}>{detail.session_id}</Text>
              </Paragraph>
            )}
            {detail.device_info && (
              <>
                <Paragraph><Text strong>设备信息：</Text></Paragraph>
                <pre style={{
                  margin: 0,
                  padding: 8,
                  background: '#fafafa',
                  border: '1px solid #f0f0f0',
                  borderRadius: 4,
                  fontSize: 12,
                  maxHeight: 300,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}>
                  {JSON.stringify(detail.device_info, null, 2)}
                </pre>
              </>
            )}
          </div>
        )}
      </Drawer>
    </div>
  );
}
