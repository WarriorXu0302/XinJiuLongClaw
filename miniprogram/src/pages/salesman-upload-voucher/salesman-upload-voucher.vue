<!--
  业务员 - 上传收款凭证（独立页）

  - 收款金额（默认填订单 pay_amount，可低于）
  - 支付方式（现金/银行/微信/支付宝）
  - 凭证图（最多 3 张，前端预先算 sha256，后端再校验）
  - 备注

  接口：POST /api/mall/salesman/orders/{order_no}/upload-payment-voucher
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        上传收款凭证
      </view>
      <view class="header__sub">
        订单 {{ orderNo }} · 应收 {{ fmtMoney(order?.pay_amount) }}
      </view>
    </view>

    <view
      v-if="!orderNo"
      class="state"
    >
      未指定订单，请返回订单列表重新进入
    </view>

    <view
      v-else
      class="form"
    >
      <view class="form__item">
        <text class="form__label">
          实收金额
        </text>
        <view class="form__row">
          <text class="form__prefix">
            ¥
          </text>
          <input
            :value="form.amount"
            type="digit"
            class="form__input"
            placeholder="0.00"
            @input="onAmountInput"
          >
        </view>
        <view
          v-if="partial"
          class="form__hint form__hint--warn"
        >
          实收 {{ fmtMoney(form.amount) }} 低于应收，差额 {{ fmtMoney(shortfall) }} 将按欠款处理
        </view>
        <view
          v-else-if="overpay"
          class="form__hint form__hint--warn"
        >
          实收高于应收 {{ fmtMoney(overpay) }}，提交前请二次核对
        </view>
      </view>

      <view class="form__item">
        <text class="form__label">
          支付方式
        </text>
        <view class="form__methods">
          <view
            v-for="m in methods"
            :key="m.code"
            :class="['form__method', form.payment_method === m.code && 'form__method--active']"
            @tap="form.payment_method = m.code"
          >
            <text class="form__method-icon">
              {{ m.icon }}
            </text>
            <text>{{ m.label }}</text>
          </view>
        </view>
      </view>

      <view class="form__item">
        <text class="form__label">
          凭证照片（{{ form.vouchers.length }}/3）
        </text>
        <view class="form__photos">
          <view
            v-for="(v, i) in form.vouchers"
            :key="i"
            class="form__photo"
          >
            <image
              class="form__photo-img"
              :src="v.url"
              mode="aspectFill"
            />
            <text
              class="form__photo-del"
              @tap="onRemovePhoto(i)"
            >
              ×
            </text>
            <view
              v-if="v.uploading"
              class="form__photo-mask"
            >
              <text>上传中…</text>
            </view>
            <text
              v-else-if="v.sha256"
              class="form__photo-hash"
            >
              {{ v.sha256.slice(0, 6) }}…
            </text>
          </view>
          <view
            v-if="form.vouchers.length < 3"
            class="form__photo-add"
            @tap="onChoosePhoto"
          >
            <text>+</text>
            <text class="form__photo-add-hint">
              拍照/相册
            </text>
          </view>
        </view>
        <view class="form__hint">
          凭证上传后会计算防篡改哈希，请上传清晰截图
        </view>
      </view>

      <view class="form__item">
        <text class="form__label">
          备注（可选）
        </text>
        <textarea
          v-model="form.remarks"
          class="form__textarea"
          placeholder="如：客户要求发票、付款银行、流水号等"
          maxlength="200"
        />
      </view>
    </view>

    <view class="actions">
      <view
        :class="['actions__btn', !canSubmit && 'actions__btn--disabled']"
        @tap="onSubmit"
      >
        <text>{{ submitting ? '提交中…' : '提交凭证' }}</text>
      </view>
    </view>
  </view>
</template>

<script setup>
const orderNo = ref('')
const order = ref(null)
const submitting = ref(false)

const methods = [
  { code: 'cash', label: '现金', icon: '💵' },
  { code: 'bank', label: '银行转账', icon: '🏦' },
  { code: 'wechat', label: '微信', icon: '💬' },
  { code: 'alipay', label: '支付宝', icon: '🅰' }
]

const form = ref({
  amount: '',
  payment_method: 'cash',
  vouchers: [],
  remarks: ''
})

const fmtMoney = salesman.fmtMoney

// 金额输入：限制两位小数 + 首位不为 .
const onAmountInput = (e) => {
  let v = (e.detail?.value ?? '').replace(/[^\d.]/g, '')
  if (v.startsWith('.')) v = '0' + v
  const parts = v.split('.')
  if (parts.length > 2) v = parts[0] + '.' + parts.slice(1).join('')
  if (parts[1]?.length > 2) v = parts[0] + '.' + parts[1].slice(0, 2)
  form.value.amount = v
}

