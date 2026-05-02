<template>
  <view class="page">
    <!-- 顶部品牌 + 搜索 -->
    <view class="topbar">
      <view class="topbar__brand">
        <text class="topbar__logo">鑫久隆</text>
      </view>
      <view class="topbar__search">
        <image class="topbar__searchIcon" src="@/static/images/icon/search.png" mode="aspectFit" />
        <input
          class="topbar__searchInput"
          type="text"
          :value="keyword"
          placeholder="搜索商品名称、品牌"
          placeholder-class="topbar__searchPlaceholder"
          confirm-type="search"
          @input="onKeywordInput"
          @confirm="onSearchConfirm"
        />
        <text v-if="keyword" class="topbar__searchClear" @tap="onSearchClear">✕</text>
      </view>
    </view>

    <!-- Banner 广告轮播 -->
    <view v-if="!searchSearched" class="banner">
      <swiper
        class="banner__swiper"
        :autoplay="true"
        :circular="true"
        :interval="3500"
        :duration="600"
        indicator-dots
        indicator-active-color="#C9A961"
        indicator-color="rgba(250, 248, 245, 0.55)"
      >
        <block v-for="(b, idx) in banners" :key="idx">
          <swiper-item class="banner__item" :data-prodid="b.prodId" @tap="onBannerTap">
            <view class="banner__card" :style="{ background: b.bg }">
              <image class="banner__img" :src="b.img" mode="aspectFill" />
              <view class="banner__mask" />
              <view class="banner__text">
                <text class="banner__tag">{{ b.tag }}</text>
                <text class="banner__title">{{ b.title }}</text>
                <text class="banner__sub">{{ b.sub }}</text>
              </view>
            </view>
          </swiper-item>
        </block>
      </swiper>
    </view>

    <!-- 品类导航 -->
    <scroll-view class="nav" scroll-x="true">
      <view class="nav__inner">
        <view
          v-for="(item, index) in taglist"
          :key="index"
          :class="['nav__item', activeNav === index ? 'nav__item--active' : '']"
          :data-index="index"
          @tap="onNavTap"
        >
          {{ item.title }}
        </view>
      </view>
    </scroll-view>

    <!-- 搜索结果 -->
    <view v-if="searchSearched" class="search-result">
      <view class="search-result__head">
        <text class="search-result__title">搜索结果</text>
        <text class="search-result__count">{{ searchProdList.length }} 件商品</text>
      </view>
      <view v-if="!searchProdList.length" class="search-result__empty">
        暂无搜索结果
      </view>
      <view v-else class="search-result__list">
        <block v-for="(item, idx) in searchProdList" :key="idx">
          <production :item="item" sts="6" />
        </block>
      </view>
    </view>

    <!-- 商品列表 -->
    <view v-if="!searchSearched" class="goods">
      <block
        v-for="(item, index) in taglist"
        :key="index"
      >
        <view
          v-if="item.prods && item.prods.length && (activeNav === -1 || activeNav === index)"
          class="goods__section"
        >
          <view class="goods__head">
            <text class="goods__title">{{ item.title }}</text>
          </view>

          <view class="goods__grid">
            <block
              v-for="(prod, idx2) in item.prods"
              :key="idx2"
            >
              <view
                class="goods__card"
                :data-prodid="prod.prodId"
                @tap="toProdPage"
              >
                <view class="goods__img">
                  <img-show
                    :src="prod.pic"
                    :class-list="['goods__imgInner']"
                  />
                </view>
                <view class="goods__info">
                  <text class="goods__name">{{ prod.prodName }}</text>
                  <view class="goods__price" v-if="prod.price !== null && prod.price !== undefined">
                    <text class="goods__priceSymbol">¥</text>
                    <text class="goods__priceNum">{{ wxs.parsePrice(prod.price)[0] }}</text>
                    <text class="goods__priceDec">.{{ wxs.parsePrice(prod.price)[1] }}</text>
                  </view>
                  <text class="goods__stock" v-if="prod.totalStocks !== null && prod.totalStocks !== undefined">
                    库存 {{ prod.totalStocks }}
                  </text>
                </view>
              </view>
            </block>
          </view>
        </view>
      </block>

      <!-- 空态 -->
      <view v-if="taglist.length === 0" class="goods__empty">
        <text class="goods__emptyText">暂无商品</text>
      </view>
    </view>
  </view>
</template>

<script setup>
const wxs = number()
const taglist = ref([])
const updata = ref(true)
const orderTitles = ['白酒', '啤酒', '红酒', '茶叶', '特产']
const activeNav = ref(-1)

