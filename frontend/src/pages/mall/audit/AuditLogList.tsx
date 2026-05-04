/**
 * 商城操作审计日志
 *
 * 共用 ERP `audit_logs` 表，entity_type 以 Mall 开头自动过滤。
 * 能看到：改价 / 订单改派作废 / 用户禁用启用换绑 / 凭证确认驳回 / 邀请码作废 等。
 * 用途：合规追溯 —— 谁在什么时间对什么对象做了什么操作，before/after 记 JSON。
 */
import { useMemo, useState } from 'react';
import {
  Button, Card, DatePicker, Drawer, Input, message, Select, Space, Table, Tag,
  Typography,
} from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import api from '../../../api/client';

const { Title, Text, Paragraph } = Typography;
const { RangePicker } = DatePicker;

interface MallUserActor {
  nickname?: string;
  username?: string;
  phone?: string;
  user_type?: string;
}

interface AuditRow {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  actor_id: string | null;
  actor_name: string | null;
  actor_type: string;
  actor_mall_user: MallUserActor | null;
  changes: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

// entity_type → 中文
const ENTITY_LABEL: Record<string, string> = {
  MallUser: '商城用户',
  MallOrder: '商城订单',
  MallPayment: '收款凭证',
  MallProduct: '商城商品',
  MallProductSku: 'SKU',
  MallCategory: '分类',
  MallProductTag: '标签',
  MallWarehouse: '商城仓库',
  MallInventory: '商城库存',
  MallInventoryBarcode: '库存条码',
  MallInviteCode: '邀请码',
  MallSkipAlert: '跳单告警',
};

// action → 中文
const ACTION_LABEL: Record<string, string> = {
  'mall_user.reactivate': '启用用户',
  'mall_user.disable': '禁用用户',
  'mall_product.create': '创建商品',
  'mall_product.update': '修改商品',
  'mall_product.on_sale': '商品上架',
  'mall_product.off_sale': '商品下架',
  'mall_product.draft': '商品转草稿',
  'mall_product.delete': '删除商品',
  'mall_sku.create': '创建 SKU',
  'mall_sku.update': '修改 SKU',
  'mall_sku.price_change': '改价',
  'mall_sku.delete': '删除 SKU',
  'mall_category.create': '创建分类',
  'mall_category.update': '修改分类',
  'mall_category.disable': '停用分类',
  'mall_tag.create': '创建标签',
  'mall_tag.update': '修改标签',
  'mall_tag.disable': '停用标签',
  'mall_tag.set_products': '标签批量绑商品',
  'mall_warehouse.create': '创建仓库',
  'mall_warehouse.update': '修改仓库',
  'mall_warehouse.disable': '停用仓库',
  'create_mall_warehouse': '创建仓库',
  'update_mall_warehouse': '修改仓库',
  'disable_mall_warehouse': '停用仓库',
  'mall_payment.confirm': '确认凭证',
  'mall_payment.reject': '驳回凭证',
  'mall_order.confirm_payment': '订单确认收款',
  'mall_order.admin_cancel': '管理员取消订单',
  'mall_order.reassign': '订单改派',
  'mall_invite_code.invalidate': '作废邀请码',
  'mall_user.archive': '归档用户',
  'mall_user.change_referrer': '换绑推荐人',
  'mall_salesman.create': '新增业务员',
  'mall_salesman.update': '修改业务员',
  'mall_salesman.enable': '启用业务员',
  'mall_salesman.disable': '禁用业务员',
  'mall_salesman.reset_password': '重置业务员密码',
  'mall_inbound': '采购入库',
  'mall_inbound_import': '批量入库导入',
  'mall_barcode_damaged': '条码报损',
  'mall_payment.manual_record': '手工补录收款',
  'mall_invite_code.invalidate_by_salesman': '业务员作废邀请码',
  'mall_user.change_password': '修改密码',
  'mall_skip_alert.appeal': '告警申诉',
  'mall_skip_alert.resolved': '告警通过',
  'mall_skip_alert.dismissed': '告警驳回',
  'mall_order.release': '业务员释放订单',
  'mall_order.admin_reassign': '管理员改派',
  'mall_payment.upload_voucher': '上传收款凭证',
  'mall_order.consumer_cancel': 'C 端取消订单',
  'mall_order.ship': '出库',
  'mall_order.deliver': '送达',
  'mall_order.partial_close': '坏账折损（自动）',
  'mall_user.login_failed': '登录失败',
  'mall_user.auto_archive': '自动归档（定时）',
  'user.login_failed': 'ERP 登录失败',
  'user.create': '创建员工账号',
  'user.update': '修改员工账号',
  'user.reset_password': '重置员工密码',
  'user.set_roles': '变更员工角色',
};

const ACTOR_TYPE_LABEL: Record<string, { text: string; color: string }> = {
  employee: { text: '员工', color: 'blue' },
  mall_user: { text: '商城用户', color: 'orange' },
  system: { text: '系统', color: 'default' },
  anonymous: { text: '匿名', color: 'red' },
};

function renderChanges(changes: Record<string, unknown> | null) {
  if (!changes || Object.keys(changes).length === 0) return <Text type="secondary">-</Text>;
  return (
    <pre style={{
      margin: 0,
      padding: 8,
      background: '#fafafa',
      border: '1px solid #f0f0f0',
      borderRadius: 4,
      fontSize: 12,
      maxHeight: 300,
      overflow: 'auto',
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-all',
    }}>
      {JSON.stringify(changes, null, 2)}
    </pre>
  );
}

export default function AuditLogList() {
  const [entityType, setEntityType] = useState<string | undefined>();
  const [action, setAction] = useState<string | undefined>();
  const [keyword, setKeyword] = useState('');
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [detail, setDetail] = useState<AuditRow | null>(null);
  const [exporting, setExporting] = useState(false);

  const exportCsv = async () => {
    setExporting(true);
    try {
      const res = await api.get('/mall/admin/audit-logs/export', {
        params: {
          entity_type: entityType,
          action,
          keyword: keyword || undefined,
          date_from: dateRange?.[0].format('YYYY-MM-DD'),
          date_to: dateRange?.[1].format('YYYY-MM-DD'),
        },
        responseType: 'blob',
      });
      const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `mall_audit_${dayjs().format('YYYYMMDD_HHmmss')}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      message.error(e?.response?.data?.detail ?? '导出失败');
    } finally {
      setExporting(false);
    }
  };

  const { data: entityOpts } = useQuery<string[]>({
    queryKey: ['mall-audit-entity-types'],
    queryFn: () => api.get('/mall/admin/audit-logs/entity-types').then(r => r.data),
  });
  const { data: actionOpts } = useQuery<string[]>({
    queryKey: ['mall-audit-actions'],
    queryFn: () => api.get('/mall/admin/audit-logs/actions').then(r => r.data),
  });

  const { data, isLoading } = useQuery({
    queryKey: ['mall-audit-logs', entityType, action, keyword, dateRange, page, pageSize],
    queryFn: () => api.get('/mall/admin/audit-logs', {
      params: {
        entity_type: entityType,
        action,
        keyword: keyword || undefined,
        date_from: dateRange?.[0].format('YYYY-MM-DD'),
        date_to: dateRange?.[1].format('YYYY-MM-DD'),
        skip: (page - 1) * pageSize,
        limit: pageSize,
      },
    }).then(r => r.data),
  });
  const rows: AuditRow[] = data?.records || [];
  const total: number = data?.total || 0;

  const columns: ColumnsType<AuditRow> = useMemo(() => [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 160,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作人',
      key: 'actor',
      width: 180,
      render: (_, r) => {
        if (!r.actor_id && !r.actor_mall_user) {
          return <Text type="secondary">系统</Text>;
        }
        const typeTag = ACTOR_TYPE_LABEL[r.actor_type];
        const name = r.actor_name || r.actor_id;
        const phone = r.actor_mall_user?.phone;
        return (
          <div>
            <div>
              {name}
              {typeTag && (
                <Tag color={typeTag.color} style={{ marginLeft: 6 }}>{typeTag.text}</Tag>
              )}
            </div>
            {phone && <div style={{ color: '#999', fontSize: 11 }}>{phone}</div>}
          </div>
        );
      },
    },
    {
      title: '对象类型',
      dataIndex: 'entity_type',
      width: 120,
      render: (v) => <Tag>{ENTITY_LABEL[v] || v}</Tag>,
    },
    {
      title: '操作',
      dataIndex: 'action',
      width: 160,
      render: (v) => ACTION_LABEL[v] || <Text code style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: '对象 ID',
      dataIndex: 'entity_id',
      width: 220,
      ellipsis: true,
      render: (v) => v ? <Text code copyable style={{ fontSize: 12 }}>{v}</Text> : '-',
    },
    {
      title: '变更摘要',
      dataIndex: 'changes',
      ellipsis: true,
      render: (v: Record<string, unknown> | null) => {
        if (!v) return <Text type="secondary">-</Text>;
        const keys = Object.keys(v);
        const preview = keys.slice(0, 3).map(k => `${k}: ${JSON.stringify(v[k])}`).join(', ');
        return (
          <Text ellipsis style={{ maxWidth: 380, color: '#666', fontSize: 12 }}>
            {preview}{keys.length > 3 ? ' ...' : ''}
          </Text>
        );
      },
    },
    {
      title: 'IP',
      dataIndex: 'ip_address',
      width: 130,
      render: (v) => v || <Text type="secondary">-</Text>,
    },
    {
      title: '',
      key: 'act',
      width: 70,
      fixed: 'right' as const,
      render: (_, r) => <Button size="small" onClick={() => setDetail(r)}>详情</Button>,
    },
  ], []);

  return (
    <div>
      <Title level={4}>商城操作审计</Title>
      <div style={{ marginBottom: 16, color: '#666', fontSize: 13 }}>
        所有敏感操作（改价 / 换绑 / 作废 / 禁用启用 / 订单改派 / 凭证确认驳回）都记录在这里。
        合规追溯、争议复盘、恶意行为排查用。
      </div>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            placeholder="对象类型"
            allowClear
            value={entityType}
            onChange={(v) => { setEntityType(v); setPage(1); }}
            style={{ width: 160 }}
            options={(entityOpts || []).map(v => ({ value: v, label: ENTITY_LABEL[v] || v }))}
          />
          <Select
            placeholder="操作"
            allowClear
            showSearch
            value={action}
            onChange={(v) => { setAction(v); setPage(1); }}
            style={{ width: 220 }}
            options={(actionOpts || []).map(v => ({ value: v, label: ACTION_LABEL[v] || v }))}
            filterOption={(input, option) =>
              (option?.label as string).toLowerCase().includes(input.toLowerCase())
            }
          />
          <Input.Search
            placeholder="模糊搜 action/entity"
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onSearch={() => setPage(1)}
            allowClear
            style={{ width: 220 }}
          />
          <RangePicker
            value={dateRange as any}
            onChange={(v) => { setDateRange(v as any); setPage(1); }}
          />
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={exportCsv}>
            导出 CSV
          </Button>
        </Space>
      </Card>

      <Table
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={isLoading}
        size="middle"
        scroll={{ x: 1200 }}
        pagination={{
          current: page, pageSize, total,
          showTotal: t => `共 ${t} 条`,
          onChange: (p, s) => { setPage(p); setPageSize(s || 50); },
          pageSizeOptions: ['20', '50', '100', '200'],
          showSizeChanger: true,
        }}
      />

      <Drawer
        title="审计详情"
        open={!!detail}
        onClose={() => setDetail(null)}
        size={720}
      >
        {detail && (
          <div>
            <Paragraph>
              <Text strong>时间：</Text>{dayjs(detail.created_at).format('YYYY-MM-DD HH:mm:ss')}
            </Paragraph>
            <Paragraph>
              <Text strong>操作人：</Text>
              {detail.actor_name || detail.actor_id || <Text type="secondary">系统</Text>}
              {detail.actor_mall_user?.phone && (
                <Text type="secondary" style={{ marginLeft: 8 }}>
                  {detail.actor_mall_user.phone}
                </Text>
              )}
              {detail.actor_id && (
                <Text code style={{ fontSize: 12, marginLeft: 8 }}>{detail.actor_id}</Text>
              )}
              <Tag
                color={ACTOR_TYPE_LABEL[detail.actor_type]?.color}
                style={{ marginLeft: 8 }}
              >
                {ACTOR_TYPE_LABEL[detail.actor_type]?.text || detail.actor_type}
              </Tag>
            </Paragraph>
            <Paragraph>
              <Text strong>对象类型：</Text>
              <Tag>{ENTITY_LABEL[detail.entity_type] || detail.entity_type}</Tag>
              <Text code style={{ fontSize: 12, marginLeft: 8 }}>{detail.entity_type}</Text>
            </Paragraph>
            <Paragraph>
              <Text strong>对象 ID：</Text>
              {detail.entity_id
                ? <Text code copyable>{detail.entity_id}</Text>
                : <Text type="secondary">-</Text>}
            </Paragraph>
            <Paragraph>
              <Text strong>操作：</Text>{ACTION_LABEL[detail.action] || detail.action}
              <Text code style={{ fontSize: 12, marginLeft: 8 }}>{detail.action}</Text>
            </Paragraph>
            <Paragraph>
              <Text strong>IP：</Text>{detail.ip_address || <Text type="secondary">-</Text>}
            </Paragraph>
            <Paragraph>
              <Text strong>变更详情：</Text>
            </Paragraph>
            {renderChanges(detail.changes)}
          </div>
        )}
      </Drawer>
    </div>
  );
}
