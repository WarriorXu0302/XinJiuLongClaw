import { Badge, Button, Card, Empty, Space, Tag, Typography } from 'antd';
import { ArrowLeftOutlined, BellOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import api from '../../api/client';

const { Title, Text } = Typography;

interface NotificationItem {
  id: string; title: string; content: string;
  status: string; related_entity_type?: string; related_entity_id?: string;
  created_at?: string;
}

function MobileNotifications() {
  const qc = useQueryClient();
  const navigate = useNavigate();

  const { data: list = [], isLoading } = useQuery<NotificationItem[]>({
    queryKey: ['m-noti-list'],
    queryFn: () => api.get('/notifications', { params: { limit: 100 } }).then(r => r.data),
  });

  const markReadMut = useMutation({
    mutationFn: (id: string) => api.post(`/notifications/${id}/mark-read`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['m-noti-list'] });
      qc.invalidateQueries({ queryKey: ['m-unread'] });
    },
  });

  const markAllMut = useMutation({
    mutationFn: () => api.post('/notifications/mark-all-read'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['m-noti-list'] });
      qc.invalidateQueries({ queryKey: ['m-unread'] });
    },
  });

  const unread = list.filter(n => n.status === 'unread').length;

  return (
    <div style={{ maxWidth: 480, margin: '0 auto', padding: 12, background: '#f0f2f5', minHeight: '100vh' }}>
      <Space style={{ marginBottom: 12, justifyContent: 'space-between', width: '100%' }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/m/checkin')}>返回</Button>
        <Title level={4} style={{ margin: 0 }}><BellOutlined /> 通知</Title>
        {unread > 0 ? (
          <Button size="small" type="link" onClick={() => markAllMut.mutate()}>全部已读</Button>
        ) : <span style={{ width: 60 }} />}
      </Space>

      {isLoading ? <Text>加载中...</Text> :
       list.length === 0 ? <Empty description="暂无通知" /> : (
        list.map(n => (
          <Card key={n.id} size="small" style={{ marginBottom: 8,
            background: n.status === 'unread' ? '#f0f5ff' : undefined }}
            onClick={() => {
              if (n.status === 'unread') markReadMut.mutate(n.id);
            }}>
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <Text strong={n.status === 'unread'}>{n.title}</Text>
                {n.status === 'unread' && <Badge status="processing" />}
              </Space>
              <Text style={{ fontSize: 12, color: '#666' }}>{n.content}</Text>
              {n.created_at && (
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {new Date(n.created_at).toLocaleString('zh-CN')}
                </Text>
              )}
            </Space>
          </Card>
        ))
      )}
    </div>
  );
}

export default MobileNotifications;
