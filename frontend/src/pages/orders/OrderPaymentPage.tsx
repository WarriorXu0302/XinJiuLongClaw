import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Alert, Button, Card, Descriptions, InputNumber, message, Radio, Space, Table, Tag, Typography, Upload } from 'antd';
import { ArrowLeftOutlined, CheckCircleOutlined, FileImageOutlined, LockOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { UploadFile } from 'antd/es/upload';
import api from '../../api/client';

const { Title, Text } = Typography;

interface OrderItem { product?: { name: string }; quantity: number; quantity_unit?: string; unit_price: string }
interface OrderDetail {
  id: string; order_no: string; status: string;
  customer?: { name: string };
  customer_id?: string;
  brand_id?: string;
  total_amount: string; customer_paid_amount?: string;
  deal_amount?: string; policy_gap?: string;
  settlement_mode?: string; items?: OrderItem[];
  payment_status?: string;
}
interface Receipt {
  id: string; receipt_no?: string; amount: string; source_type?: string;
  receipt_date?: string; payment_method?: string; notes?: string;
  created_at?: string;
}

function OrderPaymentPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [uploadedUrls, setUploadedUrls] = useState<string[]>([]);
  const [sourceType, setSourceType] = useState<'customer' | 'employee_advance'>('customer');
  const [amount, setAmount] = useState<number | null>(null);

  const { data: order, isLoading } = useQuery<OrderDetail>({
    queryKey: ['order-payment', orderId],
    queryFn: () => api.get(`/orders/${orderId}`).then(r => r.data),
    enabled: !!orderId,
  });

  const { data: receipts = [] } = useQuery<Receipt[]>({
    queryKey: ['order-receipts', orderId],
    queryFn: () => api.get('/receipts').then(r => r.data.filter((rc: any) => rc.order_id === orderId)),
    enabled: !!orderId,
  });

  const voucherMut = useMutation({
    mutationFn: ({ voucherUrls, amt }: { voucherUrls: string[]; amt: number }) => api.post(`/orders/${orderId}/upload-payment-voucher`, {
      voucher_urls: voucherUrls,
      amount: amt,
      source_type: sourceType,
    }),
    onSuccess: (r: any) => {
      const newStatus = r.data?.payment_status;
      message.success(newStatus === 'fully_paid' ? '全款已收齐，通知财务确认' : '已登记本次收款');
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      queryClient.invalidateQueries({ queryKey: ['order-receipts', orderId] });
      navigate('/orders');
    },
    onError: (err: any) => message.error(err?.response?.data?.detail ?? '提交失败'),
  });

  const handleUpload = async (options: any) => {
    const { file, onSuccess, onError } = options;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const { data } = await api.post('/uploads', formData, { headers: { 'Content-Type': 'multipart/form-data' } });
      setUploadedUrls(prev => [...prev, data.url]);
      onSuccess(data);
    } catch (err: any) {
      message.error('上传失败');
      onError(err);
    }
  };

  const handleSubmit = () => {
    if (uploadedUrls.length === 0) {
      message.warning('请至少上传一张收款凭证');
      return;
    }
    if (!amount || amount <= 0) {
      message.warning('请填写本次收款金额');
      return;
    }
    voucherMut.mutate({ voucherUrls: uploadedUrls, amt: amount });
  };

  if (isLoading || !order) return <div style={{ padding: 24 }}>加载中...</div>;
  if (order.status === 'completed') return (
    <div style={{ padding: 24 }}>
      <Alert type="success" message={`订单 ${order.order_no} 已确认收款、流转完成`} showIcon />
      <Button style={{ marginTop: 16 }} onClick={() => navigate('/orders')}>返回订单列表</Button>
    </div>
  );
  if (order.status !== 'delivered') return (
    <div style={{ padding: 24 }}>
      <Alert type="warning" message={`订单状态为 "${order.status}"，只有已送达的订单才能上传收款凭证`} showIcon />
      <Button style={{ marginTop: 16 }} onClick={() => navigate('/orders')}>返回订单列表</Button>
    </div>
  );

  const totalDue = Number(order.customer_paid_amount ?? order.total_amount);
  const receivedTotal = receipts.reduce((s, r) => s + Number(r.amount), 0);
  const customerReceived = receipts.filter(r => r.source_type === 'customer').reduce((s, r) => s + Number(r.amount), 0);
  const employeeAdvanceReceived = receipts.filter(r => r.source_type === 'employee_advance').reduce((s, r) => s + Number(r.amount), 0);
  const remaining = Math.max(0, totalDue - receivedTotal);

  const isEmployeePay = order.settlement_mode === 'employee_pay';
  const customerShare = Number(order.deal_amount ?? order.total_amount);
  const employeeShare = Number(order.policy_gap ?? 0);
  const customerRemaining = Math.max(0, customerShare - customerReceived);
  const employeeRemaining = Math.max(0, employeeShare - employeeAdvanceReceived);
  const isFullyPaid = order.payment_status === 'fully_paid';

  const SOURCE_LABEL: Record<string, { color: string; text: string }> = {
    customer: { color: 'blue', text: '客户付款' },
    employee_advance: { color: 'orange', text: '业务员垫付' },
    company_advance: { color: 'purple', text: '公司内部' },
  };

  const historyTable = (
    <Card title="已登记凭证记录" size="small" style={{ marginBottom: 16 }}>
      {receipts.length === 0 ? (
        <Text type="secondary">暂无</Text>
      ) : (
        <Table<Receipt>
          dataSource={[...receipts].sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))}
          rowKey="id" size="small" pagination={false}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 160,
              render: (v?: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
            { title: '金额', dataIndex: 'amount', align: 'right' as const, width: 110,
              render: (v: string) => <Text strong>¥{Number(v).toLocaleString()}</Text> },
            { title: '来源', dataIndex: 'source_type', width: 110,
              render: (v?: string) => {
                const m = SOURCE_LABEL[v ?? 'customer'];
                return <Tag color={m?.color ?? 'default'}>{m?.text ?? v}</Tag>;
              }},
            { title: '备注', dataIndex: 'notes', ellipsis: true },
          ]}
        />
      )}
    </Card>
  );

  return (
    <div style={{ maxWidth: 640, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/orders')}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>上传收款凭证</Title>
      </Space>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="订单号">{order.order_no}</Descriptions.Item>
          <Descriptions.Item label="客户">{order.customer?.name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="商品" span={2}>
            {order.items?.map((it, i) => (
              <Tag key={i}>{it.product?.name ?? '商品'} ×{it.quantity}{it.quantity_unit || '瓶'}</Tag>
            )) ?? '-'}
          </Descriptions.Item>
        </Descriptions>

        <div style={{ padding: 12, background: '#f6ffed', borderRadius: 6, marginTop: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <Text type="secondary">订单应收</Text>
            <Text strong style={{ fontSize: 20, color: '#52c41a' }}>¥{totalDue.toLocaleString()}</Text>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
            <Text type="secondary">已收 ¥{receivedTotal.toLocaleString()}</Text>
            <Text style={{ color: remaining > 0 ? '#fa8c16' : '#52c41a' }}>
              {remaining > 0 ? `待收 ¥${remaining.toLocaleString()}` : '已全款'}
            </Text>
          </div>
        </div>

        {isEmployeePay && (
          <Alert type="info" showIcon style={{ marginTop: 12 }}
            message="业务员垫付模式"
            description={
              <div style={{ fontSize: 13 }}>
                <div>客户应付：¥{customerShare.toLocaleString()}（已收 ¥{customerReceived.toLocaleString()}，待收 ¥{customerRemaining.toLocaleString()}）</div>
                <div>业务员垫付：¥{employeeShare.toLocaleString()}（已补 ¥{employeeAdvanceReceived.toLocaleString()}，待补 ¥{employeeRemaining.toLocaleString()}）</div>
                <div style={{ color: '#888', marginTop: 4 }}>两笔凑齐 ¥{totalDue.toLocaleString()} 才算全款，业务员才能触发提成。</div>
              </div>
            }
          />
        )}

        {order.settlement_mode === 'company_pay' && (
          <Alert type="info" showIcon style={{ marginTop: 12 }}
            message="公司垫付模式"
            description={`客户只付到手价 ¥${customerShare.toLocaleString()}，政策差 ¥${employeeShare.toLocaleString()} 由公司让利（不入收款），等厂家兑付后进 F 类账户。`}
          />
        )}
      </Card>

      {isFullyPaid ? (
        <Alert
          type="success" showIcon icon={<LockOutlined />}
          style={{ marginBottom: 16 }}
          message="已收齐全款"
          description={
            <>
              <div>订单应收 ¥{totalDue.toLocaleString()} 已收齐，正在等待财务在<strong>审批中心</strong>确认收款。</div>
              <div style={{ color: '#888', marginTop: 4 }}>本页面已锁定，不可再登记凭证。如需修正请联系财务。</div>
            </>
          }
        />
      ) : null}

      {historyTable}

      {!isFullyPaid && <Card title={<><FileImageOutlined /> 登记本次收款</>} size="small" style={{ marginBottom: 16 }}>
        {isEmployeePay && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ marginBottom: 6, fontSize: 13, color: '#666' }}>凭证来源</div>
            <Radio.Group value={sourceType} onChange={e => { setSourceType(e.target.value); setAmount(null); }}>
              <Radio.Button value="customer">客户付款（待收 ¥{customerRemaining.toLocaleString()}）</Radio.Button>
              <Radio.Button value="employee_advance">业务员垫付（待补 ¥{employeeRemaining.toLocaleString()}）</Radio.Button>
            </Radio.Group>
          </div>
        )}
        <div style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 6, fontSize: 13, color: '#666' }}>本次收款金额（必填）</div>
          <InputNumber
            style={{ width: '100%' }}
            min={0.01}
            precision={2}
            prefix="¥"
            placeholder={isEmployeePay
              ? (sourceType === 'customer' ? `建议 ¥${customerRemaining}` : `建议 ¥${employeeRemaining}`)
              : `建议 ¥${remaining}`}
            value={amount ?? undefined}
            onChange={(v) => setAmount(v == null ? null : Number(v))}
          />
        </div>
        <Upload
          listType="picture-card"
          fileList={fileList}
          customRequest={handleUpload}
          onChange={({ fileList: fl }) => setFileList(fl)}
          accept=".jpg,.jpeg,.png,.webp,.heic"
          multiple
        >
          {fileList.length < 5 && (
            <div><PlusOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>上传凭证</div></div>
          )}
        </Upload>
        <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>微信/支付宝转账截图、银行回单等</div>
      </Card>}

      {!isFullyPaid && (
        <Button
          type="primary"
          size="large"
          block
          icon={<CheckCircleOutlined />}
          disabled={uploadedUrls.length === 0}
          loading={voucherMut.isPending}
          onClick={handleSubmit}
          style={{ height: 48, fontSize: 16 }}
        >
          提交收款凭证 ({uploadedUrls.length} 张)
        </Button>
      )}
    </div>
  );
}

export default OrderPaymentPage;
