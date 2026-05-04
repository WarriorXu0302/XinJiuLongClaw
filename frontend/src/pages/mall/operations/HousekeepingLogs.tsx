/**
 * 商城定时任务执行历史
 *
 * 上半：5 个 job 的最近一次执行状态（summary 卡片）+ 手动触发按钮
 * 下半：执行历史详表（按 job_name / status / trigger 过滤）
 */
import { useState } from 'react';
import {
  Alert, Button, Card, Col, message, Popconfirm, Row, Space, Table, Tag, Tooltip, Typography,
} from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title, Text } = Typography;

const JOBS: { key: string; label: string; path: string; desc: string }[] = [
  { key: 'job_detect_unclaimed_timeout', label: '超时未接单扫描', path: 'detect-unclaimed-timeout',
    desc: '订单过独占期未被抢 → 给推荐人记 skip_log' },
  { key: 'job_archive_inactive_consumers', label: '不活跃用户归档', path: 'archive-inactive',
    desc: '按 30/90/180 天规则归档未下单用户' },
  { key: 'job_notify_archive_pre_notice', label: '归档前 7 天预告', path: 'notify-archive-pre-notice',
    desc: '即将归档的用户收到通知' },
  { key: 'job_detect_partial_close', label: '订单坏账折损', path: 'detect-partial-close',
    desc: '60 天未全款订单 → partial_closed' },
  { key: 'job_purge_old_login_logs', label: '清理旧登录日志', path: 'purge-login-logs',
    desc: '保留 90 天以内的登录日志' },
];

interface JobLog {
  id: number;
  job_name: string;
  trigger: 'scheduler' | 'manual';
  status: 'success' | 'error';
  result?: Record<string, any> | null;
  error_message?: string | null;
  duration_ms?: number | null;
  started_at?: string;
  finished_at?: string;
}

export default function HousekeepingLogs() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<{ job_name?: string; status?: string; trigger?: string }>({});

  const { data: summary, isLoading: sumLoading } = useQuery<{ records: JobLog[] }>({
    queryKey: ['housekeeping-summary'],
    queryFn: () => api.get('/mall/admin/housekeeping/logs/summary').then(r => r.data),
    refetchInterval: 30000,
  });
  const summaryMap: Record<string, JobLog> = {};
  (summary?.records || []).forEach(r => { summaryMap[r.job_name] = r; });

  const { data: logs, isLoading: logsLoading } = useQuery<{ records: JobLog[]; total: number }>({
    queryKey: ['housekeeping-logs', filters],
    queryFn: () => api.get('/mall/admin/housekeeping/logs', { params: filters }).then(r => r.data),
    refetchInterval: 30000,
  });

  const triggerMut = useMutation({
    mutationFn: (path: string) => api.post(`/mall/admin/housekeeping/${path}`),
    onSuccess: (r, path) => {
      message.success(`已手动触发（${path}）：${JSON.stringify(r.data)}`);
      queryClient.invalidateQueries({ queryKey: ['housekeeping-summary'] });
      queryClient.invalidateQueries({ queryKey: ['housekeeping-logs'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '触发失败'),
  });

  const columns: ColumnsType<JobLog> = [
    {
      title: '任务', dataIndex: 'job_name', width: 240,
      render: (v: string) => {
        const j = JOBS.find(x => x.key === v);
        return j ? <Tooltip title={j.desc}>{j.label}</Tooltip> : <code>{v}</code>;
      },
    },
    {
      title: '触发', dataIndex: 'trigger', width: 90,
      render: (v: string) => <Tag>{v === 'scheduler' ? '定时' : '手动'}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => v === 'success'
        ? <Tag icon={<CheckCircleOutlined />} color="success">成功</Tag>
        : <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>,
    },
    {
      title: '耗时', dataIndex: 'duration_ms', width: 90,
      render: (v?: number) => v != null ? `${v} ms` : '-',
    },
    {
      title: '执行结果', key: 'result',
      render: (_, r) => r.status === 'error'
        ? <Text type="danger" style={{ fontSize: 12 }}>{r.error_message?.split('\n')[0]}</Text>
        : <code style={{ fontSize: 12 }}>{r.result ? JSON.stringify(r.result) : '-'}</code>,
    },
    {
      title: '开始时间', dataIndex: 'started_at', width: 160,
      render: (v?: string) => v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-',
    },
  ];

  return (
    <div>
      <Title level={4}>定时任务执行历史</Title>
      <Alert
        type="info"
        showIcon
        title="每个任务都由 APScheduler 自动调度，也可点下方「手动触发」立即执行。"
        style={{ marginBottom: 16 }}
      />

      {/* 5 个 job 的最新状态卡片 */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {JOBS.map(j => {
          const last = summaryMap[j.key];
          return (
            <Col xs={24} sm={12} lg={12} xl={8} key={j.key}>
              <Card size="small" loading={sumLoading} title={
                <Space>
                  <strong>{j.label}</strong>
                  {last && (last.status === 'success'
                    ? <Tag color="success" icon={<CheckCircleOutlined />}>上次成功</Tag>
                    : <Tag color="error" icon={<CloseCircleOutlined />}>上次失败</Tag>
                  )}
                </Space>
              }>
                <div style={{ minHeight: 72 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>{j.desc}</Text>
                  <div style={{ marginTop: 8, fontSize: 12 }}>
                    {last ? (
                      <>
                        上次: {last.started_at ? dayjs(last.started_at).format('MM-DD HH:mm:ss') : '-'}
                        <span style={{ color: '#999' }}> · {last.duration_ms} ms · {last.trigger === 'manual' ? '手动' : '定时'}</span>
                        {last.status === 'error' && (
                          <div style={{ color: '#ff4d4f', marginTop: 4, fontSize: 11 }}>
                            {last.error_message?.split('\n')[0]}
                          </div>
                        )}
                        {last.status === 'success' && last.result && (
                          <div style={{ color: '#666', marginTop: 4, fontSize: 11 }}>
                            {JSON.stringify(last.result)}
                          </div>
                        )}
                      </>
                    ) : <Text type="secondary">尚未执行</Text>}
                  </div>
                </div>
                <Popconfirm
                  title={`手动触发「${j.label}」？`}
                  onConfirm={() => triggerMut.mutate(j.path)}
                >
                  <Button size="small" icon={<ThunderboltOutlined />} loading={triggerMut.isPending}>
                    手动触发
                  </Button>
                </Popconfirm>
              </Card>
            </Col>
          );
        })}
      </Row>

      <Card
        size="small"
        title="执行日志"
        extra={
          <Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => queryClient.invalidateQueries({ queryKey: ['housekeeping-logs'] })}
              size="small"
            >
              刷新
            </Button>
          </Space>
        }
      >
        <Space style={{ marginBottom: 12 }} wrap>
          <span>过滤：</span>
          <Button size="small" type={filters.status === 'error' ? 'primary' : 'default'}
            onClick={() => setFilters(f => ({ ...f, status: f.status === 'error' ? undefined : 'error' }))}
          >
            仅失败
          </Button>
          <Button size="small" type={filters.trigger === 'manual' ? 'primary' : 'default'}
            onClick={() => setFilters(f => ({ ...f, trigger: f.trigger === 'manual' ? undefined : 'manual' }))}
          >
            仅手动
          </Button>
          <Button size="small" onClick={() => setFilters({})}>清空过滤</Button>
        </Space>
        <Table
          dataSource={logs?.records || []}
          rowKey="id"
          columns={columns}
          loading={logsLoading}
          size="small"
          pagination={{ total: logs?.total, showTotal: (t) => `共 ${t} 条` }}
        />
      </Card>
    </div>
  );
}
