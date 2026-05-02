<!--
  业务员 - 打卡中心
  对齐 ERP 业务逻辑：
    - 上班/下班：CheckinRecord(work_in/work_out)，同一天每类型一条
    - 拜访：CustomerVisit 单条记录含 enter+leave；进店 → 选 B2B 客户 → 出店时自动算时长，≥30 分钟为有效
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        打卡中心
      </view>
      <view class="header__time">
        {{ now }}
      </view>
    </view>

    <view class="tabs">
      <view
        v-for="t in tabs"
        :key="t.key"
        :class="['tabs__item', mode === t.key && 'tabs__item--active']"
        @tap="mode = t.key"
      >
        {{ t.label }}
      </view>
    </view>

    <view
      v-if="mode !== 'visit'"
      class="big-btn"
    >
      <view
        :class="['big-btn__ring', !workDone && 'big-btn__ring--active', workDone && 'big-btn__ring--done']"
        @tap="onWorkCheckin"
      >
        <text class="big-btn__label">
          {{ workDone ? '今日已打卡' : (mode === 'work_in' ? '上班打卡' : '下班打卡') }}
        </text>
        <text class="big-btn__sub">
          {{ workDone ? `于 ${workDoneAt}` : '点击打卡' }}
        </text>
      </view>
    </view>

    <view
      v-else
      class="visit"
    >
      <view
        v-if="activeVisit"
        class="visit__active"
      >
        <view class="visit__badge">
          进店中
        </view>
        <view class="visit__name">
          {{ activeVisit.customer_name }}
        </view>
        <view class="visit__sub">
          进店于 {{ fmtEnter }}
        </view>
        <view class="visit__counter">
          {{ activeMinutes }} 分钟
        </view>
        <view class="visit__hint">
          {{ activeMinutes >= 30 ? '已达有效拜访时长' : `再 ${30 - activeMinutes} 分钟为有效拜访` }}
        </view>
        <view
          class="visit__btn visit__btn--leave"
          @tap="onLeave"
        >
          离店打卡
        </view>
      </view>
      <view
        v-else
        class="visit__enter"
      >
        <view class="visit__title">
          客户拜访（需 ≥ 30 分钟）
        </view>
        <picker
          :value="pickerIndex"
          :range="customers.map(c => c.name)"
          @change="onPickCustomer"
        >
          <view class="visit__picker">
            <text>{{ pickedCustomer ? pickedCustomer.name : '选择拜访客户' }}</text>
            <text class="visit__arrow">
              ›
            </text>
          </view>
        </picker>
        <view
          v-if="pickedCustomer"
          class="visit__meta"
        >
          <text>{{ pickedCustomer.code }} · {{ pickedCustomer.contact_name }}</text>
          <text>{{ pickedCustomer.address }}</text>
        </view>
        <view
          class="visit__btn"
          @tap="onEnter"
        >
          进店打卡
        </view>
      </view>
    </view>

    <view class="info">
      <view class="info__row">
        <text class="info__key">
          位置
        </text>
        <text class="info__val">
          {{ location || '定位中…' }}
        </text>
      </view>
      <view class="info__row">
        <text class="info__key">
          打卡照
        </text>
        <view class="info__val">
          <view
            v-if="photo"
            class="info__photo"
            :style="{ backgroundImage: `url(${photo})` }"
          />
          <view
            v-else
            class="info__choose"
            @tap="onChoosePhoto"
          >
            <text>+ 拍照</text>
          </view>
        </view>
      </view>
    </view>

    <view class="tip">
      <text v-if="mode === 'work_in'">
        上班 9:10 前为正常，超过记迟到；需位于公司范围内（200 米）。
      </text>
      <text v-else-if="mode === 'work_out'">
        下班未打卡将影响考勤，建议每日 18:00 后及时打卡。
      </text>
      <text v-else>
        拜访时长 ≥ 30 分钟为有效；离店后自动计入考勤与拜访目标（6 家/日）。
      </text>
    </view>
  </view>
</template>

