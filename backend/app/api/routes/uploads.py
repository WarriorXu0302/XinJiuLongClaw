"""
File upload API — store and serve uploaded images.
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.security import CurrentUser

router = APIRouter()

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
MAX_SIZE_BYTES = settings.UPLOAD_MAX_SIZE_MB * 1024 * 1024


@router.post("")
async def upload_file(file: UploadFile, user: CurrentUser):
    """Upload a single image file. Returns the file URL."""
    if not file.filename:
        raise HTTPException(400, "缺少文件名")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型: {ext}，允许: {', '.join(ALLOWED_EXTENSIONS)}")

    content = await file.read()
    if len(content) > MAX_SIZE_BYTES:
        raise HTTPException(400, f"文件过大，最大 {settings.UPLOAD_MAX_SIZE_MB}MB")

    # Build path: uploads/YYYY-MM/{full-uuid}{ext}
    # 用完整 UUID (2^128) 替代 8-hex 前缀，枚举空间从 4.3 亿提升到不可爆破。
    # 原文件名不再拼进来 —— 业务名（凭证.jpg 等）会让路径可预测。
    month_dir = datetime.now(timezone.utc).strftime("%Y-%m")
    safe_name = f"{uuid.uuid4().hex}{ext}"
    rel_path = os.path.join(month_dir, safe_name)

    abs_dir = Path(settings.UPLOAD_DIR) / month_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    abs_path = abs_dir / safe_name

    with open(abs_path, "wb") as f:
        f.write(content)

    return {
        "url": f"/api/uploads/files/{rel_path}",
        "filename": file.filename,
        "size": len(content),
    }


@router.get("/files/{path:path}")
async def serve_file(path: str):
    """Serve an uploaded file.

    Note: intentionally not auth-guarded — frontend uses <img src={url}> directly
    and browsers don't send Authorization headers on img requests. Security relies
    on unpredictable UUID paths. Dedicated PR needed to migrate frontend to blob
    fetch before we can require auth here.
    """
    abs_path = Path(settings.UPLOAD_DIR) / path
    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(404, "文件不存在")
    # Security: prevent path traversal
    try:
        abs_path.resolve().relative_to(Path(settings.UPLOAD_DIR).resolve())
    except ValueError:
        raise HTTPException(403, "禁止访问")
    return FileResponse(abs_path)
