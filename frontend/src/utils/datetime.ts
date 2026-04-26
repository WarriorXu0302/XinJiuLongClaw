/**
 * 全站时间显示工具 — 一律按东八区（Asia/Shanghai）展示，无论浏览器时区设置。
 *
 * 后端所有时间字段存 UTC（timezone-aware），前端展示时必须经这里转换，
 * 不能直接 substring/replace 原 ISO 字符串（会错 8 小时）。
 */

const BEIJING = 'Asia/Shanghai';

/** 完整日期+时间，如 "2026-04-26 01:24:28" */
export function formatDateTime(v: string | null | undefined): string {
  if (!v) return '-';
  return new Date(v).toLocaleString('zh-CN', {
    timeZone: BEIJING,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

/** 日期+分钟（省略秒），如 "2026-04-26 01:24" */
export function formatDateTimeShort(v: string | null | undefined): string {
  if (!v) return '-';
  return new Date(v).toLocaleString('zh-CN', {
    timeZone: BEIJING,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** 仅日期，如 "2026-04-26" */
export function formatDate(v: string | null | undefined): string {
  if (!v) return '-';
  return new Date(v).toLocaleDateString('zh-CN', {
    timeZone: BEIJING,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}