<script setup>
const tabs = [
  { key: 'work_in', label: '上班' },
  { key: 'work_out', label: '下班' },
  { key: 'visit', label: '拜访' }
]
const mode = ref('work_in')
// coords 是结构化定位结果，符合 ERP CheckinRecord(longitude/latitude/address)
const coords = ref(null)
const location = computed(() => {
  if (!coords.value) return ''
  if (coords.value.error) return coords.value.error
  return coords.value.address || `${coords.value.latitude.toFixed(4)}, ${coords.value.longitude.toFixed(4)}`
})
// 三个模式各自独立的照片，切 tab / 进店 / 离店 之间不互相污染
const photos = reactive({ work_in: '', work_out: '', visit_enter: '', visit_leave: '' })
const photo = computed({
  get: () => photos[photoKey.value],
  set: (v) => { photos[photoKey.value] = v }
})
const photoKey = computed(() => {
  if (mode.value !== 'visit') return mode.value
  return activeVisit.value ? 'visit_leave' : 'visit_enter'
})
const now = ref('')
let timer = null

// 当日已打卡状态（防重复打卡）
const todayStatus = ref({ work_in: null, work_out: null })
const workDone = computed(() => mode.value !== 'visit' && !!todayStatus.value[mode.value])
const workDoneAt = computed(() => {
  const t = todayStatus.value[mode.value]?.checkin_time
  if (!t) return ''
  const d = new Date(t)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
})

// 拜访相关
const customers = ref([])
const pickerIndex = ref(-1)
const pickedCustomer = computed(() => customers.value[pickerIndex.value])
const activeVisit = ref(null)
const activeMinutes = ref(0)
let activeTimer = null

const fmtEnter = computed(() => {
  if (!activeVisit.value?.enter_time) return ''
  const d = new Date(activeVisit.value.enter_time)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
})