const shortfall = computed(() => {
  const pay = Number(order.value?.pay_amount || 0)
  const got = Number(form.value.amount || 0)
  return Math.max(0, pay - got)
})
const overpay = computed(() => {
  const pay = Number(order.value?.pay_amount || 0)
  const got = Number(form.value.amount || 0)
  return got > pay ? got - pay : 0
})
const partial = computed(() => shortfall.value > 0)

const hasUploading = computed(() => form.value.vouchers.some(v => v.uploading))
const allUploaded = computed(() =>
  form.value.vouchers.length > 0 &&
  form.value.vouchers.every(v => !v.uploading && v.remote_url)
)

const canSubmit = computed(() => {
  const amt = parseFloat(form.value.amount)
  return !submitting.value && !hasUploading.value && amt > 0 && allUploaded.value
})

const loadOrder = async () => {
  const res = await http.request({
    url: `/api/mall/salesman/orders/${orderNo.value}`,
    method: 'GET'
  })
  order.value = res.data
  if (!form.value.amount) form.value.amount = String(res.data?.pay_amount || '')
}

// 两段式上传：(1) uni.uploadFile 把文件传到后端，拿 remote_url + sha256
// 真实哈希由后端读文件字节计算，前端不再猜
const uploadOne = (localPath) => {
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: (import.meta.env.VITE_APP_BASE_API || '') + '/api/mall/salesman/attachments/upload',
      filePath: localPath,
      name: 'file',
      formData: { kind: 'payment_voucher' },
      header: { Authorization: uni.getStorageSync('Token') },
      success: (r) => {
        try {
          const body = typeof r.data === 'string' ? JSON.parse(r.data) : r.data
          if (body.code === '00000' || body.success) {
            const d = body.data || body
            resolve({ remote_url: d.url, sha256: d.sha256, size: d.size })
          } else {
            reject(new Error(body.msg || '上传失败'))
          }
        } catch (e) {
          reject(e)
        }
      },
      fail: (err) => reject(err)
    })
  })
}

const onChoosePhoto = () => {
  const remain = 3 - form.value.vouchers.length
  if (remain <= 0) return
  uni.chooseImage({
    count: remain,
    sizeType: ['compressed'],
    sourceType: ['camera', 'album'],
    success: (res) => {
      res.tempFilePaths.forEach(localPath => {
        const item = reactive({
          local_url: localPath,
          url: localPath, // 预览用本地路径
          remote_url: null,
          sha256: null,
          uploading: true,
          error: null
        })
        form.value.vouchers.push(item)
        uploadOne(localPath)
          .then((r) => {
            item.remote_url = r.remote_url
            item.sha256 = r.sha256
            item.uploading = false
          })
          .catch((err) => {
            item.uploading = false
            item.error = err?.message || '上传失败'
            uni.showToast({ title: '凭证上传失败，请重试', icon: 'none' })
          })
      })
    }
  })
}

const onRemovePhoto = (i) => {
  const v = form.value.vouchers[i]
  if (v?.uploading) {
    uni.showToast({ title: '上传中，请稍候', icon: 'none' })
    return
  }
  uni.showModal({
    title: '删除凭证',
    content: '确定删除这张凭证图？',
    confirmColor: '#B54B4B',
    success: (r) => {
      if (r.confirm) form.value.vouchers.splice(i, 1)
    }
  })
}

const onSubmit = async () => {
  if (submitting.value) return
  if (hasUploading.value) {
    uni.showToast({ title: '凭证仍在上传，请稍候', icon: 'none' })
    return
  }
  if (form.value.vouchers.length === 0) {
    uni.showToast({ title: '请上传凭证图', icon: 'none' })
    return
  }
  if (!allUploaded.value) {
    uni.showToast({ title: '存在上传失败的凭证，请删除后重试', icon: 'none' })
    return
  }
  const amt = parseFloat(form.value.amount)
  if (!amt || amt <= 0) {
    uni.showToast({ title: '请填写金额', icon: 'none' })
    return
  }

  const doSubmit = async () => {
    submitting.value = true
    uni.showLoading({ title: '提交中…' })
    try {
      await http.request({
        url: `/api/mall/salesman/orders/${orderNo.value}/upload-payment-voucher`,
        method: 'POST',
        data: {
          amount: amt,
          payment_method: form.value.payment_method,
          vouchers: form.value.vouchers.map(v => ({ url: v.remote_url, sha256: v.sha256 })),
          remarks: form.value.remarks || null
        }
      })
      uni.hideLoading()
      uni.showToast({ title: '已提交，等财务确认', icon: 'success' })
      setTimeout(() => uni.navigateBack(), 800)
    } catch (e) {
      uni.hideLoading()
      uni.showToast({ title: e?.msg || '提交失败', icon: 'none' })
    } finally {
      submitting.value = false
    }
  }

  if (overpay.value > 0) {
    uni.showModal({
      title: '金额异常',
      content: `实收 ${fmtMoney(amt)} 高于应收 ${fmtMoney(order.value?.pay_amount)}，确认无误？`,
      success: (r) => { if (r.confirm) doSubmit() }
    })
  } else {
    doSubmit()
  }
}

