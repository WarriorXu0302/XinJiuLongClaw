/**
 * 商城运营看板
 *
 * 顶部 4 大关键指标：今日订单 / 实收 / 新用户 / 取消（vs 昨日环比）
 * 待处理红点：待接单 / 待财务确认 / 告警 / 低库存
 * 本月 30 天趋势（迷你折线 SVG）
 * 业务员排行 / 商品排行 / 低库存
 */
import { Button, Card, Col, DatePicker, Empty, Row, Segmented, Space, Statistic, Table, Tag, Tooltip, Typography, message } from 'antd';
import {
  ShoppingCartOutlined, DollarOutlined, UserAddOutlined, StopOutlined,
  WarningOutlined, FireOutlined, InboxOutlined, TrophyOutlined,
  CameraOutlined, ClockCircleOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useState } from 'react';
import dayjs from 'dayjs';
import api from '../../api/client';

const { Title, Text } = Typography;

interface Summary {
  today: {
    orders: number; received: string; new_users: number; cancelled: number;
    // G9
    revenue?: string; profit?: string; commission?: string;
    gross_margin_pct?: string | null;
  };
  yesterday: { orders: number; received: string };
  pending: {
    pending_assignment: number;
    pending_payment_confirmation: number;
    open_skip_alerts: number;
    low_stock_count: number;
    pending_applications?: number;
    pending_returns?: number;
    approved_returns_awaiting_refund?: number;
  };
  month: {
    orders: number; received: string; new_users: number;
    // G9
    revenue?: string; profit?: string; commission?: string;
    bad_debt?: string; gross_margin_pct?: string | null;
  };
  trend: { day: string; orders: number; received: string }[];
  salesman_rank: { id: string; nickname?: string; phone?: string; order_count: number; gmv: string }[];
  product_rank: { id: number; name?: string; main_image?: string; quantity: number; amount: string }[];
  low_stock: { inventory_id: string; product_id: number; product_name: string; spec?: string; quantity: number }[];
}

function diffPercent(today: number, yesterday: number): string {
  if (yesterday === 0) return today > 0 ? '+∞' : '0%';
  const rate = ((today - yesterday) / yesterday) * 100;
  return `${rate >= 0 ? '+' : ''}${rate.toFixed(1)}%`;
}

// 迷你折线（简单 SVG，避免引 echarts）
function MiniLineChart({
  data,
  metric,
  color,
  height = 200,
}: {
  data: { day: string; orders: number; received: string }[];
  metric: 'orders' | 'received';
  color: string;
  height?: number;
}) {
  const values = data.map(d => metric === 'orders' ? d.orders : Number(d.received));
  const max = Math.max(...values, 1);
  const min = 0;
  const w = 100 / (data.length - 1);

  const points = values.map((v, i) => {
    const x = i * w;
    const y = ((max - v) / (max - min)) * 80 + 10; // padding 10 top/bottom
    return `${x},${y}`;
  }).join(' ');

  // Fill area
  const areaPoints = `0,100 ${points} 100,100`;

  return (
    <div style={{ position: 'relative', height }}>
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        width="100%"
        height={height}
      >
        <polygon points={areaPoints} fill={color} fillOpacity="0.15" />
        <polyline points={points} fill="none" stroke={color} strokeWidth="0.5" strokeLinejoin="round" />
        {values.map((v, i) => {
          if (v === 0) return null;
          const x = i * w;
          const y = ((max - v) / (max - min)) * 80 + 10;
          return <circle key={i} cx={x} cy={y} r="0.8" fill={color} />;
        })}
      </svg>
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        fontSize: 11, color: '#999', marginTop: 4,
      }}>
        <span>{dayjs(data[0]?.day).format('MM-DD')}</span>
        <span>{dayjs(data[data.length - 1]?.day).format('MM-DD')}</span>
      </div>
    </div>
  );
}

// =============================================================================
// 决策 #2：业务员排行 — 实时 vs 快照双模式
// =============================================================================

interface RankingRow {
  salesman_id?: string;
  employee_id?: string;
  nickname?: string;
  gmv: string;
  order_count: number;
  commission_amount?: string;
  snapshot_at?: string;
}

interface RankingResp {
  mode: 'realtime' | 'snapshot';
  period: string;
  is_frozen: boolean;
  records: RankingRow[];
  snapshot_count?: number;
}

