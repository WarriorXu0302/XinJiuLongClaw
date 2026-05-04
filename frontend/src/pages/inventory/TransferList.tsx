/**
 * 仓库调拨单列表
 *
 * 状态过滤 + 详情抽屉。创建入口走独立页 /inventory/transfers/new。
 *
 * 业务规则（品牌主仓不参与调拨等）在创建页做前置校验。
 */
import { useState } from 'react';
import {
  Button, Descriptions, Drawer, Empty, message, Modal, Space, Table, Tabs, Tag, Typography,
} from 'antd';
import { PlusOutlined, EyeOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import api from '../../api/client';

const { Title } = Typography;

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  pending_scan: { text: '待提交', color: 'default' },
  pending_approval: { text: '待审批', color: 'orange' },
  approved: { text: '待执行', color: 'blue' },
  executed: { text: '已执行', color: 'green' },
  rejected: { text: '已驳回', color: 'red' },
  cancelled: { text: '已取消', color: 'default' },
};

interface TransferItem {
  id: string;
  barcode: string;
  product_ref: string;
  sku_ref?: string;
  cost_price_snapshot?: string;
  batch_no_snapshot?: string;
}

interface Transfer {
  id: string;
  transfer_no: string;
  source_side: 'erp' | 'mall';
  source_warehouse_id: string;
  source_warehouse_name?: string;
  dest_side: 'erp' | 'mall';
  dest_warehouse_id: string;
  dest_warehouse_name?: string;
  status: string;
  requires_approval: boolean;
  initiator_employee_id: string;
  submitted_at?: string;
  approved_at?: string;
  executed_at?: string;
  rejection_reason?: string;
  reason?: string;
  total_bottles: number;
  total_cost?: string;
  created_at: string;
  items?: TransferItem[];
}

