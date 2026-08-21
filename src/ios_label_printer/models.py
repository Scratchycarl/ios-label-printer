from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


STANDARD_STORAGE_GB = (16, 32, 64, 128, 256, 512, 1024, 2048)


def marketing_storage_gb(capacity_bytes: int | float | None) -> int | None:
    if not capacity_bytes:
        return None
    gb = float(capacity_bytes) / (1000**3)
    for size in STANDARD_STORAGE_GB:
        if gb <= size * 1.08:
            return size
    return int(round(gb))


@dataclass
class DeviceInfo:
    model: str = ""
    product_type: str = ""
    battery_health: int | None = None
    storage_gb: int | None = None
    ios_version: str = ""
    serial: str = ""
    imei: str = ""
    imei2: str = ""
    color: str = ""
    ecid: str = ""
    model_number: str = ""
    region: str = ""
    regulatory: str = ""
    cycle_count: int | None = None
    device_name: str = ""
    source: str = ""

    @classmethod
    def sample(cls) -> DeviceInfo:
        return cls(
            model="iPhone 15 Pro",
            product_type="iPhone16,1",
            battery_health=87,
            storage_gb=256,
            ios_version="18.5",
            serial="F2LXK8EXAMPLE",
            imei="356938035643809",
            color="Black",
            source="sample",
        )

    def field_value(self, field_name: str) -> str:
        mapping = {
            "model": self.model or self.product_type or "—",
            "battery_health": f"{self.battery_health}%" if self.battery_health is not None else "--%",
            "storage": f"{self.storage_gb}GB" if self.storage_gb is not None else "—",
            "ios_version": self.ios_version or "—",
            "serial": self.serial or "—",
            "imei": (self.imei or "").strip() or "No IMEI",
            "imei2": self.imei2 or "—",
            "product_type": self.product_type or "—",
            "color": self.color or "—",
        }
        if field_name == "qr_payload":
            return self.qr_payload()
        return mapping.get(field_name, "")

    def qr_value(self, field_name: str) -> str:
        if field_name == "date":
            return date.today().strftime("%Y/%m/%d")
        mapping = {
            "model": self.model,
            "color": self.color,
            "storage": f"{self.storage_gb}GB" if self.storage_gb is not None else "",
            "serial": self.serial,
            "ios_version": self.ios_version,
            "imei": (self.imei or "").strip() or "No IMEI",
            "imei2": self.imei2,
            "battery_health": f"{self.battery_health}%" if self.battery_health is not None else "",
            "ecid": self.ecid,
            "model_number": self.model_number,
            "region": self.region,
            "regulatory": self.regulatory,
            "cycle_count": "" if self.cycle_count is None else str(self.cycle_count),
            "device_name": self.device_name,
        }
        return str(mapping.get(field_name, "") or "")

    def qr_payload(self) -> str:
        element = LabelElement.default_for_field("qr_payload")
        return element.build_qr_payload(self, LabelTemplate())


LOCK_STATUS_OPTIONS = (
    "Bypassed",
    "SN-Unlocked",
    "Unlocked",
    "Locked",
    "Signal-Bypassed",
    "MDM-Bypassed",
)

LABEL_FIELDS = (
    ("custom", "Custom text"),
    ("lock_status", "Lock Status"),
    ("model", "Device model"),
    ("battery_health", "Battery health"),
    ("storage", "Storage"),
    ("ios_version", "iOS version"),
    ("serial", "Serial number"),
    ("imei", "IMEI"),
    ("qr_payload", "QR code"),
)

DEFAULT_QR_FIELDS = (
    "model",
    "color",
    "storage",
    "serial",
    "ios_version",
    "imei",
    "battery_health",
    "date",
)

