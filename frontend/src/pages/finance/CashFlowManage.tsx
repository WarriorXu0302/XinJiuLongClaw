import { Tabs, Typography } from 'antd';
import ReceiptList from './ReceiptList';
import PaymentList from './PaymentList';
import ReceivableList from './ReceivableList';
import SettlementList from './SettlementList';

const { Title } = Typography;

/**
 * 资金往来汇总页 — 合并 收款 / 付款 / 应收 / 厂家结算 四个原独立页面
 */
function CashFlowManage() {
  return (
    <>
      <Title level={4} style={{ marginBottom: 12 }}>资金往来</Title>
      <Tabs
        defaultActiveKey="receipt"
        items={[
          { key: 'receipt', label: '客户收款', children: <ReceiptList /> },
          { key: 'payment', label: '对外付款', children: <PaymentList /> },
          { key: 'receivable', label: '应收账款', children: <ReceivableList /> },
          { key: 'settlement', label: '厂家结算', children: <SettlementList /> },
        ]}
      />
    </>
  );
}

export default CashFlowManage;
