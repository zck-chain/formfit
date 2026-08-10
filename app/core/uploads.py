"""体态评估图片上传校验与规范化。

不信任客户端声明的 Content-Type 和扩展名：
1. 边读边累计字节数，超过 upload_max_bytes 立即中止（不依赖 Content-Length）。
2. 用 Pillow 实际解码并 verify()，确认是真实图片且格式在允许集合内。
3. 统一转存为 JPEG（剥离 EXIF、填白底处理透明通道），保证下游视觉模型兼容。
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Pillow 格式标识 → 标准 MIME。只放我们真正支持并能安全转存的格式。
_FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
# 反向：MIME → Pillow format
_MIME_TO_FORMAT = {v: k for k, v in _FORMAT_TO_MIME.items()}

# JPEG 输出参数
_JPEG_QUALITY = 88
_READ_CHUNK = 1024 * 256


class UploadValidationError(ValueError):
    """上传内容不合法；映射为 HTTP 4xx。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def _read_within_limit(upload: UploadFile, max_bytes: int) -> bytes:
    """分块读取上传内容，超出上限立即中止并抛 413。"""
    buf = io.BytesIO()
    total = 0
    while True:
        chunk = await upload.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            await upload.close()
            raise UploadValidationError("上传文件过大", status_code=413)
        buf.write(chunk)
    return buf.getvalue()


def _detect_format(data: bytes) -> str:
    """用 Pillow 真实解码并校验，返回 Pillow 格式名（如 JPEG）。"""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()  # 校验完整性，但 verify 后图片不可再用
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.info("图片校验失败：%s", exc)
        raise UploadValidationError("文件不是合法的图片") from exc

    # verify 之后需重新打开才能读取像素/格式
    with Image.open(io.BytesIO(data)) as img:
        fmt = (img.format or "").upper()

    if fmt not in _FORMAT_TO_MIME:
        raise UploadValidationError(
            f"不支持的图片格式：{fmt or '未知'}，仅支持 JPG/PNG/WebP"
        )

    allowed = settings.upload_allowed_type_set
    if _FORMAT_TO_MIME[fmt] not in allowed:
        raise UploadValidationError(
            f"该图片格式（{_FORMAT_TO_MIME[fmt]}）不在允许列表中"
        )
    return fmt


def _normalize_to_jpeg(data: bytes) -> bytes:
    """转成兼容的 JPEG 字节：处理透明通道、剥离元数据。"""
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        # 透明 PNG/WebP → 白底 JPEG
        if img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        ):
            background = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        return out.getvalue()


async def validate_and_normalize_upload(
    upload: UploadFile,
) -> tuple[bytes, str]:
    """校验上传图片并规范化。

    返回 ``(jpeg_bytes, extension)``，extension 形如 ``.jpg``。
    非法/超限输入抛 UploadValidationError（带 4xx 状态码）。
    """
    max_bytes = settings.upload_max_bytes
    allowed = settings.upload_allowed_type_set
    if not allowed:
        # 配置兜底：未配置允许类型时不放行任何上传
        raise UploadValidationError("服务未配置允许的图片类型", status_code=500)

    # 声明的 MIME 也做一次快速拒绝（真实内容仍以 Pillow 为准）
    declared = (upload.content_type or "").lower()
    if declared and declared not in allowed:
        raise UploadValidationError("仅支持 JPG/PNG/WebP 图片")

    data = await _read_within_limit(upload, max_bytes)
    if not data:
        raise UploadValidationError("上传文件为空")

    _detect_format(data)  # 真实格式校验（伪造 MIME / 非图片在此被拒）
    normalized = _normalize_to_jpeg(data)
    return normalized, ".jpg"
