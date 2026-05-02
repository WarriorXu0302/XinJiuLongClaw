/* eslint-disable no-console, max-params */
/**
 * 本地 Mock 层 — 开发期绕过后端直接看前端
 * 启用条件：import.meta.env.VITE_APP_ENV === 'development'
 * 关闭方法：在 http.js 开头把 import 去掉即可。
 */

// ─── 基础数据 ────────────────────────────────────────────
const PIC_BASE = 'https://picsum.photos/seed'

/**
 * 造一个商品，默认支持"瓶 / 箱"两种销售单位。
 * @param id 商品 id
 * @param name 品名
 * @param bottlePrice 单瓶价
 * @param bottlesPerCase 每箱瓶数（传 0 表示只卖单瓶，不再出箱规）
 * @param caseDiscount 整箱相对单瓶总价的折扣，默认 0.92（八折二）
 * @param stock 单瓶库存
 */
const genProd = (id, name, bottlePrice, bottlesPerCase = 6, caseDiscount = 0.92, stock = 200) => {
  const casePrice = bottlesPerCase > 0 ? Math.round(bottlePrice * bottlesPerCase * caseDiscount) : 0
  const caseStock = bottlesPerCase > 0 ? Math.floor(stock / bottlesPerCase) : 0
  const minPrice = bottlesPerCase > 0 ? Math.min(bottlePrice, casePrice) : bottlePrice
  return {
    prodId: id,
    prodName: name,
    price: bottlePrice,
    casePrice,
    bottlesPerCase,
    minPrice,
    oriPrice: Math.round(bottlePrice * 1.18),
    totalStocks: stock,
    caseStock,
    pic: `${PIC_BASE}/${id}/600/600`,
    imgs: `${PIC_BASE}/${id}/600/600,${PIC_BASE}/${id + 100}/600/600,${PIC_BASE}/${id + 200}/600/600`,
    prodCommNumber: Math.floor(Math.random() * 500),
    positiveRating: 95 + Math.floor(Math.random() * 5),
    shopId: 1,
    brief: bottlesPerCase > 0 ? `严选好酒 · 支持按瓶/按箱购买（${bottlesPerCase} 瓶/箱）` : '严选好酒 · 正品保障',
    soldNum: Math.floor(Math.random() * 2000)
  }
}

// 白酒：6 瓶/箱，整箱 92 折
const BAIJIU = [
  genProd(1001, '飞天茅台 53度 500ml', 1499, 6, 0.94, 480),
  genProd(1002, '五粮液 普五第八代 52度 500ml', 1099, 6, 0.92, 720),
  genProd(1003, '国窖1573 52度 500ml', 899, 6, 0.92, 396),
  genProd(1004, '剑南春 水晶剑 52度 500ml', 429, 6, 0.90, 1200),
  genProd(1005, '洋河 梦之蓝 M6+ 55度 500ml', 699, 6, 0.91, 900),
  genProd(1006, '汾酒 青花30 53度 500ml', 879, 6, 0.92, 270),
  genProd(1007, '郎酒 青花郎 53度 500ml', 1199, 6, 0.93, 180),
  genProd(1008, '习酒 窖藏1988 53度 500ml', 569, 6, 0.90, 1080)
]

// 啤酒：按"听"为基础单位，24 听/箱，整箱 88 折
const PIJIU = [
  genProd(2001, '百威 淡色啤酒 500ml', 8, 24, 0.88, 1200),
  genProd(2002, '青岛啤酒 纯生 500ml', 7, 24, 0.86, 1440),
  genProd(2003, '哈尔滨啤酒 冰纯 500ml', 6, 24, 0.85, 2160),
  genProd(2004, '喜力 星银啤酒 500ml', 12, 24, 0.90, 960),
  genProd(2005, '科罗娜 墨西哥啤酒 330ml', 15, 24, 0.90, 720),
  genProd(2006, '燕京 U8 小度啤酒 500ml', 5, 24, 0.86, 1800)
]

// 红酒：6 瓶/箱，整箱 90 折
const HONGJIU = [
  genProd(3001, '拉菲传奇 波尔多干红 750ml', 298, 6, 0.90, 360),
  genProd(3002, '奔富 BIN 389 干红 750ml', 658, 6, 0.92, 240),
  genProd(3003, '张裕 解百纳特选级干红 750ml', 129, 6, 0.88, 1200),
  genProd(3004, '长城 海岸葡园干红 750ml', 158, 6, 0.88, 1080)
]

// 茶：只按份卖（bottlesPerCase = 0）
const CHA = [
  genProd(4001, '龙井 明前特级 250g', 588, 0, 1, 88),
  genProd(4002, '普洱 熟饼 357g 勐海料', 368, 0, 1, 120),
  genProd(4003, '正山小种 特级红茶 200g', 268, 0, 1, 160),
  genProd(4004, '铁观音 浓香型 500g', 188, 0, 1, 230)
]

// 特产：只按份卖
const TECHAN = [
  genProd(5001, '宁夏枸杞 特级头茬 500g', 98, 0, 1, 300),
  genProd(5002, '大同黄花菜 精选 250g', 45, 0, 1, 500),
  genProd(5003, '陕西大红袍花椒 500g', 68, 0, 1, 400)
]

const ALL = [...BAIJIU, ...PIJIU, ...HONGJIU, ...CHA, ...TECHAN]

const TAGS = [
  { id: 101, title: '白酒', prods: BAIJIU },
  { id: 102, title: '啤酒', prods: PIJIU },
  { id: 103, title: '红酒', prods: HONGJIU },
  { id: 104, title: '茶叶', prods: CHA },
  { id: 105, title: '特产', prods: TECHAN }
]

// ─── 路由表 ─────────────────────────────────────────────
const ok = (data) => ({ code: '00000', msg: 'ok', data })

