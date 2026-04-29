<!--
  业务员 - 请假申请
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        请假申请
      </view>
      <view
        class="header__new"
        @tap="showForm = !showForm"
      >
        {{ showForm ? '取消' : '+ 新建' }}
      </view>
    </view>

    <view
      v-if="showForm"
      class="form"
    >
      <view class="form__item">
        <text class="form__label">
          假期类型
        </text>
        <picker
          :value="form.typeIndex"
          :range="leaveTypes"
          @change="onTypeChange"
        >
          <view class="form__val">
            <text>{{ leaveTypes[form.typeIndex] }}</text>
            <text class="form__arrow">
              ›
            </text>
          </view>
        </picker>
      </view>

      <view class="form__item">
        <text class="form__label">
          开始日期
        </text>
        <picker
          mode="date"
          :value="form.start_date"
          @change="(e) => form.start_date = e.detail.value"
        >
          <view class="form__val">
            {{ form.start_date || '选择日期' }}
          </view>
        </picker>
      </view>

      <view class="form__item">
        <text class="form__label">
          结束日期
        </text>
        <picker
          mode="date"
          :value="form.end_date"
          @change="(e) => form.end_date = e.detail.value"
        >
          <view class="form__val">
            {{ form.end_date || '选择日期' }}
          </view>
        </picker>
      </view>

      <view class="form__item form__item--textarea">
        <text class="form__label">
          事由
        </text>
        <textarea
          v-model="form.reason"
          class="form__textarea"
          placeholder="请说明请假事由"
          maxlength="200"
        />
      </view>

      <view
        class="form__submit"
        @tap="onSubmit"
      >
        提交申请
      </view>
    </view>

    <view class="section">
      <view class="section__title">
        申请记录
      </view>
      <view
        v-if="records.length === 0"
        class="section__empty"
      >
        暂无记录
      </view>
      <view
        v-for="r in records"
        :key="r.request_no"
        class="row"
      >
        <view class="row__top">
          <text class="row__no">
            {{ r.request_no }}
          </text>
          <text :class="['row__status', 'row__status--' + r.status]">
            {{ statusMap[r.status] }}
          </text>
        </view>
        <view class="row__body">
          <text>{{ typeMap[r.leave_type] }} · {{ r.total_days }} 天</text>
        </view>
        <view class="row__meta">
          {{ r.start_date }} ~ {{ r.end_date }}
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
const showForm = ref(false)
const form = ref({
  typeIndex: 0,
  start_date: '',
  end_date: '',
  reason: ''
})
const records = ref([])

const leaveTypes = ['事假', '病假', '年假', '调休']
const typeCodes = ['personal', 'sick', 'annual', 'overtime_off']
const typeMap = {
  personal: '事假',
  sick: '病假',
  annual: '年假',
  overtime_off: '调休'
}
const statusMap = {
  pending: '审批中',
  approved: '已通过',
  rejected: '已驳回'
}

const onTypeChange = (e) => {
  form.value.typeIndex = Number(e.detail.value)
}

const load = async () => {
  const res = await http.request({
    url: '/api/mall/workspace/leave-requests',
    method: 'GET'
  })
  records.value = res.data?.records || []
}

const onSubmit = async () => {
  if (!form.value.start_date || !form.value.end_date) {
    uni.showToast({ title: '请选择起止日期', icon: 'none' })
    return
  }
  if (!form.value.reason.trim()) {
    uni.showToast({ title: '请填写事由', icon: 'none' })
    return
  }
  await http.request({
    url: '/api/mall/workspace/leave-requests',
    method: 'POST',
    data: {
      leave_type: typeCodes[form.value.typeIndex],
      start_date: form.value.start_date,
      end_date: form.value.end_date,
      reason: form.value.reason
    }
  })
  const next = { typeIndex: 0, start_date: '', end_date: '', reason: '' }
  uni.showToast({ title: '已提交', icon: 'success' })
  showForm.value = false
  // eslint-disable-next-line require-atomic-updates
  form.value = next
  load()
}

onMounted(() => load())
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
  display: flex;
  justify-content: space-between;
  align-items: center;

  &__title {
    font-size: 40rpx;
    font-weight: 600;
    color: $color-gold;
  }
  &__new {
    padding: 10rpx 24rpx;
    border: 1rpx solid $color-gold;
    color: $color-gold;
    font-size: 24rpx;
    border-radius: 24rpx;
  }
}

.form {
  margin: 24rpx;
  padding: 24rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;

  &__item {
    padding: 20rpx 0;
    border-bottom: 1rpx solid $color-line-soft;

    &--textarea { border-bottom: none; }
  }
  &__label {
    display: block;
    font-size: 24rpx;
    color: $color-muted;
    margin-bottom: 12rpx;
  }
  &__val {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 28rpx;
    color: $color-ink-soft;
  }
  &__arrow { color: $color-hint; }
  &__textarea {
    width: 100%;
    min-height: 180rpx;
    padding: 16rpx 20rpx;
    background: $color-cream;
    border-radius: 12rpx;
    font-size: 26rpx;
    color: $color-ink-soft;
  }
  &__submit {
    margin-top: 24rpx;
    padding: 24rpx 0;
    background: $color-ink;
    color: $color-gold;
    text-align: center;
    font-weight: 600;
    border-radius: 12rpx;
    letter-spacing: 2rpx;
  }
}

.section {
  margin: 24rpx;
  padding: 24rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;

  &__title {
    font-size: 28rpx;
    font-weight: 600;
    color: $color-ink-soft;
    margin-bottom: 12rpx;
    padding-left: 12rpx;
    border-left: 6rpx solid $color-gold;
  }
  &__empty {
    padding: 40rpx 0;
    text-align: center;
    color: $color-hint;
  }
}

.row {
  padding: 16rpx 0;
  border-bottom: 1rpx solid $color-line-soft;

  &:last-child { border-bottom: none; }

  &__top {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__no {
    font-family: Menlo, Consolas, monospace;
    font-size: 22rpx;
    color: $color-muted;
  }
  &__status {
    padding: 4rpx 14rpx;
    font-size: 22rpx;
    border-radius: 16rpx;

    &--pending { background: rgba(201,169,97,0.18); color: $color-gold-deep; }
    &--approved { background: rgba(107,142,107,0.12); color: #6B8E6B; }
    &--rejected { background: rgba(181,75,75,0.12); color: $color-err; }
  }
  &__body {
    margin-top: 8rpx;
    font-size: 26rpx;
    color: $color-ink-soft;
  }
  &__meta {
    margin-top: 4rpx;
    font-size: 22rpx;
    color: $color-hint;
  }
}
</style>
