# =============================================================================
# 图形验证码服务：生成清晰可见的 PNG 验证码并入库
# =============================================================================

from __future__ import annotations

import base64
import io
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.logging_config import get_logger
from src.models.entities import CaptchaRecord

logger = get_logger(__name__)

# 排除易混淆字符，提升可读性
_CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _random_code(length: int = 4) -> str:
    """生成随机验证码字符串。"""
    return "".join(random.choice(_CAPTCHA_CHARS) for _ in range(length))


def _load_font(size: int = 42) -> ImageFont.ImageFont:
    """尝试加载系统 TrueType 字体，失败则回退默认字体。"""
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def render_captcha_image(code: str, width: int = 160, height: int = 56) -> str:
    """
    绘制清晰的验证码 PNG，返回 data URL (base64)。

    设计要点：
    - 较大字号、深色前景、浅色背景
    - 轻微干扰线与噪点，保证机器难识但人眼清晰
    """
    bg_color = (245, 248, 252)
    image = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(image)
    font = _load_font(42)

    # 轻微干扰线（低对比度）
    for _ in range(4):
        start = (random.randint(0, width), random.randint(0, height))
        end = (random.randint(0, width), random.randint(0, height))
        draw.line([start, end], fill=(200, 210, 220), width=1)

    # 逐字符绘制，带轻微旋转偏移
    char_space = width // (len(code) + 1)
    for i, ch in enumerate(code):
        x = char_space * (i + 1) - 12
        y = random.randint(4, 12)
        color = (
            random.randint(20, 60),
            random.randint(20, 80),
            random.randint(80, 140),
        )
        draw.text((x, y), ch, font=font, fill=color)

    # 少量噪点
    for _ in range(40):
        px = random.randint(0, width - 1)
        py = random.randint(0, height - 1)
        draw.point((px, py), fill=(180, 190, 200))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


async def create_captcha(session: AsyncSession) -> dict:
    """生成验证码图片并写入 captcha_records 表。"""
    settings = get_settings()
    fixed = (settings.captcha_fixed_code or "").strip()
    code = fixed if fixed else _random_code(4)
    captcha_id = f"cap_{uuid.uuid4()}"
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.captcha_expire_seconds
    )
    record = CaptchaRecord(
        captcha_id=captcha_id,
        code=code,
        is_used=False,
        expires_at=expires_at,
    )
    session.add(record)
    await session.commit()

    image_base64 = render_captcha_image(code)
    if fixed:
        logger.info("验证码已生成（固定码） captcha_id=%s code=%s", captcha_id, code)
    else:
        logger.info("验证码已生成 captcha_id=%s", captcha_id)
    payload = {"captcha_id": captcha_id, "image_base64": image_base64}
    # 演示固定码时回传，便于前端预填（手机端易漏填）
    if fixed:
        payload["fixed_code"] = code
    return payload


async def verify_captcha(
    session: AsyncSession,
    captcha_id: str,
    captcha_code: str,
) -> bool:
    """
    校验验证码（忽略大小写），成功后标记为已使用。

    返回 True 表示校验通过。
    """
    result = await session.execute(
        select(CaptchaRecord).where(CaptchaRecord.captcha_id == captcha_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        logger.warning("验证码不存在: %s", captcha_id)
        return False
    if record.is_used:
        logger.warning("验证码已使用: %s", captcha_id)
        return False
    now = datetime.now(timezone.utc)
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        logger.warning("验证码已过期: %s", captcha_id)
        return False
    if record.code.lower() != (captcha_code or "").strip().lower():
        logger.warning("验证码错误: %s", captcha_id)
        return False

    record.is_used = True
    await session.commit()
    return True