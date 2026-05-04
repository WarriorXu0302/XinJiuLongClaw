/**
 * 商城退货审批列表
 *
 * Tab：待审批 / 已通过 / 已退款 / 已驳回 / 全部
 * 详情抽屉：订单 + 商品明细 + 审批 / 已退 / 驳回按钮
 */
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Button, Descriptions, Drawer, Empty, InputNumber, message, Modal, Space, Table, Tabs, Tag, Typography,
} from 'antd';
import { CheckOutlined, DollarOutlined, EyeOutlined, StopOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title } = Typography;

const STATUS: Record<string, { text: string; color: string }> = {
  pending: { text: '待审批', color: 'orange' },
  approved: { text: '已通过待退款', color: 'blue' },
  refunded: { text: '已退款', color: 'green' },
  rejected: { text: '已驳回', color: 'red' },
};

interface ReturnRow {
  id: string;
  order_id: string;
  order_no?: string;
  order_pay_amount?: string;
  order_received_amount?: string;
  customer?: { id: string; nickname?: string; real_name?: string; phone?: string };
  reason: string;
  status: string;
  reviewer_employee_id?: string;
  reviewed_at?: string;
  review_note?: string;
  refund_amount?: string;
  refunded_at?: string;
  refund_method?: string;
  refund_note?: string;
  created_at: string;
}

interface ReturnDetail extends ReturnRow {
  items: {
    sku_id: number;
    product_name: string;
    sku_name: string;
    price: string;
    quantity: number;
    subtotal: string;
  }[];
}