function SalesmanRankingCard() {
  const [mode, setMode] = useState<'realtime' | 'snapshot'>('realtime');
  const [ymDay, setYmDay] = useState(dayjs());
  const yearMonth = ymDay.format('YYYY-MM');
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery<RankingResp>({
    queryKey: ['salesman-ranking', mode, yearMonth],
    queryFn: () => api.get('/mall/admin/dashboard/salesman-ranking', {
      params: { mode, year_month: yearMonth, limit: 10 },
    }).then(r => r.data),
  });

  const buildMut = useMutation({
    mutationFn: () => api.post('/mall/admin/dashboard/salesman-ranking/build-snapshot', null, {
      params: { year_month: yearMonth },
    }).then(r => r.data),
    onSuccess: (res) => {
      message.success(`已冻结 ${yearMonth}：${res.upserted} 行`);
      queryClient.invalidateQueries({ queryKey: ['salesman-ranking'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '冻结失败'),
  });

  // G7：批量回补历史月份
  const [rangeFrom, setRangeFrom] = useState(dayjs().subtract(11, 'month'));
  const [rangeTo, setRangeTo] = useState(dayjs().subtract(1, 'month'));
  const buildRangeMut = useMutation({
    mutationFn: () => api.post('/mall/admin/dashboard/salesman-ranking/build-snapshot-range', null, {
      params: {
        from_month: rangeFrom.format('YYYY-MM'),
        to_month: rangeTo.format('YYYY-MM'),
      },
    }).then(r => r.data),
    onSuccess: (res) => {
      message.success(`批量回补 ${res.months_processed} 个月，共 UPSERT ${res.total_upserted} 行`);
      queryClient.invalidateQueries({ queryKey: ['salesman-ranking'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '批量回补失败'),
  });

  const records = data?.records || [];
  const isSnapshot = mode === 'snapshot';
  const isEmptySnapshot = isSnapshot && records.length === 0;

  return (
    <Card
      title={<><TrophyOutlined /> 业务员 GMV 排行</>}
      size="small"
      extra={
        <Space size="small">
          <DatePicker.MonthPicker
            value={ymDay}
            onChange={(d) => d && setYmDay(d)}
            allowClear={false}
            size="small"
            style={{ width: 110 }}
          />
          <Segmented
            size="small"
            value={mode}
            onChange={(v) => setMode(v as any)}
            options={[
              { label: <><ClockCircleOutlined /> 实时</>, value: 'realtime' },
              { label: <><CameraOutlined /> 快照</>, value: 'snapshot' },
            ]}
          />
        </Space>
      }
    >
      {isSnapshot && (
        <div style={{ marginBottom: 8, fontSize: 12, color: '#666' }}>
          {records.length > 0 && records[0].snapshot_at ? (
            <Tooltip title="快照冻结时间。之后的退货不会再修改此数据">
              <Tag icon={<CameraOutlined />} color="gold">
                冻结于 {dayjs(records[0].snapshot_at).format('YYYY-MM-DD HH:mm')}
              </Tag>
            </Tooltip>
          ) : (
            <Space size="small">
              <Tag color="default">{yearMonth} 尚未冻结</Tag>
              <Button size="small" type="link" loading={buildMut.isPending}
                onClick={() => buildMut.mutate()}>
                立即冻结
              </Button>
            </Space>
          )}
          {/* G7：批量回补 */}
          <div style={{ marginTop: 8 }}>
            <Space size="small">
              <Text type="secondary" style={{ fontSize: 12 }}>批量回补：</Text>
              <DatePicker.MonthPicker
                value={rangeFrom}
                onChange={(d) => d && setRangeFrom(d)}
                allowClear={false}
                size="small"
                style={{ width: 110 }}
              />
              <span style={{ color: '#999' }}>→</span>
              <DatePicker.MonthPicker
                value={rangeTo}
                onChange={(d) => d && setRangeTo(d)}
                allowClear={false}
                size="small"
                style={{ width: 110 }}
              />
              <Button size="small" type="link" loading={buildRangeMut.isPending}
                onClick={() => buildRangeMut.mutate()}>
                一键回补
              </Button>
            </Space>
          </div>
        </div>
      )}
      {!isSnapshot && (
        <div style={{ marginBottom: 8, fontSize: 12, color: '#999' }}>
          实时聚合：客户退货后数字会变动；用于看趋势。
        </div>
      )}
      {isLoading ? (
        <div style={{ padding: 32, textAlign: 'center', color: '#999' }}>加载中…</div>
      ) : isEmptySnapshot ? (
        <Empty description={
          <>
            <div>{yearMonth} 快照未生成</div>
            <Button size="small" type="primary" style={{ marginTop: 8 }}
              loading={buildMut.isPending}
              onClick={() => buildMut.mutate()}>
              立即冻结
            </Button>
          </>
        } />
      ) : records.length === 0 ? (
        <Empty description="无数据" />
      ) : (
        <Table
          dataSource={records}
          rowKey={(r) => r.salesman_id || r.employee_id || ''}
          pagination={false}
          size="small"
          columns={[
            {
              title: '排名', key: 'rank', width: 50, align: 'center' as const,
              render: (_, __, idx) => {
                if (idx < 3) return <span style={{ fontSize: 18 }}>{['🥇', '🥈', '🥉'][idx]}</span>;
                return <span style={{ color: '#999' }}>{idx + 1}</span>;
              },
            },
            { title: '业务员', dataIndex: 'nickname', render: (v) => v || <span style={{ color: '#ccc' }}>—</span> },
            { title: '订单', dataIndex: 'order_count', width: 60, align: 'right' as const },
            {
              title: 'GMV', dataIndex: 'gmv', width: 110, align: 'right' as const,
              render: (v: string) => <strong>¥{Number(v).toLocaleString()}</strong>,
            },
            ...(isSnapshot ? [{
              title: '提成', dataIndex: 'commission_amount', width: 90, align: 'right' as const,
              render: (v?: string) => v ? `¥${Number(v).toLocaleString()}` : '—',
            }] : []),
          ]}
        />
      )}
    </Card>
  );
}


export default function MallDashboard() {
  const navigate = useNavigate();

  const { data, isLoading } = useQuery<Summary>({
    queryKey: ['mall-dashboard-summary'],
    queryFn: () => api.get('/mall/admin/dashboard/summary').then(r => r.data),
    refetchInterval: 30000,
  });

  if (isLoading || !data) {
    return <div>加载中…</div>;
  }

  return (
    <div>
      <Title level={4}>商城看板</Title>

      {/* 4 大关键指标 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title={<><ShoppingCartOutlined /> 今日新单</>}
              value={data.today.orders}
              suffix={
                <Text type="secondary" style={{ fontSize: 12 }}>
                  昨日 {data.yesterday.orders} · {diffPercent(data.today.orders, data.yesterday.orders)}
                </Text>
              }
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title={<><DollarOutlined /> 今日实收</>}
              value={Number(data.today.received)}
              prefix="¥"
              precision={2}
              suffix={
                <Text type="secondary" style={{ fontSize: 12 }}>
                  昨日 ¥{Number(data.yesterday.received).toLocaleString()} ·{' '}
                  {diffPercent(Number(data.today.received), Number(data.yesterday.received))}
                </Text>
              }
              styles={{ content: { color: '#C9A961' } }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title={<><UserAddOutlined /> 今日新增用户</>}
              value={data.today.new_users}
              styles={{ content: { color: '#52c41a' } }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title={<><StopOutlined /> 今日取消单</>}
              value={data.today.cancelled}
              styles={{ content: { color: data.today.cancelled > 0 ? '#ff4d4f' : undefined } }}
            />
          </Card>
        </Col>
      </Row>

      {/* 待处理事项 */}
      <Card title="待处理事项" size="small" style={{ marginBottom: 16 }}>
        <Space size="large" wrap>
          <a onClick={() => navigate('/mall/orders?status=pending_assignment')}>
            <Tag color={data.pending.pending_assignment > 0 ? 'orange' : 'default'}
              style={{ fontSize: 14, padding: '4px 12px' }}>
              <ShoppingCartOutlined /> 待接单 <strong>{data.pending.pending_assignment}</strong>
            </Tag>
          </a>
          <a onClick={() => navigate('/approval/finance')}>
            <Tag color={data.pending.pending_payment_confirmation > 0 ? 'gold' : 'default'}
              style={{ fontSize: 14, padding: '4px 12px' }}>
              <DollarOutlined /> 待财务确认 <strong>{data.pending.pending_payment_confirmation}</strong>
            </Tag>
          </a>
          <a onClick={() => navigate('/mall/skip-alerts?status=open')}>
            <Tag color={data.pending.open_skip_alerts > 0 ? 'red' : 'default'}
              style={{ fontSize: 14, padding: '4px 12px' }}>
              <WarningOutlined /> 未处理告警 <strong>{data.pending.open_skip_alerts}</strong>
            </Tag>
          </a>
          <Tag color={data.pending.low_stock_count > 0 ? 'volcano' : 'default'}
            style={{ fontSize: 14, padding: '4px 12px' }}>
            <InboxOutlined /> 低库存 SKU <strong>{data.pending.low_stock_count}</strong>
          </Tag>
          <a onClick={() => navigate('/mall/user-applications')}>
            <Tag color={(data.pending.pending_applications ?? 0) > 0 ? 'purple' : 'default'}
              style={{ fontSize: 14, padding: '4px 12px' }}>
              📝 注册待审 <strong>{data.pending.pending_applications ?? 0}</strong>
            </Tag>
          </a>
          <a onClick={() => navigate('/mall/returns?status=pending')}>
            <Tag color={(data.pending.pending_returns ?? 0) > 0 ? 'magenta' : 'default'}
              style={{ fontSize: 14, padding: '4px 12px' }}>
              ↩️ 退货待审 <strong>{data.pending.pending_returns ?? 0}</strong>
            </Tag>
          </a>
          <a onClick={() => navigate('/mall/returns?status=approved')}>
            <Tag color={(data.pending.approved_returns_awaiting_refund ?? 0) > 0 ? 'cyan' : 'default'}
              style={{ fontSize: 14, padding: '4px 12px' }}>
              💰 待退款 <strong>{data.pending.approved_returns_awaiting_refund ?? 0}</strong>
            </Tag>
          </a>
        </Space>
      </Card>

      {/* G9 利润卡片（本月） */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="本月收入（实收）"
              prefix="¥"
              value={Number(data.month.revenue || 0).toFixed(2)}
              styles={{ content: { color: '#1677ff' } }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="本月净利润"
              prefix="¥"
              value={Number(data.month.profit || 0).toFixed(2)}
              styles={{ content: { color: Number(data.month.profit || 0) > 0 ? '#52c41a' : '#ff4d4f' } }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="本月毛利率"
              value={data.month.gross_margin_pct ?? '—'}
              suffix={data.month.gross_margin_pct ? '%' : ''}
              styles={{ content: { color: '#C9A961' } }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="本月提成 / 坏账"
              value={`¥${Number(data.month.commission || 0).toLocaleString()} / ¥${Number(data.month.bad_debt || 0).toLocaleString()}`}
              styles={{ content: { color: '#8c8c8c', fontSize: 18 } }}
            />
          </Card>
        </Col>
      </Row>

      {/* 本月累计 + 趋势 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card title="本月订单数趋势（近 30 天）" size="small"
            extra={<Text strong>本月累计 {data.month.orders}</Text>}
          >
            <MiniLineChart data={data.trend} metric="orders" color="#1677ff" />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="本月实收趋势（近 30 天）" size="small"
            extra={<Text strong style={{ color: '#C9A961' }}>
              本月累计 ¥{Number(data.month.received).toLocaleString()}
            </Text>}
          >
            <MiniLineChart data={data.trend} metric="received" color="#C9A961" />
          </Card>
        </Col>
      </Row>

      {/* 排行 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <SalesmanRankingCard />
        </Col>
        <Col span={12}>
          <Card title={<><FireOutlined /> 本月商品销量 Top 10</>} size="small">
            {data.product_rank.length === 0 ? <Empty description="本月暂无销量" /> : (
              <Table
                dataSource={data.product_rank}
                rowKey="id"
                pagination={false}
                size="small"
                columns={[
                  { title: '排名', key: 'rank', width: 50, align: 'center' as const,
                    render: (_, __, idx) => idx + 1 },
                  {
                    title: '商品',
                    dataIndex: 'name',
                    ellipsis: true,
                    render: (v, r) => (
                      <Space>
                        {r.main_image && (
                          <img src={r.main_image} alt="" width={32} height={32}
                            style={{ objectFit: 'cover', borderRadius: 2 }} />
                        )}
                        <span>{v}</span>
                      </Space>
                    ),
                  },
                  { title: '销量', dataIndex: 'quantity', width: 70, align: 'right' as const },
                  {
                    title: '销售额',
                    dataIndex: 'amount',
                    width: 100,
                    align: 'right' as const,
                    render: (v: string) => `¥${Number(v).toLocaleString()}`,
                  },
                ]}
              />
            )}
          </Card>
        </Col>
      </Row>

      {/* 低库存告警 */}
      {data.low_stock.length > 0 && (
        <Card title={<><InboxOutlined /> 低库存预警（≤ 10 瓶）</>} size="small"
          style={{ marginBottom: 16 }}
        >
          <Table
            dataSource={data.low_stock}
            rowKey="inventory_id"
            pagination={false}
            size="small"
            columns={[
              { title: '商品', dataIndex: 'product_name' },
              { title: '规格', dataIndex: 'spec' },
              {
                title: '剩余',
                dataIndex: 'quantity',
                width: 100,
                align: 'right' as const,
                render: (v: number) => (
                  <Tag color={v === 0 ? 'red' : v < 5 ? 'volcano' : 'orange'}>
                    {v} 瓶
                  </Tag>
                ),
              },
            ]}
          />
        </Card>
      )}
    </div>
  );
}