const routes = [
  // 首页
  { match: /\/prod\/tag\/prodTagList/, handle: () => ok(TAGS.map(t => ({ id: t.id, title: t.title }))) },
  {
    match: /\/prod\/prodListByTagId/,
    handle: (p) => {
      const tagId = Number(p.data?.tagId)
      const tag = TAGS.find(t => t.id === tagId) || TAGS[0]
      return ok({ records: tag.prods, total: tag.prods.length, pages: 1, current: 1 })
    }
  },

  // 搜索
  {
    match: /\/search\/searchProdPage/,
    handle: (p) => {
      const kw = (p.data?.prodName || '').trim()
      const hit = kw ? ALL.filter(x => x.prodName.includes(kw)) : ALL.slice(0, 12)
      return ok({ records: hit, total: hit.length, pages: 1, current: 1 })
    }
  },
  {
    match: /\/search\/hotSearchByShopId/,
    handle: () => ok(['茅台', '五粮液', '青花郎', '国窖', '普五', '青岛啤酒', '普洱'])
  },

  // 商品详情（双 SKU：瓶 / 箱）
  {
    match: /\/prod\/prodInfo/,
    handle: (p) => {
      const id = Number(p.data?.prodId || 1001)
      const base = ALL.find(x => x.prodId === id) || ALL[0]
      const hasCase = base.bottlesPerCase > 0
      // 根据品类决定基础单位名称：啤酒叫"听"，其他叫"瓶"
      const unit = /啤酒/.test(base.prodName) ? '听' : '瓶'
      const caseLabel = hasCase ? `整箱（${base.bottlesPerCase} ${unit}/箱）` : ''
      const singleSku = {
        skuId: base.prodId * 10 + 1,
        prodId: base.prodId,
        skuName: `单${unit}`,
        price: base.price,
        oriPrice: base.oriPrice,
        stocks: base.totalStocks,
        actualStocks: base.totalStocks,
        pic: base.pic,
        properties: `销售单位:单${unit}`
      }
      const caseSku = hasCase && {
        skuId: base.prodId * 10 + 2,
        prodId: base.prodId,
        skuName: caseLabel,
        price: base.casePrice,
        oriPrice: Math.round(base.price * base.bottlesPerCase),
        stocks: base.caseStock,
        actualStocks: base.caseStock,
        pic: base.pic,
        properties: `销售单位:${caseLabel}`
      }
      const skuList = hasCase ? [singleSku, caseSku] : [singleSku]
      const ruleValues = hasCase ? [
        { propValueId: 1, propValue: `单${unit}` },
        { propValueId: 2, propValue: caseLabel }
      ] : [{ propValueId: 1, propValue: `单${unit}` }]
      return ok({
        ...base,
        content: `
          <p style="padding:16px 20px;color:#1A1A1A;font-size:14px;line-height:1.8;">
            <strong>${base.prodName}</strong><br/>
            ${hasCase ? `支持按${unit}或按箱采购，整箱价 ￥${base.casePrice}（${base.bottlesPerCase} ${unit}/箱，省 ￥${base.price * base.bottlesPerCase - base.casePrice}）。` : '单份严选 · 正品保证。'}
          </p>
          <p style="padding:0 20px;color:#6B6B6B;font-size:13px;line-height:1.8;">
            · 厂家直采 · 全国包邮（满 2000 元）<br/>
            · 批发价随箱数递减，批量采购请联系客服<br/>
            · 所有商品支持 7 天无理由退货
          </p>
        `,
        skuList,
        prodProps: [
          { propName: '销售单位', rule: ruleValues }
        ],
        tagList: [{ id: 1, title: hasCase ? '支持整箱' : '精选' }]
      })
    }
  },

  // 公告
  {
    match: /\/shop\/notice\/noticeList/,
    handle: () => ok({
      records: [
        { id: 1, title: '【上新】五粮液 普五第八代 现货首发', createTime: '2026-04-20 10:00:00' },
        { id: 2, title: '【活动】飞天茅台预约中，单人每月限购 2 瓶', createTime: '2026-04-18 09:30:00' },
        { id: 3, title: '【通知】五一期间配送时效说明', createTime: '2026-04-15 14:00:00' }
      ],
      total: 3,
      pages: 1,
      current: 1
    })
  },
  {
    match: /\/shop\/notice\/info\//,
    handle: () => ok({
      id: 1,
      title: '【上新】五粮液 普五第八代 现货首发',
      content: '<p>经典再现，匠心传承。即日起，普五第八代全系列上架鑫久隆批发商城。</p><p>数量有限，先到先得。</p>',
      createTime: '2026-04-20 10:00:00'
    })
  },

  // 购物车
  { match: /\/p\/shopCart\/prodCount/, handle: () => ok(3) },
  {
    match: /\/p\/shopCart\/info/,
    handle: () => ok([{
      shopId: 1,
      shopName: '鑫久隆旗舰店',
      shopCartItemDiscounts: [{
        shopCartItems: [
          { basketId: 1, prodId: 1001, skuId: 10011, prodName: BAIJIU[0].prodName, skuName: '500ml', pic: BAIJIU[0].pic, price: BAIJIU[0].price, prodCount: 1, shopId: 1, checked: false },
          { basketId: 2, prodId: 1004, skuId: 10041, prodName: BAIJIU[3].prodName, skuName: '500ml', pic: BAIJIU[3].pic, price: BAIJIU[3].price, prodCount: 2, shopId: 1, checked: false },
          { basketId: 3, prodId: 2001, skuId: 20011, prodName: PIJIU[0].prodName, skuName: '500ml×24罐', pic: PIJIU[0].pic, price: PIJIU[0].price, prodCount: 1, shopId: 1, checked: false }
        ]
      }]
    }])
  },
  {
    match: /\/p\/shopCart\/totalPay/,
    handle: () => ok({ totalMoney: 2357, subtractMoney: 158, finalMoney: 2199 })
  },
  { match: /\/p\/shopCart\/changeItem/, handle: () => ok(true) },
  { match: /\/p\/shopCart\/deleteItem/, handle: () => ok(true) },

  // 订单
  { match: /\/p\/myOrder\/orderCount/, handle: () => ok({ unPay: 1, payed: 1, consignment: 2, unComment: 0 }) },
  {
    match: /\/p\/myOrder\/myOrder/,
    handle: () => ok({
      records: [
        {
          orderNumber: 'XJL202604270001',
          status: 1,
          actualTotal: 1499,
          createTime: '2026-04-27 02:10:00',
          orderItemDtos: [{ prodId: 1001, prodName: BAIJIU[0].prodName, skuName: '500ml', pic: BAIJIU[0].pic, price: BAIJIU[0].price, prodCount: 1 }]
        },
        {
          orderNumber: 'XJL202604260018',
          status: 2,
          actualTotal: 1258,
          createTime: '2026-04-26 16:40:00',
          orderItemDtos: [
            { prodId: 1004, prodName: BAIJIU[3].prodName, skuName: '500ml', pic: BAIJIU[3].pic, price: BAIJIU[3].price, prodCount: 2 },
            { prodId: 2002, prodName: PIJIU[1].prodName, skuName: '12听装', pic: PIJIU[1].pic, price: PIJIU[1].price, prodCount: 4 }
          ]
        },
        {
          orderNumber: 'XJL202604240006',
          status: 3,
          actualTotal: 699,
          createTime: '2026-04-24 09:12:00',
          orderItemDtos: [{ prodId: 1005, prodName: BAIJIU[4].prodName, skuName: '500ml', pic: BAIJIU[4].pic, price: BAIJIU[4].price, prodCount: 1 }]
        },
        {
          orderNumber: 'XJL202604200004',
          status: 5,
          actualTotal: 368,
          createTime: '2026-04-20 15:00:00',
          orderItemDtos: [{ prodId: 4002, prodName: CHA[1].prodName, skuName: '357g', pic: CHA[1].pic, price: CHA[1].price, prodCount: 1 }]
        }
      ],
      total: 4,
      pages: 1,
      current: 1
    })
  },
  {
    match: /\/p\/myOrder\/orderDetail/,
    handle: () => ok({
      orderNumber: 'XJL202604270001',
      status: 1,
      total: 1499,
      actualTotal: 1499,
      transfee: 0,
      createTime: '2026-04-27 02:10:00',
      orderItemDtos: [{ prodId: 1001, prodName: BAIJIU[0].prodName, skuName: '500ml', pic: BAIJIU[0].pic, price: BAIJIU[0].price, prodCount: 1 }],
      userAddr: { receiver: '张先生', mobile: '138****5678', province: '北京市', city: '北京市', area: '朝阳区', addr: '建国路 88 号 SOHO 现代城 A 座 12 层' },
      remarks: ''
    })
  },
  { match: /\/p\/myOrder\/cancel\//, handle: () => ok(true) },
  { match: /\/p\/myOrder\/receipt\//, handle: () => ok(true) },
  { match: /\/p\/myOrder\/[^/]+$/, handle: () => ok(true) },

  // 提交订单
  {
    match: /\/p\/order\/confirm/,
    handle: () => ok({
      userAddr: { addrId: 1, receiver: '张先生', mobile: '138****5678', province: '北京市', city: '北京市', area: '朝阳区', addr: '建国路 88 号' },
      total: 2357,
      actualTotal: 2199,
      totalCount: 4,
      shopCartOrders: [{
        shopId: 1,
        shopName: '鑫久隆旗舰店',
        transfee: 0,
        shopReduce: 158,
        shopCartItemDiscounts: [{
          shopCartItems: [
            { prodId: 1001, skuId: 10011, prodName: BAIJIU[0].prodName, skuName: '500ml', pic: BAIJIU[0].pic, price: BAIJIU[0].price, prodCount: 1 },
            { prodId: 1004, skuId: 10041, prodName: BAIJIU[3].prodName, skuName: '500ml', pic: BAIJIU[3].pic, price: BAIJIU[3].price, prodCount: 2 }
          ]
        }],
        coupons: []
      }]
    })
  },
  { match: /\/p\/order\/submit/, handle: () => ok({ orderNumbers: 'XJL202604270099' }) },

  // 地址
  {
    match: /\/p\/address\/list/,
    handle: () => ok([
      { addrId: 1, receiver: '张先生', mobile: '13800001111', province: '北京市', city: '北京市', area: '朝阳区', addr: '建国路 88 号 SOHO 现代城 A 座 12 层', commonAddr: 1 },
      { addrId: 2, receiver: '李女士', mobile: '13900002222', province: '上海市', city: '上海市', area: '浦东新区', addr: '陆家嘴环路 1000 号 恒生大厦 18 楼', commonAddr: 0 }
    ])
  },
  { match: /\/p\/address\/addrInfo\//, handle: () => ok({ addrId: 1, receiver: '张先生', mobile: '13800001111', province: '北京市', city: '北京市', area: '朝阳区', addr: '建国路 88 号', commonAddr: 1, provinceId: 110000, cityId: 110100, areaId: 110105 }) },
  { match: /\/p\/address\/defaultAddr\//, handle: () => ok(true) },
  { match: /\/p\/address\/deleteAddr\//, handle: () => ok(true) },
  {
    match: /\/p\/area\/listByPid/,
    handle: (p) => {
      const pid = Number(p.data?.pid || 0)
      if (pid === 0) return ok([{ id: 110000, name: '北京市' }, { id: 310000, name: '上海市' }, { id: 440000, name: '广东省' }])
      if (pid === 110000) return ok([{ id: 110100, name: '北京市' }])
      if (pid === 310000) return ok([{ id: 310100, name: '上海市' }])
      if (pid === 440000) return ok([{ id: 440100, name: '广州市' }, { id: 440300, name: '深圳市' }])
      return ok([{ id: pid + 1, name: '朝阳区' }, { id: pid + 2, name: '海淀区' }])
    }
  },

  // 用户 / 收藏
  { match: /\/p\/user\/collection\/count/, handle: () => ok(5) },
  { match: /\/p\/user\/collection\/isCollection/, handle: () => ok(false) },
  { match: /\/p\/user\/collection\/addOrCancel/, handle: () => ok(true) },
  {
    match: /\/p\/user\/collection\/prods/,
    handle: () => ok({ records: ALL.slice(0, 6), total: 6, pages: 1, current: 1 })
  },

  // 登录 / 注册
  { match: /\/login/, handle: () => ok({ accessToken: 'MOCK_TOKEN_' + Date.now(), expiresIn: 3600, nickName: '体验账号', pic: '' }) },
  { match: /\/user\/register/, handle: () => ok(true) },
  {
    match: /\/api\/mall\/auth\/register/,
    handle: (p) => {
      const code = (p.data?.invite_code || '').toUpperCase()
      if (!code) return { code: 'A00001', msg: '邀请码必填', data: null }
      if (code === 'EXPIRED') return { code: 'A00001', msg: '邀请码已过期', data: null }
      if (code === 'USED') return { code: 'A00001', msg: '邀请码已被使用', data: null }
      return ok({
        token: 'MOCK_MALL_TOKEN_' + Date.now(),
        refresh_token: 'MOCK_REFRESH_' + Date.now(),
        user_type: 'consumer',
        user_id: 'u_' + Date.now(),
        nickname: p.data?.username || '新用户'
      })
    }
  },
  { match: /\/token\/refresh/, handle: () => ok(3600) },
  { match: /\/logOut/, handle: () => ok(true) },

  // 物流
  {
    match: /\/delivery\/check/,
    handle: () => ok({
      com: 'SF',
      nu: 'SF1234567890',
      state: '3',
      company: '顺丰速运',
      data: [
        { time: '2026-04-27 10:30', context: '快件已到达【北京朝阳望京营业点】' },
        { time: '2026-04-27 08:00', context: '快件派送中，派件员 王师傅 138****9999' },
        { time: '2026-04-26 22:15', context: '快件已从【北京转运中心】发出' },
        { time: '2026-04-26 18:00', context: '卖家已发货' }
      ]
    })
  },

  // 分类
  {
    match: /\/category\/categoryInfo/,
    handle: () => ok(TAGS.map(t => ({ categoryId: t.id, categoryName: t.title, children: [] })))
  },
  {
    match: /\/coupon\/prodListByCouponId/,
    handle: () => ok({ records: ALL.slice(0, 6), total: 6, pages: 1, current: 1 })
  },
  {
    match: /\/prod\/pageProd/,
    handle: () => ok({ records: ALL.slice(0, 12), total: ALL.length, pages: 1, current: 1 })
  },

  // ═════════════════════════════════════════════════════════
  // 业务员工作台 mock
  // ═════════════════════════════════════════════════════════

  // ── 数据看板 ──
  {
    match: /\/api\/mall\/salesman\/stats/,
    handle: () => ok({
      month_orders: 38,
      month_gmv: 128600.00,
      month_commission_pending: 3860.00,
      month_commission_settled: 2100.00,
      pool_count: 5,
      in_transit_count: 3,
      awaiting_finance_count: 2,
      daily_trend: [
        { date: '2026-04-21', orders: 3 }, { date: '2026-04-22', orders: 5 },
        { date: '2026-04-23', orders: 4 }, { date: '2026-04-24', orders: 7 },
        { date: '2026-04-25', orders: 6 }, { date: '2026-04-26', orders: 8 },
        { date: '2026-04-27', orders: 5 }
      ],
      commission_items: [
        { order_no: 'XJL202604270003', brand: '茅台', base: 3047, rate: 0.03, amount: 91.41, status: 'pending' },
        { order_no: 'XJL202604260020', brand: '五粮液', base: 6594, rate: 0.04, amount: 263.76, status: 'pending' },
        { order_no: 'XJL202604250005', brand: '拉菲', base: 596, rate: 0.05, amount: 29.80, status: 'settled' }
      ]
    })
  },
  {
    match: /\/api\/mall\/salesman\/order-count-badges/,
    handle: () => ok({ my_pool: 2, in_transit: 3, awaiting_finance: 2 })
  },

  // ── 抢单池 ──
  {
    match: /\/api\/mall\/salesman\/orders\/pool/,
    handle: (p) => {
      const scope = p.data?.scope || 'my'
      const myPool = [
        {
          order_no: 'XJL202604270003',
          customer_nick: '王先生',
          masked_phone: '138****8899',
          brief_address: '北京市朝阳区建国路',
          items_brief: '飞天茅台 × 1 / 普五 × 1 / 剑南春 × 1',
          amount: 3047,
          is_my_referral: true,
          expires_at: new Date(Date.now() + 24 * 60 * 1000).toISOString(),
          created_at: '2026-04-27 01:50:00'
        },
        {
          order_no: 'XJL202604270002',
          customer_nick: '李总',
          masked_phone: '139****2211',
          brief_address: '北京市海淀区中关村',
          items_brief: '五粮液 普五 × 6',
          amount: 6594,
          is_my_referral: true,
          expires_at: new Date(Date.now() + 18 * 60 * 1000).toISOString(),
          created_at: '2026-04-27 01:40:00'
        }
      ]
      const publicPool = [
        {
          order_no: 'XJL202604270010',
          customer_nick: '张女士',
          masked_phone: '133****5566',
          brief_address: '上海市浦东新区陆家嘴',
          items_brief: '青岛啤酒 × 2 箱',
          amount: 336,
          is_my_referral: false,
          expires_at: null,
          created_at: '2026-04-27 00:15:00'
        },
        {
          order_no: 'XJL202604270011',
          customer_nick: '赵先生',
          masked_phone: '137****7788',
          brief_address: '广州市天河区体育西路',
          items_brief: '梦之蓝 M6+ × 2 / 拉菲 × 1',
          amount: 1696,
          is_my_referral: false,
          expires_at: null,
          created_at: '2026-04-26 23:50:00'
        },
        {
          order_no: 'XJL202604270012',
          customer_nick: '黄小姐',
          masked_phone: '135****1234',
          brief_address: '深圳市南山区科技园',
          items_brief: '国窖1573 × 1 箱（6 瓶）',
          amount: 4964,
          is_my_referral: false,
          expires_at: null,
          created_at: '2026-04-26 22:30:00'
        }
      ]
      const records = scope === 'public' ? publicPool : myPool
      return ok({ records, total: records.length, pages: 1, current: 1 })
    }
  },
  { match: /\/api\/mall\/salesman\/orders\/[^/]+\/claim/, handle: () => ok({ success: true }) },
  { match: /\/api\/mall\/salesman\/orders\/[^/]+\/release/, handle: () => ok({ success: true }) },
  { match: /\/api\/mall\/salesman\/orders\/[^/]+\/ship/, handle: () => ok({ success: true }) },
  { match: /\/api\/mall\/salesman\/orders\/[^/]+\/deliver/, handle: () => ok({ success: true }) },
  {
    match: /\/api\/mall\/salesman\/orders\/[^/]+\/upload-payment-voucher/,
    handle: (p) => {
      const d = p.data || {}
      const voucherCount = (d.vouchers || []).length
      return ok({
        success: true,
        voucher_count: voucherCount,
        amount: d.amount,
        status: 'pending_payment_confirmation'
      })
    }
  },

  // ── 我的订单详情 ──（匹配末尾是订单号，不含 /action）
  {
    match: /\/api\/mall\/salesman\/orders\/XJL\d+$/,
    handle: (p) => {
      const orderNo = p.url.split('/').pop()
      return ok({
        order_no: orderNo,
        status: 'assigned',
        customer_nick: '王先生',
        customer_phone: '13888998899',
        address: {
          province: '北京市',
          city: '北京市',
          area: '朝阳区',
          addr: '建国路 88 号 SOHO 现代城 A 座 12 层',
          receiver: '王先生',
          lat: 39.9088,
          lng: 116.4635
        },
        items: [
          { prod_name: '飞天茅台 53度 500ml', sku_spec: '单瓶', price: 1499, quantity: 1, subtotal: 1499 },
          { prod_name: '五粮液 普五 52度 500ml', sku_spec: '单瓶', price: 1099, quantity: 1, subtotal: 1099 },
          { prod_name: '剑南春 水晶剑 52度 500ml', sku_spec: '单瓶', price: 429, quantity: 1, subtotal: 429 }
        ],
        total_amount: 3027,
        shipping_fee: 20,
        discount_amount: 0,
        pay_amount: 3047,
        remarks: '请下午 3 点后送达',
        timeline: [
          { event: '下单', time: '2026-04-27 01:50:00' },
          { event: '已接单', time: '2026-04-27 02:05:00' }
        ],
        payment_voucher: null,
        delivery_photos: []
      })
    }
  },

  // ── 我的订单列表 ──
  {
    match: /\/api\/mall\/salesman\/orders($|\?)/,
    handle: (p) => {
      const filter = p.data?.status_filter || 'in_transit'
      const allOrders = [
        { order_no: 'XJL202604270003', status: 'assigned', customer_nick: '王先生', items_brief: '飞天茅台 × 1 / 普五 × 1 等 3 件', amount: 3047, created_at: '2026-04-27 01:50:00', claimed_at: '2026-04-27 02:05:00' },
        { order_no: 'XJL202604260020', status: 'shipped', customer_nick: '李总', items_brief: '普五 × 6', amount: 6594, created_at: '2026-04-26 15:10:00', shipped_at: '2026-04-26 16:20:00' },
        { order_no: 'XJL202604260019', status: 'shipped', customer_nick: '周先生', items_brief: '青花郎 × 2', amount: 2398, created_at: '2026-04-26 12:00:00', shipped_at: '2026-04-26 14:00:00' },
        { order_no: 'XJL202604260015', status: 'delivered', customer_nick: '何小姐', items_brief: '梦之蓝 M6+ × 1', amount: 699, created_at: '2026-04-26 09:30:00', delivered_at: '2026-04-26 11:30:00' },
        { order_no: 'XJL202604260012', status: 'pending_payment_confirmation', customer_nick: '韩总', items_brief: '国窖1573 × 2', amount: 1798, created_at: '2026-04-26 08:00:00' },
        { order_no: 'XJL202604260011', status: 'pending_payment_confirmation', customer_nick: '吴先生', items_brief: '飞天 × 1', amount: 1499, created_at: '2026-04-26 07:30:00' },
        { order_no: 'XJL202604250005', status: 'completed', customer_nick: '郑女士', items_brief: '拉菲传奇 × 2', amount: 596, created_at: '2026-04-25 14:00:00', completed_at: '2026-04-25 19:20:00' },
        { order_no: 'XJL202604240008', status: 'completed', customer_nick: '陈总', items_brief: '青花30 × 1 箱', amount: 4852, created_at: '2026-04-24 10:00:00', completed_at: '2026-04-24 20:30:00' }
      ]
      const groups = {
        in_transit: ['assigned', 'shipped'],
        awaiting_payment: ['delivered'],
        awaiting_finance: ['pending_payment_confirmation'],
        completed: ['completed', 'partial_closed']
      }
      const want = groups[filter] || []
      const records = allOrders.filter(x => want.includes(x.status))
      return ok({ records, total: records.length, pages: 1, current: 1 })
    }
  },

  // ── 邀请码 ──
  {
    match: /\/api\/mall\/salesman\/invite-codes\/history/,
    handle: () => ok({
      records: [
        { id: 'c1', code: 'K3N9Q2W7', expires_at: '2026-04-27 05:30:00', used_at: '2026-04-27 03:10:00', used_by_nick: '王先生', status: 'used' },
        { id: 'c2', code: 'M4P6R8T5', expires_at: '2026-04-26 18:20:00', used_at: null, used_by_nick: null, status: 'expired' },
        { id: 'c3', code: 'A2D8F7H3', expires_at: '2026-04-26 10:15:00', used_at: '2026-04-26 09:45:00', used_by_nick: '李总', status: 'used' },
        { id: 'c4', code: 'X5Y2Z9B4', expires_at: '2026-04-25 22:00:00', used_at: null, used_by_nick: null, status: 'invalidated' }
      ],
      total: 4,
      pages: 1,
      current: 1
    })
  },
  { match: /\/api\/mall\/salesman\/invite-codes\/[^/]+\/invalidate/, handle: () => ok({ success: true }) },
  {
    match: /\/api\/mall\/salesman\/invite-codes$/,
    handle: () => {
      const chars = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
      let code = ''
      for (let i = 0; i < 8; i++) code += chars[Math.floor(Math.random() * chars.length)]
      return ok({
        id: 'c_' + Date.now(),
        code,
        expires_at: new Date(Date.now() + 120 * 60 * 1000).toISOString(),
        remaining_today: 17
      })
    }
  },

  // ── 我的客户 ──
  {
    match: /\/api\/mall\/salesman\/my-customers/,
    handle: () => ok({
      records: [
        { id: 'u1', nickname: '王先生', phone: '13888998899', bound_at: '2026-03-12 10:00:00', last_order_at: '2026-04-27 01:50:00', total_orders: 12, total_gmv: 48680 },
        { id: 'u2', nickname: '李总', phone: '13922221100', bound_at: '2026-02-20 14:30:00', last_order_at: '2026-04-26 15:10:00', total_orders: 8, total_gmv: 62300 },
        { id: 'u3', nickname: '周先生', phone: '13766557788', bound_at: '2026-01-15 09:20:00', last_order_at: '2026-04-26 12:00:00', total_orders: 15, total_gmv: 84500 },
        { id: 'u4', nickname: '何小姐', phone: '13511223344', bound_at: '2026-04-01 16:45:00', last_order_at: '2026-04-26 09:30:00', total_orders: 3, total_gmv: 2097 },
        { id: 'u5', nickname: '吴先生', phone: '13633445566', bound_at: '2025-11-05 11:00:00', last_order_at: '2026-04-26 07:30:00', total_orders: 28, total_gmv: 125600 }
      ],
      total: 5,
      pages: 1,
      current: 1
    })
  },

  // ── 跳单告警 ──
  {
    match: /\/api\/mall\/salesman\/skip-alerts/,
    handle: () => ok({
      records: [
        {
          id: 'a1',
          customer_nick: '何小姐',
          customer_phone_mask: '135****3344',
          skip_count: 3,
          status: 'open',
          first_at: '2026-04-05 10:00:00',
          last_at: '2026-04-26 09:30:00',
          logs: [
            { id: 'l1', order_no: 'XJL202604050003', skip_type: 'not_claimed_in_time', created_at: '2026-04-05 10:00:00' },
            { id: 'l2', order_no: 'XJL202604150006', skip_type: 'released', created_at: '2026-04-15 14:20:00' },
            { id: 'l3', order_no: 'XJL202604260015', skip_type: 'admin_reassigned', created_at: '2026-04-26 09:30:00' }
          ]
        }
      ],
      total: 1,
      pages: 1,
      current: 1
    })
  },
  { match: /\/api\/mall\/salesman\/skip-alerts\/[^/]+\/appeal/, handle: () => ok({ success: true }) },

  // ── 业务员个人信息 ──
  {
    match: /\/api\/mall\/salesman\/profile\/accepting-orders/,
    handle: () => ok({ success: true })
  },
  {
    match: /\/api\/mall\/salesman\/profile\/payment-qr/,
    handle: () => ok({ success: true })
  },
  {
    match: /\/api\/mall\/salesman\/profile$/,
    handle: () => ok({
      id: 'me',
      nickname: '张业务',
      phone: '13800001111',
      employee_no: 'E2023006',
      linked_employee_name: '张业务',
      assigned_brand_name: '青花郎',
      is_accepting_orders: true,
      default_warehouse_name: '北京主仓',
      wechat_qr_url: '',
      alipay_qr_url: ''
    })
  },

  // ── 通知中心 ──
  {
    match: /\/api\/mall\/workspace\/notifications\/unread-count/,
    handle: () => ok({ count: 3 })
  },
  {
    match: /\/api\/mall\/workspace\/notifications\/[^/]+\/mark-read/,
    handle: () => ok({ success: true })
  },
  {
    match: /\/api\/mall\/workspace\/notifications\/mark-all-read/,
    handle: () => ok({ success: true })
  },
  {
    match: /\/api\/mall\/workspace\/notifications/,
    handle: () => ok({
      records: [
        { id: 'n1', title: '销售目标已批准', content: '2026 年 4 月销售目标已由老板审批通过，完成率将在达成 100% 时获得奖金 ¥2000。', status: 'unread', created_at: '2026-04-25 10:00:00', related_entity_type: 'SalesTarget' },
        { id: 'n2', title: '新订单待接单', content: '客户 王先生 下了一个 ¥3047 的订单，请在 30 分钟内接单。', status: 'unread', created_at: '2026-04-27 01:50:30', related_entity_type: 'MallOrder' },
        { id: 'n3', title: '报销审批通过', content: '您提交的报销单 DC20260420001（¥280 油费）已审批通过。', status: 'unread', created_at: '2026-04-23 14:20:00', related_entity_type: 'ExpenseClaim' },
        { id: 'n4', title: '跳单告警', content: '您对客户 何小姐 累计跳单 3 次，已触发告警。', status: 'read', created_at: '2026-04-26 09:31:00', related_entity_type: 'MallSkipAlert' },
        { id: 'n5', title: '工资已发放', content: '2026 年 3 月工资 ¥9,860 已打款。其中商城销售提成 ¥1,860。', status: 'read', created_at: '2026-04-10 10:00:00', related_entity_type: 'SalaryRecord' }
      ],
      total: 5,
      pages: 1,
      current: 1
    })
  },

  // ── 考勤 ──
  {
    match: /\/api\/mall\/workspace\/attendance\/monthly-summary/,
    handle: () => ok({
      month: '2026-04',
      work_days: 20,
      checkin_days: 18,
      late_count: 1,
      absence_count: 0,
      leave_days: 1,
      visit_count: 42,
      valid_visit_count: 38
    })
  },
  {
    match: /\/api\/mall\/workspace\/attendance\/checkin/,
    handle: (p) => {
      if (p.method === 'POST') {
        return ok({ success: true, status: 'normal', checkin_time: new Date().toISOString() })
      }
      return ok({
        records: [
          { checkin_date: '2026-04-27', work_in: '08:55', work_out: null, status_in: 'normal' },
          { checkin_date: '2026-04-26', work_in: '08:50', work_out: '18:05', status_in: 'normal' },
          { checkin_date: '2026-04-25', work_in: '09:12', work_out: '18:00', status_in: 'late' }
        ]
      })
    }
  },
  // 查今日上/下班打卡状态（防重复打卡）
  {
    match: /\/api\/mall\/workspace\/attendance\/today/,
    handle: () => {
      const h = new Date().getHours()
      const today = new Date()
      today.setHours(9, 3, 0, 0)
      return ok({
        work_in: h >= 10 ? { checkin_time: today.toISOString(), status: 'normal' } : null,
        work_out: null
      })
    }
  },

  // 查当前进行中的拜访（enter_time 有，leave_time null）
  {
    match: /\/api\/mall\/workspace\/attendance\/visits\/active/,
    handle: () => {
      // 随机：50% 概率进行中
      if (Math.random() < 0.5) {
        return ok({
          visit_id: 'v_active_1',
          customer_id: 'c_101',
          customer_name: '朝阳区建国路华润万家',
          enter_time: new Date(Date.now() - 18 * 60 * 1000).toISOString()
        })
      }
      return ok(null)
    }
  },
  { match: /\/api\/mall\/workspace\/attendance\/visits\/enter/, handle: () => ok({ visit_id: 'v_new_' + Date.now(), enter_time: new Date().toISOString() }) },
  {
    match: /\/api\/mall\/workspace\/attendance\/visits\/leave/,
    handle: () => {
      const duration = 18 + Math.floor(Math.random() * 80)
      return ok({ duration_minutes: duration, is_valid: duration >= 30 })
    }
  },

  // ERP B2B 客户列表（给拜访打卡选择用）
  {
    match: /\/api\/mall\/workspace\/customers/,
    handle: (p) => {
      const kw = (p.data?.keyword || '').trim()
      const all = [
        { id: 'c_101', code: 'CUST0001', name: '朝阳区建国路华润万家', contact_name: '王经理', contact_phone: '13888889001', address: '北京市朝阳区建国路 88 号' },
        { id: 'c_102', code: 'CUST0002', name: '海淀区中关村全家超市', contact_name: '李店长', contact_phone: '13888889002', address: '北京市海淀区中关村大街 5 号' },
        { id: 'c_103', code: 'CUST0003', name: '三里屯屯三里酒楼', contact_name: '赵总', contact_phone: '13888889003', address: '北京市朝阳区三里屯北路 12 号' },
        { id: 'c_104', code: 'CUST0004', name: '望京悦秋酒业门店', contact_name: '钱老板', contact_phone: '13888889004', address: '北京市朝阳区望京西路 88 号' },
        { id: 'c_105', code: 'CUST0005', name: '丰台方庄副食批发部', contact_name: '孙经理', contact_phone: '13888889005', address: '北京市丰台区方庄芳群园 1 区' },
        { id: 'c_106', code: 'CUST0006', name: '通州八通步行街烟酒行', contact_name: '周老板', contact_phone: '13888889006', address: '北京市通州区八通街 66 号' },
        { id: 'c_107', code: 'CUST0007', name: '大兴亦庄经济开发区喜家德', contact_name: '吴经理', contact_phone: '13888889007', address: '北京市大兴区亦庄经济开发区' }
      ]
      const records = kw ? all.filter(x => x.name.includes(kw) || x.code.includes(kw)) : all
      return ok({ records, total: records.length, pages: 1, current: 1 })
    }
  },
  {
    match: /\/api\/mall\/workspace\/attendance\/visits/,
    handle: () => ok({
      records: [
        { id: 'v1', customer_name: '王先生', enter_time: '2026-04-27 10:00:00', leave_time: '2026-04-27 10:45:00', duration_minutes: 45, is_valid: true },
        { id: 'v2', customer_name: '李总', enter_time: '2026-04-26 14:00:00', leave_time: '2026-04-26 14:40:00', duration_minutes: 40, is_valid: true },
        { id: 'v3', customer_name: '周先生', enter_time: '2026-04-26 09:00:00', leave_time: '2026-04-26 09:15:00', duration_minutes: 15, is_valid: false }
      ],
      total: 3,
      pages: 1,
      current: 1
    })
  },

  // ── 请假 ──
  {
    match: /\/api\/mall\/workspace\/leave-requests/,
    handle: (p) => {
      if (p.method === 'POST') return ok({ request_no: 'LV-20260427-0001', status: 'pending' })
      return ok({
        records: [
          { request_no: 'LV-20260401-0012', leave_type: 'annual', start_date: '2026-04-01', end_date: '2026-04-03', total_days: 3, status: 'approved' },
          { request_no: 'LV-20260315-0008', leave_type: 'sick', start_date: '2026-03-15', end_date: '2026-03-15', total_days: 1, status: 'approved' }
        ],
        total: 2,
        pages: 1,
        current: 1
      })
    }
  },

  // ── 报销 ──
  {
    match: /\/api\/mall\/workspace\/expense-claims/,
    handle: (p) => {
      if (p.method === 'POST') return ok({ claim_no: 'DC20260427001', status: 'pending' })
      return ok({
        records: [
          { claim_no: 'DC20260420001', claim_type: 'daily', amount: 280, status: 'paid', description: '跟单油费', created_at: '2026-04-20' },
          { claim_no: 'DC20260410003', claim_type: 'daily', amount: 520, status: 'approved', description: '客户招待餐费', created_at: '2026-04-10' },
          { claim_no: 'DC20260405008', claim_type: 'daily', amount: 180, status: 'pending', description: '高速过路费', created_at: '2026-04-05' }
        ],
        total: 3,
        pages: 1,
        current: 1
      })
    }
  },

  // ── 扫码稽查 ──
  {
    match: /\/api\/mall\/workspace\/inspection-cases\/scan/,
    handle: (p) => ok({
      barcode: p.data?.barcode || '',
      product_name: '飞天茅台 53度 500ml',
      brand: '茅台',
      batch_no: 'MT2023B058',
      is_valid: true,
      last_known_location: '北京主仓',
      notes: '扫码查询结果仅供参考'
    })
  },
  {
    match: /\/api\/mall\/workspace\/inspection-cases/,
    handle: (p) => {
      if (p.method === 'POST') return ok({ case_no: 'IC20260427001', status: 'pending' })
      return ok({
        records: [
          { case_no: 'IC20260410005', case_type: 'outflow_nonmalicious', barcode: 'MT2023B058-1', status: 'executed', created_at: '2026-04-10' }
        ],
        total: 1,
        pages: 1,
        current: 1
      })
    }
  },

  // ── KPI / 销售目标 ──
  {
    match: /\/api\/mall\/workspace\/sales-targets\/my-dashboard/,
    handle: () => ok({
      target: {
        target_year: 2026,
        target_month: 4,
        receipt_target: 150000,
        sales_target: 200000,
        bonus_at_100: 2000,
        bonus_at_120: 5000,
        bonus_metric: 'receipt'
      },
      actual: { actual_receipt: 128600, actual_sales: 135200 },
      completion: { receipt_completion: 0.857, sales_completion: 0.676 },
      bonus_estimate: 0,
      bonus_next_tier: { at: '100%', missing: 21400 }
    })
  }
]

// ─── 对外：在 http 层调用 ─────────────────────────────────
// M1-M5 后端接通后默认关 mock；需要离线调 UI 时手工把环境变量改 'mock'
export const enabled = import.meta.env.VITE_APP_ENV === 'mock'

export function tryMock (params) {
  const url = params.url || ''
  // 后端已接通的 mall 真路径一律不走 mock，直接打后端
  if (url.startsWith('/api/mall/') || url.startsWith('/api/auth/')) return null
  const hit = routes.find(r => r.match.test(url))
  if (!hit) return null
  const delay = 120 + Math.floor(Math.random() * 180)
  return new Promise((resolve) => {
    setTimeout(() => {
      const res = hit.handle(params)
      console.log('%c[MOCK]', 'color:#C9A961;font-weight:bold', url, res)
      resolve(res)
    }, delay)
  })
}

// ─── uni.uploadFile 拦截 ──────────────────────────────────
// uploadFile 不走 http.request，需要单独 monkey-patch
if (enabled && typeof uni !== 'undefined' && uni.uploadFile) {
  const origUpload = uni.uploadFile.bind(uni)
  const uploadMatchers = [
    { match: /\/attachments\/upload/, kind: 'attachment' }
  ]
  uni.uploadFile = (opt) => {
    const url = opt.url || ''
    const hit = uploadMatchers.find(m => m.match.test(url))
    if (!hit) return origUpload(opt)
    const delay = 300 + Math.floor(Math.random() * 400)
    const mockSha = Array.from({ length: 64 }, () => Math.floor(Math.random() * 16).toString(16)).join('')
    const mockUrl = `/uploads/${new Date().toISOString().slice(0, 10)}/${mockSha.slice(0, 8)}.jpg`
    setTimeout(() => {
      const body = { code: '00000', msg: 'ok', data: { url: mockUrl, sha256: mockSha, size: 256000 } }
      console.log('%c[MOCK uploadFile]', 'color:#C9A961;font-weight:bold', url, body)
      opt.success?.({ statusCode: 200, data: JSON.stringify(body) })
      opt.complete?.()
    }, delay)
    return { abort: () => {} }
  }
}
