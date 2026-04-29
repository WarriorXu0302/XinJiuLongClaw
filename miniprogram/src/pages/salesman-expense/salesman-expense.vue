<!--
  业务员 - 报销申请
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        报销申请
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
          报销类型
        </text>
        <picker
          :value="form.typeIndex"
          :range="types"
          @change="(e) => form.typeIndex = Number(e.detail.value)"
        >
          <view class="form__val">
            {{ types[form.typeIndex] }}
          </view>
        </picker>
      </view>

      <view class="form__item">
        <text class="form__label">
          金额（元）
        </text>
        <input
          v-model="form.amount"
          type="digit"
          class="form__input"
          placeholder="0.00"
        >
      </view>

      <view class="form__item form__item--textarea">
        <text class="form__label">
          说明
        </text>
        <textarea
          v-model="form.description"
          class="form__textarea"
          placeholder="如：2026-04-27 送货至朝阳区油费"
          maxlength="200"
        />
      </view>

      <view class="form__item">
        <text class="form__label">
          凭证图
        </text>
        <view class="form__photos">
          <view
            v-for="(p, i) in form.vouchers"
            :key="i"
            class="form__photo"
            :style="{ backgroundImage: `url(${p})` }"
          />
          <view
            v-if="form.vouchers.length < 3"
            class="form__choose"
            @tap="onChoosePhoto"
          >
            +
          </view>
        </view>
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
        :key="r.claim_no"
        class="row"
      >
        <view class="row__top">
          <text class="row__no">
            {{ r.claim_no }}
          </text>
          <text :class="['row__status', 'row__status--' + r.status]">
            {{ statusMap[r.status] }}
          </text>
        </view>
        <view class="row__body">
          <text class="row__amount">
            {{ fmtMoney(r.amount) }}
          </text>
          <text class="row__desc">
            {{ r.description }}
          </text>
        </view>
        <view class="row__meta">
          {{ r.created_at }}
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
const showForm = ref(false)
const form = ref({
  typeIndex: 0,
  amount: '',
  description: '',
  vouchers: []
})
const records = ref([])

const types = ['日常开销', 'F 类报销', '分货费用']
const typeCodes = ['daily', 'f_class', 'share_out']
const statusMap = {
  pending: '待审批',
  approved: '已审批',
  applied: '已申请',
  arrived: '已到账',
  fulfilled: '已兑付',
  paid: '已发放',
  settled: '已归档',
  rejected: '已驳回'
}

const fmtMoney = salesman.fmtMoney

const onChoosePhoto = () => {
  uni.chooseImage({
    count: 3 - form.value.vouchers.length,
    sizeType: ['compressed'],
    success: (res) => {
      form.value.vouchers = form.value.vouchers.concat(res.tempFilePaths)
    }
  })
}

const load = async () => {
  const res = await http.request({
    url: '/api/mall/workspace/expense-claims',
    method: 'GET'
  })
  records.value = res.data?.records || []
}

const onSubmit = async () => {
  const amt = parseFloat(form.value.amount)
  if (!amt || amt <= 0) {
    uni.showToast({ title: '请输入金额', icon: 'none' })
    return
  }
  if (!form.value.description.trim()) {
    uni.showToast({ title: '请填写说明', icon: 'none' })
    return
  }
  await http.request({
    url: '/api/mall/workspace/expense-claims',
    method: 'POST',
    data: {
      claim_type: typeCodes[form.value.typeIndex],
      amount: amt,
      description: form.value.description,
      voucher_urls: form.value.vouchers
    }
  })
  const next = { typeIndex: 0, amount: '', description: '', vouchers: [] }
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
    font-size: 28rpx;
    color: $color-ink-soft;
  }
  &__input {
    width: 100%;
    height: 72rpx;
    padding: 0 20rpx;
    background: $color-cream;
    border-radius: 12rpx;
    font-size: 32rpx;
    font-family: Menlo, Consolas, monospace;
    color: $color-ink-soft;
  }
  &__textarea {
    width: 100%;
    min-height: 160rpx;
    padding: 16rpx 20rpx;
    background: $color-cream;
    border-radius: 12rpx;
    font-size: 26rpx;
    color: $color-ink-soft;
  }
  &__photos {
    display: flex;
    gap: 16rpx;
    flex-wrap: wrap;
  }
  &__photo, &__choose {
    width: 180rpx;
    height: 180rpx;
    border-radius: 8rpx;
  }
  &__photo {
    background-size: cover;
    background-position: center;
  }
  &__choose {
    background: $color-cream;
    border: 2rpx dashed $color-line;
    display: flex;
    align-items: center;
    justify-content: center;
    color: $color-hint;
    font-size: 48rpx;
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
    &--approved, &--applied, &--arrived, &--fulfilled { background: rgba(201,169,97,0.12); color: $color-gold-deep; }
    &--paid, &--settled { background: rgba(107,142,107,0.12); color: #6B8E6B; }
    &--rejected { background: rgba(181,75,75,0.12); color: $color-err; }
  }
  &__body {
    margin-top: 10rpx;
    display: flex;
    gap: 12rpx;
    align-items: baseline;
  }
  &__amount {
    font-size: 30rpx;
    font-weight: 700;
    color: $color-gold-deep;
  }
  &__desc {
    flex: 1;
    font-size: 24rpx;
    color: $color-muted;
  }
  &__meta {
    margin-top: 4rpx;
    font-size: 22rpx;
    color: $color-hint;
  }
}
</style>
