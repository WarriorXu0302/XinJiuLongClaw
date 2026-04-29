/**
 * 业务员工作台共享工具
 *
 * 职责：
 *   - 身份分流：consumer vs salesman
 *   - 状态常量与中文映射
 *   - 电话/地址/金额脱敏和格式化
 *   - 倒计时工具
 */

// ─── 用户类型 ────────────────────────────────────────────
export const USER_TYPE = {
  CONSUMER: 'consumer',
  SALESMAN: 'salesman'
}

/** 当前用户是否业务员（从 storage 读；登录时写入 userType） */
export const isSalesman = () => {
  return uni.getStorageSync('userType') === USER_TYPE.SALESMAN
}

/**
 * 登录成功后按 user_type 分流跳转
 * @param {string} userType
 * @param {string} [fallbackPath] 兜底地址
 */
export const dispatchAfterLogin = (userType, fallbackPath) => {
  uni.setStorageSync('userType', userType)
  if (userType === USER_TYPE.SALESMAN) {
    uni.reLaunch({ url: '/pages/salesman-home/salesman-home' })
  } else {
    uni.reLaunch({ url: fallbackPath || '/pages/index/index' })
  }
}

// ─── 订单状态 ────────────────────────────────────────────
// 和后端 MallOrderStatus enum 对齐（plan "models/mall/base.py"）
export const ORDER_STATUS = {
  PENDING_ASSIGNMENT: 'pending_assignment', // 待接单
  ASSIGNED: 'assigned', // 已接单待出库
  SHIPPED: 'shipped', // 已出库待送达
  DELIVERED: 'delivered', // 已送达待收款
  PENDING_PAYMENT_CONFIRMATION: 'pending_payment_confirmation', // 待财务确认
  COMPLETED: 'completed', // 已完成
  PARTIAL_CLOSED: 'partial_closed', // 折损关单
  CANCELLED: 'cancelled',
  REFUNDED: 'refunded'
}

export const ORDER_STATUS_LABEL = {
  [ORDER_STATUS.PENDING_ASSIGNMENT]: '待接单',
  [ORDER_STATUS.ASSIGNED]: '待配送',
  [ORDER_STATUS.SHIPPED]: '配送中',
  [ORDER_STATUS.DELIVERED]: '待收款',
  [ORDER_STATUS.PENDING_PAYMENT_CONFIRMATION]: '待财务确认',
  [ORDER_STATUS.COMPLETED]: '已完成',
  [ORDER_STATUS.PARTIAL_CLOSED]: '已折损',
  [ORDER_STATUS.CANCELLED]: '已取消',
  [ORDER_STATUS.REFUNDED]: '已退款'
}

/** 业务员"我的订单"4 个 Tab 的筛选组 */
export const ORDER_TAB_GROUP = {
  IN_TRANSIT: [ORDER_STATUS.ASSIGNED, ORDER_STATUS.SHIPPED], // 待配送
  AWAITING_PAYMENT: [ORDER_STATUS.DELIVERED], // 待收款
  AWAITING_FINANCE: [ORDER_STATUS.PENDING_PAYMENT_CONFIRMATION], // 待财务确认
  COMPLETED: [ORDER_STATUS.COMPLETED, ORDER_STATUS.PARTIAL_CLOSED] // 已完成
}

export const ORDER_TAB_LABELS = [
  { key: 'in_transit', label: '待配送', statuses: ORDER_TAB_GROUP.IN_TRANSIT },
  { key: 'awaiting_payment', label: '待收款', statuses: ORDER_TAB_GROUP.AWAITING_PAYMENT },
  { key: 'awaiting_finance', label: '待财务确认', statuses: ORDER_TAB_GROUP.AWAITING_FINANCE },
  { key: 'completed', label: '已完成', statuses: ORDER_TAB_GROUP.COMPLETED }
]

// ─── 跳单告警 ────────────────────────────────────────────
export const SKIP_TYPE_LABEL = {
  not_claimed_in_time: '超时未接单',
  released: '主动释放',
  admin_reassigned: '管理员改派'
}

export const SKIP_ALERT_STATUS_LABEL = {
  open: '待处理',
  resolved: '已处理',
  dismissed: '已驳回'
}

// ─── 脱敏/格式化 ────────────────────────────────────────
/** 手机号脱敏：138****1234 */
export const maskPhone = (phone) => {
  if (!phone) return ''
  const s = String(phone)
  if (s.length !== 11) return s
  return s.slice(0, 3) + '****' + s.slice(7)
}

/** 地址省市区+街道，去掉门牌号（抢单池用，抢到单后显示完整） */
export const briefAddress = (addr) => {
  if (!addr) return ''
  const { province = '', city = '', area = '', addr: detail = '' } = addr
  // 简单策略：只保留 detail 的前 N 个字符（近似取到街道）
  const brief = detail ? detail.replace(/[0-9０-９]+号?.*/g, '').slice(0, 12) : ''
  return `${province}${city}${area}${brief}`
}

/** 金额展示 ￥1,234.56 */
export const fmtMoney = (n) => {
  if (n === null || n === undefined || n === '') return '—'
  const num = Number(n)
  if (isNaN(num)) return '—'
  return '¥' + num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 相对时间 "3 分钟前" */
export const relativeTime = (ts) => {
  if (!ts) return ''
  const d = typeof ts === 'string' ? new Date(ts.replace(/-/g, '/')) : new Date(ts)
  const diff = Date.now() - d.getTime()
  if (diff < 0) return d.toLocaleString('zh-CN')
  const m = Math.floor(diff / 60000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  const dd = Math.floor(h / 24)
  if (dd < 30) return `${dd} 天前`
  return d.toLocaleDateString('zh-CN')
}

/**
 * 倒计时：返回 "HH:MM:SS"，过期返回 "00:00:00"
 * @param {number|string|Date} expiresAt
 */
export const countdown = (expiresAt) => {
  if (!expiresAt) return '00:00:00'
  let t
  if (typeof expiresAt === 'string') {
    t = new Date(expiresAt.replace(/-/g, '/')).getTime()
  } else if (expiresAt instanceof Date) {
    t = expiresAt.getTime()
  } else {
    t = Number(expiresAt)
  }
  const diff = Math.max(0, t - Date.now())
  const h = Math.floor(diff / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  const s = Math.floor((diff % 60000) / 1000)
  return [h, m, s].map(x => String(x).padStart(2, '0')).join(':')
}

export default {
  USER_TYPE,
  isSalesman,
  dispatchAfterLogin,
  ORDER_STATUS,
  ORDER_STATUS_LABEL,
  ORDER_TAB_GROUP,
  ORDER_TAB_LABELS,
  SKIP_TYPE_LABEL,
  SKIP_ALERT_STATUS_LABEL,
  maskPhone,
  briefAddress,
  fmtMoney,
  relativeTime,
  countdown
}
