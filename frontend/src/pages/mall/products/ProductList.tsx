/**
 * 商城商品列表
 *
 * 筛选：keyword / category / brand / status / source
 * 操作：新建（纯商城或 ERP 导入）/ 编辑（抽屉含 SKU 管理）/ 上架-下架 / 删除（仅 draft+未售过）
 */
import { useState } from 'react';
import {
  Button, Image, Input, message, Modal, Popconfirm, Select, Space, Table, Tabs, Tag, Tooltip, Typography,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, DeleteOutlined, EditOutlined, PlusOutlined, ImportOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';
import ProductEditDrawer from './ProductEdit';

const { Title } = Typography;

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  draft: { text: '草稿', color: 'default' },
  on_sale: { text: '在售', color: 'green' },
  off_sale: { text: '下架', color: 'orange' },
};

interface Product {
  id: number;
  name: string;
  brief?: string;
  main_image?: string;
  status: string;
  category_id?: number;
  category_name?: string;
  brand_id?: string;
  brand_name?: string;
  source_product_id?: string;
  is_pure: boolean;
  min_price?: string;
  max_price?: string;
  total_sales: number;
  sku_count: number;
  created_at: string;
}

export default function MallProductList() {
  const queryClient = useQueryClient();
  const [statusTab, setStatusTab] = useState('all');
  const [keyword, setKeyword] = useState('');
  const [categoryId, setCategoryId] = useState<number | undefined>();
  const [brandId, setBrandId] = useState<string | undefined>();
  const [source, setSource] = useState<string | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [editId, setEditId] = useState<number | null>(null);
  const [createMode, setCreateMode] = useState<null | 'pure' | 'erp_import'>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['mall-admin-products', statusTab, keyword, categoryId, brandId, source, page, pageSize],
    queryFn: () => api.get('/mall/admin/products', {
      params: {
        status: statusTab === 'all' ? undefined : statusTab,
        keyword: keyword || undefined,
        category_id: categoryId,
        brand_id: brandId,
        source,
        skip: (page - 1) * pageSize,
        limit: pageSize,
      },
    }).then(r => r.data),
  });
  const rows: Product[] = data?.records || [];
  const total: number = data?.total || 0;

  const { data: catData } = useQuery({
    queryKey: ['mall-admin-categories'],
    queryFn: () => api.get('/mall/admin/categories').then(r => r.data),
  });
  const categories = catData?.flat || [];

  const { data: brandData } = useQuery({
    queryKey: ['mall-admin-brands'],
    queryFn: () => api.get('/mall/admin/products/_helpers/brands').then(r => r.data),
  });
  const brands = brandData?.records || [];

  const statusMut = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      api.post(`/mall/admin/products/${id}/status`, { status }),
    onSuccess: (_, vars) => {
      message.success(vars.status === 'on_sale' ? '已上架' : '已下架');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-products'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.delete(`/mall/admin/products/${id}`),
    onSuccess: () => {
      message.success('已删除');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-products'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '删除失败'),
  });

  const columns: ColumnsType<Product> = [
    {
      title: '图 / 名称',
      key: 'nameImg',
      width: 320,
      fixed: 'left' as const,
      render: (_, r) => (
        <Space>
          {r.main_image ? (
            <Image src={r.main_image} width={48} height={48} style={{ objectFit: 'cover', borderRadius: 4 }} />
          ) : (
            <div style={{ width: 48, height: 48, background: '#f5f5f5', borderRadius: 4 }} />
          )}
          <div>
            <a onClick={() => setEditId(r.id)} style={{ fontWeight: 500 }}>{r.name}</a>
            <div style={{ color: '#999', fontSize: 12 }}>
              {r.brief || <span style={{ color: '#ccc' }}>无简介</span>}
            </div>
          </div>
        </Space>
      ),
    },
    {
      title: '分类',
      dataIndex: 'category_name',
      width: 100,
      render: (v) => v || '-',
    },
    {
      title: '品牌',
      dataIndex: 'brand_name',
      width: 100,
      render: (v) => v ? <Tag color="blue">{v}</Tag> : '-',
    },
    {
      title: '来源',
      dataIndex: 'is_pure',
      width: 90,
      render: (v: boolean) => v ? <Tag color="purple">纯商城</Tag> : <Tag color="cyan">ERP 导入</Tag>,
    },
    {
      title: 'SKU',
      dataIndex: 'sku_count',
      width: 70,
      render: (v: number) => v > 0 ? <Tag>{v} 个</Tag> : <Tag color="red">0</Tag>,
    },
    {
      title: '价格区间',
      key: 'price_range',
      width: 140,
      align: 'right' as const,
      render: (_, r) => r.min_price ? (
        r.min_price === r.max_price
          ? `¥${Number(r.min_price).toLocaleString()}`
          : `¥${Number(r.min_price).toLocaleString()} - ¥${Number(r.max_price).toLocaleString()}`
      ) : <span style={{ color: '#ccc' }}>无 SKU</span>,
    },
    {
      title: '销量',
      dataIndex: 'total_sales',
      width: 80,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v) => {
        const m = STATUS_LABEL[v];
        return m ? <Tag color={m.color}>{m.text}</Tag> : v;
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 130,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD'),
    },
    {
      title: '操作',
      key: 'act',
      width: 220,
      fixed: 'right' as const,
      render: (_, r) => (
        <Space>
          <Tooltip title="编辑商品 & SKU">
            <Button size="small" icon={<EditOutlined />} onClick={() => setEditId(r.id)} />
          </Tooltip>
          {r.status === 'on_sale' ? (
            <Button size="small" icon={<CloseCircleOutlined />}
              onClick={() => Modal.confirm({
                title: `下架 ${r.name}？`,
                content: '下架后客户端将不再显示，已下单未出库的订单不影响',
                onOk: () => statusMut.mutateAsync({ id: r.id, status: 'off_sale' }),
              })}
            >下架</Button>
          ) : (
            <Button size="small" type="primary" icon={<CheckCircleOutlined />}
              disabled={r.sku_count === 0}
              onClick={() => statusMut.mutateAsync({ id: r.id, status: 'on_sale' })}
            >上架</Button>
          )}
          {r.status !== 'on_sale' && r.total_sales === 0 && (
            <Popconfirm
              title={`删除 ${r.name}？`}
              description="仅限草稿/下架且无销售记录的商品"
              onConfirm={() => deleteMut.mutateAsync(r.id)}
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  const TABS = [
    { key: 'all', label: '全部' },
    { key: 'on_sale', label: '在售' },
    { key: 'draft', label: '草稿' },
    { key: 'off_sale', label: '已下架' },
  ];

  return (
    <div>
      <Title level={4}>商城商品</Title>

      <Tabs
        activeKey={statusTab}
        onChange={(k) => { setStatusTab(k); setPage(1); }}
        items={TABS.map(t => ({ key: t.key, label: t.label }))}
      />

      <Space style={{ marginBottom: 16, flexWrap: 'wrap' }}>
        <Input.Search
          placeholder="商品名 / 简介"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          onSearch={() => setPage(1)}
          allowClear
          style={{ width: 200 }}
        />
        <Select
          placeholder="分类"
          value={categoryId}
          onChange={(v) => { setCategoryId(v); setPage(1); }}
          allowClear
          style={{ width: 160 }}
          options={categories.map((c: any) => ({
            value: c.id,
            label: c.parent_id ? `└ ${c.name}` : c.name,
          }))}
        />
        <Select
          placeholder="品牌"
          value={brandId}
          onChange={(v) => { setBrandId(v); setPage(1); }}
          allowClear
          style={{ width: 140 }}
          options={brands.map((b: any) => ({ value: b.id, label: b.name }))}
        />
        <Select
          placeholder="来源"
          value={source}
          onChange={(v) => { setSource(v); setPage(1); }}
          allowClear
          style={{ width: 120 }}
          options={[
            { value: 'pure', label: '纯商城' },
            { value: 'erp', label: 'ERP 导入' },
          ]}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateMode('pure')}>
          新建商品
        </Button>
        <Button icon={<ImportOutlined />} onClick={() => setCreateMode('erp_import')}>
          从 ERP 导入
        </Button>
      </Space>

      <Table
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={isLoading}
        size="middle"
        scroll={{ x: 1500 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showTotal: t => `共 ${t} 个商品`,
          onChange: (p, s) => { setPage(p); setPageSize(s || 20); },
          pageSizeOptions: ['20', '50', '100'],
          showSizeChanger: true,
        }}
      />

      {/* 编辑抽屉（含 SKU） */}
      {(editId || createMode) && (
        <ProductEditDrawer
          productId={editId}
          createMode={createMode}
          open={!!(editId || createMode)}
          onClose={() => { setEditId(null); setCreateMode(null); }}
          categories={categories}
          brands={brands}
        />
      )}
    </div>
  );
}
