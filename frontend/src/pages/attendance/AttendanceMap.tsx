import { useMemo, useState } from 'react';
import { Card, Col, DatePicker, Row, Select, Space, Table, Tag, Typography } from 'antd';
import { EnvironmentOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs, { type Dayjs } from 'dayjs';
import { MapContainer, TileLayer, Popup, CircleMarker } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import api, { extractItems } from '../../api/client';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

// 修复 Leaflet 默认图标在打包环境下丢失的问题
delete (L.Icon.Default.prototype as any)._getRetinaUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

interface Visit {
  id: string;
  employee_id: string;
  employee_name: string;
  customer_name?: string;
  visit_date: string;
  enter_time?: string;
  leave_time?: string;
  enter_latitude?: number;
  enter_longitude?: number;
  leave_latitude?: number;
  leave_longitude?: number;
  duration_minutes?: number;
  is_valid: boolean;
}

interface Checkin {
  id: string;
  employee_id: string;
  employee_name: string;
  checkin_date: string;
  checkin_type: string;
  checkin_time: string;
  latitude?: number;
  longitude?: number;
  status: string;
}

interface Employee { id: string; name: string }

// 假设一个中国中部默认中心点（后面根据数据自动定位）
const DEFAULT_CENTER: [number, number] = [34.7472, 113.6253]; // 郑州

function AttendanceMap() {
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().startOf('day'), dayjs().endOf('day')]);
  const [empFilter, setEmpFilter] = useState<string | undefined>();

  const { data: employees = [] } = useQuery<Employee[]>({
    queryKey: ['employees-all'],
    queryFn: () => api.get('/hr/employees').then(r => extractItems(r.data)),
  });

  const sd = range[0].format('YYYY-MM-DD');
  const ed = range[1].format('YYYY-MM-DD');

  const { data: visits = [] } = useQuery<Visit[]>({
    queryKey: ['visits-map', sd, ed, empFilter],
    queryFn: () => api.get('/attendance/visits', {
      params: { start_date: sd, end_date: ed, ...(empFilter ? { employee_id: empFilter } : {}) },
    }).then(r => extractItems(r.data)),
  });

  const { data: checkins = [] } = useQuery<Checkin[]>({
    queryKey: ['checkins-map', sd, ed, empFilter],
    queryFn: () => api.get('/attendance/checkin', {
      params: { start_date: sd, end_date: ed, ...(empFilter ? { employee_id: empFilter } : {}) },
    }).then(r => extractItems(r.data)),
  });

  // 详细拜访需要 enter/leave 的 GPS。API 返回结构没直接给 GPS，
  // 我们从 stats 中展示；地图上仅画有 GPS 的上下班打卡
  const markers = useMemo(() => {
    const list: Array<{
      lat: number; lng: number;
      kind: 'checkin' | 'visit';
      label: string;
      sub: string;
      color: string;
    }> = [];
    checkins.forEach(c => {
      if (c.latitude && c.longitude) {
        list.push({
          lat: c.latitude, lng: c.longitude,
          kind: 'checkin',
          label: `${c.employee_name} · ${c.checkin_type === 'work_in' ? '上班' : '下班'}`,
          sub: `${new Date(c.checkin_time).toLocaleString('zh-CN')} · 状态 ${c.status}`,
          color: c.checkin_type === 'work_in' ? '#1890ff' : '#52c41a',
        });
      }
    });
    visits.forEach(v => {
      if (v.enter_latitude && v.enter_longitude) {
        list.push({
          lat: v.enter_latitude, lng: v.enter_longitude,
          kind: 'visit',
          label: `${v.employee_name} · 进店 ${v.customer_name || ''}`,
          sub: `${v.enter_time ? new Date(v.enter_time).toLocaleString('zh-CN') : ''}${v.is_valid ? ' · 有效' : ''}`,
          color: v.is_valid ? '#52c41a' : '#fa8c16',
        });
      }
      if (v.leave_latitude && v.leave_longitude) {
        list.push({
          lat: v.leave_latitude, lng: v.leave_longitude,
          kind: 'visit',
          label: `${v.employee_name} · 出店 ${v.customer_name || ''}`,
          sub: `${v.leave_time ? new Date(v.leave_time).toLocaleString('zh-CN') : ''} · ${v.duration_minutes || 0}分钟`,
          color: v.is_valid ? '#52c41a' : '#fa8c16',
        });
      }
    });
    return list;
  }, [checkins, visits]);

  // 计算地图默认中心（取第一个有 GPS 的点）
  const center: [number, number] = markers.length > 0
    ? [markers[0].lat, markers[0].lng]
    : DEFAULT_CENTER;

  // 拜访统计
  const employeeStats = useMemo(() => {
    const map: Record<string, { name: string; visits: number; valid: number; checkins: number }> = {};
    visits.forEach(v => {
      if (!map[v.employee_id]) map[v.employee_id] = { name: v.employee_name, visits: 0, valid: 0, checkins: 0 };
      map[v.employee_id].visits++;
      if (v.is_valid) map[v.employee_id].valid++;
    });
    checkins.forEach(c => {
      if (!map[c.employee_id]) map[c.employee_id] = { name: c.employee_name, visits: 0, valid: 0, checkins: 0 };
      map[c.employee_id].checkins++;
    });
    return Object.entries(map).map(([id, v]) => ({ employee_id: id, ...v }));
  }, [visits, checkins]);

  const statsColumns: ColumnsType<typeof employeeStats[0]> = [
    { title: '员工', dataIndex: 'name', width: 120 },
    { title: '打卡次数', dataIndex: 'checkins', width: 100, align: 'right' as const,
      render: (v: number) => <Tag>{v} 次</Tag> },
    { title: '拜访总数', dataIndex: 'visits', width: 100, align: 'right' as const,
      render: (v: number) => <Tag color="blue">{v} 次</Tag> },
    { title: '有效拜访', dataIndex: 'valid', width: 110, align: 'right' as const,
      render: (v: number) => <Tag color={v >= 6 ? 'green' : 'orange'}>{v} 次</Tag> },
  ];

  const visitColumns: ColumnsType<Visit> = [
    { title: '日期', dataIndex: 'visit_date', width: 100 },
    { title: '员工', dataIndex: 'employee_name', width: 90 },
    { title: '客户', dataIndex: 'customer_name', width: 160, render: (v: string) => v || '-' },
    { title: '进店', dataIndex: 'enter_time', width: 140,
      render: (v?: string) => v ? new Date(v).toLocaleTimeString('zh-CN') : '-' },
    { title: '出店', dataIndex: 'leave_time', width: 140,
      render: (v?: string) => v ? new Date(v).toLocaleTimeString('zh-CN') : <Tag color="orange">进行中</Tag> },
    { title: '时长', dataIndex: 'duration_minutes', width: 80,
      render: (v?: number) => v != null ? `${v} 分钟` : '-' },
    { title: '有效', dataIndex: 'is_valid', width: 80,
      render: (v: boolean) => v ? <Tag color="green">有效</Tag> : <Tag color="default">不足</Tag> },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}><EnvironmentOutlined /> 考勤地图</Title>
        <Space>
          <RangePicker value={range} onChange={(v) => v && setRange(v as any)} allowClear={false} />
          <Select placeholder="全部员工" allowClear style={{ width: 140 }} value={empFilter}
            onChange={setEmpFilter}
            options={employees.map(e => ({ value: e.id, label: e.name }))} />
        </Space>
      </div>

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small"><Text type="secondary">地图标记</Text>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{markers.length} 个定位点</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">拜访记录</Text>
          <div style={{ fontSize: 18, fontWeight: 600, color: '#1890ff' }}>{visits.length} 条</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">有效拜访</Text>
          <div style={{ fontSize: 18, fontWeight: 600, color: '#52c41a' }}>{visits.filter(v => v.is_valid).length} 条</div></Card></Col>
        <Col span={6}><Card size="small"><Text type="secondary">涉及员工</Text>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{employeeStats.length} 人</div></Card></Col>
      </Row>

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={16}>
          <Card size="small" title="定位点分布" styles={{ body: { padding: 0 } }}>
            <MapContainer center={center} zoom={markers.length > 0 ? 13 : 5}
              style={{ height: 500, borderRadius: 4 }}>
              <TileLayer
                attribution='&copy; OpenStreetMap'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
              {markers.map((m, i) => (
                <CircleMarker key={i}
                  center={[m.lat, m.lng]}
                  radius={8}
                  pathOptions={{ color: m.color, fillOpacity: 0.7 }}>
                  <Popup>
                    <b>{m.label}</b><br />
                    <small>{m.sub}</small>
                  </Popup>
                </CircleMarker>
              ))}
            </MapContainer>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title="员工出勤统计">
            <Table<typeof employeeStats[0]>
              columns={statsColumns} dataSource={employeeStats} rowKey="employee_id"
              size="small" pagination={false} />
          </Card>
        </Col>
      </Row>

      <Card size="small" title="拜访明细">
        <Table<Visit> columns={visitColumns} dataSource={visits} rowKey="id"
          size="small" pagination={{ pageSize: 20 }} />
      </Card>
    </>
  );
}

export default AttendanceMap;
