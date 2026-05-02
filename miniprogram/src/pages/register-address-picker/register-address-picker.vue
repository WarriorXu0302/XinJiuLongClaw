<!--
  注册流程 - 配送地址选择页

  独立页，让地址输入不拥挤 register 表单：
    - 省/市/区 picker（/api/mall/regions 匿名拉取）
    - 详细门牌号 textarea
    - 确认后通过 getCurrentPages 回写到上一页 (register)

  返回数据格式：
    prevPage.deliveryAddress = "省市区 + 详细"
-->
<template>
  <view class="page">
    <view class="hint">
      请准确填写配送地址，方便业务员送货
    </view>

    <view class="card">
      <view class="field">
        <text class="field__label">
          所在地区
        </text>
        <picker
          mode="multiSelector"
          :value="pickerIndex"
          :range="pickerRange"
          range-key="name"
          @change="onPickerChange"
          @columnchange="onColumnChange"
        >
          <view class="field__picker">
            <text
              v-if="region.province"
              class="field__value"
            >
              {{ region.province }} {{ region.city }} {{ region.area }}
            </text>
            <text
              v-else
              class="field__placeholder"
            >
              选择省 / 市 / 区
            </text>
            <text class="field__arrow">
              ›
            </text>
          </view>
        </picker>
      </view>

      <view class="field field--textarea">
        <text class="field__label">
          详细地址
        </text>
        <textarea
          v-model="detail"
          class="field__textarea"
          maxlength="200"
          placeholder="街道 / 小区 / 门牌号，越详细越好"
          auto-height
        />
      </view>
    </view>

    <view class="actions">
      <button
        :class="['btn', canConfirm ? 'btn--primary' : 'btn--disabled']"
        :disabled="!canConfirm"
        @tap="onConfirm"
      >
        确认地址
      </button>
    </view>
  </view>
</template>

<script setup>
const region = ref({
  province: '',
  city: '',
  area: '',
  provinceCode: '',
  cityCode: '',
  areaCode: ''
})
const detail = ref('')

// 三级联动数据
const provList = ref([])
const cityList = ref([])
const areaList = ref([])
const pickerIndex = ref([0, 0, 0])

const pickerRange = computed(() => [provList.value, cityList.value, areaList.value])

const canConfirm = computed(() => {
  return !!(region.value.province && region.value.city && region.value.area && detail.value.trim())
})

const loadRegions = (parentCode) => {
  return http.request({
    url: '/api/mall/regions',
    method: 'GET',
    login: true,
    data: parentCode ? { parent_code: parentCode } : {}
  }).then(({ data }) => {
    // 后端返 [{areaId, parentId, areaName, level}]；picker 需要 {name, code}
    return (data || []).map(x => ({
      name: x.areaName,
      code: x.areaId
    }))
  })
}

const initPickers = async () => {
  provList.value = await loadRegions()
  if (provList.value.length) {
    cityList.value = await loadRegions(provList.value[0].code)
    if (cityList.value.length) {
      areaList.value = await loadRegions(cityList.value[0].code)
    }
  }
}

// 列级变动（前两列滚动时刷新下级）。异步里不读 pickerIndex.value 避免 race
const onColumnChange = async (e) => {
  const col = e.detail.column
  const idx = e.detail.value
  if (col === 0) {
    const newCityList = await loadRegions(provList.value[idx].code)
    cityList.value = newCityList
    // eslint-disable-next-line require-atomic-updates
    areaList.value = newCityList.length ? await loadRegions(newCityList[0].code) : []
    // eslint-disable-next-line require-atomic-updates
    pickerIndex.value = [idx, 0, 0]
  } else if (col === 1) {
    const newAreaList = await loadRegions(cityList.value[idx].code)
    areaList.value = newAreaList
    // eslint-disable-next-line require-atomic-updates
    pickerIndex.value = [pickerIndex.value[0], idx, 0]
  } else {
    pickerIndex.value = [pickerIndex.value[0], pickerIndex.value[1], idx]
  }
}

const onPickerChange = (e) => {
  pickerIndex.value = e.detail.value
  const p = provList.value[pickerIndex.value[0]]
  const c = cityList.value[pickerIndex.value[1]]
  const a = areaList.value[pickerIndex.value[2]]
  region.value = {
    province: p?.name || '',
    city: c?.name || '',
    area: a?.name || '',
    provinceCode: p?.code || '',
    cityCode: c?.code || '',
    areaCode: a?.code || ''
  }
}

const onConfirm = () => {
  if (!canConfirm.value) return
  const full = `${region.value.province}${region.value.city}${region.value.area} ${detail.value.trim()}`
  const pages = getCurrentPages()
  const prev = pages[pages.length - 2]
  if (prev) {
    // 回写到 register 页；register 页在 onShow 里读取并填表
    prev.$vm = prev.$vm || {}
    prev.$vm.pickedAddress = full
    prev.$vm.pickedAddressParts = {
      ...region.value,
      detail: detail.value.trim()
    }
  }
  uni.navigateBack()
}

onLoad(() => {
  uni.setNavigationBarTitle({ title: '选择配送地址' })
  initPickers()
})
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.page {
  min-height: 100vh;
  background: $color-cream;
  padding: 24rpx;
}

.hint {
  margin-bottom: 24rpx;
  padding: 16rpx 24rpx;
  background: rgba(201, 169, 97, 0.08);
  border-radius: 12rpx;
  color: $color-gold-deep;
  font-size: 24rpx;
}

.card {
  background: #fff;
  border-radius: 16rpx;
  padding: 24rpx;
}

.field {
  padding: 24rpx 0;
  border-bottom: 1rpx solid $color-line;

  &:last-child {
    border-bottom: none;
  }

  &__label {
    display: block;
    font-size: 26rpx;
    color: $color-hint;
    margin-bottom: 12rpx;
  }

  &__picker {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &__value {
    font-size: 30rpx;
    color: $color-ink-soft;
  }

  &__placeholder {
    font-size: 30rpx;
    color: $color-hint;
  }

  &__arrow {
    color: $color-hint;
    font-size: 36rpx;
  }

  &__textarea {
    width: 100%;
    font-size: 28rpx;
    color: $color-ink-soft;
    line-height: 1.6;
    min-height: 120rpx;
  }
}

.actions {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 24rpx 48rpx calc(24rpx + env(safe-area-inset-bottom));
  background: $color-cream;
}

.btn {
  width: 100%;
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 44rpx;
  text-align: center;
  font-size: 30rpx;
  font-weight: 600;

  &--primary {
    background: $color-gold;
    color: #fff;
  }

  &--disabled {
    background: $color-line;
    color: $color-hint;
  }

  &::after {
    border: 0;
  }
}
</style>
