/**
 * 登录态辅助：刷新 token + 登录后回跳地址管理。
 *
 * refresh 契约（ERP /api/mall/auth/refresh）:
 *   请求: { refresh_token: string }
 *   响应: { token, refresh_token, expires_in, user_type, user_id, nickname, must_change_password }
 */
const loginMethods = {
  refreshToken: async () => {
    const token = uni.getStorageSync('Token')
    const refreshToken = uni.getStorageSync('RefreshToken')
    const expiresTimeStamp = uni.getStorageSync('expiresTimeStamp')
    if (!token || !refreshToken || !expiresTimeStamp) return

    const isExpiring = expiresTimeStamp < Date.now()
    const isRefreshing = uni.getStorageSync('isRefreshingToken')
    if (!isExpiring || isRefreshing) return

    uni.setStorageSync('isRefreshingToken', true)
    try {
      const res = await http.request({
        url: '/api/mall/auth/refresh',
        method: 'POST',
        login: true,
        isRefreshing: true,
        dontTrunLogin: true,
        hasCatch: true, // 不自动 toast，由本函数决定如何处理
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
      // 网络错/5xx：不清 Token，下次再试
      if (err?.status === 401 || err?.status === 403) {
        uni.removeStorageSync('Token')
        uni.removeStorageSync('RefreshToken')
        uni.removeStorageSync('expiresTimeStamp')
        uni.removeStorageSync('loginResult')
        uni.removeStorageSync('userType')
        uni.removeStorageSync('userId')
        uni.removeStorageSync('hadLogin')
      }
    } finally {
      uni.setStorageSync('isRefreshingToken', false)
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