const updateTime = () => {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  now.value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

const getLoc = ({ fresh = false } = {}) => {
  // 返回 Promise 方便提交前 await；fresh=true 强制重取不用缓存
  return new Promise((resolve) => {
    uni.getLocation({
      type: 'gcj02',
      geocode: true,
      isHighAccuracy: fresh,
      success: (res) => {
        coords.value = {
          longitude: res.longitude,
          latitude: res.latitude,
          address: res.address?.name || res.address?.street || '',
          accuracy: res.accuracy
        }
        resolve(coords.value)
      },
      fail: () => {
        coords.value = { error: '定位失败（请开启定位权限）' }
        resolve(null)
      }
    })
  })
}

const onChoosePhoto = () => {
  uni.chooseImage({
    count: 1,
    sourceType: ['camera'],
    sizeType: ['compressed'],
    success: (res) => {
      photo.value = res.tempFilePaths[0]
    }
  })
}

// 提交前都要重新取一次定位，防止用户从公司走到客户店里半小时后还发进店坐标
const ensureFreshLoc = async () => {
  await getLoc({ fresh: true })
  if (!coords.value || coords.value.error) {
    uni.showToast({ title: '请先授权定位', icon: 'none' })
    return null
  }
  return coords.value
}

const locPayload = (c) => ({
  longitude: c.longitude,
  latitude: c.latitude,
  address: c.address || null
})

const onWorkCheckin = async () => {
  if (workDone.value) {
    uni.showToast({ title: '今日已打过卡', icon: 'none' })
    return
  }
  const c = await ensureFreshLoc()
  if (!c) return
  uni.showLoading({ title: '打卡中…' })
  try {
    const res = await http.request({
      url: '/api/mall/workspace/attendance/checkin',
      method: 'POST',
      data: {
        checkin_type: mode.value,
        ...locPayload(c),
        selfie_url: photo.value || null
      }
    })
    // eslint-disable-next-line require-atomic-updates
    todayStatus.value[mode.value] = res.data || { checkin_time: new Date().toISOString() }
    uni.hideLoading()
    uni.showToast({ title: '打卡成功', icon: 'success' })
    setTimeout(() => uni.navigateBack(), 800)
  } catch (e) {
    uni.hideLoading()
    uni.showToast({ title: e?.msg || '打卡失败', icon: 'none' })
  }
}

const loadTodayStatus = async () => {
  try {
    const res = await http.request({
      url: '/api/mall/workspace/attendance/today',
      method: 'GET'
    })
    todayStatus.value = {
      work_in: res.data?.work_in || null,
      work_out: res.data?.work_out || null
    }
  } catch {
    // 拉今日打卡状态失败不阻塞主流程；业务员仍可继续打卡
  }
}

const loadCustomers = async () => {
  const res = await http.request({
    url: '/api/mall/workspace/customers',
    method: 'GET'
  })
  customers.value = res.data?.records || []
}

const loadActiveVisit = async () => {
  const res = await http.request({
    url: '/api/mall/workspace/attendance/visits/active',
    method: 'GET'
  })
  activeVisit.value = res.data || null
  if (activeVisit.value) startActiveTimer()
}

const onPickCustomer = (e) => {
  pickerIndex.value = Number(e.detail.value)
}

const onEnter = async () => {
  if (!pickedCustomer.value) {
    uni.showToast({ title: '请选择客户', icon: 'none' })
    return
  }
  const c = await ensureFreshLoc()
  if (!c) return
  const res = await http.request({
    url: '/api/mall/workspace/attendance/visits/enter',
    method: 'POST',
    data: {
      customer_id: pickedCustomer.value.id,
      ...locPayload(c),
      enter_photo_url: photo.value || null
    }
  })
  activeVisit.value = {
    visit_id: res.data.visit_id,
    customer_id: pickedCustomer.value.id,
    customer_name: pickedCustomer.value.name,
    enter_time: res.data.enter_time
  }
  startActiveTimer()
  uni.showToast({ title: '已进店', icon: 'success' })
}

const tickActiveMinutes = () => {
  if (!activeVisit.value) return
  const start = new Date(activeVisit.value.enter_time).getTime()
  activeMinutes.value = Math.max(0, Math.floor((Date.now() - start) / 60000))
}
const startActiveTimer = () => {
  if (activeTimer) clearInterval(activeTimer)
  tickActiveMinutes()
  activeTimer = setInterval(tickActiveMinutes, 10000)
}

const onLeave = () => {
  // 先立刻 tick 一次，确保弹框里的分钟数和实际一致（避免卡在 29 分钟的定时器间隙里）
  tickActiveMinutes()
  uni.showModal({
    title: '离店打卡',
    content: `已拜访 ${activeMinutes.value} 分钟，${activeMinutes.value >= 30 ? '计入有效拜访' : '时长不足 30 分钟将记为无效'}，确认离店？`,
    success: async (r) => {
      if (!r.confirm) return
      const c = await ensureFreshLoc()
      if (!c) return
      const res = await http.request({
        url: '/api/mall/workspace/attendance/visits/leave',
        method: 'POST',
        data: {
          visit_id: activeVisit.value.visit_id,
          ...locPayload(c),
          leave_photo_url: photo.value || null
        }
      })
      if (activeTimer) clearInterval(activeTimer)
      /* eslint-disable require-atomic-updates */
      activeVisit.value = null
      activeMinutes.value = 0
      pickerIndex.value = -1
      photos.visit_enter = ''
      photos.visit_leave = ''
      /* eslint-enable require-atomic-updates */
      uni.showToast({
        title: res.data?.is_valid ? '有效拜访' : '已记录',
        icon: 'success'
      })
    }
  })
}

onLoad((q) => {
  if (q?.mode === 'visit' || q?.mode === 'work_in' || q?.mode === 'work_out') {
    mode.value = q.mode
  } else {
    mode.value = new Date().getHours() < 12 ? 'work_in' : 'work_out'
  }
})

onMounted(() => {
  updateTime()
  timer = setInterval(updateTime, 1000)
  getLoc()
  loadCustomers()
  loadActiveVisit()
  loadTodayStatus()
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (activeTimer) clearInterval(activeTimer)
})
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.page {
  min-height: 100vh;
  background: $color-cream;
  padding-bottom: 40rpx;
}

.header {
  padding: 40rpx 32rpx;
  background: $color-ink;
  color: #fff;

  &__title {
    font-size: 40rpx;
    font-weight: 600;
    color: $color-gold;
  }
  &__time {
    margin-top: 8rpx;
    font-size: 26rpx;
    color: $color-gold-soft;
    font-family: Menlo, Consolas, monospace;
  }
}

.tabs {
  margin: 24rpx;
  display: flex;
  padding: 8rpx;
  background: $color-line-soft;
  border-radius: 40rpx;

  &__item {
    flex: 1;
    padding: 16rpx 0;
    text-align: center;
    border-radius: 36rpx;
    font-size: 26rpx;
    color: $color-muted;

    &--active {
      background: $color-ink;
      color: $color-gold;
      font-weight: 600;
    }
  }
}

.big-btn {
  padding: 40rpx 0 24rpx;
  display: flex;
  justify-content: center;

  &__ring {
    width: 360rpx;
    height: 360rpx;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(201,169,97,0.08) 0%, rgba(201,169,97,0.2) 100%);
    border: 8rpx solid $color-gold-soft;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    transition: all 0.25s;

    &--active {
      background: radial-gradient(circle, $color-gold 0%, $color-gold-deep 100%);
      border-color: $color-gold-deep;
      box-shadow: 0 10rpx 40rpx rgba(201,169,97,0.4);
    }
    &--done {
      background: $color-line-soft;
      border-color: $color-line;
      opacity: 0.8;
    }
  }

  &__label {
    font-size: 40rpx;
    font-weight: 700;
    color: $color-ink;
    letter-spacing: 4rpx;
  }
  &__sub {
    margin-top: 16rpx;
    font-size: 24rpx;
    color: $color-ink-soft;
  }
}

