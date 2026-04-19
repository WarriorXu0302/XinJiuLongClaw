import { useState } from 'react';
import { Card, Descriptions, Empty, Input, Spin, Tag, Timeline, Typography } from 'antd';
import { BarcodeOutlined, SearchOutlined } from '@ant-design/icons';
import api from '../../api/client';

const { Title, Text } = Typography;

interface TraceResult {
  barcode: string;
  found: boolean;
  barcode_type?: string;
  product_name?: string;
  batch_no?: string;
  warehouse_name?: string;
  status?: string;
  stock_in_flow_no?: string;
  stock_in_date?: string;
  stock_out_flow_no?: string;
  order_no?: string;
  customer_name?: string;
  salesman_name?: string;
  policy_status?: string;
  scheme_no?: string;
}

const statusColor: Record<string, string> = {
  in_stock: 'green',
  outbound: 'blue',
  locked: 'orange',
  invalid: 'red',
};

function BarcodTracePage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TraceResult | null>(null);
  const [searchCode, setSearchCode] = useState('');

  const doTrace = async (code: string) => {
    const barcode = code.trim();
    if (!barcode) return;
    setSearchCode(barcode);
    setLoading(true);
    try {
      const { data } = await api.get(`/inventory/barcode-trace/${encodeURIComponent(barcode)}`);
      setResult(data);
    } catch {
      setResult({ barcode, found: false });
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Title level={4}><SearchOutlined /> 扫码稽查追溯</Title>

      <Card style={{ marginBottom: 24 }}>
        <Input.Search
          placeholder="扫码枪扫描 或 输入条码查询"
          enterButton="追溯"
          size="large"
          prefix={<BarcodeOutlined />}
          onSearch={doTrace}
          loading={loading}
          style={{ maxWidth: 600 }}
          autoFocus
        />
      </Card>

      {loading && <Spin size="large" style={{ display: 'block', textAlign: 'center', marginTop: 48 }} />}

      {!loading && result && !result.found && (
        <Empty description={`条码 "${searchCode}" 未在系统中找到`} style={{ marginTop: 48 }} />
      )}

      {!loading && result?.found && (
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
          {/* 基本信息 */}
          <Card title="商品信息" style={{ flex: 1, minWidth: 350 }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="条码">{result.barcode}</Descriptions.Item>
              <Descriptions.Item label="类型">{result.barcode_type === 'case' ? '箱码' : '瓶码'}</Descriptions.Item>
              <Descriptions.Item label="商品">{result.product_name ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="批次">{result.batch_no ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="当前仓库">{result.warehouse_name ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={statusColor[result.status ?? ''] ?? 'default'}>{result.status}</Tag>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          {/* 流转轨迹 */}
          <Card title="流转轨迹" style={{ flex: 1, minWidth: 350 }}>
            <Timeline
              items={[
                {
                  color: 'green',
                  children: (
                    <>
                      <Text strong>入库</Text>
                      <br />
                      <Text type="secondary">流水号：{result.stock_in_flow_no ?? '-'}</Text>
                      <br />
                      <Text type="secondary">时间：{result.stock_in_date ?? '-'}</Text>
                    </>
                  ),
                },
                ...(result.stock_out_flow_no ? [{
                  color: 'blue' as const,
                  children: (
                    <>
                      <Text strong>出库</Text>
                      <br />
                      <Text type="secondary">流水号：{result.stock_out_flow_no}</Text>
                    </>
                  ),
                }] : []),
                ...(result.order_no ? [{
                  color: 'purple' as const,
                  children: (
                    <>
                      <Text strong>销售订单</Text>
                      <br />
                      <Text>订单号：{result.order_no}</Text>
                      <br />
                      <Text>客户：<strong>{result.customer_name ?? '-'}</strong></Text>
                      <br />
                      <Text>业务员：{result.salesman_name ?? '-'}</Text>
                    </>
                  ),
                }] : []),
                ...(result.scheme_no ? [{
                  color: 'gold' as const,
                  children: (
                    <>
                      <Text strong>关联政策</Text>
                      <br />
                      <Text>方案号：{result.scheme_no}</Text>
                      <br />
                      <Text>政策状态：<Tag>{result.policy_status}</Tag></Text>
                    </>
                  ),
                }] : []),
              ]}
            />
            {!result.stock_out_flow_no && (
              <Text type="warning">该商品尚未出库，仍在仓库中</Text>
            )}
          </Card>
        </div>
      )}
    </>
  );
}

export default BarcodTracePage;
