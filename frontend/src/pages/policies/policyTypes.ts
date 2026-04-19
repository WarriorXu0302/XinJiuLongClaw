export interface Expense {
  id: string; name: string; cost_amount: number; payer_type?: string;
  reimburse_amount: number; reimburse_status: string; profit_loss: number;
}
export interface RequestItem {
  id: string; benefit_type: string; name: string; quantity: number;
  quantity_unit: string; standard_total: number; total_value: number; product_name?: string;
  product_id?: string; is_material: boolean; fulfill_mode: string; fulfill_status: string;
  fulfilled_qty: number; settled_amount: number; actual_cost: number; profit_loss: number;
  arrival_amount?: number; arrival_billcode?: string; voucher_urls?: string[];
  advance_payer_type?: string; confirmed_by?: string; expenses: Expense[];
  scheme_no?: string; notes?: string;
}
export interface PolicyRequest {
  id: string; request_source: string; approval_mode: string;
  order_id: string | null; customer_id: string | null;
  target_name: string | null; usage_purpose: string | null;
  brand_id: string | null; status: string; created_at: string;
  order?: { order_no: string; total_amount: string; customer?: { name: string } };
  customer?: { name: string };
  total_policy_value?: number; total_gap?: number;
  settlement_mode?: string; scheme_no?: string;
  request_items: RequestItem[];
}

export const BENEFIT_LABEL: Record<string, string> = { tasting_meal: '品鉴会餐费', tasting_wine: '品鉴酒', travel: '庄园之旅', rebate: '返利', gift: '赠品', other: '其他' };
export const PAYER_LABEL: Record<string, string> = { customer: '客户', employee: '业务', company: '公司' };
export const SETTLEMENT_LABEL: Record<string, string> = { customer_pay: '客户结账', employee_pay: '业务垫付', company_pay: '公司垫付' };