QR_FIELD_CHOICES = (
    ("model", "Model Name"),
    ("color", "Color"),
    ("storage", "Storage"),
    ("serial", "Serial Number"),
    ("ios_version", "iOS Version"),
    ("imei", "IMEI"),
    ("imei2", "IMEI2"),
    ("ecid", "ECID"),
    ("model_number", "Model Number"),
    ("region", "Sales Region"),
    ("regulatory", "Regulatory Model"),
    ("cycle_count", "Charge Cycles"),
    ("battery_health", "Battery Health"),
    ("date", "Date"),
    ("device_name", "Name"),
)


@dataclass
class Margins:
    top: float = 1.2
    right: float = 1.2
    bottom: float = 1.2
    left: float = 1.2

    def to_dict(self) -> dict:
        return {"top": self.top, "right": self.right, "bottom": self.bottom, "left": self.left}

    @classmethod
    def from_dict(cls, data: dict | None) -> Margins:
        data = data or {}
        if isinstance(data, (int, float)):
            value = float(data)
            return cls(top=value, right=value, bottom=value, left=value)
        return cls(
            top=float(data.get("top", 1.2)),
            right=float(data.get("right", 1.2)),
            bottom=float(data.get("bottom", 1.2)),
            left=float(data.get("left", 1.2)),
        )


@dataclass
class LabelElement:
    id: str
    type: str  # "text" | "qr"
    field: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    prefix: str = ""
    font_family: str = "Segoe UI"
    font_size_pt: float = 6.0
    bold: bool = False
    align: str = "left"
    color: str = "#000000"
    visible: bool = True
    text: str = ""
    qr_fields: list[str] = field(default_factory=lambda: list(DEFAULT_QR_FIELDS))
    qr_separator: str = ","

    def is_custom(self) -> bool:
        return self.type == "custom" or self.field == "custom"

    def is_qr(self) -> bool:
        return self.type == "qr" or self.field == "qr_payload"

    def is_lock_status(self) -> bool:
        return self.field == "lock_status" or self.type == "lock_status"

    def display_text(self, device: DeviceInfo) -> str:
        if self.is_custom() or self.is_lock_status():
            return self.text
        return f"{self.prefix}{device.field_value(self.field)}"

    def build_qr_payload(self, device: DeviceInfo, template: LabelTemplate | None = None) -> str:
        parts: list[str] = []
        for key in self.qr_fields or DEFAULT_QR_FIELDS:
            value = device.qr_value(key).strip()
            if value:
                parts.append(value)
        if template:
            for element in template.elements:
                if element.is_custom() and element.visible and element.text.strip():
                    parts.append(element.text.strip())
            for element in template.elements:
                if element.is_lock_status() and element.visible and element.text.strip():
                    parts.append(element.text.strip())
        return self.qr_separator.join(parts)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "field": self.field,
            "x_mm": round(self.x_mm, 3),
            "y_mm": round(self.y_mm, 3),
            "width_mm": round(self.width_mm, 3),
            "height_mm": round(self.height_mm, 3),
            "prefix": self.prefix,
            "font_family": self.font_family,
            "font_size_pt": self.font_size_pt,
            "bold": self.bold,
            "align": self.align,
            "color": self.color,
            "visible": self.visible,
            "text": self.text,
            "qr_fields": list(self.qr_fields),
            "qr_separator": self.qr_separator,
        }

    @classmethod
    def from_dict(cls, data: dict) -> LabelElement:
        return cls(
            id=str(data.get("id") or data.get("field") or "field"),
            type=str(data.get("type", "text")),
            field=str(data.get("field", "model")),
            x_mm=float(data.get("x_mm", 1.5)),
            y_mm=float(data.get("y_mm", 1.5)),
            width_mm=float(data.get("width_mm", 20)),
            height_mm=float(data.get("height_mm", 4)),
            prefix=str(data.get("prefix", "")),
            font_family=str(data.get("font_family", "Segoe UI")),
            font_size_pt=float(data.get("font_size_pt", 6)),
            bold=bool(data.get("bold", False)),
            align=str(data.get("align", "left")),
            color=str(data.get("color", "#000000")),
            visible=bool(data.get("visible", True)),
            text=str(data.get("text", "")),
            qr_fields=list(data.get("qr_fields") or DEFAULT_QR_FIELDS),
            qr_separator=str(data.get("qr_separator", ",")),
        )

    @classmethod
    def default_for_field(cls, field_name: str) -> LabelElement:
        if field_name == "custom":
            return cls(
                id="custom",
                type="custom",
                field="custom",
                x_mm=1.4,
                y_mm=24.0,
                width_mm=37.2,
                height_mm=3.8,
                font_size_pt=6.5,
                text="",
            )
        if field_name == "lock_status":
            return cls(
                id="lock_status",
                type="lock_status",
                field="lock_status",
                x_mm=1.4,
                y_mm=24.0,
                width_mm=24.0,
                height_mm=3.8,
                font_size_pt=6.5,
                text="",
            )
        if field_name == "qr_payload":
            return cls(
                id="qr",
                type="qr",
                field="qr_payload",
                x_mm=26.4,
                y_mm=1.4,
                width_mm=12.2,
                height_mm=12.2,
                qr_fields=list(DEFAULT_QR_FIELDS),
                qr_separator=",",
            )
        defaults = {
            "model": dict(id="model", prefix="", font_size_pt=8, bold=True, y_mm=1.4, width_mm=24.4, height_mm=4.6),
            "battery_health": dict(id="battery", prefix="BH ", y_mm=6.4, width_mm=12.0, height_mm=3.6),
            "storage": dict(id="storage", prefix="", y_mm=6.4, x_mm=13.6, width_mm=12.4, height_mm=3.6),
            "ios_version": dict(id="ios", prefix="iOS ", y_mm=10.2, width_mm=24.4, height_mm=3.4),
            "serial": dict(id="serial", prefix="SN ", y_mm=14.6, width_mm=37.2, height_mm=3.6, font_size_pt=5.5),
            "imei": dict(id="imei", prefix="IMEI ", y_mm=18.6, width_mm=37.2, height_mm=3.6, font_size_pt=5.5),
        }
        values = defaults.get(field_name, {"id": field_name})
        return cls(
            type="text",
            field=field_name,
            x_mm=float(values.get("x_mm", 1.4)),
            y_mm=float(values.get("y_mm", 1.4)),
            width_mm=float(values.get("width_mm", 24)),
            height_mm=float(values.get("height_mm", 3.6)),
            prefix=str(values.get("prefix", "")),
            font_size_pt=float(values.get("font_size_pt", 6)),
            bold=bool(values.get("bold", False)),
            id=str(values.get("id", field_name)),
        )


