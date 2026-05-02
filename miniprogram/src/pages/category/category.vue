<template>
  <view class="container home-v2">
    <!-- 顶部轮播 -->
    <view class="home-v2__banner">
      <swiper
        class="home-v2__swiper"
        indicator-dots
        :autoplay="true"
        :circular="true"
        :interval="3000"
        :duration="400"
        indicator-active-color="#C9A961"
        indicator-color="rgba(250, 248, 245, 0.55)"
      >
        <block
          v-for="(b, idx) in banners"
          :key="idx"
        >
          <swiper-item class="home-v2__swiperItem">
            <image
              class="home-v2__bannerImg"
              :src="b.img"
              mode="aspectFill"
            />
          </swiper-item>
        </block>
      </swiper>
    </view>

    <!-- 快捷入口（固定顺序） -->
    <view class="home-v2__quick">
      <view
        v-for="(q, idx) in quickActions"
        :key="idx"
        class="home-v2__quickItem"
        data-sts="0"
        :data-id="q.tagId"
        :data-title="q.title"
        @tap="toClassifyPage"
      >
        <image
          class="home-v2__quickIcon"
          :src="q.icon"
          mode="aspectFit"
        />
        <text class="home-v2__quickText">{{ q.title }}</text>
      </view>
    </view>

    <!-- 公告条 -->
    <view class="home-v2__notice">
      <image
        class="home-v2__noticeIcon"
        src="@/static/images/icon/horn.png"
        mode="aspectFit"
      />
      <swiper
        class="home-v2__noticeSwiper"
        :vertical="true"
        :autoplay="true"
        :circular="true"
        :interval="2500"
        :duration="500"
      >
        <block
          v-for="(t, idx) in notices"
          :key="idx"
        >
          <swiper-item class="home-v2__noticeItem">
            {{ t }}
          </swiper-item>
        </block>
      </swiper>
      <view class="home-v2__noticeArrow" />
    </view>

    <view
      v-if="updata"
      class="home-v2__sections"
    >
      <block
        v-for="(item, index) in taglist"
        :key="index"
      >
        <view
          v-if="item.prods && item.prods.length"
          class="home-v2__section"
        >
          <view class="home-v2__sectionTitle">
            <text class="home-v2__sectionName">{{ item.title }}</text>
            <view
              class="home-v2__more"
              data-sts="0"
              :data-id="item.id"
              :data-title="item.title"
              @tap="toClassifyPage"
            >
              查看更多
            </view>
          </view>

          <view class="home-v2__list">
            <block
              v-for="(prod, index2) in item.prods"
              :key="index2"
            >
              <view
                class="home-v2__item"
                :data-prodid="prod.prodId"
                @tap="toProdPage"
              >
                <view class="home-v2__pic">
                  <img-show
                    :src="prod.pic"
                    :class-list="['home-v2__img']"
                  />
                </view>
                <view class="home-v2__meta">
                  <view class="home-v2__name">
                    {{ prod.prodName }}
                  </view>
                  <view class="home-v2__price">
                    <text v-if="prod.price !== null && prod.price !== undefined">
                      ￥{{ wxs.parsePrice(prod.price)[0] }}.{{ wxs.parsePrice(prod.price)[1] }}
                    </text>
                    <text v-else class="home-v2__priceTip">
                      价格需内部推荐可见
                    </text>
                  </view>
                  <view class="home-v2__stock">
                    <text v-if="prod.totalStocks !== null && prod.totalStocks !== undefined">
                      库存 {{ prod.totalStocks }}
                    </text>
                  </view>
                </view>
              </view>
            </block>
          </view>
        </view>
      </block>
    </view>
  </view>
</template>

<script setup>
const wxs = number()
const taglist = ref([])
const updata = ref(true)
const orderTitles = ['白酒', '啤酒', '红酒', '茶叶', '特产']

const banners = [
  { img: '/static/images/icon/bg1.png' },
  { img: '/static/images/icon/bg1.png' }
]

const notices = [
  '欢迎选购：内部推荐账号可查看价格与库存',
  '今晚 18:00 自动生成补货通知',
  '下单即扣库存（无需支付）'
]

onLoad(() => {
  getAllData()
})

onShow(() => {
  http.getCartCount()
})

onPullDownRefresh(() => {
  setTimeout(() => {
    getAllData()
    uni.stopPullDownRefresh()
  }, 100)
})

const getAllData = () => {
  http.getCartCount()
  getTag()
}

const quickActions = computed(() => {
  // 固定展示 5 个入口（顺序按 orderTitles）
  const map = new Map((taglist.value || []).map(t => [t.title, t]))
  const icons = [
    '/static/images/icon/menu-01.png',
    '/static/images/icon/menu-02.png',
    '/static/images/icon/menu-03.png',
    '/static/images/icon/menu-04.png',
    '/static/images/icon/menu-01.png'
  ]
  return orderTitles.map((title, idx) => ({
    title,
    tagId: map.get(title)?.id ?? 0,
    icon: icons[idx]
  }))
})

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
@import "./category.scss";
</style>
