import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Col, DatePicker, Form, Input, message, Modal, Row, Select, Space, Table, Tabs, Tag, Typography } from 'antd';
import { CameraOutlined, LoginOutlined, LogoutOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api, { extractItems } from '../../api/client';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

interface Checkin {
  id: string; employee_name: string; checkin_date: string; checkin_type: string;
  checkin_time: string; status: string; late_minutes: number;
  latitude?: number; longitude?: number; photo_url?: string;
}
interface Visit {
  id: string; employee_name: string; customer_name?: string; visit_date: string;
  enter_time?: string; leave_time?: string; duration_minutes?: number; is_valid: boolean;
}
interface Leave {
  id: string; request_no: string; employee_name: string; leave_type: string;
  start_date: string; end_date: string; total_days: number; reason: string; status: string;
}
interface Customer { id: string; name: string }

const LEAVE_LABEL: Record<string, string> = {
  personal: '事假', sick: '病假', annual: '年假', overtime_off: '调休',
};
const LEAVE_COLOR: Record<string, string> = {
  personal: 'orange', sick: 'red', annual: 'blue', overtime_off: 'cyan',
};

// 浏览器 GPS + 摄像头上传
async function getPosition(): Promise<{ lat: number; lng: number }> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) { reject(new Error('浏览器不支持定位')); return; }
    navigator.geolocation.getCurrentPosition(
      p => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      e => reject(new Error(`获取位置失败: ${e.message}`)),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  });
}

async function uploadFile(file: File | Blob): Promise<string> {
  const fd = new FormData();
  // Blob 没 name 属性，multipart 缺 filename 后端会 422。强制补一个带扩展名的。
  const filename = (file as File).name || `camera-${Date.now()}.jpg`;
  fd.append('file', file, filename);
  const { data } = await api.post('/uploads', fd);
  return data.url;
}

// 摄像头拍照组件
function CameraSnap({ onCaptured }: { onCaptured: (url: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [started, setStarted] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!started) return;
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } })
      .then(stream => {
        if (videoRef.current) videoRef.current.srcObject = stream;
      })
      .catch(() => message.error('摄像头访问失败'));
    return () => {
      if (videoRef.current?.srcObject) {
        (videoRef.current.srcObject as MediaStream).getTracks().forEach(t => t.stop());
      }
    };
  }, [started]);

  const snap = async () => {
    if (!videoRef.current) return;
    setLoading(true);
    try {
      const canvas = document.createElement('canvas');
      canvas.width = videoRef.current.videoWidth;
      canvas.height = videoRef.current.videoHeight;
      canvas.getContext('2d')!.drawImage(videoRef.current, 0, 0);
      const blob = await new Promise<Blob | null>(r => canvas.toBlob(r, 'image/jpeg', 0.85));
      if (!blob) throw new Error('拍照失败');
      const url = await uploadFile(blob);
      onCaptured(url);
      message.success('照片已上传');
    } catch (e: any) {
      message.error(e.message);
    } finally { setLoading(false); }
  };

  if (!started) return <Button icon={<CameraOutlined />} onClick={() => setStarted(true)}>启动摄像头</Button>;
  return (
    <Space orientation="vertical" style={{ width: '100%' }}>
      <video ref={videoRef} autoPlay playsInline style={{ width: '100%', maxHeight: 300, background: '#000' }} />
      <Button type="primary" block icon={<CameraOutlined />} loading={loading} onClick={snap}>拍照</Button>
    </Space>
  );
}

