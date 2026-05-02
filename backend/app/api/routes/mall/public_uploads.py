"""
/api/mall/public-uploads/*  —— 匿名可访问的上传端点

专用于注册流程：用户尚未登录时需要上传营业执照。
与 /salesman/attachments/upload 区分：
  - 此端点不鉴权（注册流程无 token）
  - kind 白名单仅 `business_license`（不能当作通用图床滥用）
  - 限流：单 IP 每分钟 5 次（防 DDoS 铺图）
  - 文件上限沿用 settings.MALL_UPLOAD_MAX_SIZE_MB
  - sha256 + uuid 文件名防路径注入
"""
import hashlib
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile

from app.core.config import settings

router = APIRouter()

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf"}
ALLOWED_MIMES = {
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
    "application/pdf",
}
MAX_BYTES = settings.MALL_UPLOAD_MAX_SIZE_MB * 1024 * 1024
VALID_KINDS = {"business_license"}

# 单 IP 限流（进程内 sliding window）
_RATE_LIMIT_WINDOW = 60  # 秒
_RATE_LIMIT_MAX = 5
_ip_hits: dict[str, list[float]] = defaultdict(list)


def _rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    cutoff = now - _RATE_LIMIT_WINDOW
    hits = [t for t in _ip_hits[ip] if t > cutoff]
    if len(hits) >= _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail=f"上传过于频繁，请 {_RATE_LIMIT_WINDOW} 秒后重试",
        )
    hits.append(now)
    _ip_hits[ip] = hits


@router.post("/upload")
async def public_upload(
    request: Request,
    file: UploadFile,
    kind: str = Form(...),
):
    """注册时匿名上传（比如营业执照）。"""
    _rate_limit(request)

    if kind not in VALID_KINDS:
        raise HTTPException(
            status_code=400, detail=f"kind 非法，允许: {VALID_KINDS}"
        )
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
    month_dir = datetime.now(timezone.utc).strftime("%Y-%m")
    safe_name = f"{uuid.uuid4().hex}{ext}"
    rel_path = os.path.join("mall", month_dir, "public", kind, safe_name)
    abs_dir = Path(settings.UPLOAD_DIR) / "mall" / month_dir / "public" / kind
    abs_dir.mkdir(parents=True, exist_ok=True)
    abs_path = abs_dir / safe_name
    with open(abs_path, "wb") as f:
        f.write(content)

    return {
        "url": f"/api/uploads/files/{rel_path}",
        "sha256": sha256,
        "size": len(content),
        "mime_type": file.content_type,
        "kind": kind,
    }
