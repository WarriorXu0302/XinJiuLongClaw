import { useQuery } from '@tanstack/react-query';
import { Button, Space, Table, Tag, Typography } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import api from '../../api/client';
import { useBrandFilter } from '../../stores/useBrandFilter';
import { exportExcel } from '../../utils/exportExcel';

const { Title } = Typography;

interface Receivable {
  id: string;
  receivable_no: string;
  customer_id: string;
  customer?: { name: string };
  order_id?: string;
  amount: number;
  paid_amount: number;
  due_date?: string;
  status: string;
  created_at: string;
}

const statusColor: Record<string, string> = {
  unpaid: 'red',
  partial: 'orange',
  paid: 'green',
};
const statusLabel: Record<string, string> = {
  unpaid: '未收款',
  partial: '部分收款',
  paid: '已收清',
};

const columns: ColumnsType<Receivable> = [
  { title: '应收编号', dataIndex: 'receivable_no', key: 'receivable_no', width: 180 },
  { title: '客户', key: 'customer', width: 120, render: (_: unknown, r: Receivable) => r.customer?.name ?? r.customer_id?.slice(0, 8) },
  { title: '应收金额', dataIndex: 'amount', key: 'amount', width: 110, align: 'right', render: (v: number) => `¥${Number(v).toFixed(2)}` },
  { title: '已收金额', dataIndex: 'paid_amount', key: 'paid_amount', width: 110, align: 'right', render: (v: number) => `¥${Number(v).toFixed(2)}` },
  { title: '欠款', key: 'remaining', width: 110, align: 'right', render: (_: unknown, r: Receivable) => `¥${(Number(r.amount) - Number(r.paid_amount)).toFixed(2)}` },
  { title: '到期日', dataIndex: 'due_date', key: 'due_date', width: 110 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (v: string) => <Tag color={statusColor[v] ?? 'default'}>{statusLabel[v] ?? v}</Tag> },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
];

function ReceivableList() {
  const { brandId, params } = useBrandFilter();

  const { data, isLoading } = useQuery<Receivable[]>({
    queryKey: ['receivables', brandId],
    queryFn: () => api.get('/receivables', { params }).then((r) => r.data),
  });

  const handleExport = () => {
    const rows = (data ?? []).map(r => ({
      '应收编号': r.receivable_no,
      '客户': r.customer?.name ?? '-',
      '应收金额': Number(r.amount),
      '已收金额': Number(r.paid_amount),
      '欠款': Number(r.amount) - Number(r.paid_amount),
      '到期日': r.due_date ?? '',
      '状态': statusLabel[r.status] ?? r.status,
      '创建时间': new Date(r.created_at).toLocaleString('zh-CN'),
    }));
    const amt = rows.reduce((s, x) => s + x['应收金额'], 0);
    const paid = rows.reduce((s, x) => s + x['已收金额'], 0);
    exportExcel('应收账款', '应收', rows, [
      { wch: 22 }, { wch: 16 }, { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 10 }, { wch: 18 },
    ], {
      '应收编号': '合计', '客户': '', '应收金额': amt, '已收金额': paid,
      '欠款': amt - paid, '到期日': '', '状态': '', '创建时间': '',
    } as any);
  };

  return (
    <>
      <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 12 }}>
        <Title level={4} style={{ margin: 0 }}>应收账款</Title>
        <Button icon={<DownloadOutlined />} onClick={handleExport}>导出 Excel</Button>
      </Space>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={data ?? []}
        loading={isLoading}
        size="middle"
        pagination={{ pageSize: 20 }}
        scroll={{ x: 1000 }}
      />
    </>
  );
}

export default ReceivableList;
