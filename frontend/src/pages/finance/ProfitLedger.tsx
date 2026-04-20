import { useState } from 'react';
import { Button, Card, Col, DatePicker, Row, Space, Spin, Table, Tag, Typography } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { exportExcel } from '../../utils/exportExcel';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

interface DetailRecord { id: string; label: string; detail: string; amount: number; time: string }

const { Text } = Typography;

interface ProfitItem { category: string; label: string; amount: number; direction: string }
interface ProfitSummary { total_income: number; total_expense: number; net_profit: number; items: ProfitItem[] }

const currentYear = new Date().getFullYear();

function DetailExpand({ category, brandId, dateFrom, dateTo }: { category: string; brandId: string | null; dateFrom: string; dateTo: string }) {
  const { data: details = [], isLoading } = useQuery<DetailRecord[]>({
    queryKey: ['profit-detail', category, brandId, dateFrom, dateTo],
    queryFn: () => api.get('/dashboard/profit-detail', {
      params: { category, brand_id: brandId || undefined, date_from: dateFrom, date_to: dateTo },
    }).then(r => r.data),
  });

  if (isLoading) return <Spin size="small" />;
  if (!details.length) return <Text type="secondary">暂无明细数据</Text>;

  const detailCols: ColumnsType<DetailRecord> = [
    { title: '编号/名称', dataIndex: 'label', width: 170 },
    { title: '利润来源明细', dataIndex: 'detail', render: (v: string) => (
      <div style={{ fontSize: 12 }}>{v.split('|').map((s, i) => <span key={i} style={{ marginRight: 8 }}>{s.trim()}</span>)}</div>
    ) },
    { title: '盈亏', dataIndex: 'amount', width: 100, align: 'right', render: (v: number) => (
      <Text style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>{v >= 0 ? '+' : ''}¥{Number(v).toLocaleString()}</Text>
    ) },
    { title: '时间', dataIndex: 'time', width: 110 },
  ];

  return <Table columns={detailCols} dataSource={details} rowKey="id" size="small" pagination={details.length > 10 ? { pageSize: 10 } : false} />;
}

