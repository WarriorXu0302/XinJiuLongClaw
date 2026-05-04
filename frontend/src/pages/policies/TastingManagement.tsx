import { useState } from 'react';
import { Alert, Button, Card, Col, Divider, Form, Input, InputNumber, message, Modal, Row, Select, Space, Table, Tag, Typography } from 'antd';
import { CheckCircleOutlined, WarningOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api, { extractItems } from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

const { Title, Text } = Typography;

interface Destruction { id: string; record_no: string; brand_id: string; destroyed_count: number; destruction_date: string; period: string; manufacturer_witness?: string; notes?: string; created_at: string; }
interface Reconciliation { brand_id: string; brand_name: string; period: string; tasting_outbound_count: number; destroyed_count: number; difference: number; is_matched: boolean; }

function TastingManagement() {
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const { brandId } = useBrandFilter();

  const { data: destructions = [] } = useQuery<Destruction[]>({
    queryKey: ['bottle-destructions', period, brandId],
    queryFn: () => {
      const p: Record<string, string> = { period };
      if (brandId) p.brand_id = brandId;
      return api.get('/bottle-destructions', { params: p }).then(r => extractItems(r.data));
    },
  });

  const { data: reconciliation = [] } = useQuery<Reconciliation[]>({
    queryKey: ['bottle-reconciliation', period, brandId],
    queryFn: () => {
      const p: Record<string, string> = { period };
      if (brandId) p.brand_id = brandId;
      return api.get('/bottle-reconciliation', { params: p }).then(r => extractItems(r.data));
    },
  });

  const { data: brands = [] } = useQuery<any[]>({
    queryKey: ['brands-select'],
    queryFn: () => api.get('/brands').then(r => extractItems(r.data)),
  });

  const createMutation = useMutation({
    mutationFn: (v: any) => api.post('/bottle-destructions', v),
    onSuccess: () => { message.success('销瓶记录已创建'); setModalOpen(false); form.resetFields(); queryClient.invalidateQueries({ queryKey: ['bottle-destructions'] }); queryClient.invalidateQueries({ queryKey: ['bottle-reconciliation'] }); },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  const destCols: ColumnsType<Destruction> = [
    { title: '记录号', dataIndex: 'record_no', width: 170 },
    { title: '销毁数量', dataIndex: 'destroyed_count', width: 100, align: 'right', render: (v: number) => <Text strong>{v} 瓶</Text> },
    { title: '销毁日期', dataIndex: 'destruction_date', width: 110 },
    { title: '周期', dataIndex: 'period', width: 90 },
    { title: '厂家见证人', dataIndex: 'manufacturer_witness', width: 120 },
    { title: '备注', dataIndex: 'notes', width: 200, ellipsis: true },
    { title: '创建时间', dataIndex: 'created_at', width: 150, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
  ];

  return (
    <>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Title level={4} style={{ margin: 0 }}>品鉴酒管理 — 销瓶对账</Title>
        <Space>
          <span>周期：</span>
          <Input style={{ width: 120 }} value={period} onChange={e => setPeriod(e.target.value)} placeholder="2026-04" />
          <Button type="primary" onClick={() => setModalOpen(true)}>录入销瓶记录</Button>
        </Space>
      </Space>

      {/* 对账卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        {reconciliation.map(r => (
          <Col span={8} key={r.brand_id}>
            <Card size="small" title={<Tag color="blue">{r.brand_name}</Tag>}
              style={{ borderColor: r.is_matched ? '#52c41a' : '#ff4d4f' }}>
              <Row gutter={16}>
                <Col span={8}>
                  <div><div style={{ color: '#888', fontSize: 12 }}>品鉴酒出库</div><div style={{ fontSize: 18, fontWeight: 600 }}>{r.tasting_outbound_count} 瓶</div></div>
                </Col>
                <Col span={8}>
                  <div><div style={{ color: '#888', fontSize: 12 }}>空瓶销毁</div><div style={{ fontSize: 18, fontWeight: 600 }}>{r.destroyed_count} 瓶</div></div>
                </Col>
                <Col span={8}>
                  {r.is_matched ? (
                    <div style={{ textAlign: 'center', color: '#52c41a', marginTop: 12 }}>
                      <CheckCircleOutlined style={{ fontSize: 24 }} /><br />
                      <Text type="success">已匹配</Text>
                    </div>
                  ) : (
                    <div style={{ textAlign: 'center', color: '#ff4d4f', marginTop: 12 }}>
                      <WarningOutlined style={{ fontSize: 24 }} /><br />
                      <Text type="danger">差异 {r.difference} 瓶</Text>
                    </div>
                  )}
                </Col>
              </Row>
            </Card>
          </Col>
        ))}
      </Row>

      {reconciliation.some(r => !r.is_matched) && (
        <Alert type="error" showIcon title="销瓶对账异常：出库数量与销毁数量不一致，请核实！" style={{ marginBottom: 16 }} />
      )}

      {/* 销瓶记录明细 */}
      <Divider>销瓶记录</Divider>
      <Table<Destruction> columns={destCols} dataSource={destructions} rowKey="id" size="small" pagination={{ pageSize: 20 }} />

      {/* 新建销瓶弹窗 */}
      <Modal title="录入销瓶记录" open={modalOpen}
        onOk={() => form.validateFields().then(v => createMutation.mutate(v))}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        confirmLoading={createMutation.isPending}>
        <Form form={form} layout="vertical" initialValues={{ period, destruction_date: new Date().toISOString().slice(0, 10) }}>
          <Form.Item name="brand_id" label="品牌" rules={[{ required: true }]} initialValue={brandId || undefined}>
            <Select placeholder="选择品牌" showSearch optionFilterProp="label"
              options={brands.map(b => ({ value: b.id, label: b.name }))} />
          </Form.Item>
          <Form.Item name="destroyed_count" label="销毁瓶数" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} min={1} placeholder="厂家实际销毁的空瓶数" />
          </Form.Item>
          <Form.Item name="destruction_date" label="销毁日期" rules={[{ required: true }]}>
            <Input type="date" />
          </Form.Item>
          <Form.Item name="period" label="对账周期" rules={[{ required: true }]}>
            <Input placeholder="如 2026-04" />
          </Form.Item>
          <Form.Item name="manufacturer_witness" label="厂家见证人">
            <Input placeholder="厂家人员姓名" />
          </Form.Item>
          <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default TastingManagement;