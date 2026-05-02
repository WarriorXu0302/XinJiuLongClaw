<!--
  C 端用户注册页

  决策：
    - C 端必绑微信（openid 作为唯一身份），不再提供账密注册入口
    - 审批资料必填：真实姓名 / 联系电话 / 配送地址 / 营业执照
    - 配送地址跳独立选择页（register-address-picker）
    - 业务员账号不走此流程（ERP 管理员后台创建，走账密登录）
-->
<template>
  <view class="page">
    <!-- 品牌头 -->
    <view class="hero">
      <view class="hero__logo">
        鑫
      </view>
      <view class="hero__title">
        欢迎加入鑫久隆
      </view>
      <view class="hero__sub">
        完善资料后提交审核，通常 1 个工作日内通过
      </view>
    </view>

    <!-- 邀请码：扫码进来锁定显示；否则让用户手动输入 -->
    <view
      v-if="inviteLocked"
      class="invite-card"
    >
      <view class="invite-card__row">
        <text class="invite-card__label">
          推荐码
        </text>
        <text class="invite-card__code">
          {{ form.invite_code }}
        </text>
      </view>
    </view>
    <view
      v-else
      class="invite-card invite-card--input"
    >
      <text class="invite-card__label">
        推荐码
      </text>
      <input
        v-model="form.invite_code"
        class="invite-card__input"
        maxlength="16"
        placeholder="请输入业务员发的邀请码"
        placeholder-class="invite-card__placeholder"
        @input="onInviteInput"
      >
    </view>

    <!-- 必填资料表单 -->
    <view class="form">
      <view class="form__group">
        <view class="form__label">
          <text class="form__required">
            *
          </text>
          真实姓名
        </view>
        <input
          v-model="form.real_name"
          class="form__input"
          maxlength="50"
          placeholder="与营业执照/身份证一致"
          placeholder-class="form__placeholder"
        >
      </view>

      <view class="form__group">
        <view class="form__label">
          <text class="form__required">
            *
          </text>
          联系电话
        </view>
        <input
          v-model="form.contact_phone"
          class="form__input"
          type="number"
          maxlength="11"
          placeholder="11 位手机号"
          placeholder-class="form__placeholder"
        >
      </view>

      <view class="form__group">
        <view class="form__label">
          <text class="form__required">
            *
          </text>
          配送地址
        </view>
        <view
          class="form__input form__input--link"
          @tap="toPickAddress"
        >
          <text
            v-if="form.delivery_address"
            class="form__value"
          >
            {{ form.delivery_address }}
          </text>
          <text
            v-else
            class="form__placeholder"
          >
            选择省/市/区，填写门牌号
          </text>
          <text class="form__arrow">
            ›
          </text>
        </view>
      </view>

      <view class="form__group">
        <view class="form__label">
          <text class="form__required">
            *
          </text>
          营业执照
        </view>
        <view
          class="upload"
          @tap="onChooseLicense"
        >
          <image
            v-if="form.business_license_url"
            class="upload__img"
            :src="form.business_license_url"
            mode="aspectFit"
          />
          <view
            v-else
            class="upload__placeholder"
          >
            <text class="upload__icon">
              ＋
            </text>
            <text class="upload__hint">
              点击上传
            </text>
            <text class="upload__note">
              仅限 jpg / png / pdf，5MB 以内
            </text>
          </view>
          <view
            v-if="licenseUploading"
            class="upload__mask"
          >
            <text>上传中…</text>
          </view>
        </view>
      </view>
    </view>

    <view class="agreement">
      <text>点击下方按钮即表示同意</text>
      <text class="agreement__link">
        《服务协议》
      </text>
      <text>和</text>
      <text class="agreement__link">
        《隐私政策》
      </text>
    </view>

    <view class="actions">
      <button
        class="btn btn--wechat"
        :disabled="!canSubmit || submitting"
        @tap="onWechatRegister"
      >
        <text class="btn__icon">
          💬
        </text>
        <text>{{ submitting ? '提交中…' : '微信授权并提交' }}</text>
      </button>
      <view class="actions__sub">
        <text @tap="toLogin">
          已有账号，去登录
        </text>
      </view>
    </view>
  </view>
</template>

<script setup>
const form = ref({
  invite_code: '',
  real_name: '',
  contact_phone: '',
  delivery_address: '',
  business_license_url: ''
})
const submitting = ref(false)
const licenseUploading = ref(false)
// URL 带来的邀请码锁定展示；手动进入则允许用户输入
const inviteLocked = ref(false)

onLoad((q) => {
  uni.setNavigationBarTitle({ title: '注册' })
  const raw = q?.code || q?.invite_code || q?.scene
  if (raw) {
    form.value.invite_code = String(raw).toUpperCase()
    inviteLocked.value = true
  }
})

