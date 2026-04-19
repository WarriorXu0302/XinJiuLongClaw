import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Alert, Button, Card, Descriptions, message, Space, Tag, Typography, Upload } from 'antd';
import { ArrowLeftOutlined, CheckCircleOutlined, FileImageOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { UploadFile } from 'antd/es/upload';
import api from '../../api/client';

const { Title, Text } = Typography;

interface OrderItem { product?: { name: string }; quantity: number; quantity_unit?: string; unit_price: string }
interface OrderDetail {
  id: string; order_no: string; status: string;
  customer?: { name: string };
  total_amount: string; customer_paid_amount?: string;
  settlement_mode?: string; items?: OrderItem[];
}

function OrderPaymentPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [uploadedUrls, setUploadedUrls] = useState<string[]>([]);

  const { data: order, isLoading } = useQuery<OrderDetail>({
    queryKey: ['order-payment', orderId],
    queryFn: () => api.get(`/orders/${orderId}`).then(r => r.data),
    enabled: !!orderId,
  });

  const voucherMut = useMutation({
    mutationFn: (voucherUrls: string[]) => api.post(`/orders/${orderId}/upload-payment-voucher`, { voucher_urls: voucherUrls }),
    onSuccess: () => {
      message.success('收款凭证已提交，等待确认');
      queryClient.invalidateQueries({ queryKey: ['orders'] });
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
    voucherMut.mutate(uploadedUrls);
  };

  if (isLoading || !order) return <div style={{ padding: 24 }}>加载中...</div>;
  if (order.status !== 'delivered') return (
    <div style={{ padding: 24 }}>
      <Alert type="warning" title={`订单状态为 "${order.status}"，只有已送达的订单才能上传收款凭证`} showIcon />
      <Button style={{ marginTop: 16 }} onClick={() => navigate('/orders')}>返回订单列表</Button>
    </div>
  );

  const payAmount = order.customer_paid_amount ?? order.total_amount;

  return (
    <div style={{ maxWidth: 600, margin: '0 auto' }}>
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
        <div style={{ textAlign: 'center', padding: '12px 0', background: '#f6ffed', borderRadius: 6, marginTop: 8 }}>
          <div style={{ color: '#888', fontSize: 12 }}>应收金额</div>
          <Text strong style={{ fontSize: 24, color: '#52c41a' }}>¥{Number(payAmount).toLocaleString()}</Text>
        </div>
      </Card>

      <Card title={<><FileImageOutlined /> 上传收款凭证</>} size="small" style={{ marginBottom: 16 }}>
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
      </Card>

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
    </div>
  );
}

export default OrderPaymentPage;