function WorkCheckinPanel() {
  const qc = useQueryClient();
  const [photo, setPhoto] = useState<string>('');
  const [modalType, setModalType] = useState<'work_in' | 'work_out' | null>(null);

  const { data: today = [] } = useQuery<Checkin[]>({
    queryKey: ['today-checkin'],
    queryFn: () => api.get('/attendance/checkin', {
      params: { start_date: dayjs().format('YYYY-MM-DD'), end_date: dayjs().format('YYYY-MM-DD') },
    }).then(r => extractItems<Checkin>(r.data)),
    refetchInterval: 60000,
  });

  const checkinMut = useMutation({
    mutationFn: async (t: 'work_in' | 'work_out') => {
      const pos = await getPosition();
      return api.post('/attendance/checkin', {
        checkin_type: t, latitude: pos.lat, longitude: pos.lng, photo_url: photo,
      });
    },
    onSuccess: () => {
      message.success('打卡成功');
      setModalType(null); setPhoto('');
      qc.invalidateQueries({ queryKey: ['today-checkin'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? e.message ?? '打卡失败'),
  });

  const myTodayIn = today.find(c => c.checkin_type === 'work_in');
  const myTodayOut = today.find(c => c.checkin_type === 'work_out');

  return (
    <>
      <Row gutter={16}>
        <Col span={12}>
          <Card>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <Title level={5}><LoginOutlined /> 上班打卡</Title>
              {myTodayIn ? (
                <Alert type={myTodayIn.status === 'normal' ? 'success' : 'warning'}
                  title={`已打卡 · ${new Date(myTodayIn.checkin_time).toLocaleTimeString('zh-CN')}`}
                  description={myTodayIn.status === 'late' ? `迟到 ${myTodayIn.late_minutes} 分钟`
                    : myTodayIn.status === 'late_over30' ? `迟到超30分钟（算旷工半天）` : '准时'} />
              ) : (
                <Button type="primary" size="large" block icon={<LoginOutlined />}
                  onClick={() => setModalType('work_in')}>上班打卡</Button>
              )}
            </Space>
          </Card>
        </Col>
        <Col span={12}>
          <Card>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <Title level={5}><LogoutOutlined /> 下班打卡</Title>
              {myTodayOut ? (
                <Alert type="success" title={`已打卡 · ${new Date(myTodayOut.checkin_time).toLocaleTimeString('zh-CN')}`} />
              ) : (
                <Button size="large" block icon={<LogoutOutlined />}
                  disabled={!myTodayIn}
                  onClick={() => setModalType('work_out')}>下班打卡</Button>
              )}
            </Space>
          </Card>
        </Col>
      </Row>

      <Modal title={modalType === 'work_in' ? '上班打卡' : '下班打卡'} open={!!modalType}
        onOk={() => checkinMut.mutate(modalType!)}
        okButtonProps={{ disabled: !photo }}
        onCancel={() => { setModalType(null); setPhoto(''); }}
        confirmLoading={checkinMut.isPending} destroyOnHidden okText="确认打卡">
        <Text type="secondary">系统将读取 GPS 定位并要求自拍。</Text>
        {photo ? (
          <div>
            <img src={photo} alt="" style={{ width: '100%', maxHeight: 300, marginTop: 8 }} />
            <Button style={{ marginTop: 8 }} onClick={() => setPhoto('')}>重新拍照</Button>
          </div>
        ) : (
          <CameraSnap onCaptured={setPhoto} />
        )}
      </Modal>
    </>
  );
}

function VisitPanel() {
  const qc = useQueryClient();
  const [enterOpen, setEnterOpen] = useState(false);
  const [leaveVisit, setLeaveVisit] = useState<Visit | null>(null);
  const [photo, setPhoto] = useState('');
  const [form] = Form.useForm();

  const { data: customers = [] } = useQuery<Customer[]>({
    queryKey: ['customers-select'],
    queryFn: () => api.get('/customers').then(r => extractItems<Customer>(r.data)),
  });

  const { data: myVisits = [] } = useQuery<Visit[]>({
    queryKey: ['my-visits-today'],
    queryFn: () => api.get('/attendance/visits', {
      params: { start_date: dayjs().format('YYYY-MM-DD'), end_date: dayjs().format('YYYY-MM-DD') },
    }).then(r => extractItems<Visit>(r.data)),
    refetchInterval: 60000,
  });

  const enterMut = useMutation({
    mutationFn: async (v: any) => {
      const pos = await getPosition();
      return api.post('/attendance/visits/enter', {
        customer_id: v.customer_id || null,
        customer_name: v.customer_name || null,
        latitude: pos.lat, longitude: pos.lng, photo_url: photo,
      });
    },
    onSuccess: () => {
      message.success('进店打卡成功');
      setEnterOpen(false); setPhoto(''); form.resetFields();
      qc.invalidateQueries({ queryKey: ['my-visits-today'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? e.message ?? '打卡失败'),
  });

  const leaveMut = useMutation({
    mutationFn: async () => {
      const pos = await getPosition();
      return api.post('/attendance/visits/leave', {
        visit_id: leaveVisit!.id, latitude: pos.lat, longitude: pos.lng, photo_url: photo,
      });
    },
    onSuccess: (r: any) => {
      const v = r.data;
      message.success(v.is_valid
        ? `出店打卡成功，有效拜访 (${v.duration_minutes} 分钟)`
        : `出店打卡成功，但时长 ${v.duration_minutes} 分钟 不足30分钟，不计入有效拜访`);
      setLeaveVisit(null); setPhoto('');
      qc.invalidateQueries({ queryKey: ['my-visits-today'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? e.message ?? '打卡失败'),
  });

  const validCount = myVisits.filter(v => v.is_valid).length;
  const ongoing = myVisits.find(v => v.enter_time && !v.leave_time);

  return (
    <>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Text type="secondary">今日有效拜访</Text>
          <Text strong style={{ fontSize: 18, color: validCount >= 6 ? '#52c41a' : '#fa8c16' }}>{validCount}/6</Text>
          {ongoing && <Tag color="orange">正在拜访中: {ongoing.customer_name}</Tag>}
        </Space>
      </Card>

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col>
          <Button type="primary" size="large" icon={<LoginOutlined />} onClick={() => setEnterOpen(true)}
            disabled={!!ongoing}>进店打卡</Button>
        </Col>
        {ongoing && (
          <Col>
            <Button size="large" icon={<LogoutOutlined />} onClick={() => setLeaveVisit(ongoing)}>
              出店打卡 - {ongoing.customer_name}
            </Button>
          </Col>
        )}
      </Row>

      <Table<Visit> dataSource={myVisits} rowKey="id" size="small" pagination={false}
        columns={[
          { title: '客户', dataIndex: 'customer_name', width: 180 },
          { title: '进店', dataIndex: 'enter_time', width: 140,
            render: (v?: string) => v ? new Date(v).toLocaleTimeString('zh-CN') : '-' },
          { title: '出店', dataIndex: 'leave_time', width: 140,
            render: (v?: string) => v ? new Date(v).toLocaleTimeString('zh-CN') : <Tag color="orange">进行中</Tag> },
          { title: '时长', dataIndex: 'duration_minutes', width: 100,
            render: (v?: number) => v != null ? `${v} 分钟` : '-' },
          { title: '是否有效', dataIndex: 'is_valid', width: 100,
            render: (v: boolean) => v ? <Tag color="green">有效</Tag> : <Tag>时长不足</Tag> },
        ]} />

      <Modal title="进店打卡" open={enterOpen} onOk={() => form.validateFields().then(v => enterMut.mutate(v))}
        okButtonProps={{ disabled: !photo }}
        onCancel={() => { setEnterOpen(false); setPhoto(''); form.resetFields(); }}
        confirmLoading={enterMut.isPending} destroyOnHidden>
        <Form form={form} layout="vertical">
          <Form.Item name="customer_id" label="客户">
            <Select showSearch optionFilterProp="label" allowClear placeholder="选择已有客户"
              options={customers.map(c => ({ value: c.id, label: c.name }))} />
          </Form.Item>
          <Form.Item name="customer_name" label="客户名（未录入的手填）">
            <Input placeholder="如未选择，请手填" />
          </Form.Item>
        </Form>
        <Text type="secondary">拍照：人脸 + 店面（出店需再拍一次）</Text>
        {photo ? (
          <div>
            <img src={photo} alt="" style={{ width: '100%', maxHeight: 300, marginTop: 8 }} />
            <Button style={{ marginTop: 8 }} onClick={() => setPhoto('')}>重新拍照</Button>
          </div>
        ) : (
          <CameraSnap onCaptured={setPhoto} />
        )}
      </Modal>

      <Modal title="出店打卡" open={!!leaveVisit} onOk={() => leaveMut.mutate()}
        okButtonProps={{ disabled: !photo }}
        onCancel={() => { setLeaveVisit(null); setPhoto(''); }}
        confirmLoading={leaveMut.isPending} destroyOnHidden>
        <Alert type="info" title={`出店 - ${leaveVisit?.customer_name}（进店 ${leaveVisit?.enter_time ? new Date(leaveVisit.enter_time).toLocaleTimeString('zh-CN') : ''}）`} style={{ marginBottom: 12 }} />
        <Text type="secondary">再拍一次（需满 30 分钟才算有效）</Text>
        {photo ? (
          <div>
            <img src={photo} alt="" style={{ width: '100%', maxHeight: 300, marginTop: 8 }} />
            <Button style={{ marginTop: 8 }} onClick={() => setPhoto('')}>重新拍照</Button>
          </div>
        ) : (
          <CameraSnap onCaptured={setPhoto} />
        )}
      </Modal>
    </>
  );
}

function LeavePanel() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const { data: leaves = [] } = useQuery<Leave[]>({
    queryKey: ['my-leaves'],
    queryFn: () => api.get('/attendance/leave-requests').then(r => extractItems<Leave>(r.data)),
  });

  const createMut = useMutation({
    mutationFn: (v: any) => api.post('/attendance/leave-requests', {
      leave_type: v.leave_type,
      start_date: v.range[0].format('YYYY-MM-DD'),
      end_date: v.range[1].format('YYYY-MM-DD'),
      half_day_start: v.half_day_start || false,
      half_day_end: v.half_day_end || false,
      reason: v.reason,
    }),
    onSuccess: () => {
      message.success('已提交，等待审批');
      setOpen(false); form.resetFields();
      qc.invalidateQueries({ queryKey: ['my-leaves'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '提交失败'),
  });

  const columns: ColumnsType<Leave> = [
    { title: '单号', dataIndex: 'request_no', width: 160 },
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    { title: '类型', dataIndex: 'leave_type', width: 80,
      render: (v: string) => <Tag color={LEAVE_COLOR[v] ?? 'default'}>{LEAVE_LABEL[v] ?? v}</Tag> },
    { title: '起止', key: 'range', width: 200,
      render: (_, r) => `${r.start_date} ~ ${r.end_date}` },
    { title: '天数', dataIndex: 'total_days', width: 70 },
    { title: '原因', dataIndex: 'reason', ellipsis: true },
    { title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => v === 'approved' ? <Tag color="green">已批</Tag>
        : v === 'rejected' ? <Tag color="red">已驳回</Tag> : <Tag color="orange">待审批</Tag> },
    { title: '操作', key: 'op', width: 120,
      render: (_, r) => r.status === 'pending' ? (
        <Tag color="orange">审批中心处理</Tag>
      ) : null },
  ];

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <Button type="primary" onClick={() => setOpen(true)}>申请请假</Button>
      </div>
      <Table<Leave> columns={columns} dataSource={leaves} rowKey="id" size="small" pagination={{ pageSize: 30 }} />

      <Modal title="申请请假/调休" open={open}
        onOk={() => form.validateFields().then(v => createMut.mutate(v))}
        onCancel={() => { setOpen(false); form.resetFields(); }}
        confirmLoading={createMut.isPending} destroyOnHidden>
        <Form form={form} layout="vertical">
          <Form.Item name="leave_type" label="类型" rules={[{ required: true }]}>
            <Select options={[
              { value: 'personal', label: '事假' }, { value: 'sick', label: '病假' },
              { value: 'annual', label: '年假' }, { value: 'overtime_off', label: '调休' },
            ]} />
          </Form.Item>
          <Form.Item name="range" label="起止日期" rules={[{ required: true }]}>
            <RangePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="reason" label="原因" rules={[{ required: true }]}>
            <Input.TextArea rows={3} placeholder="请假原因" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function AttendancePage() {
  return (
    <>
      <Title level={4}>考勤管理</Title>
      <Tabs defaultActiveKey="checkin" items={[
        { key: 'checkin', label: '上下班打卡', children: <WorkCheckinPanel /> },
        { key: 'visits', label: '客户拜访', children: <VisitPanel /> },
        { key: 'leave', label: '请假/调休', children: <LeavePanel /> },
      ]} />
    </>
  );
}

export default AttendancePage;
