/**
 * 商城订单详情抽屉（管理员视角）
 *
 * 状态时间线 / 商品清单 / 金额明细 / 收货地址 / 凭证图 / 物流 / claim 日志
 */
import { Descriptions, Divider, Drawer, Empty, Image, Space, Spin, Table, Tag, Timeline, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title, Text } = Typography;

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
};

const PAY_METHOD: Record<string, string> = {
  cash: '现金', bank: '银行转账', wechat: '微信', alipay: '支付宝',
};

const PAY_STATUS: Record<string, { label: string; color: string }> = {
  pending_confirmation: { label: '待审批', color: 'gold' },
  confirmed: { label: '已确认', color: 'green' },
  rejected: { label: '已驳回', color: 'red' },
};

const CLAIM_ACTION: Record<string, string> = {
  claim: '抢单',
  release: '释放',
  reassign: '改派',
  admin_assign: '管理员指派',
};

interface Props {
  orderId: string;
  open: boolean;
  onClose: () => void;
}

export default function OrderDetail({ orderId, open, onClose }: Props) {
  const { data: order, isLoading } = useQuery<any>({
    queryKey: ['mall-admin-order-detail', orderId],
    queryFn: () => api.get(`/mall/admin/orders/${orderId}`).then(r => r.data),
    enabled: open && !!orderId,
  });

  if (isLoading || !order) {
    return (
      <Drawer title="订单详情" open={open} onClose={onClose} width={900}>
        <Spin />
      </Drawer>
    );
  }

  const fmt = (t?: string) => t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-';

  // 构造时间线
  const timelineItems = [
    { key: 'created_at', label: '已下单' },
    { key: 'claimed_at', label: '已接单' },
    { key: 'shipped_at', label: '已出库（扫码）' },
    { key: 'delivered_at', label: '已送达' },
    { key: 'paid_at', label: '财务确认收款' },
    { key: 'completed_at', label: '已完成' },
    { key: 'cancelled_at', label: '已取消', color: 'red' },
  ].filter(i => order[i.key]);

  return (
    <Drawer
      title={
        <Space>
          <Title level={5} style={{ margin: 0 }}>{order.order_no}</Title>
          <Tag color={STATUS_COLOR[order.status]}>{STATUS_LABEL[order.status] ?? order.status}</Tag>
          {order.commission_posted && <Tag color="green">提成已入账</Tag>}
          {order.cancellation_reason && <Tag color="red">取消原因：{order.cancellation_reason}</Tag>}
        </Space>
      }
      open={open}
      onClose={onClose}
      width={900}
    >
      {/* 状态时间线 */}
      <Title level={5}>流转时间线</Title>
      <Timeline
        items={timelineItems.map(i => ({
          color: (i as any).color || 'green',
          children: <div><strong>{i.label}</strong><div style={{ color: '#999', fontSize: 12 }}>{fmt(order[i.key])}</div></div>,
        }))}
      />

      <Divider />

      {/* 参与方 */}
      <Title level={5}>参与方</Title>
      <Descriptions bordered size="small" column={2} styles={{ label: { width: 110 } }}>
        <Descriptions.Item label="客户">
          {order.customer?.nickname || '-'}
          {order.customer?.phone && <span style={{ color: '#999' }}> · {order.customer.phone}</span>}
        </Descriptions.Item>
        <Descriptions.Item label="推荐业务员">
          {order.referrer_salesman?.nickname || '-'}
          {order.referrer_salesman?.phone && <span style={{ color: '#999' }}> · {order.referrer_salesman.phone}</span>}
        </Descriptions.Item>
        <Descriptions.Item label="配送业务员" span={2}>
          {order.assigned_salesman?.nickname || <Tag>未接单</Tag>}
          {order.assigned_salesman?.phone && <span style={{ color: '#999' }}> · {order.assigned_salesman.phone}</span>}
        </Descriptions.Item>
      </Descriptions>

      <Divider />

      {/* 收货地址 */}
      <Title level={5}>收货地址</Title>
      {order.address ? (
        <Descriptions bordered size="small" column={2} styles={{ label: { width: 110 } }}>
          <Descriptions.Item label="收件人">{order.address.receiver || '-'}</Descriptions.Item>
          <Descriptions.Item label="手机">{order.address.mobile || '-'}</Descriptions.Item>
          <Descriptions.Item label="省/市/区" span={2}>
            {[order.address.province, order.address.city, order.address.area].filter(Boolean).join(' ')}
          </Descriptions.Item>
          <Descriptions.Item label="详细地址" span={2}>{order.address.addr || '-'}</Descriptions.Item>
        </Descriptions>
      ) : <Empty description="无地址" />}

      <Divider />

      {/* 商品 */}
      <Title level={5}>商品清单</Title>
      <Table
        dataSource={order.items || []}
        rowKey={(r: any) => `${r.product_id}-${r.sku_id}`}
        pagination={false}
        size="small"
        columns={[
          { title: 'SKU', key: 'sku', width: 250, render: (_: any, r: any) => (
            <div>
              <div>{r.sku_snapshot?.product_name}</div>
              <div style={{ color: '#999', fontSize: 12 }}>{r.sku_snapshot?.sku_name}</div>
            </div>
          )},
          { title: '单价', dataIndex: 'price', width: 100, align: 'right' as const,
            render: (v: string) => `¥${Number(v).toLocaleString()}` },
          { title: '数量', dataIndex: 'quantity', width: 80, align: 'right' as const },
          { title: '成本快照', dataIndex: 'cost_price_snapshot', width: 100, align: 'right' as const,
            render: (v: string) => v ? `¥${Number(v).toLocaleString()}` : '-' },
          { title: '小计', dataIndex: 'subtotal', width: 120, align: 'right' as const,
            render: (v: string) => <strong>¥{Number(v).toLocaleString()}</strong> },
        ]}
      />

      <Divider />

      {/* 金额明细 */}
      <Title level={5}>金额明细</Title>
      <Descriptions bordered size="small" column={2} styles={{ label: { width: 110 } }}>
        <Descriptions.Item label="商品合计">¥{Number(order.total_amount).toLocaleString()}</Descriptions.Item>
        <Descriptions.Item label="运费">¥{Number(order.shipping_fee).toLocaleString()}</Descriptions.Item>
        <Descriptions.Item label="优惠">-¥{Number(order.discount_amount).toLocaleString()}</Descriptions.Item>
        <Descriptions.Item label="应收（payAmount）">
          <strong style={{ color: '#C9A961' }}>¥{Number(order.pay_amount).toLocaleString()}</strong>
        </Descriptions.Item>
        <Descriptions.Item label="已收（received）" span={2}>
          <strong style={{ color: Number(order.received_amount) >= Number(order.pay_amount) ? '#52c41a' : '#faad14' }}>
            ¥{Number(order.received_amount).toLocaleString()}
          </strong>
          <span style={{ color: '#999', marginLeft: 8 }}>
            （差额 ¥{(Number(order.pay_amount) - Number(order.received_amount)).toLocaleString()}）
          </span>
        </Descriptions.Item>
      </Descriptions>

      <Divider />

      {/* 收款凭证 */}
      <Title level={5}>收款凭证</Title>
      {(order.payments || []).length === 0 ? <Empty description="暂无凭证" /> : (
        <Table
          dataSource={order.payments}
          rowKey="id"
          pagination={false}
          size="small"
          columns={[
            { title: '金额', dataIndex: 'amount', width: 110, align: 'right' as const,
              render: (v: string) => `¥${Number(v).toLocaleString()}` },
            { title: '方式', dataIndex: 'payment_method', width: 90,
              render: (v: string) => <Tag>{PAY_METHOD[v] ?? v}</Tag> },
            { title: '状态', dataIndex: 'status', width: 90,
              render: (v: string) => {
                const m = PAY_STATUS[v];
                return m ? <Tag color={m.color}>{m.label}</Tag> : v;
              }},
            { title: '业务员', key: 'sm', width: 120,
              render: (_: any, r: any) => r.uploaded_by?.nickname || '-' },
            { title: '确认时间', dataIndex: 'confirmed_at', width: 150,
              render: (v: string) => v ? dayjs(v).format('MM-DD HH:mm') : '-' },
            { title: '驳回原因', dataIndex: 'rejected_reason', ellipsis: true },
            { title: '上传时间', dataIndex: 'created_at', width: 150,
              render: (v: string) => dayjs(v).format('MM-DD HH:mm') },
          ]}
          expandable={{
            expandedRowRender: (r: any) => (
              (r.vouchers || []).length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无凭证图" /> :
                <Space wrap>
                  {r.vouchers.map((v: any, i: number) => (
                    <Image key={i} src={v.url} width={120} height={120} style={{ objectFit: 'cover' }} />
                  ))}
                </Space>
            ),
            rowExpandable: (r: any) => (r.vouchers || []).length > 0,
          }}
        />
      )}

      <Divider />

      {/* 物流 */}
      <Title level={5}>出库/物流</Title>
      {(order.shipments || []).length === 0 ? <Empty description="暂无出库记录" /> : (
        <Table
          dataSource={order.shipments}
          rowKey="id"
          pagination={false}
          size="small"
          columns={[
            { title: '状态', dataIndex: 'status', width: 100,
              render: (v: string) => <Tag>{v}</Tag> },
            { title: '仓库', dataIndex: 'warehouse_id', ellipsis: true },
            { title: '出库时间', dataIndex: 'shipped_at', width: 160,
              render: (v: string) => fmt(v) },
            { title: '送达时间', dataIndex: 'delivered_at', width: 160,
              render: (v: string) => fmt(v) },
          ]}
        />
      )}

      {/* 送达照片 */}
      {(order.delivery_photos || []).length > 0 && (
        <div style={{ marginTop: 12 }}>
          <Typography.Text strong>送达照片：</Typography.Text>
          <div style={{ marginTop: 8 }}>
            <Space wrap>
              {order.delivery_photos.map((p: any, i: number) => (
                <Image key={i} src={p.url} width={120} height={120} style={{ objectFit: 'cover' }} />
              ))}
            </Space>
          </div>
        </div>
      )}

      <Divider />

      {/* 抢单/改派日志 */}
      <Title level={5}>抢单/改派日志</Title>
      {(order.claim_logs || []).length === 0 ? <Empty description="无日志" /> : (
        <Table
          dataSource={order.claim_logs}
          rowKey="id"
          pagination={false}
          size="small"
          columns={[
            { title: '动作', dataIndex: 'action', width: 100,
              render: (v: string) => <Tag>{CLAIM_ACTION[v] ?? v}</Tag> },
            { title: '从', key: 'from', width: 120,
              render: (_: any, r: any) => r.from_salesman?.nickname || '-' },
            { title: '到', key: 'to', width: 120,
              render: (_: any, r: any) => r.to_salesman?.nickname || '-' },
            { title: '操作人', dataIndex: 'operator_type', width: 100,
              render: (v: string) => v ? <Tag>{v === 'mall_user' ? '业务员本人' : 'ERP 管理员'}</Tag> : '-' },
            { title: '原因', dataIndex: 'reason', ellipsis: true },
            { title: '时间', dataIndex: 'created_at', width: 150,
              render: (v: string) => dayjs(v).format('MM-DD HH:mm:ss') },
          ]}
        />
      )}

      {/* 备注 */}
      {order.remarks && (
        <>
          <Divider />
          <Title level={5}>客户备注</Title>
          <Text>{order.remarks}</Text>
        </>
      )}
    </Drawer>
  );
}
