"""
文件附件服务（凭证/送达照片防篡改）。

流程：
  - 上传：接收 UploadFile → 校验 MIME + magic number + size → 算 sha256
    → 用 uuid 重命名（防路径注入）→ 写 attachments 表 + 元数据
  - 回放：取 url 前 **再次校验** 文件 sha256 == 存库值
  - 审计：所有上传/查阅记 mall_audit_logs

字段（见 plan）：
  file_url / sha256 / file_size / mime_type / uploaded_by_user_id /
  uploaded_at / client_ip / user_agent

Phase 2 可选：RSA 签名 (sha256 + metadata) 存 signature 字段。
"""
# TODO(M4):
# async def save_attachment(db, file: UploadFile, file_type: str, order_id: str, uploader: MallUser, request: Request) -> MallPaymentAttachment | MallDeliveryAttachment: ...
# async def verify_attachment_integrity(db, attachment_id: str) -> bool: ...
