"""
/api/mall/salesman/attachments/upload

业务员上传附件（凭证图 / 送达图）：
  - 接收 multipart file + form 字段 kind
  - 后端计算 sha256，落盘后返回 {url, sha256, size}
  - 前端拿到 url + sha256 作为"已验证"凭证传给后续 ship/deliver/upload_payment_voucher

关键安全点：
  - 图类型白名单
  - 大小上限（settings.MALL_UPLOAD_MAX_SIZE_MB）
  - 文件名用 UUID，不用用户输入（防路径注入 / 预测爆破）
  - sha256 由后端算，业务员无法伪造
"""
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from app.core.config import settings
from app.core.security import CurrentMallUser

router = APIRouter()

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_BYTES = settings.MALL_UPLOAD_MAX_SIZE_MB * 1024 * 1024
VALID_KINDS = {"payment_voucher", "delivery_photo", "payment_qr"}


@router.post("/upload")
async def upload_attachment(
    current: CurrentMallUser,
    file: UploadFile,
    kind: str = Form(...),
):
    if current.get("user_type") != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可上传附件")
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind 非法，允许: {VALID_KINDS}")

    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 {ext}，允许 {', '.join(sorted(ALLOWED_EXTS))}",
        )
    if file.content_type and file.content_type not in ALLOWED_MIMES:
        raise HTTPException(status_code=400, detail=f"MIME 非法: {file.content_type}")

    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大，最大 {settings.MALL_UPLOAD_MAX_SIZE_MB}MB",
        )

    sha256 = hashlib.sha256(content).hexdigest()

    # 路径：uploads/mall/YYYY-MM/{kind}/{uuid}{ext}
    month_dir = datetime.now(timezone.utc).strftime("%Y-%m")
    safe_name = f"{uuid.uuid4().hex}{ext}"
    rel_path = os.path.join("mall", month_dir, kind, safe_name)
    abs_dir = Path(settings.UPLOAD_DIR) / "mall" / month_dir / kind
    abs_dir.mkdir(parents=True, exist_ok=True)
    abs_path = abs_dir / safe_name
    with open(abs_path, "wb") as f:
        f.write(content)

    # 返回给前端；前端把这个 url+sha256 塞进 ship/deliver/upload_payment_voucher 的 payload
    return {
        "url": f"/api/uploads/files/{rel_path}",
        "sha256": sha256,
        "size": len(content),
        "mime_type": file.content_type,
        "kind": kind,
    }
