import { useState } from 'react';
import { Badge, Button, Empty, Popover, Spin, Typography } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import api, { extractItems } from '../api/client';

const { Text } = Typography;

interface NotificationItem {
  id: string;
  title: string;
  content: string;
  status: string;
  related_entity_type?: string;
  related_entity_id?: string;
  created_at?: string;
}

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const { data: unreadCount = 0 } = useQuery<number>({
    queryKey: ['notifications-unread-count'],
    queryFn: () => api.get('/notifications/unread-count').then(r => r.data.count),
    refetchInterval: 10_000,
  });

  const { data: notifications = [], isLoading } = useQuery<NotificationItem[]>({
    queryKey: ['notifications-recent'],
    queryFn: () => api.get('/notifications', { params: { limit: 20 } }).then(r => extractItems<NotificationItem>(r.data)),
    refetchInterval: 15_000,
    enabled: open,
  });

  const markReadMut = useMutation({
    mutationFn: (id: string) => api.post(`/notifications/${id}/mark-read`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-recent'] });
    },
  });

  const markAllReadMut = useMutation({
    mutationFn: () => api.post('/notifications/mark-all-read'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-recent'] });
    },
  });

  const handleClick = (item: NotificationItem) => {
    if (item.status === 'unread') markReadMut.mutate(item.id);
    setOpen(false);
    // 按实体类型跳对应页
    switch (item.related_entity_type) {
      case 'Order': navigate('/orders'); break;
      case 'SalesTarget': navigate('/sales/targets'); break;
      case 'SalaryRecord': navigate('/me'); break;
      case 'PolicyRequest': navigate('/policies/requests'); break;
      case 'PurchaseOrder': navigate('/purchase/orders'); break;
      case 'InspectionCase': navigate('/inspections/cases'); break;
      case 'LeaveRequest': navigate('/attendance'); break;
      case 'Account': navigate('/finance/accounts'); break;
      case 'ExpenseClaim': navigate('/approval/finance'); break;
      default: break;
    }
  };

  const content = (
    <div style={{ width: 340, maxHeight: 420, overflow: 'auto' }}>
      {unreadCount > 0 && (
        <div style={{ textAlign: 'right', padding: '0 4px 8px' }}>
          <Button type="link" size="small" onClick={() => markAllReadMut.mutate()}>全部标为已读</Button>
        </div>
      )}
      {isLoading ? <Spin size="small" style={{ display: 'block', textAlign: 'center', padding: 16 }} /> :
       notifications.length === 0 ? (
        <Empty description="暂无通知" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        notifications.map((item) => (
          <div
            key={item.id}
            style={{
              cursor: 'pointer',
              background: item.status === 'unread' ? '#f0f5ff' : undefined,
              padding: '8px 12px',
              borderBottom: '1px solid #f5f5f5',
            }}
            onClick={() => handleClick(item)}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Text strong={item.status === 'unread'} style={{ fontSize: 13 }}>{item.title}</Text>
              {item.status === 'unread' && <Badge status="processing" />}
            </div>
            <div style={{ color: '#888', fontSize: 12, marginTop: 2 }}>{item.content}</div>
            {item.created_at && (
              <div style={{ color: '#aaa', fontSize: 11, marginTop: 2 }}>
                {new Date(item.created_at).toLocaleString('zh-CN')}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );

  return (
    <Popover
      content={content}
      title="通知"
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
    >
      <Badge count={unreadCount} size="small" offset={[-2, 2]}>
        <BellOutlined style={{ fontSize: 18, cursor: 'pointer', padding: '4px 8px' }} />
      </Badge>
    </Popover>
  );
}

export default NotificationBell;
