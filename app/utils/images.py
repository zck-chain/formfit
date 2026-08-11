"""上传图片安全校验与转码：magic bytes 真实验型 + 大小限制 + HEIC 转 JPEG。

为什么需要：仅信任 UploadFile.content_type 不安全——它由客户端声明，可伪造。
这里用 Pillow 实际解码读取图片格式，确保：
1. 文件确实是受支持的图片（而非伪装的脚本/可执行文件）；
2. 真实格式与大小在限制内；
3. HEIC/HEIF 统一转码为 JPEG 再送视觉模型（data-url / 模型兼容性更好）。

pillow-heif 为可选依赖：未安装时 HEIC 上传返回 415，其余格式照常工作。
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.core.config import settings

logger = logging.getLogger(__name__)

# 接受的真实图片格式（Pillow format 名）→ 输出扩展名/mime
_ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF", "HEIC"}
_NORMALIZED_EXT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
_NORMALIZED_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}

# JPEG 输出质量（兼顾体积与视觉评估可用性）
_JPEG_QUALITY = 90

_heif_registered = False


def _ensure_heif_support() -> bool:
    """惰性注册 pillow-heif 的 HEIF/HEIC 解码器。返回是否可用。"""
    global _heif_registered
    if _heif_registered:
        return True
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
        _heif_registered = True
        return True
    except ImportError:
        logger.warning(
            "pillow-heif 未安装，HEIC/HEIF 上传将被拒绝；"
            "如需支持 iPhone 照片，请安装 pillow-heif"
        )
        return False


class ImageValidationError(Exception):
    """图片校验失败，携带应返回的 HTTP 状态码与提示。"""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def validate_and_prepare(
    raw: bytes,
    declared_content_type: str | None,
    *,
    max_bytes: int | None = None,
) -> tuple[bytes, str, str]:
    """校验上传字节并返回可安全存储/送模的图片。

    返回 ``(output_bytes, ext, mime)``：
    - JPEG/PNG/WebP：原样返回；
    - HEIC/HEIF：转码为 JPEG 返回。

    失败抛 :class:`ImageValidationError`，路由层映射为 4xx。
    """
    limit = max_bytes if max_bytes is not None else settings.upload_max_bytes
    if len(raw) == 0:
        raise ImageValidationError(400, "上传文件为空")
    if len(raw) > limit:
        raise ImageValidationError(
            413, f"图片过大，最大允许 {limit // (1024 * 1024)}MB"
        )

    # Pillow 在 verify 后不能再用同一 image 对象做转换，所以这里 open 两次：
    # 一次读格式，一次（必要时）转码。
    try:
        with Image.open(io.BytesIO(raw)) as img:
            real_format = (img.format or "").upper()
    except UnidentifiedImageError as exc:
        raise ImageValidationError(
            415, "无法识别的图片类型，仅支持 JPG/PNG/WebP/HEIC"
        ) from exc

    if real_format in ("HEIF", "HEIC") and not _ensure_heif_support():
        raise ImageValidationError(
            415, "服务器未启用 HEIC 支持，请先转存为 JPG/PNG 后上传"
        )

    if real_format not in _ACCEPTED_FORMATS:
        raise ImageValidationError(
            415, f"不支持的图片格式：{real_format or '未知'}，仅支持 JPG/PNG/WebP/HEIC"
        )

    # HEIC 统一转 JPEG，确保下游 data-url / 模型兼容
    if real_format in ("HEIF", "HEIC"):
        out = io.BytesIO()
        with Image.open(io.BytesIO(raw)) as img:
            img = img.convert("RGB")
            img.save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        return out.getvalue(), ".jpg", "image/jpeg"

    return raw, _NORMALIZED_EXT[real_format], _NORMALIZED_MIME[real_format]


def guess_extension(filename: str | None) -> str:
    """从原始文件名取后缀，作为回退；不信任其内容。"""
    ext = Path(filename or "").suffix.lower()
    return ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif") else ".img"
