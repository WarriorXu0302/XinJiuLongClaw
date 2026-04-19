import React, { useState } from 'react';
import { Button, Descriptions, Divider, Empty, Input, message, Modal, Space, Table, Tag, Typography } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import { useBrandFilter } from '../../stores/useBrandFilter';
import api from '../../api/client';

const { Title, Text } = Typography;

interface OrderItem { product_name?: string; quantity: number; unit_price: string }
interface RequestItem {
  id: string; benefit_type: string; name: string; quantity: number;
  standard_unit_value: number; standard_total: number;
  unit_value: number; total_value: number;
  product_name?: string; is_material: boolean;
}
interface PolicyRequest {
  id: string;
  request_source: string;
  approval_mode: string;
  order_id?: string;
  order?: {
    order_no: string; total_amount: string;
    deal_unit_price?: string; deal_amount?: string;
    policy_gap?: string; policy_value?: string; policy_surplus?: string;
    settlement_mode?: string;
    customer?: { name: string }; salesman?: { name: string };
    items?: OrderItem[];
  };
  customer?: { name: string };
  brand_id?: string;
  usage_purpose?: string;
  scheme_no?: string;
  total_policy_value?: number;
  total_gap?: number;
  settlement_mode?: string;
  request_items?: RequestItem[];
  policy_snapshot?: Record<string, unknown>;
  status: string;
  created_at: string;
}

const sourceLabel: Record<string, string> = { order: '订单', hospitality: '客情', market_activity: '市场活动', manual: '手工' };
const benefitLabel: Record<string, string> = { tasting_meal: '品鉴会餐费', tasting_wine: '品鉴酒', travel: '庄园之旅', rebate: '返利', gift: '赠品', other: '其他' };
const settlementLabel: Record<string, string> = { customer_pay: '客户按进货价结账', employee_pay: '业务垫付', company_pay: '公司垫付' };

