/**
 * 商城订单列表（管理员视角）
 */
import { useState } from 'react';
import { Button, DatePicker, Input, message, Modal, Select, Space, Table, Tabs, Tag, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';
import OrderDetail from './OrderDetail';

const { Title } = Typography;
const { RangePicker } = DatePicker;

const STATUS_LABEL: Record<string, string> = {
  pending_assignment: '待接单',
  assigned: '待配送',
  shipped: '配送中',
  delivered: '待收款',
  pending_payment_confirmation: '待财务确认',
  completed: '已完成',
  cancelled: '已取消',
  partial_closed: '已折损',
  refunded: '已退款',
};

const STATUS_COLOR: Record<string, string> = {
  pending_assignment: 'orange',
  assigned: 'cyan',
  shipped: 'geekblue',
  delivered: 'blue',
  pending_payment_confirmation: 'gold',
  completed: 'green',
  cancelled: 'default',
  partial_closed: 'volcano',
  refunded: 'default',
};

interface MallOrderRow {
  id: string;
  order_no: string;
  status: string;
  payment_status: string;
  total_amount: string;
  pay_amount: string;
  received_amount: string;
  customer?: { id: string; nickname?: string; phone?: string };
  assigned_salesman?: { id: string; nickname?: string };
  referrer_salesman?: { id: string; nickname?: string };
  items_brief: string;
  created_at: string;
  remarks?: string;
  cancellation_reason?: string;
}

export default function MallOrderList() {
  const queryClient = useQueryClient();
  // 支持从 Dashboard 跳转带 ?status=pending_assignment 自动选中对应 Tab
  const [searchParams] = useSearchParams();
  const initialStatus = searchParams.get('status') || 'all';
  const [statusTab, setStatusTab] = useState<string>(initialStatus);
  const [orderNo, setOrderNo] = useState('');
  const [customerKw, setCustomerKw] = useState('');
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [reassignOrder, setReassignOrder] = useState<MallOrderRow | null>(null);
  const [reassignTarget, setReassignTarget] = useState<string | undefined>();
  const [reassignReason, setReassignReason] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['mall-admin-orders', statusTab, orderNo, customerKw, dateRange, page, pageSize],
    queryFn: () => api.get('/mall/admin/orders', {
      params: {
        status: statusTab === 'all' ? undefined : statusTab,
        order_no: orderNo || undefined,
        customer_keyword: customerKw || undefined,
        date_from: dateRange?.[0].format('YYYY-MM-DD'),
        date_to: dateRange?.[1].format('YYYY-MM-DD'),
        skip: (page - 1) * pageSize,
        limit: pageSize,
      },
    }).then(r => r.data),
    refetchInterval: 10000,
  });
  const rows: MallOrderRow[] = data?.records || [];
  const total: number = data?.total || 0;

  // 改派：业务员下拉
  const { data: salesmenData } = useQuery({
    queryKey: ['mall-admin-salesmen'],
    queryFn: () => api.get('/mall/admin/orders/_helpers/salesmen').then(r => r.data),
    enabled: !!reassignOrder,
  });

  const cancelMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.post(`/mall/admin/orders/${id}/cancel`, { reason }),
    onSuccess: () => {
      message.success('订单已取消');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-orders'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '取消失败'),
  });

  const reassignMut = useMutation({
    mutationFn: ({ id, target, reason }: { id: string; target: string; reason: string }) =>
      api.post(`/mall/admin/orders/${id}/reassign`, {
        target_salesman_user_id: target,
        reason,
      }),
    onSuccess: () => {
      message.success('改派成功');
      setReassignOrder(null);
      setReassignTarget(undefined);
      setReassignReason('');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-orders'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '改派失败'),
  });

  const canCancel = (s: string) => !['completed', 'cancelled', 'partial_closed', 'refunded'].includes(s);
  const canReassign = (s: string) => !['completed', 'cancelled', 'partial_closed', 'refunded'].includes(s);

  const columns: ColumnsType<MallOrderRow> = [
    {
      title: '订单号',
      dataIndex: 'order_no',
      width: 180,
      fixed: 'left',
      render: (v, r) => <a onClick={() => setDetailId(r.id)}>{v}</a>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (v: string) => <Tag color={STATUS_COLOR[v]}>{STATUS_LABEL[v] ?? v}</Tag>,
    },
    {
      title: '金额',
      key: 'amount',
      width: 170,
      align: 'right' as const,
      render: (_, r) => (
        <div>
          <div>应收 ¥{Number(r.pay_amount).toLocaleString()}</div>
          <div style={{ color: '#999', fontSize: 12 }}>
            已收 ¥{Number(r.received_amount).toLocaleString()}
          </div>
        </div>
      ),
    },
    {
      title: '客户',
      key: 'customer',
      width: 140,
      render: (_, r) => r.customer ? (
        <div>
          <div>{r.customer.nickname || '-'}</div>
          {r.customer.phone && <div style={{ color: '#999', fontSize: 12 }}>{r.customer.phone}</div>}
        </div>
      ) : '-',
    },
    {
      title: '配送业务员',
      key: 'assigned',
      width: 120,
      render: (_, r) => r.assigned_salesman?.nickname || <Tag>未接单</Tag>,
    },
    {
      title: '推荐人',
      key: 'referrer',
      width: 100,
      render: (_, r) => r.referrer_salesman?.nickname || '-',
    },
    {
      title: '商品',
      dataIndex: 'items_brief',
      ellipsis: true,
      width: 200,
    },
    {
      title: '下单时间',
      dataIndex: 'created_at',
      width: 150,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'act',
      width: 200,
      fixed: 'right',
      render: (_, r) => (
        <Space>
          <a onClick={() => setDetailId(r.id)}>详情</a>
          {canReassign(r.status) && <a onClick={() => setReassignOrder(r)}>改派</a>}
          {canCancel(r.status) && (
            <a style={{ color: '#ff4d4f' }} onClick={() => {
              let reason = '';
              Modal.confirm({
                title: `取消订单 ${r.order_no}`,
                content: (
                  <div>
                    <div style={{ marginBottom: 8, color: '#ff4d4f' }}>
                      将退回库存、恢复条码为 in_stock，pending 凭证全部驳回
                    </div>
                    <Input.TextArea rows={3} placeholder="取消原因（必填）"
                      onChange={e => { reason = e.target.value; }} />
                  </div>
                ),
                onOk: () => {
                  if (!reason.trim()) { message.warning('请填写原因'); return Promise.reject(); }
                  return cancelMut.mutateAsync({ id: r.id, reason });
                },
              });
            }}>取消</a>
          )}
        </Space>
      ),
    },
  ];

  const TABS = [
    { key: 'all', label: '全部' },
    { key: 'pending_assignment', label: '待接单' },
    { key: 'assigned', label: '待配送' },
    { key: 'shipped', label: '配送中' },
    { key: 'delivered', label: '待收款' },
    { key: 'pending_payment_confirmation', label: '待财务确认' },
    { key: 'completed', label: '已完成' },
    { key: 'partial_closed', label: '已折损' },
    { key: 'refunded', label: '已退货' },
    { key: 'cancelled', label: '已取消' },
  ];

  return (
    <div>
      <Title level={4}>商城订单</Title>

      <Tabs
        activeKey={statusTab}
        onChange={(k) => { setStatusTab(k); setPage(1); }}
        items={TABS.map(t => ({ key: t.key, label: t.label }))}
      />

      <Space style={{ marginBottom: 16, flexWrap: 'wrap' }}>
        <Input.Search
          placeholder="订单号"
          value={orderNo}
          onChange={e => setOrderNo(e.target.value)}
          onSearch={() => setPage(1)}
          allowClear
          style={{ width: 200 }}
        />
        <Input.Search
          placeholder="客户昵称/手机号"
          value={customerKw}
          onChange={e => setCustomerKw(e.target.value)}
          onSearch={() => setPage(1)}
          allowClear
          style={{ width: 200 }}
        />
        <RangePicker
          value={dateRange as any}
          onChange={(v) => { setDateRange(v as any); setPage(1); }}
        />
        <Button onClick={() => queryClient.invalidateQueries({ queryKey: ['mall-admin-orders'] })}>刷新</Button>
      </Space>

      <Table
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={isLoading}
        size="middle"
        scroll={{ x: 1400 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showTotal: t => `共 ${t} 条`,
          onChange: (p, s) => { setPage(p); setPageSize(s || 20); },
          pageSizeOptions: ['20', '50', '100'],
          showSizeChanger: true,
        }}
      />

      {detailId && (
        <OrderDetail
          orderId={detailId}
          open={!!detailId}
          onClose={() => setDetailId(null)}
        />
      )}

      <Modal
        title={`改派订单 ${reassignOrder?.order_no}`}
        open={!!reassignOrder}
        onCancel={() => { setReassignOrder(null); setReassignTarget(undefined); setReassignReason(''); }}
        onOk={() => {
          if (!reassignOrder || !reassignTarget) { message.warning('请选择目标业务员'); return; }
          reassignMut.mutate({
            id: reassignOrder.id,
            target: reassignTarget,
            reason: reassignReason || '管理员改派',
          });
        }}
        confirmLoading={reassignMut.isPending}
      >
        {reassignOrder && (
          <div>
            <div style={{ marginBottom: 12, color: '#666' }}>
              当前业务员：<strong>{reassignOrder.assigned_salesman?.nickname || '未接单'}</strong>
            </div>
            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4 }}>目标业务员：<span style={{ color: '#999', fontSize: 12 }}>（按推荐程度自动排序）</span></div>
              <Select
                showSearch
                placeholder="选择业务员"
                value={reassignTarget}
                onChange={setReassignTarget}
                style={{ width: '100%' }}
                optionLabelProp="label"
                options={(salesmenData?.records || []).map((s: any) => {
                  const warn: string[] = [];
                  if (!s.is_accepting_orders) warn.push('未开放接单');
                  if (!s.has_linked_employee) warn.push('未绑 ERP 员工');
                  if (s.open_alerts > 0) warn.push(`${s.open_alerts} 个告警`);
                  return {
                    value: s.id,
                    label: `${s.nickname || s.username} ${s.phone ? `· ${s.phone}` : ''}`,
                    title: warn.join(' / '),
                    children: (
                      <div>
                        <div>
                          <strong>{s.nickname || s.username}</strong>
                          {s.phone && <span style={{ color: '#999', marginLeft: 8 }}>· {s.phone}</span>}
                        </div>
                        <div style={{ fontSize: 12, color: '#666', marginTop: 2 }}>
                          在途 {s.in_progress_count}
                          <span style={{ marginLeft: 12 }}>
                            {s.is_accepting_orders
                              ? <Tag color="green" style={{ marginLeft: 4 }}>接单中</Tag>
                              : <Tag color="default" style={{ marginLeft: 4 }}>未开放</Tag>}
                            {!s.has_linked_employee && <Tag color="red" style={{ marginLeft: 4 }}>无 ERP 员工</Tag>}
                            {s.open_alerts > 0 && <Tag color="orange" style={{ marginLeft: 4 }}>{s.open_alerts} 告警</Tag>}
                          </span>
                        </div>
                      </div>
                    ),
                  };
                })}
                filterOption={(input, option) =>
                  (option?.label as string).toLowerCase().includes(input.toLowerCase())
                }
              />
              {reassignTarget && (() => {
                const s = (salesmenData?.records || []).find((x: any) => x.id === reassignTarget);
                if (!s) return null;
                const issues: string[] = [];
                if (!s.is_accepting_orders) issues.push('该业务员未开放接单');
                if (!s.has_linked_employee) issues.push('未绑定 ERP 员工，无法计提成');
                if (s.open_alerts > 0) issues.push(`有 ${s.open_alerts} 条未解决告警`);
                return issues.length > 0 ? (
                  <div style={{ marginTop: 6, fontSize: 12, color: '#faad14' }}>
                    ⚠️ 警告：{issues.join('；')}，确认仍要改派给他？
                  </div>
                ) : null;
              })()}
            </div>
            <div>
              <div style={{ marginBottom: 4 }}>原因（可选）：</div>
              <Input.TextArea
                rows={2}
                placeholder="改派原因（记入审计）"
                value={reassignReason}
                onChange={e => setReassignReason(e.target.value)}
              />
            </div>
            <div style={{ marginTop: 12, fontSize: 12, color: '#ff4d4f' }}>
              改派会给原业务员记一条跳单（可能触发告警），请谨慎操作
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
