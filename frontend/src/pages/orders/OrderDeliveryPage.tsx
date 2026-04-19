import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Alert, Button, Card, Descriptions, message, Space, Tag, Typography, Upload } from 'antd';
import { ArrowLeftOutlined, CameraOutlined, CheckCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { UploadFile } from 'antd/es/upload';
import api from '../../api/client';

const { Title } = Typography;

interface OrderItem { product?: { name: string }; quantity: number; quantity_unit?: string; unit_price: string }
interface OrderDetail {
  id: string; order_no: string; status: string;
  customer?: { name: string }; salesman?: { name: string };
  total_amount: string; items?: OrderItem[];
}

function OrderDeliveryPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [uploadedUrls, setUploadedUrls] = useState<string[]>([]);

  const { data: order, isLoading } = useQuery<OrderDetail>({
    queryKey: ['order-delivery', orderId],
    queryFn: () => api.get(`/orders/${orderId}`).then(r => r.data),
    enabled: !!orderId,
  });

  const deliveryMut = useMutation({
    mutationFn: (photoUrls: string[]) => api.post(`/orders/${orderId}/upload-delivery`, { photo_urls: photoUrls }),
    onSuccess: () => {
      message.success('送达确认成功！');
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      navigate('/orders');
    },
    onError: (err: any) => message.error(err?.response?.data?.detail ?? '确认送达失败'),
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
      message.warning('请至少上传一张送货照片');
      return;
    }
    deliveryMut.mutate(uploadedUrls);
  };

  if (isLoading || !order) return <div style={{ padding: 24 }}>加载中...</div>;
  if (order.status !== 'shipped') return (
    <div style={{ padding: 24 }}>
      <Alert type="warning" title={`订单状态为 "${order.status}"，只有已出库的订单才能确认送达`} showIcon />
      <Button style={{ marginTop: 16 }} onClick={() => navigate('/orders')}>返回订单列表</Button>
    </div>
  );

  return (
    <div style={{ maxWidth: 600, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/orders')}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>确认送达</Title>
      </Space>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="订单号">{order.order_no}</Descriptions.Item>
          <Descriptions.Item label="客户">{order.customer?.name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="金额">¥{Number(order.total_amount).toLocaleString()}</Descriptions.Item>
          <Descriptions.Item label="商品" span={2}>
            {order.items?.map((it, i) => (
              <Tag key={i}>{it.product?.name ?? '商品'} ×{it.quantity}{it.quantity_unit || '瓶'}</Tag>
            )) ?? '-'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title={<><CameraOutlined /> 上传送货照片</>} size="small" style={{ marginBottom: 16 }}>
        <Upload
          listType="picture-card"
          fileList={fileList}
          customRequest={handleUpload}
          onChange={({ fileList: fl }) => setFileList(fl)}
          accept=".jpg,.jpeg,.png,.webp,.heic"
          multiple
        >
          {fileList.length < 9 && (
            <div><PlusOutlined /><div style={{ marginTop: 4, fontSize: 12 }}>上传照片</div></div>
          )}
        </Upload>
        <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>支持 JPG/PNG/WEBP 格式，最多9张</div>
      </Card>

      <Button
        type="primary"
        size="large"
        block
        icon={<CheckCircleOutlined />}
        disabled={uploadedUrls.length === 0}
        loading={deliveryMut.isPending}
        onClick={handleSubmit}
        style={{ height: 48, fontSize: 16 }}
      >
        确认送达 ({uploadedUrls.length} 张照片)
      </Button>
    </div>
  );
}

export default OrderDeliveryPage;
