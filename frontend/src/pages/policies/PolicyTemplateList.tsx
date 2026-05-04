import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Table, Tag, Typography, Button, Descriptions, Modal, Form, Input, InputNumber, Select, Switch, Space, Divider, DatePicker, Row, Col, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api, { extractItems } from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';
import { useAuthStore } from '../../stores/authStore';

const { Title, Text } = Typography;

const BENEFIT_TYPES = [
  { value: 'tasting_meal', label: '品鉴会餐费' },
  { value: 'tasting_wine', label: '品鉴酒' },
  { value: 'travel', label: '庄园之旅' },
  { value: 'rebate', label: '返利' },
  { value: 'gift', label: '赠品' },
  { value: 'other', label: '其他' },
];

interface BenefitItem { id: string; benefit_type: string; name: string; quantity: number; unit_value: number; total_value: number; product_id?: string; product_name?: string; is_material: boolean; }
interface TemplateItem {
  id: string; code: string; name: string; template_type: string; brand_id?: string;
  required_unit_price?: number; benefit_rules?: Record<string, unknown>; internal_valuation?: Record<string, unknown>;
  min_cases?: number; max_cases?: number; member_tier?: string; min_points?: number; max_points?: number;
  valid_from?: string; valid_to?: string; default_scheme_no?: string; total_policy_value: number;
  version: number; is_active: boolean; notes?: string; benefits: BenefitItem[]; created_at: string;
}

