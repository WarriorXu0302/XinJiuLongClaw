import * as XLSX from 'xlsx';
import { message } from 'antd';

/**
 * 导出 Excel 通用工具
 *
 * @param filename 文件名（不含扩展名，会自动加 _YYYY-MM-DD.xlsx）
 * @param sheetName 工作表名
 * @param rows 已处理好的对象数组（key 是中文列名）
 * @param colWidths 可选列宽 [{wch:10},...]
 * @param summaryRow 可选合计行（对象）
 */
export function exportExcel<T extends Record<string, any>>(
  filename: string,
  sheetName: string,
  rows: T[],
  colWidths?: { wch: number }[],
  summaryRow?: T,
): void {
  if (!rows || rows.length === 0) {
    message.warning('无数据可导出');
    return;
  }
  const data = summaryRow ? [...rows, summaryRow] : rows;
  const ws = XLSX.utils.json_to_sheet(data);
  if (colWidths) ws['!cols'] = colWidths;
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, sheetName);
  const today = new Date().toISOString().slice(0, 10);
  XLSX.writeFile(wb, `${filename}_${today}.xlsx`);
  message.success('已导出');
}
