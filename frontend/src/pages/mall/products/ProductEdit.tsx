/**
 * 商品编辑抽屉（含 SKU 管理 Tab）
 *
 * 打开方式：
 *   createMode='pure'       新建纯商城商品
 *   createMode='erp_import' 从 ERP 导入
 *   productId=N             编辑现有商品
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Button, Card, Divider, Drawer, Form, Input, InputNumber, message, Modal, Popconfirm, Select, Space, Table, Tabs, Tag, Upload,
} from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../../../api/client';

const { TextArea } = Input;

interface Category { id: number; name: string; parent_id: number | null }
interface Brand { id: string; name: string }

// ────────────────────────────────────────────────────────────
// 图片上传组件（单张 or 多张）
// ────────────────────────────────────────────────────────────
interface ImageUploadProps {
  value?: string | string[];           // 单张是 string，多张是 string[]
  onChange?: (v: string | string[] | undefined) => void;
  multiple?: boolean;                   // 默认 false 单张
  maxCount?: number;                    // 多张上限，默认 9
}

function ImageUpload({ value, onChange, multiple = false, maxCount = 9 }: ImageUploadProps) {
  // normalize value → UploadFile[]
  const urls: string[] = multiple
    ? (Array.isArray(value) ? value : [])
    : (typeof value === 'string' && value ? [value] : []);
  const fileList: UploadFile[] = urls.map((url, i) => ({
    uid: `-${i}`, name: url.split('/').pop() || 'image', status: 'done', url,
  }));

  const handleChange = (newUrls: string[]) => {
    if (multiple) {
      onChange?.(newUrls);
    } else {
      onChange?.(newUrls[0] || undefined);
    }
  };

  return (
    <Upload
      listType="picture-card"
      accept=".jpg,.jpeg,.png,.webp"
      fileList={fileList}
      maxCount={multiple ? maxCount : 1}
      multiple={multiple}
      customRequest={async ({ file, onSuccess, onError }: any) => {
        const fd = new FormData();
        fd.append('file', file);
        try {
          const { data } = await api.post('/uploads', fd);
          handleChange([...urls, data.url]);
          onSuccess(data);
        } catch (e: any) {
          message.error(e?.response?.data?.detail || '上传失败');
          onError(e);
        }
      }}
      onRemove={(file) => {
        const removed = urls.filter(u => u !== file.url);
        handleChange(removed);
      }}
    >
      {urls.length >= (multiple ? maxCount : 1) ? null : (
        <div>
          <PlusOutlined />
          <div style={{ marginTop: 4, fontSize: 12 }}>
            {multiple ? `上传（${urls.length}/${maxCount}）` : '上传'}
          </div>
        </div>
      )}
    </Upload>
  );
}

interface Props {
  productId: number | null;
  createMode: null | 'pure' | 'erp_import';
  open: boolean;
  onClose: () => void;
  categories: Category[];
  brands: Brand[];
}

export default function ProductEditDrawer({ productId, createMode, open, onClose, categories, brands }: Props) {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [tab, setTab] = useState<'basic' | 'sku'>('basic');
  const [createdProductId, setCreatedProductId] = useState<number | null>(null);

  const effectiveId = productId ?? createdProductId;

  const { data: prod, isLoading: prodLoading } = useQuery({
    queryKey: ['mall-admin-product-detail', effectiveId],
    queryFn: () => api.get(`/mall/admin/products/${effectiveId}`).then(r => r.data),
    enabled: !!effectiveId,
  });

  const createPureMut = useMutation({
    mutationFn: (body: any) => api.post('/mall/admin/products', body).then(r => r.data),
    onSuccess: (res) => {
      message.success('商品已创建（草稿）');
      setCreatedProductId(res.id);
      setTab('sku');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-products'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '创建失败'),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: any) => api.put(`/mall/admin/products/${id}`, body),
    onSuccess: () => {
      message.success('已保存');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-products'] });
      queryClient.invalidateQueries({ queryKey: ['mall-admin-product-detail'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '保存失败'),
  });

  useEffect(() => {
    if (!open) {
      form.resetFields();
      setTab('basic');
      setCreatedProductId(null);
      return;
    }
    if (prod) {
      form.setFieldsValue({
        name: prod.name,
        brief: prod.brief,
        category_id: prod.category_id,
        brand_id: prod.brand_id,
        main_image: prod.main_image,
        images: prod.images || [],
        detail_html: prod.detail_html,
      });
    }
  }, [open, prod, form]);

  const handleSave = () => {
    form.validateFields().then(values => {
      if (effectiveId) {
        updateMut.mutate({ id: effectiveId, body: values });
      } else {
        createPureMut.mutate({ ...values, status: 'draft' });
      }
    });
  };

  const title = useMemo(() => {
    if (productId) return `编辑商品 · ${prod?.name || ''}`;
    if (createMode === 'erp_import') return '从 ERP 导入商品';
    return '新建纯商城商品';
  }, [productId, createMode, prod]);

  return (
    <Drawer
      title={title}
      open={open}
      onClose={onClose}
      width={900}
      extra={
        effectiveId && (
          <Tag color={prod?.is_pure ? 'purple' : 'cyan'}>
            {prod?.is_pure ? '纯商城' : 'ERP 导入'}
          </Tag>
        )
      }
    >
      {createMode === 'erp_import' && !createdProductId ? (
        <ErpImportPanel
          brands={brands}
          categories={categories}
          onCreated={(id: number) => {
            setCreatedProductId(id);
            setTab('basic');
            queryClient.invalidateQueries({ queryKey: ['mall-admin-products'] });
          }}
        />
      ) : (
        <Tabs
          activeKey={tab}
          onChange={(k) => setTab(k as any)}
          items={[
            {
              key: 'basic',
              label: '基本信息',
              children: (
                <Form form={form} layout="vertical" disabled={prodLoading}>
                  <Form.Item name="name" label="商品名称"
                    rules={[{ required: true, max: 200, message: '必填，≤200 字符' }]}
                  >
                    <Input placeholder="例：飞天茅台 53度 500ml" />
                  </Form.Item>
                  <Form.Item name="brief" label="简介（列表页副标题）">
                    <Input placeholder="例：严选正品 · 6 瓶/箱" maxLength={500} showCount />
                  </Form.Item>
                  <Space.Compact block>
                    <Form.Item name="category_id" label="分类" style={{ flex: 1, marginRight: 12 }}>
                      <Select
                        allowClear
                        placeholder="选择分类"
                        options={categories.map(c => ({
                          value: c.id,
                          label: c.parent_id ? `└ ${c.name}` : c.name,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item name="brand_id" label="品牌" style={{ flex: 1 }}>
                      <Select
                        allowClear
                        placeholder="选择品牌"
                        options={brands.map(b => ({ value: b.id, label: b.name }))}
                      />
                    </Form.Item>
                  </Space.Compact>
                  <Form.Item name="main_image" label="主图"
                    extra="列表页 / 详情页 banner 第一张，建议 1:1 正方形，≤2MB"
                  >
                    <ImageUpload />
                  </Form.Item>
                  <Form.Item name="images" label="详情图（最多 9 张）"
                    extra="小程序详情页 swiper 轮播"
                  >
                    <ImageUpload multiple maxCount={9} />
                  </Form.Item>
                  <Form.Item name="detail_html" label="详情（HTML 或纯文字）"
                    extra="小程序详情页商品说明，支持 HTML"
                  >
                    <TextArea rows={6} placeholder="例：产地 / 原料 / 口感 / 饮用建议..." />
                  </Form.Item>

                  <Divider />
                  <Space>
                    <Button type="primary" onClick={handleSave}
                      loading={createPureMut.isPending || updateMut.isPending}
                    >
                      {effectiveId ? '保存修改' : '创建草稿'}
                    </Button>
                    {!effectiveId && (
                      <span style={{ color: '#999', fontSize: 12 }}>
                        创建后将自动进入 SKU 管理
                      </span>
                    )}
                  </Space>
                </Form>
              ),
            },
            {
              key: 'sku',
              label: `SKU 管理 ${prod?.skus?.length ? `(${prod.skus.length})` : ''}`,
              disabled: !effectiveId,
              children: effectiveId ? <SkuPanel productId={effectiveId} product={prod} /> : null,
            },
          ]}
        />
      )}
    </Drawer>
  );
}

// ────────────────────────────────────────────────────────────
// ERP 导入 Panel
// ────────────────────────────────────────────────────────────
function ErpImportPanel({ brands, categories, onCreated }: any) {
  const [keyword, setKeyword] = useState('');
  const [selected, setSelected] = useState<any>(null);
  const [form] = Form.useForm();

  const { data } = useQuery({
    queryKey: ['erp-products-bindable', keyword],
    queryFn: () => api.get('/mall/admin/products/_helpers/erp-products', {
      params: { keyword: keyword || undefined },
    }).then(r => r.data),
  });
  const list = data?.records || [];

  const createMut = useMutation({
    mutationFn: (body: any) => api.post('/mall/admin/products', body).then(r => r.data),
    onSuccess: (res) => {
      message.success('已从 ERP 导入');
      onCreated(res.id);
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '导入失败'),
  });

  return (
    <div>
      <Input.Search
        placeholder="搜 ERP 商品名"
        value={keyword}
        onChange={e => setKeyword(e.target.value)}
        allowClear
        style={{ width: 300, marginBottom: 12 }}
      />
      <Card size="small" style={{ marginBottom: 12 }}>
        {list.length === 0 ? (
          <div style={{ color: '#999' }}>无可导入商品（全部已导入 or 无匹配）</div>
        ) : (
          <Table
            size="small"
            dataSource={list}
            rowKey="id"
            pagination={false}
            rowSelection={{
              type: 'radio',
              selectedRowKeys: selected ? [selected.id] : [],
              onChange: (_: any, rows: any[]) => {
                const r: any = rows[0];
                setSelected(r);
                if (r) {
                  form.setFieldsValue({
                    name: r.name,
                    brand_id: r.brand_id,
                    source_product_id: r.id,
                  });
                }
              },
            }}
            columns={[
              { title: 'ERP 商品', dataIndex: 'name' },
              {
                title: '品牌',
                dataIndex: 'brand_id',
                width: 120,
                render: (v: string) => brands.find((b: any) => b.id === v)?.name || '-',
              },
              {
                title: '指导价',
                dataIndex: 'guide_price',
                width: 100,
                align: 'right' as const,
                render: (v: string) => v ? `¥${Number(v).toLocaleString()}` : '-',
              },
            ]}
          />
        )}
      </Card>

      {selected && (
        <Card size="small" title="确认导入信息（可修改）">
          <Form form={form} layout="vertical">
            <Form.Item name="source_product_id" hidden>
              <Input />
            </Form.Item>
            <Form.Item name="name" label="商品名（默认取 ERP 名）"
              rules={[{ required: true, max: 200 }]}
            >
              <Input />
            </Form.Item>
            <Form.Item name="brief" label="简介">
              <Input placeholder="可选" />
            </Form.Item>
            <Space.Compact block>
              <Form.Item name="category_id" label="分类" style={{ flex: 1, marginRight: 12 }}>
                <Select
                  allowClear
                  placeholder="选择分类"
                  options={categories.map((c: any) => ({
                    value: c.id,
                    label: c.parent_id ? `└ ${c.name}` : c.name,
                  }))}
                />
              </Form.Item>
              <Form.Item name="brand_id" label="品牌" style={{ flex: 1 }}>
                <Select
                  options={brands.map((b: any) => ({ value: b.id, label: b.name }))}
                />
              </Form.Item>
            </Space.Compact>
            <Form.Item name="main_image" label="主图">
              <ImageUpload />
            </Form.Item>
            <Button type="primary"
              onClick={() => form.validateFields().then(v => createMut.mutate({ ...v, status: 'draft' }))}
              loading={createMut.isPending}
            >
              导入（创建为草稿）
            </Button>
            <span style={{ color: '#999', fontSize: 12, marginLeft: 12 }}>
              导入后需创建 SKU 并上架
            </span>
          </Form>
        </Card>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────
// SKU Panel
// ────────────────────────────────────────────────────────────
function SkuPanel({ productId, product }: any) {
  const queryClient = useQueryClient();
  const [skuModal, setSkuModal] = useState<{ mode: 'create' | 'edit'; row?: any } | null>(null);
  const [skuForm] = Form.useForm();

  const skus: any[] = product?.skus || [];
  const isPure = product?.is_pure;

  const createMut = useMutation({
    mutationFn: (body: any) => api.post('/mall/admin/skus', body),
    onSuccess: () => {
      message.success('SKU 已创建');
      setSkuModal(null);
      skuForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['mall-admin-product-detail', productId] });
      queryClient.invalidateQueries({ queryKey: ['mall-admin-products'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: any) => api.put(`/mall/admin/skus/${id}`, body),
    onSuccess: () => {
      message.success('已保存');
      setSkuModal(null);
      skuForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['mall-admin-product-detail', productId] });
      queryClient.invalidateQueries({ queryKey: ['mall-admin-products'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.delete(`/mall/admin/skus/${id}`),
    onSuccess: () => {
      message.success('已删除');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-product-detail', productId] });
      queryClient.invalidateQueries({ queryKey: ['mall-admin-products'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '删除失败'),
  });

  const openCreate = () => {
    skuForm.resetFields();
    setSkuModal({ mode: 'create' });
  };

  const openEdit = (row: any) => {
    setSkuModal({ mode: 'edit', row });
    skuForm.setFieldsValue({
      spec: row.spec,
      price: row.price,
      cost_price: row.cost_price,
      image: row.image,
      barcode: row.barcode,
      status: row.status,
    });
  };

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建 SKU
        </Button>
        {isPure && (
          <span style={{ color: '#999', fontSize: 12 }}>
            纯商城商品 → SKU 必填成本价（利润台账依赖）
          </span>
        )}
      </Space>

      <Table
        dataSource={skus}
        rowKey="id"
        size="small"
        pagination={false}
        columns={[
          { title: '规格', dataIndex: 'spec', render: (v) => v || <span style={{ color: '#ccc' }}>无规格</span> },
          {
            title: '售价',
            dataIndex: 'price',
            width: 110,
            align: 'right' as const,
            render: (v: string) => <strong>¥{Number(v).toLocaleString()}</strong>,
          },
          {
            title: '成本',
            dataIndex: 'cost_price',
            width: 110,
            align: 'right' as const,
            render: (v?: string) => v ? `¥${Number(v).toLocaleString()}` : (
              isPure
                ? <Tag color="red">未填</Tag>
                : <span style={{ color: '#999' }}>ERP</span>
            ),
          },
          {
            title: '毛利',
            key: 'margin',
            width: 90,
            align: 'right' as const,
            render: (_, r: any) => {
              if (!r.cost_price) return '-';
              const p = Number(r.price);
              const c = Number(r.cost_price);
              if (p <= 0) return '-';
              const rate = ((p - c) / p * 100).toFixed(1);
              return <Tag color={Number(rate) >= 20 ? 'green' : 'orange'}>{rate}%</Tag>;
            },
          },
          { title: '条码', dataIndex: 'barcode', render: (v) => v || '-' },
          {
            title: '状态',
            dataIndex: 'status',
            width: 80,
            render: (v: string) => v === 'active' ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>,
          },
          {
            title: '操作',
            key: 'act',
            width: 140,
            render: (_: any, r: any) => (
              <Space>
                <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
                <Popconfirm
                  title={`删除 SKU "${r.spec}"？`}
                  description="仅限无库存且未售过的 SKU；否则请切为停用"
                  onConfirm={() => deleteMut.mutateAsync(r.id)}
                >
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title={skuModal?.mode === 'edit' ? '编辑 SKU' : '新建 SKU'}
        open={!!skuModal}
        onCancel={() => { setSkuModal(null); skuForm.resetFields(); }}
        onOk={() => {
          skuForm.validateFields().then((v: any) => {
            if (skuModal?.mode === 'edit') {
              updateMut.mutate({ id: skuModal.row.id, body: v });
            } else {
              createMut.mutate({ product_id: productId, ...v });
            }
          });
        }}
        confirmLoading={createMut.isPending || updateMut.isPending}
      >
        <Form form={skuForm} layout="vertical" preserve={false}>
          <Form.Item name="spec" label="规格" rules={[{ max: 200 }]}>
            <Input placeholder="例：单瓶 / 整箱 6 瓶" />
          </Form.Item>
          <Space.Compact block>
            <Form.Item name="price" label="售价（¥）" style={{ flex: 1, marginRight: 12 }}
              rules={[{ required: true, type: 'number', min: 0, message: '必填' }]}
            >
              <InputNumber min={0} precision={2} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="cost_price" label={`成本（¥）${isPure ? ' *' : ''}`} style={{ flex: 1 }}
              rules={isPure ? [{ required: true, message: '纯商城 SKU 必填成本' }] : []}
              extra={!isPure && 'ERP 商品成本从采购价自动溯源'}
            >
              <InputNumber min={0} precision={2} style={{ width: '100%' }} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="barcode" label="条码（可选）">
            <Input placeholder="扫码出库用；全局唯一" />
          </Form.Item>
          <Form.Item name="image" label="SKU 图（可选，留空用商品主图）">
            <ImageUpload />
          </Form.Item>
          {skuModal?.mode === 'edit' && (
            <Form.Item name="status" label="状态">
              <Select options={[
                { value: 'active', label: '启用' },
                { value: 'inactive', label: '停用' },
              ]} />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
}
