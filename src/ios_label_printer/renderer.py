from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import qrcode
from qrcode.constants import ERROR_CORRECT_M

from ios_label_printer.models import DeviceInfo, LabelElement, LabelTemplate
from ios_label_printer.units import mm_to_px, pt_to_px

WINDOWS_FONT_DIR = Path(r"C:\Windows\Fonts")
FONT_CANDIDATES = {
    "Segoe UI": ("segoeui.ttf", "segoeuib.ttf"),
    "Arial": ("arial.ttf", "arialbd.ttf"),
    "Calibri": ("calibri.ttf", "calibrib.ttf"),
    "Tahoma": ("tahoma.ttf", "tahomabd.ttf"),
}


@lru_cache(maxsize=32)
def resolve_font_path(family: str, bold: bool) -> str | None:
    names = FONT_CANDIDATES.get(family, FONT_CANDIDATES["Segoe UI"])
    filename = names[1] if bold and len(names) > 1 else names[0]
    path = WINDOWS_FONT_DIR / filename
    if path.exists():
        return str(path)
    for fallback in ("segoeui.ttf", "arial.ttf"):
        candidate = WINDOWS_FONT_DIR / fallback
        if candidate.exists():
            return str(candidate)
    return None


def load_font(family: str, bold: bool, size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = resolve_font_path(family, bold)
    if path:
        return ImageFont.truetype(path, size_px)
    return ImageFont.load_default()


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, element: LabelElement, box: tuple[int, int], dpi: int):
    width, height = box
    size = pt_to_px(element.font_size_pt, dpi)
    font = load_font(element.font_family, element.bold, size)
    while size > 8:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        if text_w <= width and text_h <= height:
            return font
        size -= 1
        font = load_font(element.font_family, element.bold, size)
    return font


def _draw_text(image: Image.Image, element: LabelElement, device: DeviceInfo, dpi: int) -> None:
    draw = ImageDraw.Draw(image)
    x = mm_to_px(element.x_mm, dpi)
    y = mm_to_px(element.y_mm, dpi)
    width = mm_to_px(element.width_mm, dpi)
    height = mm_to_px(element.height_mm, dpi)
    text = element.display_text(device)
    if not text:
        return
    font = _fit_font(draw, text, element, (width, height), dpi)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw_x = x - bbox[0]
    if element.align == "center":
        draw_x += max(0, (width - text_w) // 2)
    elif element.align == "right":
        draw_x += max(0, width - text_w)
    draw_y = y - bbox[1] + max(0, (height - text_h) // 2)
    draw.text((draw_x, draw_y), text, font=font, fill=_hex_to_rgb(element.color))


def render_qr_image(payload: str, size: int) -> Image.Image:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=1, border=0)
    qr.add_data(payload or " ")
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return qr_image.resize((size, size), Image.Resampling.NEAREST)


def _draw_qr(image: Image.Image, element: LabelElement, device: DeviceInfo, dpi: int, template: LabelTemplate) -> None:
    size = min(mm_to_px(element.width_mm, dpi), mm_to_px(element.height_mm, dpi))
    payload = element.build_qr_payload(device, template)
    qr_image = render_qr_image(payload, size)
    x = mm_to_px(element.x_mm, dpi)
    y = mm_to_px(element.y_mm, dpi)
    image.paste(qr_image, (x, y))


def render_label(template: LabelTemplate, device: DeviceInfo, dpi: int | None = None) -> Image.Image:
    dpi = int(dpi or template.dpi or 600)
    width = mm_to_px(template.width_mm, dpi)
    height = mm_to_px(template.height_mm, dpi)
    image = Image.new("RGB", (width, height), _hex_to_rgb(template.background))
    for element in template.elements:
        if not element.visible:
            continue
        if element.type == "qr" or element.field == "qr_payload":
            _draw_qr(image, element, device, dpi, template)
        else:
            _draw_text(image, element, device, dpi)
    return image
