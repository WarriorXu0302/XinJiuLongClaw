/**
 * 门店销售流水 + 统计看板
 */
import { useState } from 'react';
import {
  Button, Card, Col, DatePicker, Descriptions, Drawer, Row, Segmented, Select, Space,
  Statistic, Table, Tag, Typography, message,
} from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs, { Dayjs } from 'dayjs';
import api, { extractItems } from '../../api/client';

const { Title } = Typography;
const { RangePicker } = DatePicker;

const METHOD_LABEL: Record<string, { text: string; color: string }> = {
  cash: { text: '现金', color: 'green' },
  wechat: { text: '微信', color: 'cyan' },
  alipay: { text: '支付宝', color: 'blue' },
  card: { text: '刷卡', color: 'purple' },
};

interface Sale {
  id: string;
  sale_no: string;
  store_id: string;
  store_name?: string;
  cashier_employee_id: string;
  cashier_name?: string;
  customer_id: string;
  customer_name?: string;
  total_sale_amount: string;
  total_cost: string;
  total_profit: string;
  total_commission: string;
  total_bottles: number;
  payment_method: string;
  created_at: string;
  items?: any[];
}

interface Store {
  id: string;
  name: string;
  warehouse_type: string;
}

export default function StoreSaleList() {
  const [storeId, setStoreId] = useState<string | undefined>();
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>([
    dayjs().startOf('month'), dayjs().endOf('day'),
  ]);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [statsView, setStatsView] = useState<'total' | 'by_store'>('total');

  const params: any = { limit: 200 };
  if (storeId) params.store_id = storeId;
  if (range) {
    params.start_date = range[0].format('YYYY-MM-DD');
    params.end_date = range[1].format('YYYY-MM-DD');
  }

  const { data: allWhs = [] } = useQuery<Store[]>({
    queryKey: ['stores-for-sale-list'],
    queryFn: () => api.get('/inventory/warehouses').then(r => extractItems<Store>(r.data)),
  });
  const stores = allWhs.filter(s => s.warehouse_type === 'store');

  const { data, isLoading } = useQuery<{ records: Sale[]; total: number }>({
    queryKey: ['store-sales', params],
    queryFn: () => api.get('/store-sales', { params }).then(r => r.data),
  });
  const { data: stats } = useQuery<any>({
    queryKey: ['store-sales-stats', params],
    queryFn: () => api.get('/store-sales/stats', { params }).then(r => r.data),
  });
  const { data: statsByStore } = useQuery<any>({
    queryKey: ['store-sales-stats-by-store', params],
    queryFn: () => api.get('/store-sales/stats', {
      params: { ...params, group_by: 'store' },
    }).then(r => r.data),
    enabled: statsView === 'by_store',
  });

  const handleExport = async () => {
    try {
      const res = await api.get('/store-sales/export', {
        params,
        responseType: 'blob',
      });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url;
      const period = range
        ? `${range[0].format('YYYY-MM-DD')}_${range[1].format('YYYY-MM-DD')}`
        : 'all';
      a.download = `门店销售流水_${period}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      message.success('导出成功');
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '导出失败');
    }
  };
  const rows = data?.records || [];

  const { data: detailData } = useQuery<Sale>({
    queryKey: ['store-sale-detail', detailId],
    queryFn: () => api.get(`/store-sales/${detailId}`).then(r => r.data),
    enabled: !!detailId,
  });

  const columns: ColumnsType<Sale> = [
    { title: '销售单号', dataIndex: 'sale_no', width: 210 },
    { title: '门店', dataIndex: 'store_name', width: 180 },
    { title: '店员', dataIndex: 'cashier_name', width: 120 },
    { title: '客户', dataIndex: 'customer_name', width: 120 },
    { title: '瓶数', dataIndex: 'total_bottles', width: 70, align: 'right' as const },
    {
      title: '销售额', dataIndex: 'total_sale_amount', width: 110, align: 'right' as const,
      render: (v: string) => `¥${v}`,
    },
    {
      title: '利润', dataIndex: 'total_profit', width: 110, align: 'right' as const,
      render: (v: string) => <span style={{ color: Number(v) >= 0 ? '#52c41a' : '#ff4d4f' }}>¥{v}</span>,
    },
    {
      title: '店员提成', dataIndex: 'total_commission', width: 110, align: 'right' as const,
      render: (v: string) => `¥${v}`,
    },
    {
      title: '付款', dataIndex: 'payment_method', width: 80,
      render: (v: string) => METHOD_LABEL[v] ? <Tag color={METHOD_LABEL[v].color}>{METHOD_LABEL[v].text}</Tag> : v,
    },
    {
      title: '时间', dataIndex: 'created_at', width: 150,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    {
      title: '操作', key: 'act', width: 70,
      render: (_, r) => <a onClick={() => setDetailId(r.id)}>详情</a>,
    },
  ];

  return (
    <div>
      <Title level={4}>门店销售流水</Title>

      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="按门店筛选"
          style={{ width: 220 }}
          value={storeId}
          onChange={setStoreId}
          options={stores.map(s => ({ value: s.id, label: s.name }))}
          allowClear
        />
        <RangePicker
          value={range as any}
          onChange={(v) => setRange(v as any)}
        />
        <Segmented
          value={statsView}
          onChange={(v) => setStatsView(v as any)}
          options={[
            { label: '汇总', value: 'total' },
            { label: '按店分组', value: 'by_store' },
          ]}
        />
        <Button
          icon={<DownloadOutlined />}
          onClick={handleExport}
        >
          导出 CSV
        </Button>
      </Space>

      {statsView === 'total' && stats && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={4}>
            <Card size="small"><Statistic title="成交单数" value={stats.sale_count} /></Card>
          </Col>
          <Col span={4}>
            <Card size="small"><Statistic title="瓶数" value={stats.total_bottles} suffix="瓶" /></Card>
          </Col>
          <Col span={4}>
            <Card size="small"><Statistic title="销售额" value={Number(stats.total_sale_amount)} precision={2} prefix="¥" /></Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic title="成本" value={Number(stats.total_cost)} precision={2} prefix="¥" valueStyle={{ color: '#8c8c8c' }} />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="利润"
                value={Number(stats.total_profit)}
                precision={2}
                prefix="¥"
                valueStyle={{ color: Number(stats.total_profit) >= 0 ? '#52c41a' : '#ff4d4f' }}
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small"><Statistic title="店员提成" value={Number(stats.total_commission)} precision={2} prefix="¥" valueStyle={{ color: '#1677ff' }} /></Card>
          </Col>
        </Row>
      )}

      {statsView === 'by_store' && statsByStore && (
        <Card size="small" style={{ marginBottom: 16 }}
          title={`按店分组（合计：销售额 ¥${Number(statsByStore.total?.total_sale_amount || 0).toLocaleString()} / 利润 ¥${Number(statsByStore.total?.total_profit || 0).toLocaleString()} / 毛利率 ${statsByStore.total?.gross_margin_pct ?? '—'}%）`}
        >
          <Table
            size="small"
            pagination={false}
            rowKey="store_id"
            dataSource={statsByStore.by_store || []}
            columns={[
              { title: '门店', dataIndex: 'store_name' },
              { title: '单数', dataIndex: 'sale_count', width: 80, align: 'right' as const },
              { title: '瓶数', dataIndex: 'total_bottles', width: 80, align: 'right' as const },
              {
                title: '销售额', dataIndex: 'total_sale_amount', width: 130, align: 'right' as const,
                render: (v: string) => `¥${Number(v).toLocaleString()}`,
              },
              {
                title: '成本', dataIndex: 'total_cost', width: 120, align: 'right' as const,
                render: (v: string) => <span style={{ color: '#8c8c8c' }}>¥{Number(v).toLocaleString()}</span>,
              },
              {
                title: '利润', dataIndex: 'total_profit', width: 120, align: 'right' as const,
                render: (v: string) =>
                  <span style={{ color: Number(v) >= 0 ? '#52c41a' : '#ff4d4f' }}>¥{Number(v).toLocaleString()}</span>,
              },
              {
                title: '店员提成', dataIndex: 'total_commission', width: 120, align: 'right' as const,
                render: (v: string) => <span style={{ color: '#1677ff' }}>¥{Number(v).toLocaleString()}</span>,
              },
              {
                title: '毛利率', dataIndex: 'gross_margin_pct', width: 90, align: 'right' as const,
                render: (v: string | null) => v ? `${v}%` : '—',
              },
            ]}
          />
        </Card>
      )}

      <Table
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={isLoading}
        size="middle"
        scroll={{ x: 1400 }}
        pagination={{ pageSize: 20 }}
      />

      <Drawer
        title={detailData ? `销售单 ${detailData.sale_no}` : '销售详情'}
        open={!!detailId}
        onClose={() => setDetailId(null)}
        size={760}
      >
        {detailData && (
          <>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="门店">{detailData.store_name}</Descriptions.Item>
              <Descriptions.Item label="店员">{detailData.cashier_name}</Descriptions.Item>
              <Descriptions.Item label="客户" span={2}>{detailData.customer_name}</Descriptions.Item>
              <Descriptions.Item label="瓶数">{detailData.total_bottles}</Descriptions.Item>
              <Descriptions.Item label="付款">
                {METHOD_LABEL[detailData.payment_method]?.text || detailData.payment_method}
              </Descriptions.Item>
              <Descriptions.Item label="销售额">¥{detailData.total_sale_amount}</Descriptions.Item>
              <Descriptions.Item label="成本">¥{detailData.total_cost}</Descriptions.Item>
              <Descriptions.Item label="利润">
                <span style={{ color: '#52c41a', fontWeight: 600 }}>¥{detailData.total_profit}</span>
              </Descriptions.Item>
              <Descriptions.Item label="店员提成">
                <span style={{ color: '#1677ff', fontWeight: 600 }}>¥{detailData.total_commission}</span>
              </Descriptions.Item>
              <Descriptions.Item label="时间" span={2}>
                {dayjs(detailData.created_at).format('YYYY-MM-DD HH:mm:ss')}
              </Descriptions.Item>
            </Descriptions>

            <div style={{ marginTop: 16 }}>
              <Typography.Text strong>明细</Typography.Text>
              <Table
                dataSource={detailData.items || []}
                rowKey="id"
                size="small"
                pagination={false}
                columns={[
                  { title: '条码', dataIndex: 'barcode', width: 240 },
                  { title: '批次', dataIndex: 'batch_no_snapshot', width: 110 },
                  { title: '售价', dataIndex: 'sale_price', align: 'right' as const, render: (v: string) => `¥${v}` },
                  { title: '成本', dataIndex: 'cost_price_snapshot', align: 'right' as const, render: (v: string) => `¥${v}` },
                  { title: '利润', dataIndex: 'profit', align: 'right' as const, render: (v: string) => `¥${v}` },
                  {
                    title: '提成率', dataIndex: 'rate_on_profit_snapshot', align: 'right' as const,
                    render: (v: string) => v ? `${(Number(v) * 100).toFixed(2)}%` : '-',
                  },
                  { title: '店员提成', dataIndex: 'commission_amount', align: 'right' as const, render: (v: string) => `¥${v}` },
                ]}
              />
            </div>
          </>
        )}
      </Drawer>
    </div>
  );
}
