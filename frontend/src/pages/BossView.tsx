import { Card, Col, DatePicker, Row, Statistic, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import dayjs, { type Dayjs } from 'dayjs';
import api from '../api/client';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

interface UnitRow {
  id: string;
  code: string;
  name: string;
  gmv: number;
  net_profit: number;
  commission_total: number;
  inventory_value: number;
  account_balance: number;
  pending_receivables: number;
}

interface BossSummary {
  period: { from: string; to: string };
  units: UnitRow[];
  grand_total: {
    gmv: number;
    net_profit: number;
    commission_total: number;
    inventory_value: number;
    account_balance: number;
    pending_receivables: number;
  };
}

const UNIT_COLOR: Record<string, string> = {
  brand_agent: '#1677ff',
  retail: '#52c41a',
  mall: '#722ed1',
};

export default function BossView() {
  const today = dayjs();
  const [range, setRange] = useState<[Dayjs, Dayjs]>([today.startOf('month'), today]);

  const { data, isLoading } = useQuery<BossSummary>({
    queryKey: ['business-unit-summary', range[0].format('YYYY-MM-DD'), range[1].format('YYYY-MM-DD')],
    queryFn: () => api.get('/dashboard/business-unit-summary', {
      params: {
        date_from: range[0].format('YYYY-MM-DD'),
        date_to: range[1].format('YYYY-MM-DD'),
      },
    }).then(r => r.data),
  });

  return (
    <>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>经营单元看板</Title>
          <Text type="secondary">按事业部统计 GMV / 利润 / 库存 / 账户 / 待收，品牌维度保留在其他报表</Text>
        </Col>
        <Col>
          <RangePicker
            value={range}
            onChange={v => v && setRange([v[0]!, v[1]!])}
            presets={[
              { label: '本月', value: [today.startOf('month'), today] },
              { label: '上月', value: [today.subtract(1, 'month').startOf('month'), today.subtract(1, 'month').endOf('month')] },
              { label: '本季度', value: [today.startOf('quarter'), today] },
              { label: '今年', value: [today.startOf('year'), today] },
            ]}
            allowClear={false}
          />
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        {(data?.units ?? []).map(u => (
          <Col xs={24} md={12} lg={8} key={u.code}>
            <Card
              loading={isLoading}
              title={
                <span>
                  <Tag color={UNIT_COLOR[u.code] ?? 'default'}>{u.code}</Tag>
                  {u.name}
                </span>
              }
              styles={{ header: { borderBottom: `2px solid ${UNIT_COLOR[u.code] ?? '#d9d9d9'}` } }}
            >
              <Row gutter={[12, 12]}>
                <Col span={12}>
                  <Statistic title="GMV" value={u.gmv} precision={2} prefix="¥" />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="净利润"
                    value={u.net_profit}
                    precision={2}
                    prefix="¥"
                    valueStyle={{ color: u.net_profit >= 0 ? '#389e0d' : '#cf1322' }}
                  />
                </Col>
                <Col span={12}>
                  <Statistic title="提成" value={u.commission_total} precision={2} prefix="¥" />
                </Col>
                <Col span={12}>
                  <Statistic title="库存价值" value={u.inventory_value} precision={0} prefix="¥" />
                </Col>
                <Col span={12}>
                  <Statistic title="账户余额" value={u.account_balance} precision={2} prefix="¥" />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="待收款"
                    value={u.pending_receivables}
                    precision={2}
                    prefix="¥"
                    valueStyle={{ color: u.pending_receivables > 0 ? '#faad14' : undefined }}
                  />
                </Col>
              </Row>
            </Card>
          </Col>
        ))}
      </Row>

      {/* grand total */}
      {data?.grand_total && (
        <Card style={{ marginTop: 16 }} title="总公司合计（仅分析视角，不代表独立账套）">
          <Row gutter={16}>
            <Col span={4}><Statistic title="总 GMV" value={data.grand_total.gmv} precision={2} prefix="¥" /></Col>
            <Col span={4}>
              <Statistic
                title="总净利润"
                value={data.grand_total.net_profit}
                precision={2}
                prefix="¥"
                valueStyle={{ color: data.grand_total.net_profit >= 0 ? '#389e0d' : '#cf1322' }}
              />
            </Col>
            <Col span={4}><Statistic title="总提成" value={data.grand_total.commission_total} precision={2} prefix="¥" /></Col>
            <Col span={4}><Statistic title="总库存价值" value={data.grand_total.inventory_value} precision={0} prefix="¥" /></Col>
            <Col span={4}><Statistic title="总账户余额" value={data.grand_total.account_balance} precision={2} prefix="¥" /></Col>
            <Col span={4}>
              <Statistic
                title="总待收款"
                value={data.grand_total.pending_receivables}
                precision={2}
                prefix="¥"
                valueStyle={{ color: data.grand_total.pending_receivables > 0 ? '#faad14' : undefined }}
              />
            </Col>
          </Row>
        </Card>
      )}

      <div style={{ marginTop: 12, color: '#8c8c8c', fontSize: 12 }}>
        <Text type="secondary">
          数据口径：GMV = 订单应收合计；净利润 = GMV - 提成（品牌代理走简化口径，详细科目请看财务 → 利润台账）；
          库存价值 = Inventory.quantity × cost_price（mall 走 avg_cost_price）；账户余额按 MALL_MASTER/STORE_MASTER/品牌现金账户区分。
        </Text>
      </div>
    </>
  );
}
