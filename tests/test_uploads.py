"""上传图片校验模块测试。"""
import asyncio
import io
import random

import pytest
from fastapi import UploadFile
from PIL import Image

from app.core import uploads
from app.core.config import Settings
from app.core.uploads import UploadValidationError, validate_and_normalize_upload


def _make_image(fmt: str = "JPEG", size=(16, 16), mode="RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color=(120, 200, 80)).save(buf, format=fmt)
    return buf.getvalue()


def _upload(data: bytes, content_type: str | None, filename: str = "photo.jpg"):
    return UploadFile(
        filename=filename,
        file=io.BytesIO(data),
        headers={"content-type": content_type} if content_type is not None else {},
    )


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def safe_settings(monkeypatch):
    s = Settings(
        environment="development",
        upload_max_bytes=1024 * 64,
        upload_allowed_types="image/jpeg,image/png,image/webp",
    )
    monkeypatch.setattr(uploads, "settings", s)
    return s


def test_valid_jpeg_accepted_and_normalized(safe_settings):
    out, ext = _run(
        validate_and_normalize_upload(_upload(_make_image("JPEG"), "image/jpeg"))
    )
    assert ext == ".jpg"
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "JPEG"


def test_valid_png_with_transparency_normalized_to_jpeg(safe_settings):
    out, ext = _run(
        validate_and_normalize_upload(
            _upload(_make_image("PNG", mode="RGBA"), "image/png")
        )
    )
    assert ext == ".jpg"
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"


def test_valid_webp_accepted(safe_settings):
    out, _ = _run(
        validate_and_normalize_upload(_upload(_make_image("WEBP"), "image/webp"))
    )
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "JPEG"


def test_rejects_non_image_bytes(safe_settings):
    with pytest.raises(UploadValidationError) as exc:
        _run(
            validate_and_normalize_upload(
                _upload(b"not an image, just text", "image/jpeg", "x.jpg")
            )
        )
    assert exc.value.status_code == 400


def test_rejects_content_type_spoofing(safe_settings):
    with pytest.raises(UploadValidationError):
        _run(
            validate_and_normalize_upload(
                _upload(b"<?php phpinfo(); ?>", "image/jpeg", "shell.php")
            )
        )


def test_rejects_disallowed_content_type_early(safe_settings):
    with pytest.raises(UploadValidationError) as exc:
        _run(
            validate_and_normalize_upload(
                _upload(_make_image("JPEG"), "image/gif", "x.gif")
            )
        )
    assert exc.value.status_code == 400


def test_rejects_oversize(safe_settings):
    safe_settings.upload_max_bytes = 1024
    noisy = bytes(random.randint(0, 255) for _ in range(64 * 64))
    img = Image.frombytes("L", (64, 64), noisy).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    data = buf.getvalue()
    assert len(data) > 1024
    with pytest.raises(UploadValidationError) as exc:
        _run(validate_and_normalize_upload(_upload(data, "image/jpeg")))
    assert exc.value.status_code == 413


def test_rejects_empty_upload(safe_settings):
    with pytest.raises(UploadValidationError) as exc:
        _run(validate_and_normalize_upload(_upload(b"", "image/jpeg")))
    assert exc.value.status_code == 400


def test_rejects_unsupported_image_format(safe_settings):
    with pytest.raises(UploadValidationError):
        _run(
            validate_and_normalize_upload(
                _upload(_make_image("GIF"), "image/gif", "x.gif")
            )
        )
