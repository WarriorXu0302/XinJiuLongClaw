<template>
  <!-- 商品详情 -->
  <view class="container">
    <!-- 轮播图 -->
    <swiper
      :indicator-dots="indicatorDots"
      :autoplay="autoplay"
      :indicator-color="indicatorColor"
      :interval="interval"
      :duration="duration"
      :indicator-active-color="indicatorActiveColor"
    >
      <block
        v-for="(item, index) in imgs"
        :key="index"
      >
        <swiper-item>
          <image :src="item" />
        </swiper-item>
      </block>
    </swiper>
    <!-- end  轮播图 -->
    <!-- 商品信息 -->
    <view class="prod-info">
      <view class="tit-wrap">
        <view class="prod-tit">
          {{ prodName }}
        </view>
        <view
          class="col"
          @tap="addOrCannelCollection"
        >
          <image
            v-if="!isCollection"
            src="@/static/images/icon/prod-col.png"
          />
          <image
            v-if="isCollection"
            src="@/static/images/icon/prod-col-red.png"
          />
          收藏
        </view>
      </view>
      <view class="sales-p">
        {{ brief }}
      </view>
      <view class="prod-price">
        <text
          v-if="defaultSku && defaultSku.price"
          class="price"
        >
          ￥
          <text class="price-num">
            {{ wxs.parsePrice(defaultSku.price)[0] }}
          </text>
          .{{ wxs.parsePrice(defaultSku.price)[1] }}
        </text>
        <text
          v-else-if="defaultSku"
          class="price-hint"
        >
          联系业务员获取价格
        </text>
        <text
          v-if="defaultSku && defaultSku.oriPrice"
          class="ori-price"
        >
          ￥{{ wxs.parsePrice(defaultSku.oriPrice)[0] }}.{{ wxs.parsePrice(defaultSku.oriPrice)[1] }}
        </text>
        <text class="sales" />
      </view>
      <view class="prod-stock">
        <text v-if="canOperateTrade && stockNum !== null">
          库存：{{ stockNum }}
        </text>
      </view>
    </view>
    <!-- 已选规格 -->
    <view
      class="sku"
      @tap="showSku"
    >
      <view class="sku-tit">
        已选
      </view>
      <view class="sku-con">
        {{ selectedProp.length > 0 ? selectedProp + '，' : '' }}{{ prodNum }}件
      </view>
      <view class="more">
        ...
      </view>
    </view>
    <!-- 商品详情 -->
    <view class="prod-detail">
      <view>
        <rich-text :nodes="content" />
      </view>
    </view>
    <!-- end 商品详情 -->

    <!-- 底部按钮 -->
    <view class="cart-footer">
      <view
        class="btn icon"
        @tap="toHomePage"
      >
        <image src="@/static/images/tabbar/homepage.png" />
        首页
      </view>
      <view
        class="btn icon"
        @tap="toCartPage"
      >
        <image src="@/static/images/tabbar/basket.png" />
        购物车
        <view
          v-if="totalCartNum>0"
          class="badge badge-1"
        >
          {{ totalCartNum }}
        </view>
      </view>
      <view
        class="btn cart"
        @tap="onTapCartOrBuy"
      >
        <text>加入购物车</text>
      </view>
      <view
        class="btn buy"
        @tap="onTapCartOrBuy"
      >
        <text>立即购买</text>
      </view>
    </view>
    <!-- end 底部按钮 -->

    <!-- 规格弹窗 -->
    <view
      v-if="skuShow"
      class="pup-sku"
    >
      <view class="pup-sku-main">
        <view class="pup-sku-header">
          <image
            class="pup-sku-img"
            :src="defaultSku.pic?defaultSku.pic:pic"
          />
          <view class="pup-sku-price">
            ￥
            <text
              v-if="defaultSku && defaultSku.price"
              class="pup-sku-price-int"
            >
              {{ wxs.parsePrice(defaultSku.price)[0] }}
            </text>
            .{{ wxs.parsePrice(defaultSku.price)[1] }}
          </view>
          <view class="pup-sku-prop">
            <text>已选</text>
            {{ selectedProp.length > 0 ? selectedProp + '，' : '' }}{{ prodNum }}件
          </view>
          <view
            class="close"
            @tap="closePopup"
          />
        </view>
        <view class="pup-sku-body">
          <view class="pup-sku-area">
            <view
              v-if="skuList.length"
              class="sku-box"
            >
              <block
                v-for="(skuGroupItem, skuGroupItemIndex) in skuGroupList"
                :key="skuGroupItemIndex"
              >
                <view
                  v-for="(skuLine, key) in skuGroupItem"
                  :key="key"
                  class="items sku-text"
                >
                  <text class="sku-kind">
                    {{ key }}
                  </text>
                  <view class="con">
                    <text
                      v-for="skuLineItem in skuLine"
                      :key="skuLineItem"
                      class="sku-choose-item"
                      :class="[selectedPropList.indexOf(key + ':' + skuLineItem) !== -1?'active':'',
                               isSkuLineItemNotOptional(allProperties,selectedPropObj,key,skuLineItem,propKeys)? 'dashed' : '']"
                      @click="toChooseItem(skuGroupItemIndex, skuLineItem, key)"
                    >
                      {{ skuLineItem }}
                    </text>
                  </view>
                </view>
              </block>
            </view>
          </view>
          <view class="pup-sku-count">
            <view class="num-wrap">
              <view
                class="minus"
                @tap="onCountMinus"
              >
                <text class="row" />
              </view>
              <view class="text-wrap">
                <input
                  type="number"
                  :value="prodNum"
                  disabled
                >
              </view>
              <view
                class="plus"
                @tap="onCountPlus"
              >
                <text class="row" />
                <text class="col" />
              </view>
            </view>
            <view class="count-name">
              数量
            </view>
          </view>
        </view>
        <view class="pup-sku-footer">
          <view
            class="btn cart"
            @tap="addToCart"
          >
            加入购物车
          </view>
          <view
            class="btn buy"
            @tap="buyNow"
          >
            立即购买
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
const wxs = number()