export default function ReturnList() {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const initialStatus = searchParams.get('status') || 'pending';
  const [statusTab, setStatusTab] = useState<string>(initialStatus);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [detailId, setDetailId] = useState<string | null>(null);
  useEffect(() => {
    const s = searchParams.get('status');
    if (s) { setStatusTab(s); setPage(1); }
  }, [searchParams]);

  const { data, isLoading } = useQuery({
    queryKey: ['mall-returns', statusTab, page, pageSize],
    queryFn: () => api.get('/mall/admin/returns', {
      params: {
        status: statusTab === 'all' ? undefined : statusTab,
        skip: (page - 1) * pageSize,
        limit: pageSize,
      },
    }).then(r => r.data),
    refetchInterval: 15000,
  });
  const rows: ReturnRow[] = data?.records || [];
  const total: number = data?.total || 0;

  const { data: detail } = useQuery({
    queryKey: ['mall-return-detail', detailId],
    queryFn: () => api.get(`/mall/admin/returns/${detailId}`).then(r => r.data as ReturnDetail),
    enabled: !!detailId,
  });

  const approveMut = useMutation({
    mutationFn: ({ id, refund_amount, note }: { id: string; refund_amount?: number; note?: string }) =>
      api.post(`/mall/admin/returns/${id}/approve`, { refund_amount, note }),
    onSuccess: () => {
      message.success('已批准退货，库存已回退，订单状态已改为 refunded');
      setDetailId(null);
      queryClient.invalidateQueries({ queryKey: ['mall-returns'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '批准失败'),
  });

  const rejectMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.post(`/mall/admin/returns/${id}/reject`, { reason }),
    onSuccess: () => {
      message.success('已驳回');
      setDetailId(null);
      queryClient.invalidateQueries({ queryKey: ['mall-returns'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '驳回失败'),
  });

  const markRefundedMut = useMutation({
    mutationFn: ({ id, refund_method, refund_amount, note }: { id: string; refund_method: string; refund_amount?: number; note?: string }) =>
      api.post(`/mall/admin/returns/${id}/mark-refunded`, { refund_method, refund_amount, note }),
    onSuccess: () => {
      message.success('已标记退款完成');
      setDetailId(null);
      queryClient.invalidateQueries({ queryKey: ['mall-returns'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '标记失败'),
  });

  const columns: ColumnsType<ReturnRow> = [
    {
      title: '订单号', dataIndex: 'order_no', width: 180,
      render: (v: string) => <code>{v}</code>,
    },
    {
      title: '客户', key: 'cust', width: 160,
      render: (_, r) => r.customer ? (
        <div>
          <div><strong>{r.customer.real_name || r.customer.nickname || '-'}</strong></div>
          {r.customer.phone && <div style={{ color: '#999', fontSize: 12 }}>{r.customer.phone}</div>}
        </div>
      ) : '-',
    },
    { title: '申请原因', dataIndex: 'reason', ellipsis: true },
    {
      title: '订单金额', dataIndex: 'order_pay_amount', width: 110,
      render: (v?: string) => v ? `¥${v}` : '-',
    },
    {
      title: '退款金额', dataIndex: 'refund_amount', width: 110,
      render: (v?: string) => v ? <span style={{ color: '#cf1322' }}>¥{v}</span> : '-',
    },
    {
      title: '状态', dataIndex: 'status', width: 120,
      render: (v: string) => <Tag color={STATUS[v]?.color}>{STATUS[v]?.text || v}</Tag>,
    },
    {
      title: '申请时间', dataIndex: 'created_at', width: 150,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作', key: 'act', width: 90, fixed: 'right' as const,
      render: (_, r) => (
        <Button size="small" icon={<EyeOutlined />} onClick={() => setDetailId(r.id)}>
          查看
        </Button>
      ),
    },
  ];

  const TABS = [
    { key: 'pending', label: '待审批' },
    { key: 'approved', label: '已通过待退款' },
    { key: 'refunded', label: '已退款' },
    { key: 'rejected', label: '已驳回' },
    { key: 'all', label: '全部' },
  ];

  return (
    <div>
      <Title level={4}>商城退货审批</Title>
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
        scroll={{ x: 1200 }}
        locale={{ emptyText: <Empty description="暂无退货申请" /> }}
      />

      <Drawer
        title="退货申请详情"
        open={!!detailId}
        onClose={() => setDetailId(null)}
        size={760}
      >
        {detail && (
          <Space orientation="vertical" size="large" style={{ width: '100%' }}>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="订单号">{detail.order_no}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS[detail.status]?.color}>{STATUS[detail.status]?.text}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="申请人">{detail.customer?.real_name || detail.customer?.nickname}</Descriptions.Item>
              <Descriptions.Item label="联系电话">{detail.customer?.phone || '-'}</Descriptions.Item>
              <Descriptions.Item label="订单金额">¥{detail.order_pay_amount}</Descriptions.Item>
              <Descriptions.Item label="订单已收">¥{detail.order_received_amount}</Descriptions.Item>
              <Descriptions.Item label="退款金额" span={2}>
                {detail.refund_amount ? <span style={{ color: '#cf1322' }}>¥{detail.refund_amount}</span> : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="申请时间" span={2}>{dayjs(detail.created_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
              <Descriptions.Item label="申请原因" span={2}>{detail.reason}</Descriptions.Item>
              {detail.reviewed_at && (
                <Descriptions.Item label="审批时间" span={2}>{dayjs(detail.reviewed_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
              )}
              {detail.review_note && (
                <Descriptions.Item label="审批备注" span={2}>{detail.review_note}</Descriptions.Item>
              )}
              {detail.refunded_at && (
                <Descriptions.Item label="退款时间" span={2}>{dayjs(detail.refunded_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
              )}
              {detail.refund_method && (
                <Descriptions.Item label="退款方式">{detail.refund_method}</Descriptions.Item>
              )}
            </Descriptions>

            <div>
              <Title level={5}>商品明细</Title>
              <Table
                dataSource={detail.items}
                rowKey="sku_id"
                size="small"
                pagination={false}
                columns={[
                  { title: '商品', dataIndex: 'product_name' },
                  { title: '规格', dataIndex: 'sku_name' },
                  { title: '单价', dataIndex: 'price', render: (v: string) => `¥${v}` },
                  { title: '数量', dataIndex: 'quantity' },
                  { title: '小计', dataIndex: 'subtotal', render: (v: string) => `¥${v}` },
                ]}
              />
            </div>

            {detail.status === 'pending' && (
              <Space>
                <Button
                  type="primary"
                  icon={<CheckOutlined />}
                  loading={approveMut.isPending}
                  onClick={() => {
                    let amt: number | undefined = Number(detail.order_received_amount || 0);
                    Modal.confirm({
                      title: `批准订单 ${detail.order_no} 的退货？`,
                      content: (
                        <div>
                          <div style={{ color: '#faad14', marginBottom: 8 }}>
                            批准后将：回退库存 + 订单状态改为 refunded + 相关提成标为 reversed
                          </div>
                          <div>
                            退款金额（默认为已收金额，可调整）：
                            <InputNumber
                              style={{ marginLeft: 8 }}
                              defaultValue={amt}
                              min={0}
                              precision={2}
                              onChange={(v) => { amt = v ?? undefined; }}
                            />
                          </div>
                        </div>
                      ),
                      onOk: () => approveMut.mutateAsync({ id: detail.id, refund_amount: amt }),
                    });
                  }}
                >
                  批准退货
                </Button>
                <Button
                  danger
                  icon={<StopOutlined />}
                  loading={rejectMut.isPending}
                  onClick={() => {
                    let reason = '';
                    Modal.confirm({
                      title: `驳回订单 ${detail.order_no} 的退货申请？`,
                      content: (
                        <div>
                          <textarea
                            rows={3}
                            placeholder="驳回原因（必填，会通知用户）"
                            style={{ width: '100%' }}
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

            {detail.status === 'approved' && (
              <Space>
                <Button
                  type="primary"
                  icon={<DollarOutlined />}
                  loading={markRefundedMut.isPending}
                  onClick={() => {
                    let method = 'cash';
                    let amount: number | undefined = Number(detail.refund_amount || 0);
                    Modal.confirm({
                      title: `标记订单 ${detail.order_no} 退款已完成？`,
                      content: (
                        <div>
                          <div style={{ color: '#52c41a', marginBottom: 8 }}>
                            请确认线下退款已完成（现金 / 转账等），系统将记录为"已退款"并通知客户。
                          </div>
                          <div style={{ marginBottom: 8 }}>
                            退款方式：
                            <select
                              defaultValue={method}
                              style={{ marginLeft: 8 }}
                              onChange={e => { method = e.target.value; }}
                            >
                              <option value="cash">现金</option>
                              <option value="bank">银行转账</option>
                              <option value="wechat">微信</option>
                              <option value="alipay">支付宝</option>
                            </select>
                          </div>
                          <div>
                            实际退款金额：
                            <InputNumber
                              style={{ marginLeft: 8 }}
                              defaultValue={amount}
                              min={0}
                              precision={2}
                              onChange={(v) => { amount = v ?? undefined; }}
                            />
                          </div>
                        </div>
                      ),
                      onOk: () => markRefundedMut.mutateAsync({
                        id: detail.id, refund_method: method, refund_amount: amount,
                      }),
                    });
                  }}
                >
                  标记退款完成
                </Button>
              </Space>
            )}
          </Space>
        )}
      </Drawer>
    </div>
  );
}
