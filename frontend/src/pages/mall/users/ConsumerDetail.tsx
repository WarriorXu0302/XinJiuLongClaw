/**
 * C 端用户详情抽屉
 *
 * 展示：基础信息 / 订单统计 / 订单历史 / 登录日志 / 地址列表
 */
import {
  Descriptions, Divider, Drawer, Empty, Space, Spin, Statistic, Table, Tabs, Tag, Typography,
} from 'antd';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title } = Typography;

const STATUS: Record<string, { text: string; color: string }> = {
  active: { text: '正常', color: 'green' },
  disabled: { text: '已禁用', color: 'red' },
  inactive_archived: { text: '已归档', color: 'default' },
};

const ORDER_STATUS: Record<string, string> = {
  pending_assignment: '待接单',
  assigned: '待配送',
  shipped: '配送中',
  delivered: '待收款',
  pending_payment_confirmation: '待财务确认',
  completed: '已完成',
  cancelled: '已取消',
  partial_closed: '已折损',
};

const LOGIN_METHOD: Record<string, string> = {
  password: '账密登录',
  wechat: '微信登录',
  refresh: '自动续期',
};

interface Props {
  userId: string;
  open: boolean;
  onClose: () => void;
}

export default function ConsumerDetail({ userId, open, onClose }: Props) {
  const { data, isLoading } = useQuery<any>({
    queryKey: ['mall-admin-user-detail', userId],
    queryFn: () => api.get(`/mall/admin/users/${userId}`).then(r => r.data),
    enabled: open && !!userId,
  });

  if (isLoading || !data) {
    return (
      <Drawer title="用户详情" open={open} onClose={onClose} width={900}>
        <Spin />
      </Drawer>
    );
  }

  const status = STATUS[data.status];

  return (
    <Drawer
      title={
        <Space>
          <Title level={5} style={{ margin: 0 }}>
            {data.nickname || data.username || '-'}
          </Title>
          {status && <Tag color={status.color}>{status.text}</Tag>}
        </Space>
      }
      open={open}
      onClose={onClose}
      width={900}
    >
      {/* 统计 */}
      <Space size="large" style={{ marginBottom: 20 }}>
        <Statistic title="累计订单" value={data.order_count} />
        <Statistic
          title="累计实收"
          value={Number(data.total_gmv || 0)}
          prefix="¥"
          precision={2}
        />
        <Statistic
          title="登录次数"
          value={data.login_logs?.length}
          suffix={`最近 ${data.login_logs?.length ? '10 条' : '无'}`}
        />
      </Space>

      <Tabs
        defaultActiveKey="basic"
        items={[
          {
            key: 'basic',
            label: '基本信息',
            children: (
              <Descriptions bordered size="small" column={2} styles={{ label: { width: 120 } }}>
                <Descriptions.Item label="账号">{data.username || '-'}</Descriptions.Item>
                <Descriptions.Item label="手机">{data.phone || '-'}</Descriptions.Item>
                <Descriptions.Item label="昵称">{data.nickname || '-'}</Descriptions.Item>
                <Descriptions.Item label="用户类型">
                  <Tag color={data.user_type === 'salesman' ? 'blue' : 'purple'}>
                    {data.user_type === 'salesman' ? '业务员' : 'C 端消费者'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="推荐业务员" span={2}>
                  {data.referrer ? (
                    <>
                      {data.referrer.nickname}
                      {data.referrer.phone && <span style={{ color: '#999' }}> · {data.referrer.phone}</span>}
                    </>
                  ) : <Tag color="red">未绑定</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="注册时间">
                  {dayjs(data.created_at).format('YYYY-MM-DD HH:mm:ss')}
                </Descriptions.Item>
                <Descriptions.Item label="最近下单">
                  {data.last_order_at
                    ? dayjs(data.last_order_at).format('YYYY-MM-DD HH:mm')
                    : '无'}
                </Descriptions.Item>
                <Descriptions.Item label="归档时间" span={2}>
                  {data.archived_at
                    ? dayjs(data.archived_at).format('YYYY-MM-DD HH:mm')
                    : '-'}
                </Descriptions.Item>
              </Descriptions>
            ),
          },
          {
            key: 'orders',
            label: `订单历史 (${data.orders?.length || 0})`,
            children: (data.orders || []).length === 0 ? <Empty description="无订单" /> : (
              <Table
                dataSource={data.orders}
                rowKey="id"
                size="small"
                pagination={false}
                columns={[
                  { title: '订单号', dataIndex: 'order_no', width: 180 },
                  {
                    title: '状态',
                    dataIndex: 'status',
                    width: 100,
                    render: (v: string) => <Tag>{ORDER_STATUS[v] ?? v}</Tag>,
                  },
                  {
                    title: '应付',
                    dataIndex: 'total_amount',
                    width: 100,
                    align: 'right' as const,
                    render: (v: string) => `¥${Number(v).toLocaleString()}`,
                  },
                  {
                    title: '已收',
                    dataIndex: 'received_amount',
                    width: 100,
                    align: 'right' as const,
                    render: (v: string) => <strong>¥{Number(v).toLocaleString()}</strong>,
                  },
                  {
                    title: '下单时间',
                    dataIndex: 'created_at',
                    width: 140,
                    render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
                  },
                  {
                    title: '完成时间',
                    dataIndex: 'completed_at',
                    width: 140,
                    render: (v?: string) => v ? dayjs(v).format('MM-DD HH:mm') : '-',
                  },
                ]}
              />
            ),
          },
          {
            key: 'logins',
            label: `登录日志 (${data.login_logs?.length || 0})`,
            children: (data.login_logs || []).length === 0 ? <Empty description="无日志" /> : (
              <Table
                dataSource={data.login_logs}
                rowKey="id"
                size="small"
                pagination={false}
                columns={[
                  {
                    title: '登录时间',
                    dataIndex: 'login_at',
                    width: 160,
                    render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
                  },
                  {
                    title: '方式',
                    dataIndex: 'login_method',
                    width: 100,
                    render: (v: string) => <Tag>{LOGIN_METHOD[v] ?? v}</Tag>,
                  },
                  { title: 'IP', dataIndex: 'ip_address', width: 140 },
                  {
                    title: '客户端',
                    dataIndex: 'client_app',
                    width: 110,
                    render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-',
                  },
                  { title: 'User-Agent', dataIndex: 'user_agent', ellipsis: true },
                ]}
              />
            ),
          },
          {
            key: 'addresses',
            label: `地址 (${data.addresses?.length || 0})`,
            children: (data.addresses || []).length === 0 ? <Empty description="无地址" /> : (
              <div>
                {data.addresses.map((a: any) => (
                  <div
                    key={a.id}
                    style={{
                      border: '1px solid #f0f0f0',
                      borderRadius: 4,
                      padding: 12,
                      marginBottom: 8,
                      position: 'relative',
                    }}
                  >
                    {a.is_default && (
                      <Tag color="gold" style={{ position: 'absolute', top: 8, right: 8 }}>默认</Tag>
                    )}
                    <div><strong>{a.receiver}</strong> · {a.mobile || '-'}</div>
                    <div style={{ color: '#666', marginTop: 4 }}>
                      {[a.province, a.city, a.area].filter(Boolean).join(' ')} {a.addr}
                    </div>
                  </div>
                ))}
              </div>
            ),
          },
        ]}
      />

      {data.referrer_change_reason && (
        <>
          <Divider />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            最近换绑原因：{data.referrer_change_reason}
            {data.referrer_last_changed_at && (
              <span> · {dayjs(data.referrer_last_changed_at).format('YYYY-MM-DD HH:mm')}</span>
            )}
          </Typography.Text>
        </>
      )}
    </Drawer>
  );
}