const indicatorDots = ref(true)
const indicatorColor = ref('rgba(14, 14, 14, 0.15)')
const indicatorActiveColor = ref('#C9A961')
const autoplay = ref(true)
const interval = ref(3000)
const duration = ref(1000)
const selectedProp = ref([])
let prodId = 0
/**
 * 生命周期函数--监听页面加载
 */
onLoad((options) => {
  prodId = options.prodid
  // 加载商品数据
  getProdInfo()
  // 查看用户是否关注
  getCollection()
})

const app = getApp()

const canOperateTrade = computed(() => {
  // 后端无权限时会把价格置空
  return !!(defaultSku.value && defaultSku.value.price !== null && defaultSku.value.price !== undefined)
})

const stockNum = computed(() => {
  const sku = defaultSku.value
  if (!sku) {
    return null
  }
  const val = (sku.actualStocks ?? sku.stocks)
  if (val === null || val === undefined) {
    return null
  }
  const n = Number(val)
  return Number.isFinite(n) ? n : null
})

const onTapCartOrBuy = () => {
  if (!canOperateTrade.value) {
    uni.showToast({
      title: '需内部员工推荐注册/登录后才可加购下单',
      icon: 'none'
    })
    return
  }
  showSku()
}
const totalCartNum = ref(0)
/**
 * 生命周期函数--监听页面显示
 */
onShow(() => {
  totalCartNum.value = app.globalData.totalCartCount
})

/**
 * 分享设置
 */
onShareAppMessage(() => {
  return {
    title: prodName.value,
    path: '/pages/prod/prod?prodid=' + prodId
  }
})

const isCollection = ref(false)
/**
 * 查询当前商品是否已收藏
 */
const getCollection = () => {
  if (!uni.getStorageSync('Token')) {
    return
  }
  http.request({
    url: '/api/mall/collections/check',
    method: 'GET',
    data: { product_id: prodId }
  }).then(({ data }) => {
    isCollection.value = Array.isArray(data?.collected) &&
      data.collected.map(String).includes(String(prodId))
  }).catch(() => {
    isCollection.value = false
  })
}

/**
 * 添加或取消收藏
 */
const addOrCannelCollection = () => {
  if (!uni.getStorageSync('Token')) {
    uni.navigateTo({ url: '/pages/accountLogin/accountLogin' })
    return
  }
  if (isCollection.value) {
    http.request({
      url: `/api/mall/collections/${prodId}`,
      method: 'DELETE'
    }).then(() => {
      isCollection.value = false
      uni.showToast({ title: '已取消收藏', icon: 'none' })
    }).catch(() => {
      uni.showToast({ title: '操作失败', icon: 'none' })
    })
  } else {
    http.request({
      url: '/api/mall/collections',
      method: 'POST',
      data: { product_id: Number(prodId) }
    }).then(() => {
      isCollection.value = true
      uni.showToast({ title: '已收藏', icon: 'none' })
    }).catch(() => {
      uni.showToast({ title: '操作失败', icon: 'none' })
    })
  }
}