@dataclass
class LabelTemplate:
    name: str = "Default 40×30"
    width_mm: float = 40.0
    height_mm: float = 30.0
    dpi: int = 600
    margin_mm: Margins = field(default_factory=Margins)
    background: str = "#FFFFFF"
    elements: list[LabelElement] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "dpi": self.dpi,
            "margin_mm": self.margin_mm.to_dict(),
            "background": self.background,
            "elements": [element.to_dict() for element in self.elements],
        }

    @classmethod
    def from_dict(cls, data: dict) -> LabelTemplate:
        elements = [LabelElement.from_dict(item) for item in data.get("elements", [])]
        return cls(
            name=str(data.get("name", "Untitled")),
            width_mm=float(data.get("width_mm", 40)),
            height_mm=float(data.get("height_mm", 30)),
            dpi=int(data.get("dpi", 600)),
            margin_mm=Margins.from_dict(data.get("margin_mm")),
            background=str(data.get("background", "#FFFFFF")),
            elements=elements,
        )

    def element_by_field(self, field_name: str) -> LabelElement | None:
        for element in self.elements:
            if element.field == field_name:
                return element
        return None

    def next_custom_id(self) -> str:
        existing = {element.id for element in self.elements}
        index = 1
        while f"custom_{index}" in existing:
            index += 1
        return f"custom_{index}"
