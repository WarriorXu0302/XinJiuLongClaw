/**
 * 跳单告警管理
 *
 * 列表：状态 Tab + 申诉过滤
 * 详情：展开 skip_logs + 订单链路
 * 操作：resolved（确认跳单成立，业务员承担）/ dismissed（驳回，对应 skip_logs 标 dismissed）
 */
import { useState } from 'react';
import {
  Button, Descriptions, Drawer, Empty, Input, message, Modal, Space, Spin, Table, Tabs, Tag, Tooltip, Typography,
} from 'antd';
import { CheckOutlined, StopOutlined, EyeOutlined, WarningOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title } = Typography;

const STATUS: Record<string, { text: string; color: string }> = {
  open: { text: '待处理', color: 'orange' },
  resolved: { text: '已通过', color: 'red' },
  dismissed: { text: '已驳回', color: 'green' },
};

const SKIP_TYPE: Record<string, string> = {
  released: '业务员主动释放',
  not_claimed_in_time: '超时未接单',
  admin_reassigned: '管理员改派',
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

interface Alert {
  id: string;
  customer?: { id: string; nickname?: string; phone?: string };
  salesman?: { id: string; nickname?: string; phone?: string };
  skip_count: number;
  status: string;
  appeal_reason?: string;
  appeal_at?: string;
  resolved_at?: string;
  resolution_note?: string;
  created_at: string;
}

export default function SkipAlertList() {
  const queryClient = useQueryClient();
  // 支持从 Dashboard 跳转带 ?status=open/resolved/dismissed 自动选中 Tab
  const [searchParams] = useSearchParams();
  const initialStatus = searchParams.get('status') || 'open';
  const [statusTab, setStatusTab] = useState<string>(initialStatus);
  const [hasAppeal, setHasAppeal] = useState<boolean | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [detailId, setDetailId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['mall-admin-skip-alerts', statusTab, hasAppeal, page, pageSize],
    queryFn: () => api.get('/mall/admin/skip-alerts', {
      params: {
        status: statusTab === 'all' ? undefined : statusTab,
        has_appeal: hasAppeal,
        skip: (page - 1) * pageSize,
        limit: pageSize,
      },
    }).then(r => r.data),
    refetchInterval: 30000,
  });
  const rows: Alert[] = data?.records || [];
  const total: number = data?.total || 0;

  const resolveMut = useMutation({
    mutationFn: ({ id, status, note }: any) =>
      api.post(`/mall/admin/skip-alerts/${id}/resolve`, {
        resolution_status: status, note,
      }),
    onSuccess: (_, v: any) => {
      message.success(v.status === 'resolved' ? '已通过 · 跳单成立' : '已驳回 · 对应 skip_logs 不计入');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-skip-alerts'] });
      queryClient.invalidateQueries({ queryKey: ['mall-admin-skip-alert-detail'] });
      setDetailId(null);
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  const columns: ColumnsType<Alert> = [
    {
      title: '告警时间',
      dataIndex: 'created_at',
      width: 150,
      fixed: 'left' as const,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '客户',
      key: 'cust',
      width: 160,
      render: (_, r) => r.customer ? (
        <div>
          <div>{r.customer.nickname || '-'}</div>
          {r.customer.phone && <div style={{ color: '#999', fontSize: 12 }}>{r.customer.phone}</div>}
        </div>
      ) : '-',
    },
    {
      title: '涉事业务员',
      key: 'sm',
      width: 160,
      render: (_, r) => r.salesman ? (
        <div>
          <div>{r.salesman.nickname || '-'}</div>
          {r.salesman.phone && <div style={{ color: '#999', fontSize: 12 }}>{r.salesman.phone}</div>}
        </div>
      ) : '-',
    },
    {
      title: '跳单次数',
      dataIndex: 'skip_count',
      width: 100,
      align: 'center' as const,
      render: (v: number) => (
        <Tag color={v >= 5 ? 'red' : v >= 3 ? 'orange' : 'default'} icon={<WarningOutlined />}>
          {v} 次 / 30 天
        </Tag>
      ),
    },
    {
      title: '业务员申诉',
      key: 'appeal',
      width: 200,
      render: (_, r) => r.appeal_reason ? (
        <Tooltip title={r.appeal_reason}>
          <div style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            <Tag color="blue">已申诉</Tag> {r.appeal_reason}
          </div>
        </Tooltip>
      ) : <span style={{ color: '#ccc' }}>-</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (v: string) => {
        const m = STATUS[v];
        return m ? <Tag color={m.color}>{m.text}</Tag> : v;
      },
    },
    {
      title: '处理结果',
      dataIndex: 'resolution_note',
      ellipsis: true,
      render: (v?: string) => v || <span style={{ color: '#ccc' }}>-</span>,
    },
    {
      title: '操作',
      key: 'act',
      width: 150,
      fixed: 'right' as const,
      render: (_, r) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => setDetailId(r.id)}>
            详情
          </Button>
        </Space>
      ),
    },
  ];

  const TABS = [
    { key: 'open', label: '待处理' },
    { key: 'resolved', label: '已通过' },
    { key: 'dismissed', label: '已驳回' },
    { key: 'all', label: '全部' },
  ];

  return (
    <div>
      <Title level={4}>跳单告警</Title>
      <div style={{ marginBottom: 16, color: '#666', fontSize: 13 }}>
        规则：业务员对同一客户在 30 天内发生 3 次跳单（释放 / 超时 / 改派）会自动触发告警，
        业务员可通过小程序提交申诉，这里审核：
        <span style={{ color: '#ff4d4f' }}>通过</span>=确认跳单成立（跳单次数保留）；
        <span style={{ color: '#52c41a' }}>驳回</span>=业务员申诉成立（对应 skip_logs 不计入下次阈值）
      </div>

      <Tabs
        activeKey={statusTab}
        onChange={(k) => { setStatusTab(k); setPage(1); }}
        items={TABS.map(t => ({ key: t.key, label: t.label }))}
      />

      <Space style={{ marginBottom: 16 }}>
        <span style={{ color: '#666' }}>申诉筛选：</span>
        <Button.Group>
          <Button
            type={hasAppeal === undefined ? 'primary' : 'default'}
            onClick={() => setHasAppeal(undefined)}
          >全部</Button>
          <Button
            type={hasAppeal === true ? 'primary' : 'default'}
            onClick={() => { setHasAppeal(true); setPage(1); }}
          >有申诉</Button>
          <Button
            type={hasAppeal === false ? 'primary' : 'default'}
            onClick={() => { setHasAppeal(false); setPage(1); }}
          >无申诉</Button>
        </Button.Group>
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
          onChange: (p, s) => { setPage(p); setPageSize(s || 20); },
          pageSizeOptions: ['20', '50', '100'],
          showSizeChanger: true,
        }}
      />

      {detailId && (
        <AlertDetail
          alertId={detailId}
          open={!!detailId}
          onClose={() => setDetailId(null)}
          onResolve={(status, note) => resolveMut.mutate({ id: detailId, status, note })}
          resolving={resolveMut.isPending}
        />
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────
// 详情抽屉
// ────────────────────────────────────────────────────────────
interface DetailProps {
  alertId: string;
  open: boolean;
  onClose: () => void;
  onResolve: (status: 'resolved' | 'dismissed', note: string) => void;
  resolving: boolean;
}

function AlertDetail({ alertId, open, onClose, onResolve, resolving }: DetailProps) {
  const { data: alert, isLoading } = useQuery<any>({
    queryKey: ['mall-admin-skip-alert-detail', alertId],
    queryFn: () => api.get(`/mall/admin/skip-alerts/${alertId}`).then(r => r.data),
    enabled: open && !!alertId,
  });

  const confirmResolve = (status: 'resolved' | 'dismissed') => {
    let note = '';
    Modal.confirm({
      title: status === 'resolved' ? '确认通过 · 跳单成立' : '确认驳回 · 申诉成立',
      content: (
        <div>
          <div style={{ marginBottom: 8, color: status === 'resolved' ? '#ff4d4f' : '#52c41a' }}>
            {status === 'resolved'
              ? '跳单次数保留，业务员后续再跳单将再次触发新告警'
              : '对应 3 条 skip_logs 标 dismissed，不计入未来的 30 天阈值'}
          </div>
          <Input.TextArea rows={3} placeholder="处理意见（选填，记审计）"
            onChange={e => { note = e.target.value; }}
          />
        </div>
      ),
      onOk: () => onResolve(status, note),
    });
  };

  return (
    <Drawer
      title="跳单告警详情"
      open={open}
      onClose={onClose}
      size={800}
      extra={alert && alert.status === 'open' && (
        <Space>
          <Button danger icon={<CheckOutlined />} onClick={() => confirmResolve('resolved')}
            loading={resolving}>通过（跳单成立）</Button>
          <Button type="primary" icon={<StopOutlined />} onClick={() => confirmResolve('dismissed')}
            loading={resolving}>驳回（申诉成立）</Button>
        </Space>
      )}
    >
      {isLoading || !alert ? <Spin /> : (
        <>
          {/* 基本 */}
          <Descriptions bordered size="small" column={2} styles={{ label: { width: 120 } }}>
            <Descriptions.Item label="告警时间">
              {dayjs(alert.created_at).format('YYYY-MM-DD HH:mm:ss')}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={STATUS[alert.status]?.color}>{STATUS[alert.status]?.text}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="客户">
              {alert.customer?.nickname || '-'}
              {alert.customer?.phone && <span style={{ color: '#999' }}> · {alert.customer.phone}</span>}
            </Descriptions.Item>
            <Descriptions.Item label="涉事业务员">
              {alert.salesman?.nickname || '-'}
              {alert.salesman?.phone && <span style={{ color: '#999' }}> · {alert.salesman.phone}</span>}
            </Descriptions.Item>
            <Descriptions.Item label="跳单次数" span={2}>
              <Tag color="red"><WarningOutlined /> {alert.skip_count} 次 / 30 天</Tag>
            </Descriptions.Item>
          </Descriptions>

          {/* 申诉 */}
          {alert.appeal_reason && (
            <>
              <Typography.Title level={5} style={{ marginTop: 20 }}>业务员申诉</Typography.Title>
              <div style={{
                background: '#f0f5ff', padding: 12, borderRadius: 4,
                borderLeft: '3px solid #1677ff',
              }}>
                <div>{alert.appeal_reason}</div>
                {alert.appeal_at && (
                  <div style={{ marginTop: 4, color: '#999', fontSize: 12 }}>
                    提交于 {dayjs(alert.appeal_at).format('YYYY-MM-DD HH:mm')}
                  </div>
                )}
              </div>
            </>
          )}

          {/* 处理结果 */}
          {alert.status !== 'open' && (
            <>
              <Typography.Title level={5} style={{ marginTop: 20 }}>处理结果</Typography.Title>
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="结论">
                  <Tag color={STATUS[alert.status]?.color}>{STATUS[alert.status]?.text}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="处理时间">
                  {alert.resolved_at ? dayjs(alert.resolved_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="处理意见" span={2}>
                  {alert.resolution_note || '-'}
                </Descriptions.Item>
              </Descriptions>
            </>
          )}

          {/* skip_logs */}
          <Typography.Title level={5} style={{ marginTop: 20 }}>
            触发事件（{alert.skip_logs?.length || 0} 条）
          </Typography.Title>
          {(alert.skip_logs || []).length === 0 ? <Empty description="无日志" /> : (
            <Table
              dataSource={alert.skip_logs}
              rowKey="id"
              pagination={false}
              size="small"
              columns={[
                {
                  title: '跳单类型',
                  dataIndex: 'skip_type',
                  width: 150,
                  render: (v: string) => <Tag>{SKIP_TYPE[v] ?? v}</Tag>,
                },
                {
                  title: '关联订单',
                  dataIndex: 'order_no',
                  width: 180,
                  render: (v: string) => v || '-',
                },
                {
                  title: '订单状态',
                  dataIndex: 'order_status',
                  width: 100,
                  render: (v?: string) => v ? <Tag>{ORDER_STATUS[v] ?? v}</Tag> : '-',
                },
                {
                  title: '发生时间',
                  dataIndex: 'created_at',
                  width: 160,
                  render: (v: string) => dayjs(v).format('MM-DD HH:mm:ss'),
                },
                {
                  title: 'dismissed',
                  dataIndex: 'dismissed',
                  width: 90,
                  render: (v: boolean) => v ? <Tag color="green">是</Tag> : <Tag>否</Tag>,
                },
              ]}
            />
          )}
        </>
      )}
    </Drawer>
  );
}
