import { useState } from 'react';
import { Table, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';

const { Title } = Typography;

interface UsageRecord {
  id: string;
  benefit_item_type: string;
  usage_scene: string | null;
  planned_amount: number;
  actual_amount: number;
  reimbursement_amount: number;
  execution_status: string;
  claim_status: string;
  created_at: string;
}

const columns: ColumnsType<UsageRecord> = [
  { title: '权益类型', dataIndex: 'benefit_item_type', width: 120 },
  { title: '使用场景', dataIndex: 'usage_scene', width: 200, ellipsis: true },
  { title: '预算金额', dataIndex: 'planned_amount', width: 100, align: 'right', render: (v: number) => `¥${Number(v).toFixed(2)}` },
  { title: '实际金额', dataIndex: 'actual_amount', width: 100, align: 'right', render: (v: number) => `¥${Number(v).toFixed(2)}` },
  { title: '可申报金额', dataIndex: 'reimbursement_amount', width: 110, align: 'right', render: (v: number) => `¥${Number(v).toFixed(2)}` },
  { title: '执行状态', dataIndex: 'execution_status', width: 100, render: (s: string) => <Tag color={{ pending: 'default', in_progress: 'blue', completed: 'green' }[s] || 'default'}>{s}</Tag> },
  { title: '申报状态', dataIndex: 'claim_status', width: 100, render: (s: string) => <Tag color={{ unclaimed: 'default', partially_claimed: 'orange', fully_claimed: 'green' }[s] || 'default'}>{s}</Tag> },
  { title: '创建时间', dataIndex: 'created_at', width: 170, render: (v: string) => v ? new Date(v).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '-' },
];

function UsageRecordList() {
  const { brandId, params } = useBrandFilter();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data: listResp, isLoading } = useQuery<{ items: UsageRecord[]; total: number }>({
    queryKey: ['usage-records', brandId, page, pageSize],
    queryFn: async () => { const { data } = await api.get('/policies/usage-records', { params: { ...params, skip: (page - 1) * pageSize, limit: pageSize } }); return data; },
  });
  const data = listResp?.items ?? [];
  const total = listResp?.total ?? 0;

  return (
    <>
      <Title level={4}>执行记录</Title>
      <Table<UsageRecord> columns={columns} dataSource={data} rowKey="id" loading={isLoading} pagination={{ current: page, pageSize, total, showTotal: (t) => '共 ' + t + ' 条', showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} />
    </>
  );
}

export default UsageRecordList;