const skuList = ref([])
const brief = ref('')
const prodNum = ref(1)
const pic = ref('')
const imgs = ref('')
const prodName = ref('')
const price = ref(0)
const content = ref('')
/**
 * 获取商品信息
 */
const getProdInfo = () => {
  uni.showLoading()
  http.request({
    url: `/api/mall/products/${prodId}`,
    method: 'GET',
    data: {}
  })
    .then(({ data }) => {
      uni.hideLoading()
      if (!data) {
        setTimeout(() => {
          uni.navigateBack()
        }, 1000)
        return
      }
      // 后端返数组（JSONB），老协议是逗号字符串；两种都兼容
      imgs.value = Array.isArray(data.imgs) ? data.imgs : (typeof data.imgs === 'string' ? data.imgs.split(',') : [])
      content.value = util.formatHtml(data.content)
      price.value = data.price
      prodName.value = data.prodName
      prodId = data.prodId
      brief.value = data.brief
      skuList.value = data.skuList
      pic.value = data.pic
      // 组装sku
      groupSkuProp(data.skuList, data.price)
      uni.hideLoading()
    })
}

let selectedPropObjList = null
const skuGroup = ref({})
const defaultSku = ref(null)
const selectedPropObj = ref({})
const propKeys = ref([])
const allProperties = ref([])
const findSku = ref(true)
const skuGroupList = ref([])
/**
 * 组装SKU
 */
const groupSkuProp = (skuList, defaultPrice) => {
  if (skuList.length === 1 && !skuList[0].properties) {
    defaultSku.value = skuList[0]
    findSku.value = true
    return
  }
  const _skuGroupList = []
  const skuGroupParam = {}
  const _allProperties = []
  const _propKeys = []
  const _selectedPropObj = {}
  const selectedPropObjListParam = []

  let defaultSkuParam = null
  for (let i = 0; i < skuList.length; i++) {
    let isDefault = false
    if (!defaultSkuParam && skuList[i].price == defaultPrice) {
      defaultSkuParam = skuList[i]
      isDefault = true
    }
    // 后端 MallSkuVO 无 properties 字段；当前 mall SKU 都是单规格不走本分支
    // 老 mall4j 协议下 properties 是 "版本:公开版;颜色:金色" 分号分隔字符串
    const properties = skuList[i].properties || ''
    _allProperties.push(properties)
    if (!properties) continue // 没规格属性跳过（避免 split 崩）
    const propList = properties.split(';') // ["版本:公开版","颜色:金色","内存:64GB"]
    for (let j = 0; j < propList.length; j++) {
      const propval = propList[j].split(':') // ["版本","公开版"]
      let props = skuGroupParam[propval[0]] // 先取出 版本对应的值数组
      // 如果当前是默认选中的sku，把对应的属性值 组装到selectedProp
      if (isDefault) {
        _propKeys.push(propval[0])
        _selectedPropObj[propval[0]] = propval[1]
        const selectedPropObjItem = {}
        selectedPropObjItem[propval[0]] = propval[1]
        selectedPropObjListParam.push(selectedPropObjItem)
      }
      if (!props) {
        props = [] // 假设还没有版本，新建个新的空数组
        props.push(propval[1]) // 把 "公开版" 放进空数组
      } else {
        if (props.indexOf(propval[1]) === -1) { // 如果数组里面没有"公开版"
          props.push(propval[1]) // 把 "公开版" 放进数组
        }
      }
      skuGroupParam[propval[0]] = props // 最后把数据 放回版本对应的值
      const propListItem = {}
      propListItem[propval[0]] = props
      _skuGroupList.push(propListItem)
    }
  }
  defaultSku.value = defaultSkuParam
  propKeys.value = _propKeys
  selectedPropObj.value = _selectedPropObj
  skuGroup.value = skuGroupParam
  selectedPropObjList = selectedPropObjListParam
  skuGroupList.value = unique(_skuGroupList)
  allProperties.value = _allProperties
  parseSelectedObjToVals(skuList)
}

const selectedPropList = ref(null)
/**
 * 将已选的 {key:val,key2:val2}转换成 [val,val2]
 */