onLoad((q) => {
  orderNo.value = q?.order_no || ''
  if (orderNo.value) loadOrder()
})
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.page {
  min-height: 100vh;
  background: $color-cream;
  padding-bottom: 160rpx;
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
  &__sub {
    margin-top: 8rpx;
    font-size: 24rpx;
    color: $color-gold-soft;
    font-family: Menlo, Consolas, monospace;
  }
}

.state {
  padding: 120rpx 32rpx;
  text-align: center;
  color: $color-hint;
  font-size: 26rpx;
}

.form {
  margin: 24rpx;
  padding: 8rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;

  &__item {
    padding: 24rpx 0;
    border-bottom: 1rpx solid $color-line-soft;

    &:last-child { border-bottom: none; }
  }
  &__label {
    display: block;
    font-size: 24rpx;
    color: $color-muted;
    margin-bottom: 12rpx;
  }

  &__row {
    display: flex;
    align-items: center;
    padding: 8rpx 20rpx;
    background: $color-cream;
    border-radius: 12rpx;
  }
  &__prefix {
    font-size: 36rpx;
    color: $color-gold-deep;
    margin-right: 8rpx;
    font-family: Menlo, Consolas, monospace;
  }
  &__input {
    flex: 1;
    height: 72rpx;
    font-size: 36rpx;
    font-family: Menlo, Consolas, monospace;
    color: $color-ink-soft;
  }

  &__hint {
    margin-top: 8rpx;
    font-size: 22rpx;
    color: $color-hint;
    line-height: 1.5;

    &--warn { color: $color-err; }
  }

  &__methods {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12rpx;
  }
  &__method {
    padding: 20rpx;
    background: $color-cream;
    border: 2rpx solid transparent;
    border-radius: 12rpx;
    display: flex;
    align-items: center;
    gap: 12rpx;
    font-size: 26rpx;
    color: $color-ink-soft;
    transition: all 0.2s;

    &--active {
      border-color: $color-gold;
      background: rgba(201,169,97,0.08);
      color: $color-gold-deep;
      font-weight: 600;
    }
  }
  &__method-icon { font-size: 32rpx; }

  &__photos {
    display: flex;
    gap: 16rpx;
    flex-wrap: wrap;
  }
  &__photo {
    position: relative;
    width: 200rpx;
    height: 200rpx;
    border-radius: 12rpx;
    overflow: hidden;
    background: $color-cream;
  }
  &__photo-img {
    width: 100%;
    height: 100%;
  }
  &__photo-del {
    position: absolute;
    top: 4rpx;
    right: 4rpx;
    width: 40rpx;
    height: 40rpx;
    line-height: 36rpx;
    text-align: center;
    background: rgba(0,0,0,0.5);
    color: #fff;
    border-radius: 50%;
    font-size: 28rpx;
  }
  &__photo-hash {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 4rpx 8rpx;
    background: rgba(0,0,0,0.5);
    color: #fff;
    font-size: 18rpx;
    font-family: Menlo, Consolas, monospace;
    text-align: center;
  }
  &__photo-mask {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0,0,0,0.55);
    color: #fff;
    font-size: 24rpx;
  }
  &__photo-add {
    width: 200rpx;
    height: 200rpx;
    border: 2rpx dashed $color-line;
    border-radius: 12rpx;
    background: $color-cream;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: $color-hint;
    font-size: 48rpx;
  }
  &__photo-add-hint {
    margin-top: 4rpx;
    font-size: 22rpx;
    color: $color-hint;
  }

  &__textarea {
    width: 100%;
    min-height: 140rpx;
    padding: 16rpx 20rpx;
    background: $color-cream;
    border-radius: 12rpx;
    font-size: 26rpx;
    color: $color-ink-soft;
  }
}

.actions {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 20rpx 24rpx calc(20rpx + env(safe-area-inset-bottom));
  background: $color-card;
  box-shadow: 0 -4rpx 24rpx rgba(14,14,14,0.06);

  &__btn {
    padding: 28rpx 0;
    background: $color-ink;
    color: $color-gold;
    text-align: center;
    border-radius: 12rpx;
    font-size: 30rpx;
    font-weight: 600;
    letter-spacing: 4rpx;

    &--disabled {
      opacity: 0.5;
    }
  }
}
</style>
