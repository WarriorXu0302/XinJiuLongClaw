const util = {
  formatTime: date => {
    const year = date.getFullYear()
    const month = date.getMonth() + 1
    const day = date.getDate()
    const hour = date.getHours()
    const minute = date.getMinutes()
    const second = date.getSeconds()
    return [year, month, day].map(util.formatNumber).join('/') + ' ' + [hour, minute, second].map(util.formatNumber).join(':')
  },

  formatNumber: n => {
    n = n.toString()
    return n[1] ? n : '0' + n
  },

  formatHtml: content => {
    if (!content) {
      return
    }
    content = content.replace(/<p/gi, '<p style="max-width:100% !important;word-wrap:break-word;word-break:break-word;" ')
    content = content.replace(/<img/gi, '<img style="max-width:100% !important;height:auto !important;margin:0;display:flex;" ')
    content = content.replace(/style="/gi, 'style="max-width:100% !important;table-layout:fixed;word-wrap:break-word;word-break:break-word;')
    content = content.replace(/<table/gi, '<table style="table-layout:fixed;word-wrap:break-word;word-break:break-word;" ')
    content = content.replace(/<td/gi, '<td cellspacing="0" cellpadding="0" style="border-width:1px; border-style:solid; border-color:#666; margin: 0px; padding: 0px;"')
    content = content.replace(/width=/gi, 'sss=')
    content = content.replace(/height=/gi, 'sss=')
    content = content.replace(/\/>/gi, ' style="max-width:100% !important;height:auto !important;margin:0;display:block;" />')
    return content
  },

  /**
   * 移除购物车Tabbar的数字
   * 只在 TabBar 页面调用 removeTabBarBadge，否则小程序会在 native 层抛错
   */
  removeTabBadge: () => {
    const pages = getCurrentPages()
    const current = pages[pages.length - 1]
    if (!current) return
    const tabRoutes = ['pages/index/index', 'pages/basket/basket', 'pages/user/user']
    if (!tabRoutes.includes(current.route)) return
    uni.removeTabBarBadge({
      index: 1,
      fail: () => {}
    })
  },
  /**
   * 获取链接上的参数
   */
  getUrlKey: (name) => {
    return decodeURIComponent((new RegExp('[?|&]' + name + '=' + '([^&;]+?)(&|#|;|$)').exec(location.href) || ['', ''])[1]
      .replace(/\+/g, '%20')) || null
  },
  /**
   * 文件地址校验
   * @param fileUrl 获取到的文件路径
   */
  checkFileUrl: (fileUrl) => {
    const url = fileUrl || ''
    if (!url) return url
    // 完整 URL（http/https/data/blob）直接返回，不再拼 CDN 前缀
    if (/^(https?:|data:|blob:)/i.test(url)) return url
    const baseUrl = import.meta.env.VITE_APP_RESOURCES_URL
    if (url.indexOf(baseUrl) !== -1) return url
    return baseUrl + url
  }
}

export default util