function PolicyTemplateList() {
  const [modalOpen, setModalOpen] = useState(false);
  const [viewRecord, setViewRecord] = useState<TemplateItem | null>(null);
  const [editingRecord, setEditingRecord] = useState<TemplateItem | null>(null);
  const [form] = Form.useForm();
  const queryClient = useQueryClient();
  const roles = useAuthStore((s) => s.roles) ?? [];
  const canSeeValuation = roles.some(r => ['admin', 'boss', 'finance'].includes(r));
  const { brandId, params } = useBrandFilter();
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data: listResp, isLoading } = useQuery<{ items: TemplateItem[]; total: number }>({
    queryKey: ['policy-templates', brandId, page, pageSize],
    queryFn: () => api.get('/policy-templates/templates', { params: { ...params, skip: (page - 1) * pageSize, limit: pageSize } }).then(r => r.data),
  });
  const templateData = listResp?.items ?? [];
  const total = listResp?.total ?? 0;

  const { data: brands = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ['brands-select'],
    queryFn: () => api.get('/products/brands').then(r => extractItems<{ id: string; name: string }>(r.data)),
  });

  const { data: products = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ['products-select', brandId],
    queryFn: () => api.get('/products', { params }).then(r => extractItems<{ id: string; name: string }>(r.data)),
  });

  const createMutation = useMutation({
    mutationFn: (values: any) => api.post('/policy-templates/templates', values),
    onSuccess: () => { message.success('创建成功'); queryClient.invalidateQueries({ queryKey: ['policy-templates'] }); setModalOpen(false); form.resetFields(); },
  });

  const editMutation = useMutation({
    mutationFn: ({ id, ...values }: any) => api.put(`/policy-templates/templates/${id}`, values),
    onSuccess: () => { message.success('更新成功'); queryClient.invalidateQueries({ queryKey: ['policy-templates'] }); setModalOpen(false); setEditingRecord(null); form.resetFields(); },
  });

  const extendMutation = useMutation({
    mutationFn: ({ id, new_valid_to }: { id: string; new_valid_to: string }) => api.post(`/policy-templates/templates/${id}/extend`, { new_valid_to }),
    onSuccess: () => { message.success('延期成功'); queryClient.invalidateQueries({ queryKey: ['policy-templates'] }); },
    onError: (err: any) => message.error(err?.response?.data?.detail ?? '延期失败'),
  });

  const templateType = Form.useWatch('template_type', form);
  const benefitsWatch = Form.useWatch('benefits', form) || [];
  const reqPrice = Form.useWatch('required_unit_price', form) || 0;
  const custPrice = Form.useWatch('customer_unit_price', form) || 0;
  const minCases = Form.useWatch('min_cases', form) || 0;
  const benefitsStandardTotal = (benefitsWatch as any[]).reduce((s: number, b: any) => {
    if (!b) return s;
    return s + (Number(b.quantity) || 0) * (Number(b.standard_unit_value) || 0);
  }, 0);
  const benefitsDiscountTotal = (benefitsWatch as any[]).reduce((s: number, b: any) => {
    if (!b) return s;
    return s + (Number(b.quantity) || 0) * (Number(b.unit_value) || 0);
  }, 0);
  const benefitsLoss = benefitsStandardTotal - benefitsDiscountTotal;
  const customerGap = reqPrice > 0 && custPrice > 0 && minCases > 0 ? (reqPrice - custPrice) * 6 * minCases : 0;
  const policyProfit = benefitsDiscountTotal - customerGap;

  const isExpired = (r: TemplateItem) => r.valid_to && new Date(r.valid_to) < new Date();

  const handleEdit = (record: TemplateItem) => {
    setEditingRecord(record);
    form.setFieldsValue({
      ...record,
      benefit_rules: record.benefit_rules ? JSON.stringify(record.benefit_rules, null, 2) : '',
      internal_valuation: record.internal_valuation ? JSON.stringify(record.internal_valuation, null, 2) : '',
      valid_from: record.valid_from ? dayjs(record.valid_from) : null,
      valid_to: record.valid_to ? dayjs(record.valid_to) : null,
      benefits: record.benefits?.length > 0 ? record.benefits.map((b: any) => ({
        benefit_type: b.benefit_type, name: b.name, quantity: b.quantity,
        standard_unit_value: b.standard_unit_value ?? 0, unit_value: b.unit_value,
        quantity_unit: b.quantity_unit || '次', product_id: b.product_id, is_material: b.is_material, fulfill_mode: b.fulfill_mode || (b.is_material ? 'material' : 'claim'),
      })) : [],
    });
    setModalOpen(true);
  };

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      if (values.valid_from) values.valid_from = values.valid_from.format('YYYY-MM-DD');
      if (values.valid_to) values.valid_to = values.valid_to.format('YYYY-MM-DD');
      for (const key of ['benefit_rules', 'internal_valuation']) {
        if (typeof values[key] === 'string' && values[key].trim()) {
          try { values[key] = JSON.parse(values[key]); } catch { message.error(`${key} JSON 格式不正确`); return; }
        } else if (!values[key]) { values[key] = null; }
      }
      // Clean benefits
      values.benefits = (values.benefits ?? []).filter((b: any) => b?.name).map((b: any, i: number) => ({
        benefit_type: b.benefit_type || 'other', name: b.name, quantity: b.quantity || 1,
        standard_unit_value: b.standard_unit_value || 0, unit_value: b.unit_value || 0,
        quantity_unit: b.quantity_unit || '次', product_id: b.product_id || null, is_material: b.fulfill_mode === 'material', fulfill_mode: b.fulfill_mode || 'claim', sort_order: i,
      }));
      if (editingRecord) editMutation.mutate({ id: editingRecord.id, ...values });
      else createMutation.mutate(values);
    });
  };

  const columns: ColumnsType<TemplateItem> = [
    { title: '编码', dataIndex: 'code', width: 110 },
    { title: '类型', dataIndex: 'template_type', width: 70, render: (v: string) => <Tag color={v === 'channel' ? 'blue' : 'purple'}>{v === 'channel' ? '渠道' : '团购'}</Tag> },
    { title: '名称', dataIndex: 'name', width: 160 },
    { title: '匹配条件', key: 'match', width: 120, render: (_: unknown, r: TemplateItem) => r.template_type === 'channel' ? `${r.min_cases ?? '-'} 箱` : <><Tag color="gold">{r.member_tier}</Tag>{r.min_points ?? 0}~{r.max_points ?? '∞'}分</> },
    { title: '价格', key: 'prices', width: 130, render: (_: unknown, r: TemplateItem) => r.required_unit_price ? <Text type="secondary">{r.required_unit_price}→{(r as any).customer_unit_price ?? '?'}</Text> : '-' },
    { title: '折算总价值', dataIndex: 'total_policy_value', width: 100, align: 'right', render: (v: number) => v > 0 ? <Text strong style={{ color: '#1890ff' }}>¥{Number(v).toLocaleString()}</Text> : '-' },
    { title: '政策明细', key: 'benefits', width: 320, ellipsis: true, render: (_: unknown, r: TemplateItem) => r.benefits?.length > 0 ? r.benefits.map((b: any) => `${b.name}×${b.quantity}${b.quantity_unit || '次'}(¥${b.standard_total ?? 0}/¥${b.total_value})`).join('、') : '-' },
    { title: '有效期', key: 'validity', width: 160, render: (_: unknown, r: TemplateItem) => <span style={isExpired(r) ? { color: '#ff4d4f' } : undefined}>{r.valid_from ?? '—'} ~ {r.valid_to ?? '长期'}{isExpired(r) ? ' (过期)' : ''}</span> },
    { title: '状态', dataIndex: 'is_active', width: 60, render: (v: boolean) => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag> },
    { title: '操作', key: 'actions', width: 100, render: (_: unknown, record: TemplateItem) => (
      <Space>
        <a onClick={() => setViewRecord(record)}>查看</a>
        <a onClick={() => handleEdit(record)}>编辑</a>
        {isExpired(record) && canSeeValuation && <a style={{ color: '#faad14' }} onClick={() => {
          Modal.confirm({ title: '延期', content: <DatePicker id="ext-date" style={{ width: '100%', marginTop: 8 }} onChange={(d) => { (window as any).__extDate = d?.format('YYYY-MM-DD'); }} />,
            onOk: () => { const dt = (window as any).__extDate; if (dt) extendMutation.mutate({ id: record.id, new_valid_to: dt }); else message.warning('请选择日期'); } });
        }}>延期</a>}
      </Space>
    ) },
  ];

  return (
    <>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>政策模板</Title>
          <Select placeholder="全部类型" allowClear style={{ width: 120 }} onChange={(v) => { setTypeFilter(v ?? null); setPage(1); }}
            options={[{ value: 'channel', label: '渠道' }, { value: 'group_purchase', label: '团购' }]} />
        </Space>
        <Button type="primary" onClick={() => { setEditingRecord(null); form.resetFields(); form.setFieldsValue({ template_type: 'channel', brand_id: brandId || undefined, benefits: [{ quantity: 1 }] }); setModalOpen(true); }}>新建</Button>
      </Space>
      <Table rowKey="id" columns={columns} dataSource={templateData.filter(t => !typeFilter || t.template_type === typeFilter)} loading={isLoading} size="middle" pagination={{ current: page, pageSize, total, showTotal: (t) => '共 ' + t + ' 条', showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} scroll={{ x: 1200 }} />

      <Modal title={editingRecord ? '编辑模板' : '新建模板'} open={modalOpen} onOk={handleSubmit}
        onCancel={() => { setModalOpen(false); setEditingRecord(null); form.resetFields(); }}
        confirmLoading={createMutation.isPending || editMutation.isPending} width={850}>
        <Form form={form} layout="vertical" initialValues={{ template_type: 'channel', is_active: true, version: 1, benefits: [{}] }}>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="code" label="编码" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col span={8}><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col span={8}><Form.Item name="template_type" label="类型" rules={[{ required: true }]}>
              <Select options={[{ value: 'channel', label: '渠道（按箱数）' }, { value: 'group_purchase', label: '团购（按积分）' }]} />
            </Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="brand_id" label="品牌" rules={[{ required: true, message: '请选择品牌' }]}>
              <Select showSearch optionFilterProp="label" placeholder="选择品牌"
                options={brands.map((b: any) => ({ value: b.id, label: b.name }))} />
            </Form.Item></Col>
            <Col span={4}><Form.Item name="required_unit_price" label="进货价/瓶"><InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" placeholder="885" /></Form.Item></Col>
            <Col span={4}><Form.Item name="customer_unit_price" label="客户折算价/瓶"><InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" placeholder="650" /></Form.Item></Col>
            <Col span={8}><Form.Item name="default_scheme_no" label="方案号"><Input /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="valid_from" label="生效日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="valid_to" label="到期日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={4}><Form.Item name="version" label="版本"><InputNumber style={{ width: '100%' }} min={1} /></Form.Item></Col>
            <Col span={4}><Form.Item name="is_active" label="启用" valuePropName="checked"><Switch /></Form.Item></Col>
          </Row>

          {templateType === 'group_purchase' ? (
            <Row gutter={16}>
              <Col span={8}><Form.Item name="member_tier" label="会员等级" rules={[{ required: true }]}>
                <Select options={[{ value: '金卡', label: '金卡' }, { value: '铂金卡', label: '铂金卡' }, { value: '钻石卡', label: '钻石卡' }, { value: '黑金卡', label: '黑金卡' }, { value: '企业直采', label: '企业直采' }]} />
              </Form.Item></Col>
              <Col span={8}><Form.Item name="min_points" label="最低积分"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
              <Col span={8}><Form.Item name="max_points" label="最高积分"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            </Row>
          ) : (
            <Form.Item name="min_cases" label="匹配箱数" rules={[{ required: true }]}>
              <InputNumber min={1} style={{ width: 200 }} placeholder="如 5，表示正好5箱匹配" />
            </Form.Item>
          )}

          <Divider>政策明细</Divider>
          {/* 表头 */}
          <div style={{ display: 'grid', gridTemplateColumns: '90px 1fr 50px 50px 90px 90px 120px 65px 30px', gap: 6, padding: '6px 0', borderBottom: '2px solid #d9d9d9', fontSize: 12, color: '#555', marginBottom: 4, fontWeight: 600 }}>
            <span>类型</span><span>名称</span><span>数量</span><span>单位</span><span>面值/个</span><span>折算/个</span><span>关联商品</span><span>兑付</span><span></span>
          </div>
          <Form.List name="benefits">
            {(fields, { add, remove }) => (
              <>
                {fields.map(({ key, name, ...rest }) => (
                  <div key={key} style={{ display: 'grid', gridTemplateColumns: '90px 1fr 50px 50px 90px 90px 120px 65px 30px', gap: 6, alignItems: 'center', padding: '6px 0', borderBottom: '1px solid #f5f5f5' }}>
                    <Form.Item {...rest} name={[name, 'benefit_type']} style={{ marginBottom: 0 }}>
                      <Select placeholder="类型" options={BENEFIT_TYPES} size="small" />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'name']} rules={[{ required: true, message: '名称' }]} style={{ marginBottom: 0 }}>
                      <Input placeholder="名称" size="small" />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'quantity']} initialValue={1} style={{ marginBottom: 0 }}>
                      <InputNumber placeholder="1" min={1} style={{ width: '100%' }} size="small" />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'quantity_unit']} initialValue="次" style={{ marginBottom: 0 }}>
                      <Select size="small" options={[{ value: '场', label: '场' }, { value: '瓶', label: '瓶' }, { value: '次', label: '次' }, { value: '笔', label: '笔' }, { value: '个', label: '个' }, { value: '箱', label: '箱' }]} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'standard_unit_value']} style={{ marginBottom: 0 }}>
                      <InputNumber placeholder="0" min={0} precision={0} style={{ width: '100%' }} size="small" />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'unit_value']} style={{ marginBottom: 0 }}>
                      <InputNumber placeholder="0" min={0} precision={0} style={{ width: '100%' }} size="small" />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'product_id']} style={{ marginBottom: 0 }}>
                      <Select allowClear placeholder="商品" size="small" showSearch optionFilterProp="label"
                        options={products.map(p => ({ value: p.id, label: p.name }))} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'fulfill_mode']} initialValue="claim" style={{ marginBottom: 0 }}>
                      <Select size="small" options={[{ value: 'claim', label: '对账' }, { value: 'direct', label: '福利' }, { value: 'material', label: '出库' }]} />
                    </Form.Item>
                    <a style={{ color: '#ff4d4f', fontSize: 12 }} onClick={() => remove(name)}>删</a>
                  </div>
                ))}
                <Button type="dashed" onClick={() => add({ quantity: 1 })} block icon={<PlusOutlined />} style={{ marginTop: 8 }}>添加政策项</Button>
              </>
            )}
          </Form.List>

          {/* 统计区 */}
          <div style={{ marginTop: 16, padding: 16, background: '#f0f5ff', borderRadius: 8 }}>
            <Row gutter={[16, 12]}>
              <Col span={8}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: '#888', fontSize: 12 }}>厂家面值合计</div>
                  <div style={{ fontSize: 20, fontWeight: 600 }}>¥{benefitsStandardTotal.toLocaleString()}</div>
                </div>
              </Col>
              <Col span={8}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: '#888', fontSize: 12 }}>折算到手合计</div>
                  <div style={{ fontSize: 20, fontWeight: 600, color: '#1890ff' }}>¥{benefitsDiscountTotal.toLocaleString()}</div>
                </div>
              </Col>
              <Col span={8}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: '#888', fontSize: 12 }}>套现折损</div>
                  <div style={{ fontSize: 20, fontWeight: 600, color: benefitsLoss > 0 ? '#ff4d4f' : '#52c41a' }}>¥{benefitsLoss.toLocaleString()}</div>
                </div>
              </Col>
            </Row>
            {custPrice > 0 && reqPrice > 0 && minCases > 0 && (
              <>
                <Divider style={{ margin: '12px 0' }} />
                <Row gutter={[16, 12]}>
                  <Col span={8}>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ color: '#888', fontSize: 12 }}>客户差价补贴</div>
                      <div style={{ fontSize: 18, fontWeight: 600, color: '#fa8c16' }}>¥{customerGap.toLocaleString()}</div>
                      <div style={{ color: '#aaa', fontSize: 11 }}>({reqPrice}-{custPrice}) × {minCases * 6}瓶</div>
                    </div>
                  </Col>
                  <Col span={8}>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ color: '#888', fontSize: 12, fontWeight: 600 }}>政策套利</div>
                      <div style={{ fontSize: 24, fontWeight: 700, color: policyProfit >= 0 ? '#52c41a' : '#ff4d4f' }}>
                        {policyProfit >= 0 ? '+' : ''}¥{policyProfit.toLocaleString()}
                      </div>
                      <div style={{ color: '#aaa', fontSize: 11 }}>谁垫付谁享受</div>
                    </div>
                  </Col>
                  <Col span={8}>
                    <div style={{ textAlign: 'center', padding: '4px 8px', background: '#fff', borderRadius: 6, fontSize: 11, color: '#666', lineHeight: 1.6 }}>
                      折算价值 {benefitsDiscountTotal.toLocaleString()}<br/>
                      - 客户差价 {customerGap.toLocaleString()}<br/>
                      = 套利 <strong style={{ color: policyProfit >= 0 ? '#52c41a' : '#ff4d4f' }}>{policyProfit >= 0 ? '+' : ''}{policyProfit.toLocaleString()}</strong>
                    </div>
                  </Col>
                </Row>
              </>
            )}
          </div>

          {canSeeValuation && (
            <>
              <Divider><Text type="danger">内部估值（仅老板/财务可见）</Text></Divider>
              <Form.Item name="internal_valuation" label="折算估值">
                <Input.TextArea rows={3} placeholder='{"套现折损": 850, "备注": "..."}' />
              </Form.Item>
            </>
          )}

          <Divider />
          <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      {/* 查看详情弹窗 */}
      <Modal title={`政策模板详情 — ${viewRecord?.name ?? ''}`} open={!!viewRecord} onCancel={() => setViewRecord(null)} footer={null} width={650}>
        {viewRecord && (
          <>
            <Descriptions column={3} size="small" bordered style={{ marginBottom: 12 }}>
              <Descriptions.Item label="编码">{viewRecord.code}</Descriptions.Item>
              <Descriptions.Item label="类型"><Tag color={viewRecord.template_type === 'channel' ? 'blue' : 'purple'}>{viewRecord.template_type === 'channel' ? '渠道' : '团购'}</Tag></Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={viewRecord.is_active ? 'green' : 'default'}>{viewRecord.is_active ? '启用' : '停用'}</Tag></Descriptions.Item>
              <Descriptions.Item label="匹配条件">{viewRecord.template_type === 'channel' ? `${viewRecord.min_cases ?? '-'}箱` : `${viewRecord.member_tier} ${viewRecord.min_points ?? 0}~${viewRecord.max_points ?? '∞'}分`}</Descriptions.Item>
              <Descriptions.Item label="进货价">{viewRecord.required_unit_price ? `¥${viewRecord.required_unit_price}/瓶` : '-'}</Descriptions.Item>
              <Descriptions.Item label="客户折算价">{(viewRecord as any).customer_unit_price ? `¥${(viewRecord as any).customer_unit_price}/瓶` : '-'}</Descriptions.Item>
              <Descriptions.Item label="有效期" span={2}>{viewRecord.valid_from ?? '—'} ~ {viewRecord.valid_to ?? '长期'}</Descriptions.Item>
              <Descriptions.Item label="政策总价值"><Text strong style={{ color: '#1890ff' }}>¥{Number(viewRecord.total_policy_value).toLocaleString()}</Text></Descriptions.Item>
            </Descriptions>
            {viewRecord.benefits?.length > 0 && (
              <>
                <Divider titlePlacement="start" style={{ margin: '8px 0' }}>政策明细</Divider>
                <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                  <thead><tr style={{ background: '#fafafa' }}>
                    <th style={{ padding: '5px 8px', textAlign: 'left' }}>类型</th>
                    <th style={{ padding: '5px 8px', textAlign: 'left' }}>名称</th>
                    <th style={{ padding: '5px 8px' }}>数量</th>
                    <th style={{ padding: '5px 8px', textAlign: 'right' }}>面值</th>
                    <th style={{ padding: '5px 8px', textAlign: 'right' }}>折算</th>
                    <th style={{ padding: '5px 8px' }}>兑付方式</th>
                  </tr></thead>
                  <tbody>{viewRecord.benefits.map((b: any, i: number) => (
                    <tr key={i} style={{ borderBottom: '1px solid #f0f0f0' }}>
                      <td style={{ padding: '5px 8px' }}><Tag>{BENEFIT_TYPES.find(t => t.value === b.benefit_type)?.label ?? b.benefit_type}</Tag></td>
                      <td style={{ padding: '5px 8px' }}>{b.name}{b.product_name ? <Text type="secondary" style={{ fontSize: 11 }}> ({b.product_name})</Text> : ''}</td>
                      <td style={{ padding: '5px 8px', textAlign: 'center' }}>{b.quantity}{b.quantity_unit || '次'}</td>
                      <td style={{ padding: '5px 8px', textAlign: 'right' }}>¥{(b.standard_total ?? 0).toLocaleString()}</td>
                      <td style={{ padding: '5px 8px', textAlign: 'right' }}>¥{b.total_value.toLocaleString()}</td>
                      <td style={{ padding: '5px 8px' }}>{(b as any).fulfill_mode === 'direct' ? <Tag color="green">福利</Tag> : (b as any).fulfill_mode === 'material' ? <Tag color="cyan">出库</Tag> : <Tag color="blue">对账</Tag>}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </>
            )}
            {viewRecord.notes && <><Divider style={{ margin: '8px 0' }} /><Text type="secondary">{viewRecord.notes}</Text></>}
          </>
        )}
      </Modal>
    </>
  );
}

export default PolicyTemplateList;
