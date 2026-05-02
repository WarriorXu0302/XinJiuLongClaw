/**
 * 登录态辅助：刷新 token + 登录后回跳地址管理。
 *
 * refresh 契约（ERP /api/mall/auth/refresh）:
 *   请求: { refresh_token: string }
 *   响应: { token, refresh_token, expires_in, user_type, user_id, nickname, must_change_password }
 *
 * 并发保护：同一 JS 运行时内（小程序每个页面共享同一个 app 实例），
 * 用模块级 Promise 保证多个并发请求共享同一个 refresh 调用，避免重复刷新。
 */

// 模块级单例 promise：refresh 进行中时，其他调用方 await 同一个
let _refreshInflight = null

const _doRefresh = async () => {
  const refreshToken = uni.getStorageSync('RefreshToken')
  if (!refreshToken) return
  try {
    const res = await http.request({
      url: '/api/mall/auth/refresh',
      method: 'POST',
      login: true,
      isRefreshing: true,
      dontTrunLogin: true,
      hasCatch: true,
      data: { refresh_token: refreshToken }
    })
    const d = res.data || {}
    if (d.token) {
      uni.setStorageSync('Token', d.token)
      if (d.refresh_token) uni.setStorageSync('RefreshToken', d.refresh_token)
      const expiresIn = Number(d.expires_in || 0) * 1000
      if (expiresIn > 0) {
        uni.setStorageSync('expiresTimeStamp', Date.now() + expiresIn / 2)
      }
    }
  } catch (err) {
    // refresh_token 过期/失效：立即清 session，下一次请求撞 401 跳登录
    if (err?.status === 401 || err?.status === 403) {
      uni.removeStorageSync('Token')
      uni.removeStorageSync('RefreshToken')
      uni.removeStorageSync('expiresTimeStamp')
      uni.removeStorageSync('loginResult')
      uni.removeStorageSync('userType')
      uni.removeStorageSync('userId')
      uni.removeStorageSync('hadLogin')
    }
    // 网络错/5xx 不清 Token，下次再试；异常不向上抛，业务请求自己会拿到最新 token 重试
  }
}

const loginMethods = {
  refreshToken: async () => {
    const token = uni.getStorageSync('Token')
    const refreshToken = uni.getStorageSync('RefreshToken')
    const expiresTimeStamp = uni.getStorageSync('expiresTimeStamp')
    if (!token || !refreshToken || !expiresTimeStamp) return
    // 未到过期窗口
    if (expiresTimeStamp >= Date.now()) return

    // 已有 refresh 在进行 → 等它完成（共享结果），不自己再发一次
    if (_refreshInflight) {
      try {
        await _refreshInflight
      } catch {}
      return
    }

    // 先同步赋值再 await：避免两个并发调用都看到 null → 都进入赋值
    const p = _doRefresh()
    _refreshInflight = p
    try {
      await p
    } finally {
      if (_refreshInflight === p) _refreshInflight = null
    }
  },

  setRouteUrlAfterLogin: () => {
    const pages = getCurrentPages()
    const last = pages[pages.length - 1]
    if (last && last.route && last.route.indexOf('user-login') === -1) {
      uni.setStorageSync('routeUrlAfterLogin', last.$page?.fullPath || '')
    }
  }
}

export default loginMethods
