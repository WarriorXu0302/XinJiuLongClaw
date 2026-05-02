/**
 * 分类树 + 首页标签管理
 *
 * 左侧：分类树（支持多级 CRUD）
 * 右侧：标签列表 + 关联商品多选
 */
import { useState } from 'react';
import {
  Button, Card, Form, Input, InputNumber, message, Modal, Select, Space, Table, Tag, Tooltip, Tree, Typography,
} from 'antd';
import {
  DeleteOutlined, EditOutlined, PlusOutlined, LinkOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { DataNode } from 'antd/es/tree';
import api from '../../../api/client';

const { Title } = Typography;

interface Category {
  id: number;
  parent_id: number | null;
  name: string;
  icon?: string;
  sort_order: number;
  status: string;
  product_count?: number;
  children?: Category[];
}

interface TagItem {
  id: number;
  title: string;
  icon?: string;
  sort_order: number;
  status: string;
  product_count: number;
}

interface Product {
  id: number;
  name: string;
  brief?: string;
  status: string;
  main_image?: string;
}

export default function MallCategoryTree() {
  const queryClient = useQueryClient();
  const [catModalOpen, setCatModalOpen] = useState(false);
  const [catEditTarget, setCatEditTarget] = useState<Category | null>(null);
  const [catParentId, setCatParentId] = useState<number | null>(null);
  const [catForm] = Form.useForm();

  const [tagModalOpen, setTagModalOpen] = useState(false);
  const [tagEditTarget, setTagEditTarget] = useState<TagItem | null>(null);
  const [tagForm] = Form.useForm();

  const [linkTag, setLinkTag] = useState<TagItem | null>(null);
  const [linkedIds, setLinkedIds] = useState<number[]>([]);

  // ── Categories ──
  const { data: catData, isLoading: catLoading } = useQuery({
    queryKey: ['mall-admin-categories'],
    queryFn: () => api.get('/mall/admin/categories').then(r => r.data),
  });
  const catTree: Category[] = catData?.records || [];
  const catFlat: Category[] = catData?.flat || [];

  const catCreateMut = useMutation({
    mutationFn: (body: any) => api.post('/mall/admin/categories', body),
    onSuccess: () => {
      message.success('已创建');
      setCatModalOpen(false);
      catForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['mall-admin-categories'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });
  const catUpdateMut = useMutation({
    mutationFn: ({ id, body }: any) => api.put(`/mall/admin/categories/${id}`, body),
    onSuccess: () => {
      message.success('已更新');
      setCatModalOpen(false);
      setCatEditTarget(null);
      queryClient.invalidateQueries({ queryKey: ['mall-admin-categories'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });
  const catDeleteMut = useMutation({
    mutationFn: (id: number) => api.delete(`/mall/admin/categories/${id}`),
    onSuccess: () => {
      message.success('已删除');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-categories'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '删除失败'),
  });

  // ── Tags ──
  const { data: tagData } = useQuery({
    queryKey: ['mall-admin-tags'],
    queryFn: () => api.get('/mall/admin/tags').then(r => r.data),
  });
  const tags: TagItem[] = tagData?.records || [];

  const tagCreateMut = useMutation({
    mutationFn: (body: any) => api.post('/mall/admin/tags', body),
    onSuccess: () => {
      message.success('已创建');
      setTagModalOpen(false);
      tagForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['mall-admin-tags'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });
  const tagUpdateMut = useMutation({
    mutationFn: ({ id, body }: any) => api.put(`/mall/admin/tags/${id}`, body),
    onSuccess: () => {
      message.success('已更新');
      setTagModalOpen(false);
      setTagEditTarget(null);
      queryClient.invalidateQueries({ queryKey: ['mall-admin-tags'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });
  const tagDeleteMut = useMutation({
    mutationFn: (id: number) => api.delete(`/mall/admin/tags/${id}`),
    onSuccess: () => {
      message.success('已删除');
      queryClient.invalidateQueries({ queryKey: ['mall-admin-tags'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  // ── Tag-Product 关联 ──
  const { data: tagProdData } = useQuery({
    queryKey: ['mall-admin-tag-products', linkTag?.id],
    queryFn: () =>
      linkTag
        ? api.get(`/mall/admin/tags/${linkTag.id}/products`).then(r => r.data)
        : Promise.resolve({ records: [] }),
    enabled: !!linkTag,
  });

  // 所有商品（供选择，用已有 /api/mall/products 列表）
  // 第一版简化用公共商品搜索端点；如需管理员视角 admin/products，后续补
  const { data: allProds } = useQuery({
    queryKey: ['mall-all-products-for-tag'],
    queryFn: () => api.get('/mall/products', { params: { limit: 200 } }).then(r => r.data),
    enabled: !!linkTag,
  });

  const saveTagProductsMut = useMutation({
    mutationFn: ({ tag_id, product_ids }: any) =>
      api.put(`/mall/admin/tags/${tag_id}/products`, { product_ids }),
    onSuccess: () => {
      message.success('已保存');
      setLinkTag(null);
      queryClient.invalidateQueries({ queryKey: ['mall-admin-tags'] });
    },
    onError: (e: any) => message.error(e?.response?.data?.detail ?? '失败'),
  });

  // Tree 数据转换
  const toTreeData = (cats: Category[]): DataNode[] =>
    cats.map(c => ({
      key: c.id,
      title: (
        <Space>
          <span>{c.name}</span>
          {c.product_count !== undefined && c.product_count > 0 && (
            <Tag color="blue">{c.product_count} 商品</Tag>
          )}
          <Tooltip title="新增子分类">
            <Button size="small" type="text" icon={<PlusOutlined />}
              onClick={(e) => { e.stopPropagation(); openCatCreate(c.id); }}
            />
          </Tooltip>
          <Tooltip title="编辑">
            <Button size="small" type="text" icon={<EditOutlined />}
              onClick={(e) => { e.stopPropagation(); openCatEdit(c); }}
            />
          </Tooltip>
          <Tooltip title="删除">
            <Button size="small" type="text" danger icon={<DeleteOutlined />}
              onClick={(e) => {
                e.stopPropagation();
                Modal.confirm({
                  title: `删除分类 "${c.name}"？`,
                  content: '有子分类或商品时会被拒绝',
                  onOk: () => catDeleteMut.mutateAsync(c.id),
                });
              }}
            />
          </Tooltip>
        </Space>
      ),
      children: c.children && c.children.length ? toTreeData(c.children) : undefined,
    }));

  const openCatCreate = (parent_id: number | null) => {
    setCatEditTarget(null);
    setCatParentId(parent_id);
    catForm.resetFields();
    setCatModalOpen(true);
  };

  const openCatEdit = (c: Category) => {
    setCatEditTarget(c);
    setCatParentId(c.parent_id);
    catForm.setFieldsValue({ name: c.name, icon: c.icon, sort_order: c.sort_order, parent_id: c.parent_id });
    setCatModalOpen(true);
  };

  const openTagCreate = () => {
    setTagEditTarget(null);
    tagForm.resetFields();
    setTagModalOpen(true);
  };
  const openTagEdit = (t: TagItem) => {
    setTagEditTarget(t);
    tagForm.setFieldsValue({ title: t.title, icon: t.icon, sort_order: t.sort_order });
    setTagModalOpen(true);
  };

  return (
    <div>
      <Title level={4}>商城 · 分类与标签</Title>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {/* 分类 */}
        <Card
          title="分类（树状）"
          extra={
            <Button type="primary" icon={<PlusOutlined />}
              onClick={() => openCatCreate(null)}
            >
              新增顶级分类
            </Button>
          }
        >
          {catLoading ? <div>加载中…</div> : (
            catTree.length === 0 ? <div style={{ color: '#999' }}>暂无分类</div> :
            <Tree treeData={toTreeData(catTree)} showLine defaultExpandAll />
          )}
        </Card>

        {/* 标签 */}
        <Card
          title="首页标签（楼层）"
          extra={
            <Button type="primary" icon={<PlusOutlined />} onClick={openTagCreate}>
              新增标签
            </Button>
          }
        >
          <Table
            dataSource={tags}
            rowKey="id"
            pagination={false}
            size="small"
            columns={[
              { title: '排序', dataIndex: 'sort_order', width: 60 },
              { title: '名称', dataIndex: 'title' },
              {
                title: '关联商品',
                dataIndex: 'product_count',
                width: 90,
                render: (v: number) => <Tag>{v} 个</Tag>,
              },
              {
                title: '操作',
                key: 'act',
                width: 160,
                render: (_: any, r: TagItem) => (
                  <Space>
                    <Tooltip title="关联商品">
                      <Button size="small" icon={<LinkOutlined />}
                        onClick={() => setLinkTag(r)}
                      />
                    </Tooltip>
                    <Tooltip title="编辑">
                      <Button size="small" icon={<EditOutlined />} onClick={() => openTagEdit(r)} />
                    </Tooltip>
                    <Tooltip title="删除">
                      <Button size="small" danger icon={<DeleteOutlined />}
                        onClick={() => Modal.confirm({
                          title: `删除标签 "${r.title}"？`,
                          onOk: () => tagDeleteMut.mutateAsync(r.id),
                        })}
                      />
                    </Tooltip>
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      </div>

      {/* 分类 新建/编辑 Modal */}
      <Modal
        title={catEditTarget ? `编辑分类` : `新增分类`}
        open={catModalOpen}
        onCancel={() => { setCatModalOpen(false); setCatEditTarget(null); }}
        onOk={() => {
          catForm.validateFields().then((v: any) => {
            const payload = {
              ...v,
              parent_id: v.parent_id ?? catParentId ?? null,
            };
            if (catEditTarget) {
              catUpdateMut.mutate({ id: catEditTarget.id, body: payload });
            } else {
              catCreateMut.mutate(payload);
            }
          });
        }}
      >
        <Form form={catForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label="名称"
            rules={[{ required: true, max: 100, message: '必填，最多 100 字符' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="parent_id" label="父分类"
            extra={catParentId ? '当前从父节点新增' : '留空为顶级分类'}
          >
            <Select
              allowClear
              placeholder="选择父分类（不选=顶级）"
              options={catFlat
                .filter(c => !catEditTarget || c.id !== catEditTarget.id)
                .map(c => ({ value: c.id, label: c.parent_id ? `└ ${c.name}` : c.name }))}
            />
          </Form.Item>
          <Form.Item name="sort_order" label="排序" initialValue={0}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="icon" label="图标 URL（可选）">
            <Input placeholder="https://..." />
          </Form.Item>
        </Form>
      </Modal>

      {/* 标签 新建/编辑 Modal */}
      <Modal
        title={tagEditTarget ? '编辑标签' : '新增标签'}
        open={tagModalOpen}
        onCancel={() => { setTagModalOpen(false); setTagEditTarget(null); }}
        onOk={() => {
          tagForm.validateFields().then((v: any) => {
            if (tagEditTarget) {
              tagUpdateMut.mutate({ id: tagEditTarget.id, body: v });
            } else {
              tagCreateMut.mutate(v);
            }
          });
        }}
      >
        <Form form={tagForm} layout="vertical" preserve={false}>
          <Form.Item name="title" label="标签名称"
            rules={[{ required: true, max: 100, message: '必填，最多 100 字符' }]}
          >
            <Input placeholder="如「新品上架」「热卖推荐」" />
          </Form.Item>
          <Form.Item name="sort_order" label="排序（首页展示顺序）" initialValue={0}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="icon" label="图标 URL（可选）">
            <Input placeholder="https://..." />
          </Form.Item>
        </Form>
      </Modal>

      {/* 标签-商品关联 */}
      <Modal
        title={`关联商品到标签 · ${linkTag?.title || ''}`}
        open={!!linkTag}
        width={600}
        onCancel={() => setLinkTag(null)}
        onOk={() => {
          if (!linkTag) return;
          saveTagProductsMut.mutate({ tag_id: linkTag.id, product_ids: linkedIds });
        }}
        confirmLoading={saveTagProductsMut.isPending}
        afterOpenChange={(o) => {
          if (o && tagProdData) {
            setLinkedIds((tagProdData.records || []).map((r: any) => r.product_id));
          }
        }}
      >
        {linkTag && (
          <div>
            <div style={{ marginBottom: 8, color: '#666' }}>
              当前 {linkedIds.length} 个商品（保存时按选择顺序决定 sort_order）
            </div>
            <Select
              mode="multiple"
              placeholder="搜索商品名称添加"
              value={linkedIds}
              onChange={setLinkedIds}
              style={{ width: '100%' }}
              showSearch
              filterOption={(input, option) =>
                (option?.label as string).toLowerCase().includes(input.toLowerCase())
              }
              options={(allProds?.records || []).map((p: Product) => ({
                value: p.id,
                label: p.name,
              }))}
              maxTagCount="responsive"
            />
            <div style={{ marginTop: 12, fontSize: 12, color: '#999' }}>
              小贴士：排序 = 选中顺序。先取消再重选可以调顺序
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