function ProfitLedger() {
  const { brandId, params } = useBrandFilter();
  const [dateFrom, setDateFrom] = useState(`${currentYear}-01-01`);
  const [dateTo, setDateTo] = useState(`${currentYear}-12-31`);

  const { data, isLoading } = useQuery<ProfitSummary>({
    queryKey: ['profit-summary', brandId, dateFrom, dateTo],
    queryFn: () => api.get('/dashboard/profit-summary', {
      params: { ...params, date_from: dateFrom, date_to: dateTo },
    }).then(r => r.data),
  });

  const income = data?.total_income ?? 0;
  const expense = data?.total_expense ?? 0;
  const net = data?.net_profit ?? 0;
  const items = data?.items ?? [];

  const incomeItems = items.filter(i => i.direction === 'income' && i.amount !== 0);
  const expenseItems = items.filter(i => i.direction === 'expense' && i.amount !== 0);

  const columns: ColumnsType<ProfitItem> = [
    { title: '分类', dataIndex: 'label', width: 180 },
    { title: '方向', dataIndex: 'direction', width: 70, render: (v: string) => v === 'income' ? <Tag color="green">收入</Tag> : <Tag color="red">支出</Tag> },
    { title: '金额', dataIndex: 'amount', width: 120, align: 'right', render: (v: number, r) => (
      <Text strong style={{ color: r.direction === 'income' ? '#52c41a' : '#ff4d4f', fontSize: 15 }}>
        {r.direction === 'income' ? '+' : '-'}¥{Number(v).toLocaleString()}
      </Text>
    ) },
    { title: '占比', key: 'pct', width: 80, align: 'right', render: (_, r) => {
      const base = r.direction === 'income' ? income : expense;
      return base > 0 ? `${Math.round(r.amount / base * 100)}%` : '-';
    } },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>利润台账</h2>
        <Space>
          <Button icon={<DownloadOutlined />} onClick={() => {
            const rows = items.filter(i => i.amount !== 0).map(i => ({
              '分类': i.label,
              '方向': i.direction === 'income' ? '收入' : '支出',
              '金额': Number(i.amount),
              '带符号': i.direction === 'income' ? Number(i.amount) : -Number(i.amount),
            }));
            exportExcel(`利润台账_${dateFrom}_${dateTo}`, '利润', rows, [
              { wch: 24 }, { wch: 10 }, { wch: 14 }, { wch: 14 },
            ], {
              '分类': '净利润', '方向': '', '金额': net, '带符号': net,
            } as any);
          }}>导出 Excel</Button>
          <DatePicker.RangePicker
            value={[dayjs(dateFrom), dayjs(dateTo)]}
            onChange={(dates) => {
              if (dates) { setDateFrom(dates[0]!.format('YYYY-MM-DD')); setDateTo(dates[1]!.format('YYYY-MM-DD')); }
            }}
            presets={[
              { label: '本月', value: [dayjs().startOf('month'), dayjs().endOf('month')] },
              { label: '上月', value: [dayjs().subtract(1, 'month').startOf('month'), dayjs().subtract(1, 'month').endOf('month')] },
              { label: '本季', value: [dayjs().startOf('quarter'), dayjs().endOf('quarter')] },
              { label: '本年', value: [dayjs().startOf('year'), dayjs().endOf('year')] },
            ]}
          />
        </Space>
      </div>

      {/* 汇总卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card style={{ textAlign: 'center', borderTop: '3px solid #52c41a' }}>
            <div style={{ color: '#888', fontSize: 13 }}>总收入</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#52c41a' }}>¥{income.toLocaleString()}</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card style={{ textAlign: 'center', borderTop: '3px solid #ff4d4f' }}>
            <div style={{ color: '#888', fontSize: 13 }}>总支出</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#ff4d4f' }}>¥{expense.toLocaleString()}</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card style={{ textAlign: 'center', borderTop: `3px solid ${net >= 0 ? '#1890ff' : '#ff4d4f'}` }}>
            <div style={{ color: '#888', fontSize: 13 }}>净利润</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: net >= 0 ? '#1890ff' : '#ff4d4f' }}>
              {net >= 0 ? '+' : ''}¥{net.toLocaleString()}
            </div>
          </Card>
        </Col>
      </Row>

      {/* 收入明细 */}
      <Row gutter={16}>
        <Col span={12}>
          <Card title={<span style={{ color: '#52c41a' }}>收入明细</span>} size="small">
            <Table columns={columns} dataSource={incomeItems} rowKey="category" size="small" pagination={false} loading={isLoading}
              summary={() => (
                <Table.Summary.Row>
                  <Table.Summary.Cell index={0}><Text strong>合计</Text></Table.Summary.Cell>
                  <Table.Summary.Cell index={1} />
                  <Table.Summary.Cell index={2} align="right"><Text strong style={{ color: '#52c41a', fontSize: 15 }}>+¥{income.toLocaleString()}</Text></Table.Summary.Cell>
                  <Table.Summary.Cell index={3} />
                </Table.Summary.Row>
              )}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title={<span style={{ color: '#ff4d4f' }}>支出明细</span>} size="small">
            <Table columns={columns} dataSource={expenseItems} rowKey="category" size="small" pagination={false} loading={isLoading}
              summary={() => (
                <Table.Summary.Row>
                  <Table.Summary.Cell index={0}><Text strong>合计</Text></Table.Summary.Cell>
                  <Table.Summary.Cell index={1} />
                  <Table.Summary.Cell index={2} align="right"><Text strong style={{ color: '#ff4d4f', fontSize: 15 }}>-¥{expense.toLocaleString()}</Text></Table.Summary.Cell>
                  <Table.Summary.Cell index={3} />
                </Table.Summary.Row>
              )}
            />
          </Card>
        </Col>
      </Row>

      {/* 全部明细表（可展开查看详情） */}
      <Card title="全部明细（点击行查看详情）" size="small" style={{ marginTop: 16 }}>
        <Table columns={columns} dataSource={items.filter(i => i.amount !== 0)} rowKey="category" size="small" pagination={false} loading={isLoading}
          expandable={{
            expandedRowRender: (record) => <DetailExpand category={record.category} brandId={brandId} dateFrom={dateFrom} dateTo={dateTo} />,
            rowExpandable: (r) => !['rebate', 'share_diff'].includes(r.category),
            expandIcon: () => null,
            expandRowByClick: true,
          }}
          summary={() => (
            <Table.Summary.Row style={{ background: net >= 0 ? '#f6ffed' : '#fff1f0' }}>
              <Table.Summary.Cell index={0}><Text strong style={{ fontSize: 15 }}>净利润</Text></Table.Summary.Cell>
              <Table.Summary.Cell index={1} />
              <Table.Summary.Cell index={2} align="right">
                <Text strong style={{ fontSize: 18, color: net >= 0 ? '#52c41a' : '#ff4d4f' }}>{net >= 0 ? '+' : ''}¥{net.toLocaleString()}</Text>
              </Table.Summary.Cell>
              <Table.Summary.Cell index={3} />
            </Table.Summary.Row>
          )}
        />
      </Card>
    </>
  );
}

export default ProfitLedger;