function PolicyApproval() {
  const queryClient = useQueryClient();
  const [rejectId, setRejectId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [detailRecord, setDetailRecord] = useState<PolicyRequest | null>(null);

  const { brandId, params: brandParams } = useBrandFilter();

  const { data: pendingInternal = [], isLoading: loadingInternal } = useQuery<PolicyRequest[]>({
    queryKey: ['policy-requests-approval-internal', brandId],
    queryFn: () => api.get('/policies/requests', { params: { status: 'pending_internal', limit: 200 } }).then(r => r.data),
    refetchInterval: 5000,
  });

  const { data: pendingExternal = [] } = useQuery<PolicyRequest[]>({
    queryKey: ['policy-requests-approval-external', brandId],
    queryFn: () => api.get('/policies/requests', { params: { status: 'pending_external', limit: 200 } }).then(r => r.data),
    refetchInterval: 5000,
  });

  const pendingRequests = [...pendingInternal, ...pendingExternal];
  const isLoading = loadingInternal;
  const allRequests = pendingRequests;

  const approveMutation = useMutation({
    mutationFn: async (prId: string) => {
      // 1. Update policy request status to approved
      await api.put(`/policies/requests/${prId}`, { status: 'approved' });

      // 2. Find the linked order and approve its policy
      const pr = allRequests.find(r => r.id === prId);
      if (pr?.order_id) {
        try {
          await api.post(`/orders/${pr.order_id}/approve-policy`);
        } catch { /* order might not be in correct state */ }
      }
    },
    onSuccess: () => {
      message.success('政策审批通过，订单已放行');
      queryClient.invalidateQueries({ queryKey: ['policy-requests-approval-internal'] }); queryClient.invalidateQueries({ queryKey: ['policy-requests-approval-external'] });
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (err: any) => message.error(err?.response?.data?.detail ?? '审批失败'),
  });

  const rejectMutation = useMutation({
    mutationFn: async ({ id, reason }: { id: string; reason: string }) => {
      await api.put(`/policies/requests/${id}`, { status: 'rejected' });
      const pr = allRequests.find(r => r.id === id);
      if (pr?.order_id) {
        try {
          await api.post(`/orders/${pr.order_id}/reject-policy`, { rejection_reason: reason });
        } catch { /* ignore */ }
      }
    },
    onSuccess: () => {
      message.success('已驳回');
      setRejectId(null);
      setRejectReason('');
      queryClient.invalidateQueries({ queryKey: ['policy-requests-approval-internal'] }); queryClient.invalidateQueries({ queryKey: ['policy-requests-approval-external'] });
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (err: any) => message.error(err?.response?.data?.detail ?? '驳回失败'),
  });

  const columns: ColumnsType<PolicyRequest> = [
    { title: '来源', dataIndex: 'request_source', width: 80, render: (v: string) => <Tag>{sourceLabel[v] ?? v}</Tag> },
    { title: '客户', key: 'customer', width: 120, render: (_, r) => r.customer?.name ?? r.order?.customer?.name ?? '-' },
    { title: '订单号', key: 'order', width: 160, render: (_, r) => r.order?.order_no ?? '-' },
    { title: '订单金额', key: 'amount', width: 100, align: 'right', render: (_, r) => r.order ? `¥${Number(r.order.total_amount).toFixed(0)}` : '-' },
    { title: '审批模式', dataIndex: 'approval_mode', width: 130, render: (v: string) => v === 'internal_only' ? <Tag color="blue">仅内部</Tag> : <Tag color="orange">内部+外部</Tag> },
    { title: '方案号', dataIndex: 'scheme_no', width: 140, render: (v: string) => v ?? <Text type="warning">待回填</Text> },
    { title: '申请时间', dataIndex: 'created_at', width: 160, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
    {
      title: '操作', key: 'action', width: 200,
      render: (_, record) => (
        <Space>
          <a onClick={() => setDetailRecord(record)}>查看</a>
          <Button size="small" type="primary" icon={<CheckCircleOutlined />}
            onClick={() => approveMutation.mutate(record.id)}
            loading={approveMutation.isPending}
          >通过</Button>
          <Button size="small" danger icon={<CloseCircleOutlined />}
            onClick={() => setRejectId(record.id)}
          >驳回</Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Title level={4}>政策审批 <Tag color="red">{pendingRequests.length} 待审</Tag></Title>

      {pendingRequests.length === 0 && !isLoading ? (
        <Empty description="暂无待审批的政策申请" />
      ) : (
        <Table<PolicyRequest>
          columns={columns}
          dataSource={pendingRequests}
          rowKey="id"
          loading={isLoading}
          size="middle"
          pagination={false}
        />
      )}

      {/* 政策详情弹窗 */}
      <Modal title="政策审批详情" open={!!detailRecord} onCancel={() => setDetailRecord(null)} width={720}
        footer={detailRecord ? (
          <Space>
            <Button danger icon={<CloseCircleOutlined />} onClick={() => { setDetailRecord(null); setRejectId(detailRecord.id); }}>驳回</Button>
            <Button type="primary" icon={<CheckCircleOutlined />} loading={approveMutation.isPending}
              onClick={() => { approveMutation.mutate(detailRecord.id); setDetailRecord(null); }}>审批通过</Button>
          </Space>
        ) : null}
      >
        {detailRecord && (() => {
          const o = detailRecord.order;
          // 盈亏 = 政策总价值 - 政策差额（优先从政策申请取，其次订单）
          const pv = detailRecord.total_policy_value ?? (o?.policy_value ? Number(o.policy_value) : 0);
          const gap = detailRecord.total_gap ?? (o?.policy_gap ? Number(o.policy_gap) : 0);
          const surplus = pv && gap ? pv - gap : (o?.policy_surplus ? Number(o.policy_surplus) : null);
          return (
            <>
              {/* 基本信息 */}
              <Descriptions column={3} size="small" bordered style={{ marginBottom: 16 }}>
                <Descriptions.Item label="来源"><Tag>{sourceLabel[detailRecord.request_source]}</Tag></Descriptions.Item>
                <Descriptions.Item label="审批模式">{detailRecord.approval_mode === 'internal_only' ? <Tag color="blue">仅内部</Tag> : <Tag color="orange">内部+外部</Tag>}</Descriptions.Item>
                <Descriptions.Item label="方案号">{detailRecord.scheme_no ?? <Text type="warning">待回填</Text>}</Descriptions.Item>
                <Descriptions.Item label="客户">{detailRecord.customer?.name ?? o?.customer?.name ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="业务员">{o?.salesman?.name ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="结算模式">{settlementLabel[detailRecord.settlement_mode ?? o?.settlement_mode ?? ''] ?? '-'}</Descriptions.Item>
              </Descriptions>

              {/* 订单信息 */}
              {o && (
                <>
                  <Divider orientation="left" style={{ margin: '12px 0 8px' }}>订单信息</Divider>
                  <Descriptions column={3} size="small" bordered style={{ marginBottom: 8 }}>
                    <Descriptions.Item label="订单号"><Text copyable>{o.order_no}</Text></Descriptions.Item>
                    <Descriptions.Item label="订单货款"><Text strong>¥{Number(o.total_amount).toLocaleString()}</Text></Descriptions.Item>
                    <Descriptions.Item label="到手单价">{o.deal_unit_price ? `¥${Number(o.deal_unit_price).toLocaleString()}` : '-'}</Descriptions.Item>
                    <Descriptions.Item label="到手总额">{o.deal_amount ? `¥${Number(o.deal_amount).toLocaleString()}` : '-'}</Descriptions.Item>
                    <Descriptions.Item label="政策差额">{o.policy_gap ? <Text type="warning">¥{Number(o.policy_gap).toLocaleString()}</Text> : '-'}</Descriptions.Item>
                    <Descriptions.Item label="政策红利/折损">{surplus !== null ? <Text strong style={{ color: surplus >= 0 ? '#52c41a' : '#ff4d4f' }}>{surplus >= 0 ? '+' : ''}¥{surplus.toLocaleString()}</Text> : '-'}</Descriptions.Item>
                  </Descriptions>

                  {/* 订单商品 */}
                  {o.items && o.items.length > 0 && (
                    <div style={{ background: '#fafafa', borderRadius: 6, padding: '8px 12px', marginBottom: 8 }}>
                      <Text type="secondary" style={{ fontSize: 12, fontWeight: 600 }}>商品明细</Text>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 80px 100px', gap: '4px 12px', marginTop: 4, fontSize: 13 }}>
                        <Text type="secondary" style={{ fontSize: 11 }}>商品</Text>
                        <Text type="secondary" style={{ fontSize: 11 }}>数量</Text>
                        <Text type="secondary" style={{ fontSize: 11, textAlign: 'right' }}>单价</Text>
                        {o.items.map((item, i) => (
                          <React.Fragment key={i}>
                            <span>{item.product_name ?? '-'}</span>
                            <span>{item.quantity}</span>
                            <span style={{ textAlign: 'right' }}>¥{Number(item.unit_price).toLocaleString()}</span>
                          </React.Fragment>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* 政策明细 */}
              {detailRecord.request_items && detailRecord.request_items.length > 0 && (
                <>
                  <Divider orientation="left" style={{ margin: '12px 0 8px' }}>政策明细（折算价值 ¥{detailRecord.total_policy_value?.toLocaleString() ?? 0}）</Divider>
                  <div style={{ display: 'grid', gridTemplateColumns: '90px 1fr 50px 90px 90px', gap: '4px 8px', fontSize: 13, padding: '0 4px' }}>
                    <Text type="secondary" style={{ fontSize: 11, fontWeight: 600 }}>类型</Text>
                    <Text type="secondary" style={{ fontSize: 11, fontWeight: 600 }}>名称</Text>
                    <Text type="secondary" style={{ fontSize: 11, fontWeight: 600 }}>数量</Text>
                    <Text type="secondary" style={{ fontSize: 11, fontWeight: 600, textAlign: 'right' }}>面值</Text>
                    <Text type="secondary" style={{ fontSize: 11, fontWeight: 600, textAlign: 'right' }}>折算价值</Text>
                    {detailRecord.request_items.map((ri) => (
                      <React.Fragment key={ri.id}>
                        <Tag style={{ margin: 0 }}>{benefitLabel[ri.benefit_type] ?? ri.benefit_type}</Tag>
                        <span>{ri.name}{ri.product_name ? <Text type="secondary" style={{ fontSize: 11 }}> ({ri.product_name})</Text> : ''}{ri.is_material ? <Tag color="cyan" style={{ marginLeft: 4, fontSize: 10 }}>物料</Tag> : ''}</span>
                        <span>{ri.quantity}{(ri as any).quantity_unit || '次'}</span>
                        <span style={{ textAlign: 'right' }}>¥{ri.standard_total.toLocaleString()}</span>
                        <span style={{ textAlign: 'right' }}>¥{ri.total_value.toLocaleString()}</span>
                      </React.Fragment>
                    ))}
                  </div>
                </>
              )}

              {/* 盈亏汇总 */}
              {o && (() => {
                const totalAmt = Number(o.total_amount);
                const dealAmt = Number(o.deal_amount ?? 0);
                const policyGap = Number(detailRecord.total_gap ?? o.policy_gap ?? 0);
                const policyValue = Number(detailRecord.total_policy_value ?? o.policy_value ?? 0);
                const custPaid = Number(o.customer_paid_amount ?? totalAmt);
                const policyReceivable = Number(o.policy_receivable ?? 0);
                // 预估利润 = 政策价值 - 政策差额（红利部分就是利润空间）
                const policySurplus = surplus ?? 0;
                return (
                  <div style={{ marginTop: 16, padding: 16, background: '#f0f5ff', borderRadius: 8 }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, textAlign: 'center', marginBottom: 12 }}>
                      <div><div style={{ color: '#888', fontSize: 11 }}>订单货款</div><div style={{ fontSize: 16, fontWeight: 600 }}>¥{totalAmt.toLocaleString()}</div></div>
                      <div><div style={{ color: '#888', fontSize: 11 }}>到手总额</div><div style={{ fontSize: 16, fontWeight: 600 }}>¥{dealAmt.toLocaleString()}</div></div>
                      <div><div style={{ color: '#888', fontSize: 11 }}>政策差额</div><div style={{ fontSize: 16, fontWeight: 600, color: '#fa8c16' }}>¥{policyGap.toLocaleString()}</div></div>
                      <div><div style={{ color: '#888', fontSize: 11 }}>政策总价值</div><div style={{ fontSize: 16, fontWeight: 600, color: '#1890ff' }}>¥{policyValue.toLocaleString()}</div></div>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, textAlign: 'center', borderTop: '1px solid #d9e8ff', paddingTop: 12 }}>
                      <div><div style={{ color: '#888', fontSize: 11 }}>客户实付</div><div style={{ fontSize: 16, fontWeight: 600 }}>¥{custPaid.toLocaleString()}</div></div>
                      <div><div style={{ color: '#888', fontSize: 11 }}>政策应收</div><div style={{ fontSize: 16, fontWeight: 600, color: policyReceivable > 0 ? '#ff4d4f' : '#52c41a' }}>¥{policyReceivable.toLocaleString()}</div></div>
                      <div><div style={{ color: '#888', fontSize: 11 }}>结算模式</div><div style={{ fontSize: 14, fontWeight: 600 }}>{settlementLabel[detailRecord.settlement_mode ?? o?.settlement_mode ?? ''] ?? '-'}</div></div>
                      <div>
                        <div style={{ color: '#888', fontSize: 11, fontWeight: 600 }}>预估盈亏</div>
                        <div style={{ fontSize: 22, fontWeight: 700, color: policySurplus >= 0 ? '#52c41a' : '#ff4d4f' }}>
                          {policySurplus >= 0 ? '+' : ''}¥{policySurplus.toLocaleString()}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })()}
            </>
          );
        })()}
      </Modal>

      {/* 驳回原因弹窗 */}
      <Modal title="驳回原因" open={!!rejectId} okText="确认驳回" okButtonProps={{ danger: true }}
        onOk={() => { if (rejectId && rejectReason) rejectMutation.mutate({ id: rejectId, reason: rejectReason }); }}
        onCancel={() => { setRejectId(null); setRejectReason(''); }}
        confirmLoading={rejectMutation.isPending}
      >
        <Input.TextArea rows={3} placeholder="请输入驳回原因" value={rejectReason} onChange={e => setRejectReason(e.target.value)} />
      </Modal>
    </>
  );
}

export default PolicyApproval;
