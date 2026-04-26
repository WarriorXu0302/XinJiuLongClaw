/**
 * 手机端打卡 H5 —— 业务员外出用
 * 路由 /m/checkin
 * 无侧边栏、全屏响应式、大按钮
 */
import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Form, Input, List, message, Modal, Select, Space, Tag, Typography } from 'antd';
import { BellOutlined, CameraOutlined, EnvironmentOutlined, LoginOutlined, LogoutOutlined, UserOutlined, LogoutOutlined as SignOutIcon } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import api, { extractItems } from '../../api/client';
import { useAuthStore } from '../../stores/authStore';

const { Title, Text } = Typography;

interface Checkin {
  id: string; checkin_date: string; checkin_type: string;
  checkin_time: string; status: string; late_minutes: number;
}
interface Visit {
  id: string; customer_name?: string; visit_date: string;
  enter_time?: string; leave_time?: string;
  duration_minutes?: number; is_valid: boolean;
}
interface Customer { id: string; name: string }

async function getPosition(): Promise<{ lat: number; lng: number }> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error('浏览器不支持定位'));
    navigator.geolocation.getCurrentPosition(
      p => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      e => reject(new Error(`获取位置失败: ${e.message}`)),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  });
}

async function uploadFile(blob: Blob): Promise<string> {
  const fd = new FormData();
  // Blob 没 name 属性，必须显式传 filename 否则 FastAPI UploadFile 422
  fd.append('file', blob, `checkin-${Date.now()}.jpg`);
  const { data } = await api.post('/uploads', fd);
  return data.url;
}

function CameraModal({ open, onCaptured, onCancel }: { open: boolean; onCaptured: (url: string) => void; onCancel: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<string>('');

  useEffect(() => {
    if (!open) { setPreview(''); return; }
    let stream: MediaStream | null = null;
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } })
      .then(s => {
        stream = s;
        if (videoRef.current) videoRef.current.srcObject = s;
      })
      .catch(() => message.error('摄像头访问失败，请检查权限'));
    return () => { stream?.getTracks().forEach(t => t.stop()); };
  }, [open]);

  const snap = async () => {
    if (!videoRef.current) return;
    setLoading(true);
    try {
      const canvas = document.createElement('canvas');
      canvas.width = videoRef.current.videoWidth;
      canvas.height = videoRef.current.videoHeight;
      canvas.getContext('2d')!.drawImage(videoRef.current, 0, 0);
      const blob = await new Promise<Blob | null>(r => canvas.toBlob(r, 'image/jpeg', 0.75));
      if (!blob) throw new Error('拍照失败');
      const url = await uploadFile(blob);
      setPreview(url);
    } catch (e: any) {
      message.error(e.message);
    } finally { setLoading(false); }
  };

  return (
    <Modal open={open} onCancel={onCancel} footer={null} width="95%"
      style={{ top: 20 }} bodyStyle={{ padding: 12 }}>
      {preview ? (
        <Space direction="vertical" style={{ width: '100%' }}>
          <img src={preview} alt="" style={{ width: '100%' }} />
          <Space style={{ width: '100%' }}>
            <Button size="large" block onClick={() => setPreview('')}>重拍</Button>
            <Button size="large" type="primary" block onClick={() => { onCaptured(preview); setPreview(''); }}>使用此图</Button>
          </Space>
        </Space>
      ) : (
        <Space direction="vertical" style={{ width: '100%' }}>
          <video ref={videoRef} autoPlay playsInline style={{ width: '100%', background: '#000', minHeight: 300 }} />
          <Button size="large" type="primary" block icon={<CameraOutlined />} loading={loading} onClick={snap}>拍照</Button>
        </Space>
      )}
    </Modal>
  );
}