.visit {
  margin: 0 24rpx;

  &__active {
    padding: 40rpx 32rpx;
    background: linear-gradient(135deg, #0E0E0E 0%, #2A211B 100%);
    color: #fff;
    border-radius: 16rpx;
  }
  &__badge {
    font-size: 22rpx;
    color: $color-gold-soft;
  }
  &__name {
    margin-top: 16rpx;
    font-size: 36rpx;
    font-weight: 700;
    color: $color-gold;
  }
  &__sub {
    margin-top: 8rpx;
    font-size: 22rpx;
    color: rgba(255,255,255,0.6);
  }
  &__counter {
    margin-top: 24rpx;
    font-size: 80rpx;
    font-weight: 700;
    color: #fff;
    font-family: Menlo, Consolas, monospace;
  }
  &__hint {
    margin-top: 8rpx;
    font-size: 22rpx;
    color: $color-gold-soft;
  }

  &__enter {
    padding: 32rpx;
    background: $color-card;
    border-radius: 16rpx;
  }
  &__title {
    font-size: 26rpx;
    font-weight: 600;
    color: $color-ink-soft;
    margin-bottom: 16rpx;
  }
  &__picker {
    padding: 24rpx 32rpx;
    background: $color-cream;
    border-radius: 12rpx;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 28rpx;
    color: $color-ink-soft;
  }
  &__arrow { color: $color-hint; }
  &__meta {
    margin-top: 12rpx;
    display: flex;
    flex-direction: column;
    gap: 6rpx;
    padding: 0 8rpx;
    font-size: 22rpx;
    color: $color-muted;
  }
  &__btn {
    margin-top: 24rpx;
    padding: 24rpx 0;
    background: $color-ink;
    color: $color-gold;
    text-align: center;
    font-weight: 600;
    border-radius: 12rpx;
    letter-spacing: 2rpx;

    &--leave {
      background: $color-gold;
      color: $color-ink;
    }
  }
}

.info {
  margin: 24rpx;
  padding: 24rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;

  &__row {
    display: flex;
    align-items: center;
    padding: 16rpx 0;
    border-bottom: 1rpx solid $color-line-soft;

    &:last-child { border-bottom: none; }
  }
  &__key {
    width: 140rpx;
    color: $color-muted;
    font-size: 26rpx;
  }
  &__val {
    flex: 1;
    font-size: 26rpx;
    color: $color-ink-soft;
  }
  &__photo {
    width: 140rpx;
    height: 140rpx;
    background-size: cover;
    background-position: center;
    border-radius: 8rpx;
  }
  &__choose {
    width: 140rpx;
    height: 140rpx;
    background: $color-cream;
    border: 2rpx dashed $color-line;
    border-radius: 8rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    color: $color-hint;
    font-size: 24rpx;
  }
}

.tip {
  margin: 24rpx;
  padding: 16rpx 24rpx;
  background: rgba(201,169,97,0.08);
  border-radius: 8rpx;
  font-size: 22rpx;
  color: $color-muted;
  line-height: 1.5;
}
</style>