const onInviteInput = (e) => {
  // 邀请码统一大写
  const v = (e?.detail?.value || '').toUpperCase()
  form.value.invite_code = v
}

// 从地址选择页回来 —— 从 storage 取，取完立即删
onShow(() => {
  const picked = uni.getStorageSync('pickedAddress')
  if (picked) {
    form.value.delivery_address = picked
    uni.removeStorageSync('pickedAddress')
    uni.removeStorageSync('pickedAddressParts')
  }
})

// 上传营业执照（匿名端点）
const onChooseLicense = () => {
  if (licenseUploading.value) return
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['camera', 'album'],
    success: (r) => {
      if (!r.tempFilePaths?.length) return
      licenseUploading.value = true
      uni.uploadFile({
        url: (import.meta.env.VITE_APP_BASE_API || '') + '/api/mall/public-uploads/upload',
        filePath: r.tempFilePaths[0],
        name: 'file',
        formData: { kind: 'business_license' },
        success: (res) => {
          try {
            const body = typeof res.data === 'string' ? JSON.parse(res.data) : res.data
            if (res.statusCode >= 200 && res.statusCode < 300 && body.url) {
              form.value.business_license_url = body.url
              uni.showToast({ title: '上传成功', icon: 'success' })
            } else {
              uni.showToast({ title: body?.detail || '上传失败', icon: 'none' })
            }
          } catch (e) {
            uni.showToast({ title: '上传失败', icon: 'none' })
          }
        },
        fail: () => uni.showToast({ title: '上传失败', icon: 'none' }),
        complete: () => { licenseUploading.value = false }
      })
    }
  })
}

const toPickAddress = () => {
  uni.navigateTo({ url: '/pages/register-address-picker/register-address-picker' })
}

const canSubmit = computed(() => {
  return !!(
    form.value.invite_code &&
    form.value.real_name.trim() &&
    /^1[3-9]\d{9}$/.test(form.value.contact_phone.trim()) &&
    form.value.delivery_address.trim().length >= 5 &&
    form.value.business_license_url
  )
})

const toLogin = () => uni.navigateTo({ url: '/pages/accountLogin/accountLogin' })

const validate = () => {
  if (!form.value.invite_code) {
    uni.showToast({ title: '邀请码缺失', icon: 'none' })
    return false
  }
  if (!form.value.real_name.trim()) {
    uni.showToast({ title: '请填写真实姓名', icon: 'none' })
    return false
  }
  if (!/^1[3-9]\d{9}$/.test(form.value.contact_phone.trim())) {
    uni.showToast({ title: '请填写正确的手机号', icon: 'none' })
    return false
  }
  if (form.value.delivery_address.trim().length < 5) {
    uni.showToast({ title: '请选择配送地址', icon: 'none' })
    return false
  }
  if (!form.value.business_license_url) {
    uni.showToast({ title: '请上传营业执照', icon: 'none' })
    return false
  }
  return true
}

// dev H5 下：如果设置了 devMockOpenid 就直接用（注册/登录共用同一个 mock openid）
const getDevMockCode = () => {
  // #ifdef H5
  if (import.meta.env.DEV) {
    const saved = uni.getStorageSync('devMockOpenid')
    if (saved) return `devmock:${saved}`
  }
  // #endif
  return null
}

// 微信一键注册 + 提交资料
const onWechatRegister = () => {
  if (!validate()) return
  submitting.value = true
  const devCode = getDevMockCode()
  // eslint-disable-next-line n/no-callback-literal
  const wxLoginCall = devCode ? (cb) => cb({ code: devCode }) : (cb) => uni.login({
    provider: 'weixin',
    success: cb,
    fail: () => {
      submitting.value = false
      uni.showToast({ title: '微信授权失败，请重试', icon: 'none' })
    }
  })
  wxLoginCall(({ code }) => {
    if (!code) {
      submitting.value = false
      uni.showToast({ title: '微信授权失败，请重试', icon: 'none' })
      return
    }
    http.request({
      url: '/api/mall/auth/wechat-register',
      method: 'POST',
      login: true,
      hasCatch: true,
      data: {
        code,
        invite_code: form.value.invite_code.trim().toUpperCase(),
        real_name: form.value.real_name.trim(),
        contact_phone: form.value.contact_phone.trim(),
        delivery_address: form.value.delivery_address.trim(),
        business_license_url: form.value.business_license_url
      }
    }).then(({ data }) => {
      submitting.value = false
      if (data?.token) {
        http.loginSuccess(data, () => {
          uni.showToast({ title: '欢迎回来', icon: 'success' })
          setTimeout(() => salesman.dispatchAfterLogin(data.user_type || 'consumer'), 800)
        })
      } else if (data?.application_id) {
        uni.showToast({ title: '申请已提交', icon: 'success', duration: 1200 })
        setTimeout(() => {
          uni.reLaunch({
            url: `/pages/pending-approval/pending-approval?application_id=${data.application_id}`
          })
        }, 1000)
      }
    }).catch((e) => {
      submitting.value = false
      uni.showToast({ title: e?.detail || e?.msg || '注册失败', icon: 'none' })
    })
  })
}
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.page {
  min-height: 100vh;
  background: $color-cream;
  padding: 40rpx 24rpx 48rpx;
}