export default function TransferList() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [statusTab, setStatusTab] = useState<string>('all');
  const [detailId, setDetailId] = useState<string | null>(null);

  const { data, isLoading } = useQuery<{ records: Transfer[]; total: number }>({
    queryKey: ['wh-transfers', statusTab],
    queryFn: () => api.get('/transfers', {
      params: { status: statusTab === 'all' ? undefined : statusTab, limit: 100 },
    }).then(r => r.data),
  });
  const rows = data?.records || [];

  const { data: detailData } = useQuery<Transfer>({
    queryKey: ['wh-transfer-detail', detailId],
    queryFn: () => api.get(`/transfers/${detailId}`).then(r => r.data),
    enabled: !!detailId,
  });

  const submitMut = useMutation({
    mutationFn: (id: string) => api.post(`/transfers/${id}/submit`),
    onSuccess: () => {
      message.success('已提交审批');
      queryClient.invalidateQueries({ queryKey: ['wh-transfers'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '提交失败'),
  });

  const executeMut = useMutation({
    mutationFn: (id: string) => api.post(`/transfers/${id}/execute`),
    onSuccess: () => {
      message.success('已执行，条码已过户');
      queryClient.invalidateQueries({ queryKey: ['wh-transfers'] });
      queryClient.invalidateQueries({ queryKey: ['wh-transfer-detail'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '执行失败'),
  });

  const cancelMut = useMutation({
    mutationFn: (id: string) => api.post(`/transfers/${id}/cancel`, {}),
    onSuccess: () => {
      message.success('已取消');
      queryClient.invalidateQueries({ queryKey: ['wh-transfers'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '取消失败'),
  });

  const columns: ColumnsType<Transfer> = [
    { title: '调拨单号', dataIndex: 'transfer_no', width: 210 },
    {
      title: '源仓', key: 'src', width: 180,
      render: (_, r) => (
        <>
          <Tag color={r.source_side === 'mall' ? 'gold' : 'blue'}>
            {r.source_side === 'mall' ? '商城' : 'ERP'}
          </Tag>
          {r.source_warehouse_name || r.source_warehouse_id.slice(0, 8)}
        </>
      ),
    },
    {
      title: '目标仓', key: 'dst', width: 180,
      render: (_, r) => (
        <>
          <Tag color={r.dest_side === 'mall' ? 'gold' : 'blue'}>
            {r.dest_side === 'mall' ? '商城' : 'ERP'}
          </Tag>
          {r.dest_warehouse_name || r.dest_warehouse_id.slice(0, 8)}
        </>
      ),
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => {
        const m = STATUS_LABEL[v];
        return m ? <Tag color={m.color}>{m.text}</Tag> : v;
      },
    },
    {
      title: '审批', dataIndex: 'requires_approval', width: 70,
      render: (v: boolean) => v ? <Tag color="orange">要</Tag> : <Tag>免</Tag>,
    },
    { title: '瓶数', dataIndex: 'total_bottles', width: 70, align: 'right' as const },
    {
      title: '成本合计', dataIndex: 'total_cost', width: 110, align: 'right' as const,
      render: (v?: string) => v ? `¥${v}` : '-',
    },
    {
      title: '创建时间', dataIndex: 'created_at', width: 150,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作', key: 'act', width: 240,
      render: (_, r) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => setDetailId(r.id)}>详情</Button>
          {/* 免审：直接 execute；需审：submit → 审批中心 → execute */}
          {r.status === 'pending_scan' && r.requires_approval && (
            <Button size="small" type="primary" onClick={() => submitMut.mutate(r.id)}>提交审批</Button>
          )}
          {r.status === 'pending_scan' && !r.requires_approval && (
            <Button size="small" type="primary" icon={<ThunderboltOutlined />}
              onClick={() => Modal.confirm({
                title: `执行调拨 ${r.transfer_no}？`,
                content: `${r.total_bottles} 瓶条码将过户到目标仓`,
                onOk: () => executeMut.mutateAsync(r.id),
              })}
            >免审执行</Button>
          )}
          {r.status === 'approved' && (
            <Button size="small" type="primary" icon={<ThunderboltOutlined />}
              onClick={() => Modal.confirm({
                title: `执行调拨 ${r.transfer_no}？`,
                content: '审批已通过，执行后条码将过户',
                onOk: () => executeMut.mutateAsync(r.id),
              })}
            >执行</Button>
          )}
          {['pending_scan', 'pending_approval'].includes(r.status) && (
            <Button size="small" danger onClick={() => Modal.confirm({
              title: `取消调拨 ${r.transfer_no}？`,
              onOk: () => cancelMut.mutateAsync(r.id),
            })}>取消</Button>
          )}
        </Space>
      ),
    },
  ];

  const TABS = [
    { key: 'all', label: '全部' },
    { key: 'pending_scan', label: '待提交' },
    { key: 'pending_approval', label: '待审批' },
    { key: 'approved', label: '待执行' },
    { key: 'executed', label: '已执行' },
    { key: 'rejected', label: '已驳回' },
    { key: 'cancelled', label: '已取消' },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>仓库调拨</Title>
        <Button type="primary" icon={<PlusOutlined />}
          onClick={() => navigate('/inventory/transfers/new')}
        >
          新建调拨单
        </Button>
      </div>

      <Tabs
        activeKey={statusTab}
        onChange={(k) => setStatusTab(k)}
        items={TABS.map(t => ({ key: t.key, label: t.label }))}
      />

      {rows.length === 0 && !isLoading ? (
        <Empty description="暂无调拨单" />
      ) : (
        <Table
          columns={columns}
          dataSource={rows}
          rowKey="id"
          loading={isLoading}
          size="middle"
          scroll={{ x: 1400 }}
          pagination={{ pageSize: 20 }}
        />
      )}

      <Drawer
        title={detailData ? `调拨单 ${detailData.transfer_no}` : '调拨详情'}
        open={!!detailId}
        onClose={() => setDetailId(null)}
        size={720}
      >
        {detailData && (
          <>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="状态" span={2}>
                {STATUS_LABEL[detailData.status]
                  ? <Tag color={STATUS_LABEL[detailData.status].color}>{STATUS_LABEL[detailData.status].text}</Tag>
                  : detailData.status}
                <span style={{ marginLeft: 12, color: '#8c8c8c' }}>
                  {detailData.requires_approval ? '需审批' : '免审'}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="源仓">
                <Tag color={detailData.source_side === 'mall' ? 'gold' : 'blue'}>
                  {detailData.source_side === 'mall' ? '商城' : 'ERP'}
                </Tag>
                {detailData.source_warehouse_name}
              </Descriptions.Item>
              <Descriptions.Item label="目标仓">
                <Tag color={detailData.dest_side === 'mall' ? 'gold' : 'blue'}>
                  {detailData.dest_side === 'mall' ? '商城' : 'ERP'}
                </Tag>
                {detailData.dest_warehouse_name}
              </Descriptions.Item>
              <Descriptions.Item label="瓶数">{detailData.total_bottles}</Descriptions.Item>
              <Descriptions.Item label="成本合计">¥{detailData.total_cost || 0}</Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {dayjs(detailData.created_at).format('YYYY-MM-DD HH:mm:ss')}
              </Descriptions.Item>
              <Descriptions.Item label="提交时间">
                {detailData.submitted_at ? dayjs(detailData.submitted_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="审批时间">
                {detailData.approved_at ? dayjs(detailData.approved_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="执行时间">
                {detailData.executed_at ? dayjs(detailData.executed_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
              </Descriptions.Item>
              {detailData.reason && (
                <Descriptions.Item label="备注" span={2}>{detailData.reason}</Descriptions.Item>
              )}
              {detailData.rejection_reason && (
                <Descriptions.Item label="驳回原因" span={2}>
                  <span style={{ color: '#ff4d4f' }}>{detailData.rejection_reason}</span>
                </Descriptions.Item>
              )}
            </Descriptions>

            <div style={{ marginTop: 16 }}>
              <Typography.Text strong>明细（每瓶一行）</Typography.Text>
              <Table
                dataSource={detailData.items || []}
                rowKey="id"
                size="small"
                pagination={{ pageSize: 20, showSizeChanger: false }}
                columns={[
                  { title: '#', key: 'idx', width: 50, render: (_, __, i) => i + 1 },
                  { title: '条码', dataIndex: 'barcode', width: 260 },
                  { title: '批次', dataIndex: 'batch_no_snapshot', width: 120 },
                  {
                    title: '成本快照', dataIndex: 'cost_price_snapshot', width: 110, align: 'right' as const,
                    render: (v?: string) => v ? `¥${v}` : '-',
                  },
                ]}
              />
            </div>
          </>
        )}
      </Drawer>
    </div>
  );
}