function MobileCheckin() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const username = useAuthStore(s => s.username);
  const logout = useAuthStore(s => s.logout);

  const [camOpen, setCamOpen] = useState(false);
  const [afterCapture, setAfterCapture] = useState<((url: string) => void) | null>(null);
  const [enterVisible, setEnterVisible] = useState(false);
  const [leaveVisit, setLeaveVisit] = useState<Visit | null>(null);
  const [enterForm] = Form.useForm();

  const today = dayjs().format('YYYY-MM-DD');

  const { data: checkins = [] } = useQuery<Checkin[]>({
    queryKey: ['m-checkin'],
    queryFn: () => api.get('/attendance/checkin', { params: { start_date: today, end_date: today } }).then(r => extractItems<Checkin>(r.data)),
    refetchInterval: 60000,
  });
  const { data: visits = [] } = useQuery<Visit[]>({
    queryKey: ['m-visits'],
    queryFn: () => api.get('/attendance/visits', { params: { start_date: today, end_date: today } }).then(r => extractItems<Visit>(r.data)),
    refetchInterval: 60000,
  });
  const { data: customers = [] } = useQuery<Customer[]>({
    queryKey: ['customers-m'],
    queryFn: () => api.get('/customers').then(r => extractItems<Customer>(r.data)),
  });

  const { data: unreadCount = 0 } = useQuery<number>({
    queryKey: ['m-unread'],
    queryFn: () => api.get('/notifications/unread-count').then(r => r.data.count),
    refetchInterval: 30000,
  });

  const workIn = checkins.find(c => c.checkin_type === 'work_in');
  const workOut = checkins.find(c => c.checkin_type === 'work_out');
  const ongoing = visits.find(v => v.enter_time && !v.leave_time);
  const validVisits = visits.filter(v => v.is_valid).length;

  const doCheckin = useMutation({
    mutationFn: async (p: { type: 'work_in' | 'work_out'; photo: string }) => {
      const pos = await getPosition();
      return api.post('/attendance/checkin', {
        checkin_type: p.type, latitude: pos.lat, longitude: pos.lng, photo_url: p.photo,
      });
    },
    onSuccess: () => {
      message.success('打卡成功');
      qc.invalidateQueries({ queryKey: ['m-checkin'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? e.message ?? '打卡失败'),
  });

  const doEnter = useMutation({
    mutationFn: async (p: { customer_id?: string; customer_name?: string; photo: string }) => {
      const pos = await getPosition();
      return api.post('/attendance/visits/enter', {
        customer_id: p.customer_id || null,
        customer_name: p.customer_name || null,
        latitude: pos.lat, longitude: pos.lng, photo_url: p.photo,
      });
    },
    onSuccess: () => {
      message.success('进店打卡成功');
      setEnterVisible(false); enterForm.resetFields();
      qc.invalidateQueries({ queryKey: ['m-visits'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? e.message ?? '失败'),
  });

  const doLeave = useMutation({
    mutationFn: async (p: { visit_id: string; photo: string }) => {
      const pos = await getPosition();
      return api.post('/attendance/visits/leave', {
        visit_id: p.visit_id, latitude: pos.lat, longitude: pos.lng, photo_url: p.photo,
      });
    },
    onSuccess: (r: any) => {
      const v = r.data;
      message.success(v.is_valid ? `出店成功，有效拜访 (${v.duration_minutes}分钟)` : `时长 ${v.duration_minutes} 分钟 不足 30 分钟`);
      setLeaveVisit(null);
      qc.invalidateQueries({ queryKey: ['m-visits'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? e.message ?? '失败'),
  });

  const openCamera = (cb: (url: string) => void) => {
    setAfterCapture(() => cb);
    setCamOpen(true);
  };

  return (
    <div style={{ maxWidth: 480, margin: '0 auto', padding: 12, paddingBottom: 60, background: '#f0f2f5', minHeight: '100vh' }}>
      {/* 顶栏 */}
      <Card size="small" bodyStyle={{ padding: '8px 12px' }} style={{ marginBottom: 8 }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space><UserOutlined /><Text strong>{username}</Text></Space>
          <Space>
            <BellOutlined style={{ fontSize: 16 }} onClick={() => navigate('/m/notifications')} />
            {unreadCount > 0 && <Tag color="red" style={{ marginRight: 0 }}>{unreadCount}</Tag>}
            <SignOutIcon style={{ fontSize: 16, color: '#ff4d4f' }} onClick={() => { logout(); navigate('/login'); }} />
          </Space>
        </Space>
      </Card>

      <Title level={4} style={{ textAlign: 'center', margin: '12px 0' }}>
        {dayjs().format('YYYY年MM月DD日 dddd')}
      </Title>

      {/* 上下班打卡 */}
      <Card title="上下班打卡" size="small" style={{ marginBottom: 12 }}>
        {workIn ? (
          <Alert
            type={workIn.status === 'normal' ? 'success' : 'warning'}
            title={`上班 ${new Date(workIn.checkin_time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`}
            description={workIn.status === 'late' ? `迟到 ${workIn.late_minutes} 分钟`
              : workIn.status === 'late_over30' ? '迟到 >30 分钟，算旷工半天' : '准时'}
            style={{ marginBottom: 8 }}
          />
        ) : (
          <Button type="primary" size="large" block icon={<LoginOutlined />} style={{ height: 60, fontSize: 18 }}
            onClick={() => openCamera(photo => doCheckin.mutate({ type: 'work_in', photo }))}>
            上班打卡
          </Button>
        )}
        {workIn && (workOut ? (
          <Alert type="success" title={`下班 ${new Date(workOut.checkin_time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`} />
        ) : (
          <Button size="large" block icon={<LogoutOutlined />} style={{ height: 60, fontSize: 18 }}
            onClick={() => openCamera(photo => doCheckin.mutate({ type: 'work_out', photo }))}>
            下班打卡
          </Button>
        ))}
      </Card>

      {/* 客户拜访 */}
      <Card title={<Space>客户拜访 <Tag color={validVisits >= 6 ? 'green' : 'orange'}>有效 {validVisits}/6</Tag></Space>} size="small" style={{ marginBottom: 12 }}>
        {ongoing ? (
          <Alert
            type="warning"
            title={`正在拜访: ${ongoing.customer_name || '-'}`}
            description={ongoing.enter_time ? `进店于 ${new Date(ongoing.enter_time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}` : ''}
            style={{ marginBottom: 8 }}
          />
        ) : null}
        <Space direction="vertical" style={{ width: '100%' }}>
          {!ongoing && (
            <Button type="primary" size="large" block icon={<LoginOutlined />}
              style={{ height: 56, fontSize: 16 }}
              onClick={() => setEnterVisible(true)}>进店打卡</Button>
          )}
          {ongoing && (
            <Button size="large" type="primary" danger block icon={<LogoutOutlined />}
              style={{ height: 56, fontSize: 16 }}
              onClick={() => setLeaveVisit(ongoing)}>出店打卡</Button>
          )}
        </Space>
      </Card>

      {/* 今日拜访列表 */}
      {visits.length > 0 && (
        <Card title="今日拜访" size="small">
          <List
            size="small" dataSource={visits}
            renderItem={v => (
              <List.Item>
                <List.Item.Meta
                  title={<Space>
                    <Text strong>{v.customer_name}</Text>
                    {v.is_valid ? <Tag color="green">有效</Tag> :
                     v.leave_time ? <Tag>时长不足</Tag> :
                     <Tag color="orange">进行中</Tag>}
                  </Space>}
                  description={
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {v.enter_time && `进 ${new Date(v.enter_time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`}
                      {v.leave_time && ` · 出 ${new Date(v.leave_time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`}
                      {v.duration_minutes != null && ` · ${v.duration_minutes}分钟`}
                    </Text>
                  }
                />
              </List.Item>
            )}
          />
        </Card>
      )}

      {/* 进店弹窗 */}
      <Modal title="进店打卡" open={enterVisible}
        onCancel={() => { setEnterVisible(false); enterForm.resetFields(); }}
        footer={null} width="95%" style={{ top: 20 }} destroyOnHidden>
        <Form form={enterForm} layout="vertical">
          <Form.Item name="customer_id" label="客户">
            <Select showSearch optionFilterProp="label" allowClear placeholder="选择客户（已录入）"
              options={customers.map(c => ({ value: c.id, label: c.name }))} />
          </Form.Item>
          <Form.Item name="customer_name" label="或手输客户名">
            <Input placeholder="未录入客户可手填" />
          </Form.Item>
          <Button type="primary" size="large" block icon={<CameraOutlined />} loading={doEnter.isPending}
            onClick={() => {
              enterForm.validateFields().then(v => {
                if (!v.customer_id && !v.customer_name) { message.warning('请选择或填写客户'); return; }
                openCamera(photo => doEnter.mutate({ customer_id: v.customer_id, customer_name: v.customer_name, photo }));
              });
            }}>拍照打卡</Button>
        </Form>
      </Modal>

      {/* 出店弹窗 */}
      <Modal title={`出店打卡 - ${leaveVisit?.customer_name}`} open={!!leaveVisit}
        onCancel={() => setLeaveVisit(null)} footer={null} width="95%" style={{ top: 20 }} destroyOnHidden>
        <Alert type="info" style={{ marginBottom: 12 }}
          title={`进店 ${leaveVisit?.enter_time ? new Date(leaveVisit.enter_time).toLocaleTimeString('zh-CN') : ''}`}
          description="需满 30 分钟才算有效拜访" />
        <Button type="primary" size="large" block icon={<CameraOutlined />} loading={doLeave.isPending}
          onClick={() => openCamera(photo => doLeave.mutate({ visit_id: leaveVisit!.id, photo }))}>拍照打卡</Button>
      </Modal>

      <CameraModal open={camOpen} onCancel={() => setCamOpen(false)}
        onCaptured={(url) => { setCamOpen(false); afterCapture?.(url); }} />
    </div>
  );
}

export default MobileCheckin;