.hero {
  text-align: center;
  margin-bottom: 32rpx;

  &__logo {
    width: 108rpx;
    height: 108rpx;
    line-height: 108rpx;
    font-size: 56rpx;
    font-weight: 700;
    color: #fff;
    background: $color-ink;
    border-radius: 50%;
    margin: 0 auto 24rpx;
    letter-spacing: 0;
  }
  &__title {
    font-size: 40rpx;
    font-weight: 600;
    color: $color-ink-soft;
    margin-bottom: 8rpx;
  }
  &__sub {
    font-size: 24rpx;
    color: $color-hint;
  }
}

.invite-card {
  background: linear-gradient(135deg, #2A2013 0%, #0E0E0E 100%);
  border-radius: 16rpx;
  padding: 28rpx 32rpx;
  margin-bottom: 24rpx;

  &__row {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__label {
    font-size: 24rpx;
    color: rgba(255, 255, 255, 0.6);
  }
  &__code {
    font-size: 36rpx;
    font-weight: 700;
    color: $color-gold;
    letter-spacing: 6rpx;
  }

  &--input {
    display: flex;
    flex-direction: column;
    gap: 12rpx;
  }

  &__input {
    width: 100%;
    font-size: 34rpx;
    font-weight: 700;
    color: $color-gold;
    letter-spacing: 4rpx;
    background: transparent;
    padding: 4rpx 0;
  }

  // placeholder-class 样式脱离 scoped 作用域，用属性选择器替代
}

// eslint-disable-next-line vue-scoped-css/no-unused-selector
.invite-card__placeholder {
  font-size: 28rpx;
  font-weight: 400;
  color: rgba(255, 255, 255, 0.3);
  letter-spacing: 0;
}

.form {
  background: #fff;
  border-radius: 16rpx;
  padding: 8rpx 24rpx;

  &__group {
    padding: 24rpx 0;
    border-bottom: 1rpx solid $color-line;

    &:last-child {
      border-bottom: none;
    }
  }

  &__label {
    font-size: 26rpx;
    color: $color-hint;
    margin-bottom: 16rpx;
  }

  &__required {
    color: $color-err;
    margin-right: 6rpx;
  }

  &__input {
    font-size: 30rpx;
    color: $color-ink-soft;
    width: 100%;

    &--link {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
  }

  &__placeholder {
    color: $color-hint;
  }

  &__value {
    flex: 1;
    font-size: 30rpx;
    color: $color-ink-soft;
    word-break: break-all;
  }

  &__arrow {
    color: $color-hint;
    font-size: 36rpx;
    margin-left: 16rpx;
  }
}

.upload {
  width: 280rpx;
  height: 280rpx;
  position: relative;
  background: $color-cream;
  border: 2rpx dashed $color-line;
  border-radius: 12rpx;
  overflow: hidden;

  &__img {
    width: 100%;
    height: 100%;
    display: block;
  }

  &__placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6rpx;
  }

  &__icon {
    font-size: 64rpx;
    color: $color-gold;
    line-height: 1;
  }

  &__hint {
    font-size: 24rpx;
    color: $color-ink-soft;
    margin-top: 6rpx;
  }

  &__note {
    font-size: 20rpx;
    color: $color-hint;
    padding: 0 16rpx;
    text-align: center;
    line-height: 1.4;
  }

  &__mask {
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24rpx;
  }
}

.agreement {
  margin-top: 32rpx;
  text-align: center;
  font-size: 22rpx;
  color: $color-hint;

  &__link {
    color: $color-gold-deep;
  }
}

.actions {
  margin-top: 32rpx;

  &__sub {
    margin-top: 24rpx;
    text-align: center;
    font-size: 26rpx;
    color: $color-gold-deep;
  }
}

.btn {
  width: 100%;
  height: 96rpx;
  line-height: 96rpx;
  border-radius: 48rpx;
  font-size: 30rpx;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;

  &--wechat {
    background: #07C160;
    color: #fff;
  }

  &[disabled] {
    background: $color-line !important;
    color: $color-hint !important;
  }

  &__icon {
    font-size: 30rpx;
    margin-right: 8rpx;
  }

  &::after {
    border: 0;
  }
}
</style>
