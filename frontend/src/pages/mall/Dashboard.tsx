/**
 * 商城运营看板（《商城》一级菜单首页）
 *
 * 内容：今日/本月订单数、GMV、实收；业务员排行；商品销量排行；待处理项
 *
 * TODO(M5):
 *   - GET /api/mall/admin/dashboard/metrics
 *   - GET /api/mall/admin/dashboard/salesman-ranking
 *   - GET /api/mall/admin/dashboard/product-ranking
 *   - GET /api/mall/admin/dashboard/pending-tasks
 */
import { Typography } from 'antd';

const { Title } = Typography;

export default function MallDashboard() {
  return (
    <div>
      <Title level={3}>商城看板</Title>
      <p>TODO(M5): 今日订单 / GMV / 实收 / 业务员排行 / 商品排行 / 待处理项</p>
    </div>
  );
}