const parseSelectedObjToVals = (skuList) => {
  const selectedPropObjListParam = selectedPropObjList
  let selectedPropertiesParam = ''
  const selectedPropListParam = []
  const selectedPropShowListParam = []
  for (let i = 0; i < selectedPropObjListParam.length; i++) {
    const selectedPropObjItem = selectedPropObjListParam[i]
    for (const key in selectedPropObjItem) {
      if (Object.hasOwnProperty.call(selectedPropObjItem, key)) {
        selectedPropListParam.push(key + ':' + selectedPropObjItem[key])
        selectedPropShowListParam.push(selectedPropObjItem[key])
        selectedPropertiesParam += key + ':' + selectedPropObjItem[key] + ';'
      }
    }
  }
  selectedPropertiesParam = selectedPropertiesParam.substring(0, selectedPropertiesParam.length - 1)
  selectedPropList.value = selectedPropListParam
  selectedPropObjList = selectedPropObjListParam
  let findSkuParam = false
  for (let i = 0; i < skuList.length; i++) {
    if (skuList[i].properties == selectedPropertiesParam) {
      findSkuParam = true
      defaultSku.value = skuList[i]
      break
    }
  }
  findSku.value = findSkuParam
}

/**
 * 判断当前的规格值 是否可以选
 */
const isSkuLineItemNotOptional = (allProperties, selectedPropObjParam, key, item, propKeys) => {
  const selectedPropObj = Object.assign({}, selectedPropObjParam)
  let properties = ''
  selectedPropObj[key] = item
  for (let j = 0; j < propKeys.length; j++) {
    properties += propKeys[j] + ':' + selectedPropObj[propKeys[j]] + ';'
  }
  properties = properties.substring(0, properties.length - 1)
  for (let i = 0; i < allProperties.length; i++) {
    if (properties == allProperties[i]) {
      return false
    }
  }
  for (let i = 0; i < allProperties.length; i++) {
    if (allProperties[i].indexOf(item) >= 0) {
      return true
    }
  }
  return false
}

/**
 * 规格点击事件
 */
const toChooseItem = (skuGroupItemIndex, skuLineItem, key) => {
  selectedPropObjList[skuGroupItemIndex][key] = skuLineItem
  selectedPropObj.value[key] = skuLineItem
  parseSelectedObjToVals(skuList.value)
}

/**
 * 去重
 */
const unique = (arr) => {
  const map = {}
  arr.forEach(item => {
    const obj = {}
    Object.keys(item).sort().map(key => (obj[key] = item[key]))
    map[JSON.stringify(obj)] = item
  })
  return Object.keys(map).map(key => JSON.parse(key))
}

/**
 * 跳转到首页
 */
const toHomePage = () => {
  uni.switchTab({
    url: '/pages/index/index'
  })
}

/**
 * 跳转到购物车
 */
const toCartPage = () => {
  uni.switchTab({
    url: '/pages/basket/basket'
  })
}

const shopId = 1
/**
 * 加入购物车
 */
const addToCart = () => {
  uni.showLoading({
    mask: true
  })
  http.request({
    url: '/api/mall/cart/change',
    method: 'POST',
    data: {
      count: prodNum.value,
      prodId,
      skuId: defaultSku.value.skuId
    }
  })
    .then(() => {
      totalCartNum.value = totalCartNum.value + prodNum.value
      uni.hideLoading()
      uni.showToast({
        title: '加入购物车成功',
        icon: 'none'
      })
    })
}

/**
 * 立即购买
 */
const buyNow = () => {
  uni.setStorageSync('orderItem', JSON.stringify({
    prodId,
    skuId: defaultSku.value.skuId,
    prodCount: prodNum.value,
    shopId
  }))
  uni.navigateTo({
    url: '/pages/submit-order/submit-order?orderEntry=1'
  })
}

/**
 * 减数量
 */
const onCountMinus = () => {
  if (prodNum.value > 1) {
    prodNum.value = prodNum.value - 1
  }
}

/**
 * 加数量
 */
const onCountPlus = () => {
  if (prodNum.value < 1000) {
    prodNum.value = prodNum.value + 1
  }
}

const skuShow = ref(false)
const showSku = () => {
  skuShow.value = true
}

const commentShow = ref(false)

const closePopup = () => {
  skuShow.value = false
  commentShow.value = false
}
</script>

<style scoped lang="scss">
@use './prod.scss';
</style>
