<template>
  <view class="container">
    <view>
      <block
        v-for="(item, index) in prodList"
        :key="index"
      >
        <production :item="item" />
      </block>
      <view
        v-if="!prodList.length"
        class="empty"
      >
        暂无数据
      </view>
    </view>
  </view>
</template>

<script setup>
const sts = ref(0)
const title = ref('')
const current = ref(1)
const size = ref(10)
const pages = ref(0)
const tagid = ref(0)
/**
 * 生命周期函数--监听页面加载
 */
onLoad((options) => {
  current.value = 1
  pages.value = 0
  sts.value = options.sts
  title.value = options.title ? options.title : ''

  if (options.tagid) {
    tagid.value = options.tagid
  }

  if (sts.value == 0) {
    if (options.tagid == 1) {
      uni.setNavigationBarTitle({
        title: '每日上新'
      })
    } else if (options.tagid == 2) {
      uni.setNavigationBarTitle({
        title: '商城热卖'
      })
    } else if (options.tagid == 3) {
      uni.setNavigationBarTitle({
        title: '更多宝贝'
      })
    }
  } else if (sts.value == 1) {
    uni.setNavigationBarTitle({
      title: '新品推荐'
    })
  } else if (sts.value == 2) {
    uni.setNavigationBarTitle({
      title: '限时特惠'
    })
  } else if (sts.value == 3) {
    uni.setNavigationBarTitle({
      title: '每日疯抢'
    })
  } else if (sts.value == 4) {
    uni.setNavigationBarTitle({
      title: '优惠券活动商品'
    })
  } else if (sts.value == 5) {
    uni.setNavigationBarTitle({
      title: '我的收藏商品'
    })
  } else {
    uni.setNavigationBarTitle({
      title: title.value
    })
  }

  loadProdData(options)
})

/**
 * 页面上拉触底事件的处理函数
 */
onReachBottom(() => {
  if (current.value < pages.value) {
    current.value = current.value + 1
    loadProdData()
  }
})

/**
 * 加载商品数据
 */
const loadProdData = (options) => {
  const stsParam = sts.value

  if (stsParam == 0) {
    // 分组标签商品列表
    getTagProd()
  } else if (stsParam == 1) {
    // 新品推荐 → filter=lasted
    getActProd({ filter: 'lasted' })
  } else if (stsParam == 2) {
    // 限时特惠 → filter=discount
    getActProd({ filter: 'discount' })
  } else if (stsParam == 3) {
    // 每日疯抢 → filter=hot
    getActProd({ filter: 'hot' })
  } else if (stsParam == 4) {
    // 优惠券商品列表 — 后端未实现 coupon 路由
    getProdByCouponId(options?.tagid)
  } else if (stsParam == 5) {
    // 我的收藏商品列表
    getCollectionProd()
  }
}

const prodList = ref([])
const getActProd = (extraParams) => {
  uni.showLoading()
  http.request({
    url: '/api/mall/products',
    method: 'GET',
    data: {
      skip: (current.value - 1) * size.value,
      limit: size.value,
      ...(extraParams || {})
    }
  })
    .then(({ data }) => {
      let list
      if ((data.current || 1) === 1) {
        list = data.records
      } else {
        list = prodList.value
        list = list.concat(data.records)
      }
      prodList.value = list
      pages.value = data.pages
      uni.hideLoading()
    })
}

/**
 * 获取我的收藏商品
 */
const getCollectionProd = () => {
  uni.showLoading()
  http.request({
    url: '/api/mall/collections',
    method: 'GET',
    data: {
      skip: (current.value - 1) * size.value,
      limit: size.value
    }
  }).then(({ data }) => {
    // 后端返回 {records, total}；records 已是商品维度（展开 product 字段）
    const list = (data.records || []).map(r => ({
      prodId: r.product_id,
      prodName: r.name,
      brief: r.brief,
      pic: r.main_image,
      price: r.min_price,
      origPrice: r.max_price
    }))
    if (current.value === 1) {
      prodList.value = list
    } else {
      prodList.value = prodList.value.concat(list)
    }
    pages.value = Math.max(1, Math.ceil((data.total || 0) / size.value))
    uni.hideLoading()
  }).catch(() => {
    prodList.value = []
    pages.value = 0
    uni.hideLoading()
  })
}

/**
 * 获取标签列表
 */
const getTagProd = () => {
  uni.showLoading()
  http.request({
    url: '/api/mall/products',
    method: 'GET',
    data: {
      tag_id: tagid.value,
      skip: (current.value - 1) * size.value,
      limit: size.value
    }
  })
    .then(({ data }) => {
      let list
      if ((data.current || 1) === 1) {
        list = data.records
      } else {
        list = prodList.value.concat(data.records)
      }
      prodList.value = list
      pages.value = data.pages
      uni.hideLoading()
    })
}

/**
 * 获取优惠券商品列表
 * TODO: 后端 coupon 路由未实现，空占位。
 */
const getProdByCouponId = () => {
  prodList.value = []
  pages.value = 0
}
</script>

<style scoped lang="scss">
@use './prod-classify.scss';
</style>
