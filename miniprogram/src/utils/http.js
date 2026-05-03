/* eslint-disable no-console */
// 全局请求封装（ERP 原生协议）
//
// 协议差异对照：
//   旧 mall4j：{code: '00000'|'A00004'|..., data: {...}, msg}
//   新 ERP   ：成功 2xx + 直接 JSON body；失败 4xx/5xx + {detail: "..."}
//
// 分派规则：
//   2xx            → resolve({ data: body })  兼容老模板的 `res.data.xxx` 读法
//   401            → 清 Token，可选提示后跳登录；reject(body)
//   403            → toast detail（账号停用 / 权限不足），reject(body)
//   400/404/409/429 → toast detail，reject(body)
//   500+            → 通用"服务器出错"，reject(body)
//
// 特殊标志：
//   params.login       首次登录类，不做 refresh 前置
//   params.isRefreshing refresh 本身调用时防递归
//   params.dontTrunLogin 401 时不弹框不跳转
//   params.hasCatch     4xx 时不 toast（调用方自己处理错误）
//   params.responseType = 'arraybuffer' 直接返回
//
import loginMethods from './login'
import { enabled as mockEnabled, tryMock } from './mock'

const http = {
  request: async function (params) {
    // 开发期：优先走本地 mock（C 端旧路径仍靠 mock 顶住，等 M2+ 真实后端实现）
    if (mockEnabled) {
      const mocked = tryMock(params)
      if (mocked) return mocked
    }

    // 参数归一化
    if (Object.prototype.toString.call(params.data) === '[object Array]') {
      params.data = JSON.stringify(params.data)
    } else if (Object.prototype.toString.call(params.data) === '[object Number]') {
      params.data = params.data + ''
    }

    // 自动 refresh token（登录/refresh 本身跳过）
    if (!params.login && !getApp()?.globalData?.isLanding && !params.isRefreshing) {
      await loginMethods.refreshToken()
    }

    const token = uni.getStorageSync('Token')
    const header = {
      'Content-Type': 'application/json'
    }
    if (token) header.Authorization = token.startsWith('Bearer ') ? token : `Bearer ${token}`

    return new Promise((resolve, reject) => {
      uni.request({
        url: (params.domain || import.meta.env.VITE_APP_BASE_API) + params.url,
        data: params.data,
        method: params.method === undefined ? 'POST' : params.method,
        header,
        dataType: 'json',
        responseType: params.responseType === undefined ? 'text' : params.responseType,
        success: (res) => {
          const body = res.data
          const status = res.statusCode

          if (params.responseType === 'arraybuffer' && status === 200) {
            return resolve(body)
          }

          if (status >= 200 && status < 300) {
            return resolve({ data: body })
          }

          // 4xx 类
          if (status === 401) {
            // 在清 Storage 之前快照一下 hadLogin 决定文案（先读再清）
            const wasLogged = !!uni.getStorageSync('hadLogin')
            uni.removeStorageSync('Token')
            uni.removeStorageSync('RefreshToken')
            uni.removeStorageSync('expiresTimeStamp')
            uni.removeStorageSync('loginResult')
            uni.removeStorageSync('userType')
            uni.removeStorageSync('userId')
            uni.removeStorageSync('hadLogin')
            if (!params.dontTrunLogin) {
              uni.showModal({
                title: '提示',
                content: wasLogged ? '登录已过期，请重新登录' : '请先登录',
                cancelText: '取消',
                confirmText: '确定',
                success: (r) => {
                  if (r.confirm) {
                    uni.navigateTo({ url: '/pages/accountLogin/accountLogin' })
                  } else {
                    const pages = getCurrentPages()
                    if (pages[0]?.route === 'pages/basket/basket') {
                      uni.switchTab({ url: '/pages/index/index' })
                    }
                  }
                }
              })
            }
            const e401 = new Error(body?.detail || '未登录')
            e401.status = status
            e401.detail = body?.detail
            e401.data = body
            return reject(e401)
          }

          if (status >= 400 && status < 500) {
            const detail = body?.detail || body?.msg || '请求失败'
            // 业务员 linked_employee 被 ERP 端停用：弹模态而不是 toast，并登出 mall session
            // 后端 detail 固定前缀"您绑定的 ERP 员工已停用"（见 validators.assert_salesman_linked_employee_active）
            if (status === 403 && typeof detail === 'string' && detail.startsWith('您绑定的 ERP 员工已停用')) {
              uni.removeStorageSync('Token')
              uni.removeStorageSync('RefreshToken')
              uni.removeStorageSync('expiresTimeStamp')
              uni.removeStorageSync('loginResult')
              uni.removeStorageSync('userType')
              uni.removeStorageSync('userId')
              uni.removeStorageSync('hadLogin')
              if (!params.dontTrunLogin) {
                uni.showModal({
                  title: '账号已停用',
                  content: detail + '\n您的登录已失效，请联系 HR 处理后再登录。',
                  showCancel: false,
                  confirmText: '我知道了',
                  success: () => {
                    uni.reLaunch({ url: '/pages/accountLogin/accountLogin' })
                  }
                })
              }
              const eEmp = new Error(detail)
              eEmp.status = status
              eEmp.detail = detail
              eEmp.data = body
              eEmp.code = 'EMPLOYEE_INACTIVE'
              return reject(eEmp)
            }
            if (!params.hasCatch) {
              uni.showToast({ title: detail, icon: 'none' })
            }
            const e4xx = new Error(detail)
            e4xx.status = status
            e4xx.detail = detail
            e4xx.msg = detail
            e4xx.data = body
            return reject(e4xx)
          }

          // 5xx
          this.onRequestFail(params, body)
          if (!params.hasCatch) {
            uni.showToast({ title: '服务器出了点小差～', icon: 'none' })
          }
          const e5xx = new Error(body?.detail || '服务器错误')
          e5xx.status = status
          e5xx.data = body
          return reject(e5xx)
        },
        fail: (err) => {
          uni.showToast({ title: '网络请求失败', icon: 'none' })
          reject(err)
        }
      })
    })
  },

  getCartCount: () => {
    if (!uni.getStorageSync('Token')) {
      util.removeTabBadge()
      return
    }
    http.request({
      url: '/api/mall/cart/count',
      method: 'GET',
      dontTrunLogin: true,
      data: {}
    }).then(({ data }) => {
      const pages = getCurrentPages()
      const current = pages[pages.length - 1]
      const tabRoutes = ['pages/index/index', 'pages/basket/basket', 'pages/user/user']
      const isTabPage = current && tabRoutes.includes(current.route)
      if (data > 0) {
        if (isTabPage) {
          uni.setTabBarBadge({ index: 1, text: data + '', fail: () => {} })
        }
        getApp().globalData.totalCartCount = data
      } else {
        if (isTabPage) {
          uni.removeTabBarBadge({ index: 1, fail: () => {} })
        }
        getApp().globalData.totalCartCount = 0
      }
    }).catch(() => {})
  },

  onRequestFail: (params, body) => {
    console.error('============== 请求异常 ==============')
    console.log('接口地址:', params.url)
    console.log('异常 body:', body)
    console.error('============== 请求异常 end ==========')
  },

  /**
   * 登录成功后执行。ERP 响应格式：
   *   { token, refresh_token, expires_in, user_type, user_id, nickname, must_change_password }
   */
  loginSuccess: (result, fn) => {
    uni.setStorageSync('loginResult', result)
    uni.setStorageSync('hadLogin', true)
    uni.setStorageSync('Token', result.token)
    if (result.refresh_token) uni.setStorageSync('RefreshToken', result.refresh_token)
    if (result.user_type) uni.setStorageSync('userType', result.user_type)
    if (result.user_id) uni.setStorageSync('userId', result.user_id)

    // expires_in 单位秒；过期判定取 1/2 留刷新窗口
    const expiresIn = Number(result.expires_in || 0) * 1000
    if (expiresIn > 0) {
      uni.setStorageSync('expiresTimeStamp', Date.now() + expiresIn / 2)
    }

    if (fn) fn()
  }
}
export default http