const keyword = ref('')
const searchSearched = ref(false)
const searchProdList = ref([])

// Banner 广告位
const banners = ref([
  {
    prodId: 1001,
    tag: '臻品推荐',
    title: '飞天茅台 · 53 度',
    sub: '正品保真 · 严选到仓',
    img: 'https://picsum.photos/seed/xjl-banner-01/900/400',
    bg: 'linear-gradient(135deg, #1A1A1A 0%, #2A2013 100%)'
  },
  {
    prodId: 1002,
    tag: '厂家直供',
    title: '五粮液 · 普五第八代',
    sub: '渠道直采 · 价格到底',
    img: 'https://picsum.photos/seed/xjl-banner-02/900/400',
    bg: 'linear-gradient(135deg, #0E0E0E 0%, #3A2B17 100%)'
  },
  {
    prodId: 2001,
    tag: '整箱特惠',
    title: '百威啤酒 · 经典淡爽',
    sub: '24 听整箱 · 限时直降',
    img: 'https://picsum.photos/seed/xjl-banner-03/900/400',
    bg: 'linear-gradient(135deg, #1B1F1A 0%, #2A3522 100%)'
  }
])

const onBannerTap = (e) => {
  const prodId = e.currentTarget.dataset.prodid
  if (prodId) {
    uni.navigateTo({ url: '/pages/prod/prod?prodid=' + prodId })
  }
}

// 业务员不走 C 端首页，拦截到工作台（tabBar 点哪个都会经过）
onShow(() => {
  if (uni.getStorageSync('userType') === 'salesman') {
    uni.reLaunch({ url: '/pages/salesman-home/salesman-home' })
  }
})

onLoad(() => {
  getAllData()
})

onPullDownRefresh(() => {
  setTimeout(() => {
    getAllData()
    uni.stopPullDownRefresh()
  }, 100)
})

const getAllData = () => {
  getTag()
}

const onNavTap = (e) => {
  const index = e.currentTarget.dataset.index
  activeNav.value = activeNav.value === index ? -1 : index
}

const toSearchPage = () => {
  uni.navigateTo({
    url: '/pages/search-page/search-page'
  })
}

const onKeywordInput = (e) => {
  keyword.value = e.detail.value
  if (!keyword.value || !keyword.value.trim()) {
    searchSearched.value = false
    searchProdList.value = []
  }
}

const onSearchClear = () => {
  keyword.value = ''
  searchSearched.value = false
  searchProdList.value = []
}

const onSearchConfirm = (e) => {
  const v = (e?.detail?.value ?? keyword.value ?? '').trim()
  keyword.value = v
  if (!v) {
    searchSearched.value = false
    searchProdList.value = []
    return
  }
  searchSearched.value = true
  activeNav.value = -1
  uni.showLoading({ mask: true, title: '搜索中' })
  http.request({
    url: '/api/mall/search/products',
    method: 'GET',
    data: {
      q: v,
      skip: 0,
      limit: 20
    }
  })
    .then(({ data }) => {
      searchProdList.value = data?.records || []
    })
    .finally(() => {
      uni.hideLoading()
    })
}

const toProdPage = (e) => {
  const prodid = e.currentTarget.dataset.prodid
  if (prodid) {
    uni.navigateTo({
      url: '/pages/prod/prod?prodid=' + prodid
    })
  }
}

const toClassifyPage = (e) => {
  let url = '/pages/prod-classify/prod-classify?sts=' + e.currentTarget.dataset.sts
  const id = e.currentTarget.dataset.id
  const title = e.currentTarget.dataset.title
  if (id) {
    url += '&tagid=' + id + '&title=' + title
  }
  uni.navigateTo({ url })
}

const getTag = () => {
  http.request({
    url: '/api/mall/products/tags',
    method: 'GET',
    data: {}
  })
    .then(({ data }) => {
      const list = (data || []).filter(t => orderTitles.includes(t.title))
      list.sort((a, b) => orderTitles.indexOf(a.title) - orderTitles.indexOf(b.title))
      taglist.value = list
      for (let i = 0; i < list.length; i++) {
        updata.value = false
        updata.value = true
        getTagProd(list[i].id, i)
      }
    })
}

const getTagProd = (id, index) => {
  http.request({
    url: '/api/mall/products',
    method: 'GET',
    data: { tag_id: id, limit: 12 }
  })
    .then(({ data }) => {
      updata.value = false
      updata.value = true
      const taglistParam = taglist.value
      taglistParam[index].prods = data.records
      taglist.value = taglistParam
    })
}
</script>

<style scoped lang="scss">
@import "./index.scss";
</style>
