from __future__ import annotations

import asyncio
import inspect
import plistlib
import re
import shutil
import subprocess
from contextlib import asynccontextmanager
from typing import Any

from ios_label_printer.models import DeviceInfo, marketing_storage_gb
from ios_label_printer.template import load_device_color_maps, load_device_model_map

MODEL_MAP = load_device_model_map()
MODEL_NUMBER_COLORS, PRODUCT_ENCLOSURE_COLORS = load_device_color_maps()

# Named / hex finishes only. Bare enclosure digits are product-specific and live in device_colors.json.
COLOR_MAP = {
    "black": "Black",
    "white": "White",
    "gold": "Gold",
    "silver": "Silver",
    "pink": "Pink",
    "blue": "Blue",
    "red": "Red",
    "yellow": "Yellow",
    "green": "Green",
    "purple": "Purple",
    "starlight": "Starlight",
    "midnight": "Midnight",
    "space black": "Space Black",
    "space gray": "Space Gray",
    "space grey": "Space Gray",
    "graphite": "Graphite",
    "sierra blue": "Sierra Blue",
    "alpine green": "Alpine Green",
    "deep purple": "Deep Purple",
    "natural titanium": "Natural Titanium",
    "blue titanium": "Blue Titanium",
    "white titanium": "White Titanium",
    "black titanium": "Black Titanium",
    "desert titanium": "Desert Titanium",
    "ultramarine": "Ultramarine",
    "teal": "Teal",
    "1f2020": "Space Black",
    "f5f5f0": "Silver",
    "fae7cf": "Gold",
    "a7c1d9": "Sierra Blue",
    "3c3c3d": "Graphite",
    "e3ccb4": "Gold",
    "f1f2ed": "Silver",
    "394c38": "Alpine Green",
    "9ed2cd": "Green",
    "ba0c2e": "Red",
    "f9e5c9": "Starlight",
    "2d3132": "Midnight",
    "bfa48f": "Gold",
    "7d7e80": "Space Gray",
    "e4e4e1": "White",
    "5eb0e5": "Blue",
    "d4e4ed": "Blue",
    "e6d0c5": "Pink",
    "e1ccb5": "Gold",
    "e8b4c8": "Pink",
    "e4c1d0": "Pink",
    "f2c4d0": "Pink",
    "e3b2c4": "Pink",
    "f5d0dc": "Pink",
    "d4a5b8": "Pink",
    "fac8d4": "Pink",
    "c8b8d8": "Purple",
    "b8a8c8": "Purple",
    "d4c8e0": "Purple",
    "b9b7ba": "Purple",
    "e8dcc8": "Starlight",
    "f1e6d4": "Starlight",
    "e1e4e3": "Silver",
    "5c5b57": "Black Titanium",
    "f2f1ed": "White Titanium",
    "3b3b3c": "Black Titanium",
    "beb4aa": "Natural Titanium",
    "3c475b": "Blue Titanium",
    "c2a48d": "Desert Titanium",
}

# Front bezel digits are mostly Black/White across generations.
FRONT_DIGIT_COLORS = {
    "1": "Black",
    "2": "White",
}

# Housing/back first. DeviceColor is the front bezel and is "1" (Black) on every iPad mini 6/7.
_HOUSING_COLOR_KEYS = (
    "DeviceHousingColor",
    "DeviceEnclosureColor",
    "DeviceBackingColor",
)
_HOUSING_RGB_KEYS = ("DeviceEnclosureRGBColor",)
_FRONT_COLOR_KEYS = ("DeviceCoverGlassColor", "DeviceColor")
_FRONT_RGB_KEYS = ("DeviceRGBColor",)
COLOR_LOCKDOWN_KEYS = _HOUSING_COLOR_KEYS + _HOUSING_RGB_KEYS + _FRONT_COLOR_KEYS + _FRONT_RGB_KEYS
_HEX_DISTANCE_LIMIT = 32 * 32 * 3
_MODEL_NUMBER_RE = re.compile(r"[A-Z0-9]{4,}")


BATTERY_MAX_KEYS = (
    "NominalChargeCapacity",
    "AppleRawMaxCapacity",
    "MaxCapacity",
    "AppleRawMaxCapability",
)
BATTERY_DESIGN_KEYS = ("DesignCapacity", "DesignMaxCapacity")


class DeviceReadError(RuntimeError):
    pass


def model_name_from_product_type(product_type: str) -> str:
    return MODEL_MAP.get(product_type, product_type or "Unknown")


def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return value
    return value


async def _call(func, *args, **kwargs):
    result = func(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _walk_find(obj: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys and key not in found:
                found[key] = value
            nested = _walk_find(value, keys)
            for nested_key, nested_value in nested.items():
                found.setdefault(nested_key, nested_value)
    elif isinstance(obj, list):
        for item in obj:
            nested = _walk_find(item, keys)
            for nested_key, nested_value in nested.items():
                found.setdefault(nested_key, nested_value)
    return found


def _first_number(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def battery_health_from_payload(payload: Any) -> int | None:
    values = _walk_find(payload, BATTERY_MAX_KEYS + BATTERY_DESIGN_KEYS)
    maximum = _first_number(values, BATTERY_MAX_KEYS)
    design = _first_number(values, BATTERY_DESIGN_KEYS)
    if maximum is None or design is None or design <= 0:
        return None
    return int(round(100.0 * maximum / design))


def _storage_from_disk_usage(payload: Any) -> int | None:
    values = _walk_find(payload, ("TotalDiskCapacity", "TotalDataCapacity", "NANDInfo"))
    capacity = _first_number(values, ("TotalDiskCapacity", "TotalDataCapacity"))
    if capacity is None:
        return None
    return marketing_storage_gb(capacity)


def _hex_rgb(token: str) -> tuple[int, int, int] | None:
    text = token.strip().lstrip("#").lower()
    if len(text) != 6 or any(ch not in "0123456789abcdef" for ch in text):
        return None
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _normalize_color_value(value: Any, as_rgb: bool = False) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bytes):
        value = value.hex()
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        number = int(value)
        if as_rgb or number > 15:
            return f"{number & 0xFFFFFF:06x}"
        if number >= 0:
            return str(number)
        return ""
    return str(value).strip()


def _nearest_named_hex(token: str) -> str:
    rgb = _hex_rgb(token)
    if rgb is None:
        return ""
    best_name = ""
    best_dist = _HEX_DISTANCE_LIMIT + 1
    for map_key, name in COLOR_MAP.items():
        other = _hex_rgb(map_key)
        if other is None:
            continue
        dist = sum((left - right) ** 2 for left, right in zip(rgb, other))
        if dist < best_dist:
            best_dist = dist
            best_name = name
    if best_dist <= _HEX_DISTANCE_LIMIT:
        return best_name
    return ""


def color_from_model_number(model_number: str) -> str:
    text = (model_number or "").strip().upper()
    if not text:
        return ""
    match = _MODEL_NUMBER_RE.search(text)
    if not match:
        return ""
    token = match.group(0)
    if token in MODEL_NUMBER_COLORS:
        return MODEL_NUMBER_COLORS[token]
    # Region suffixes (LL/A, ZP/A, …) are already stripped by the regex cut at non-alnum,
    # but keep a 5-char Apple marketing prefix fallback (MLWL3, MK7M3).
    if len(token) >= 5 and token[:5] in MODEL_NUMBER_COLORS:
        return MODEL_NUMBER_COLORS[token[:5]]
    return ""


def color_from_product_enclosure(product_type: str, enclosure: str) -> str:
    mapping = PRODUCT_ENCLOSURE_COLORS.get(product_type or "")
    if not mapping:
        return ""
    return mapping.get(str(enclosure).strip().lstrip("#"), "")


def _pretty_color(value: str, *, allow_front_digits: bool = False) -> str:
    text = value.strip().lstrip("#")
    if not text:
        return ""
    key = text.lower().replace("_", " ").replace("-", " ")
    if allow_front_digits and key in FRONT_DIGIT_COLORS:
        return FRONT_DIGIT_COLORS[key]
    if key in COLOR_MAP:
        return COLOR_MAP[key]
    compact = key.replace(" ", "")
    if compact in COLOR_MAP:
        return COLOR_MAP[compact]
    # Bare enclosure digits are not universal (3 means Gold on old iPhones, Pink on mini 6).
    if compact.isdigit():
        return ""
    named_hex = _nearest_named_hex(compact)
    if named_hex:
        return named_hex
    if compact.isalpha():
        return " ".join(part.capitalize() for part in key.split())
    return ""


def _color_tokens(values: dict[str, Any], keys: tuple[str, ...], rgb_keys: tuple[str, ...] = ()) -> list[str]:
    tokens: list[str] = []
    for key in keys:
        token = _normalize_color_value(values.get(key), as_rgb=False)
        if token and token != "0":
            tokens.append(token)
    for key in rgb_keys:
        token = _normalize_color_value(values.get(key), as_rgb=True)
        if token:
            tokens.append(token)
    return tokens


def color_from_lockdown(values: dict[str, Any]) -> str:
    product_type = str(values.get("ProductType") or "").strip()
    model_number = str(values.get("ModelNumber") or "").strip()

    from_model = color_from_model_number(model_number)
    if from_model:
        return from_model

    housing = _color_tokens(values, _HOUSING_COLOR_KEYS, _HOUSING_RGB_KEYS)
    for token in housing:
        from_product = color_from_product_enclosure(product_type, token)
        if from_product:
            return from_product
        pretty = _pretty_color(token, allow_front_digits=False)
        if pretty:
            return pretty
    if housing:
        return ""

    for token in _color_tokens(values, _FRONT_COLOR_KEYS, _FRONT_RGB_KEYS):
        pretty = _pretty_color(token, allow_front_digits=True)
        if pretty:
            return pretty
    return ""


async def _fill_lockdown_color_keys(lockdown, values: dict[str, Any]) -> None:
    for key in COLOR_LOCKDOWN_KEYS:
        if values.get(key) not in (None, ""):
            continue
        try:
            got = await _call(lockdown.get_value, key=key)
        except TypeError:
            try:
                got = await _call(lockdown.get_value, None, key)
            except Exception:
                continue
        except Exception:
            continue
        if got not in (None, ""):
            values[key] = got


def cycle_count_from_payload(payload: Any) -> int | None:
    values = _walk_find(payload, ("CycleCount", "AppleRawCycleCount"))
    for key in ("CycleCount", "AppleRawCycleCount"):
        value = values.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return None


def _format_ecid(value: Any) -> str:
    if value in (None, "", 0):
        return ""
    try:
        return format(int(value), "X")
    except (TypeError, ValueError):
        return str(value)


def device_info_from_lockdown_values(values: dict[str, Any], extra: dict[str, Any] | None = None) -> DeviceInfo:
    extra = extra or {}
    product_type = str(values.get("ProductType") or extra.get("ProductType") or "")
    serial = str(values.get("SerialNumber") or extra.get("SerialNumber") or "")
    ios_version = str(values.get("ProductVersion") or extra.get("ProductVersion") or "")
    imei = str(
        values.get("InternationalMobileEquipmentIdentity")
        or extra.get("InternationalMobileEquipmentIdentity")
        or ""
    )
    imei2 = str(
        values.get("InternationalMobileEquipmentIdentity2")
        or extra.get("InternationalMobileEquipmentIdentity2")
        or ""
    )
    battery = extra.get("battery_health")
    storage = extra.get("storage_gb")
    return DeviceInfo(
        model=model_name_from_product_type(product_type),
        product_type=product_type,
        battery_health=battery,
        storage_gb=storage,
        ios_version=ios_version,
        serial=serial,
        imei=imei,
        imei2=imei2,
        color=color_from_lockdown(values) or str(extra.get("color") or ""),
        ecid=_format_ecid(values.get("UniqueChipID") or extra.get("UniqueChipID")),
        model_number=str(values.get("ModelNumber") or extra.get("ModelNumber") or ""),
        region=str(values.get("RegionInfo") or extra.get("RegionInfo") or ""),
        regulatory=str(values.get("RegulatoryModelNumber") or extra.get("RegulatoryModelNumber") or ""),
        cycle_count=extra.get("cycle_count"),
        device_name=str(values.get("DeviceName") or extra.get("DeviceName") or ""),
        source=str(extra.get("source", "pymobiledevice3")),
    )


@asynccontextmanager
async def _enter(obj):
    if hasattr(obj, "__aenter__"):
        async with obj as value:
            yield value
        return
    if hasattr(obj, "__enter__"):
        with obj as value:
            yield value
        return
    yield obj


async def _fetch_pymobiledevice3() -> DeviceInfo:
    try:
        from pymobiledevice3.exceptions import MuxException
        from pymobiledevice3.lockdown import PlistUsbmuxLockdownClient, create_using_usbmux
    except ImportError as exc:
        raise DeviceReadError("pymobiledevice3 is not installed") from exc

    _patch_usbmux_pair_record_save(PlistUsbmuxLockdownClient, MuxException)

    created = None
    last_error: Exception | None = None
    for kwargs in ({"connection_type": "USB"}, {}):
        try:
            created = create_using_usbmux(**kwargs)
            if inspect.isawaitable(created):
                created = await created
            break
        except Exception as exc:
            last_error = exc
            created = None
    if created is None:
        raise last_error or DeviceReadError("No iPhone is connected.")

    async with _enter(created) as lockdown:
        values = getattr(lockdown, "all_values", None)
        if not values:
            values = await _call(lockdown.get_value)
        if not isinstance(values, dict):
            values = {}
        else:
            values = dict(values)
        await _fill_lockdown_color_keys(lockdown, values)

        extra: dict[str, Any] = {"source": "pymobiledevice3"}
        try:
            disk = await _call(lockdown.get_value, domain="com.apple.disk_usage")
            extra["storage_gb"] = _storage_from_disk_usage(disk)
        except Exception:
            extra["storage_gb"] = _storage_from_disk_usage(values)

        battery_payload: Any = None
        try:
            from pymobiledevice3.services.diagnostics import DiagnosticsService

            diagnostics = DiagnosticsService(lockdown)
            async with _enter(diagnostics) as diag:
                if hasattr(diag, "get_battery"):
                    battery_payload = await _call(diag.get_battery)
                if not battery_payload and hasattr(diag, "ioregistry"):
                    try:
                        battery_payload = await _call(diag.ioregistry, ioclass="IOPMPowerSource")
                    except TypeError:
                        battery_payload = await _call(diag.ioregistry, "IOPMPowerSource")
                if not battery_payload and hasattr(diag, "info"):
                    battery_payload = await _call(diag.info, "All")
        except Exception:
            battery_payload = None

        if battery_payload is None:
            try:
                battery_payload = await _call(lockdown.get_value, domain="com.apple.mobile.battery")
            except Exception:
                battery_payload = None

        extra["battery_health"] = battery_health_from_payload(battery_payload)
        extra["cycle_count"] = cycle_count_from_payload(battery_payload)
        return device_info_from_lockdown_values(values, extra)


def _run_cli(command: list[str], timeout: int = 12) -> str:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    if completed.returncode != 0:
        raise DeviceReadError(completed.stderr.strip() or f"{command[0]} failed")
    return completed.stdout


def _parse_ideviceinfo(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def _fetch_libimobiledevice_cli() -> DeviceInfo:
    ideviceinfo = shutil.which("ideviceinfo")
    if not ideviceinfo:
        raise DeviceReadError("ideviceinfo is not on PATH")

    values = _parse_ideviceinfo(_run_cli([ideviceinfo]))
    extra: dict[str, Any] = {"source": "libimobiledevice"}
    try:
        disk_text = _run_cli([ideviceinfo, "-q", "com.apple.disk_usage"])
        extra["storage_gb"] = _storage_from_disk_usage(_parse_ideviceinfo(disk_text))
    except Exception:
        extra["storage_gb"] = None

    battery_payload: Any = None
    idevicediagnostics = shutil.which("idevicediagnostics")
    if idevicediagnostics:
        for args in (
            [idevicediagnostics, "ioreg", "IOPMPowerSource"],
            [idevicediagnostics, "diagnostics", "All"],
        ):
            try:
                raw = _run_cli(args)
                try:
                    battery_payload = plistlib.loads(raw.encode("utf-8"))
                except Exception:
                    battery_payload = raw
                break
            except Exception:
                continue
    extra["battery_health"] = battery_health_from_payload(battery_payload)
    extra["cycle_count"] = cycle_count_from_payload(battery_payload)
    for key in COLOR_LOCKDOWN_KEYS:
        if values.get(key) not in (None, ""):
            continue
        try:
            text = _run_cli([ideviceinfo, "-k", key], timeout=4).strip()
        except Exception:
            continue
        if text:
            values[key] = text
    return device_info_from_lockdown_values(values, extra)


def _patch_usbmux_pair_record_save(plist_client_cls, mux_error_cls) -> None:
    """Windows Apple Mobile Device Support often rejects SavePairRecord with 183 (already exists).

    The pair record is already written to disk by then, so the usbmux save can be ignored.
    """
    if getattr(plist_client_cls.save_pair_record, "_ios_label_patched", False):
        return
    original = plist_client_cls.save_pair_record

    async def patched(self):
        try:
            await original(self)
        except mux_error_cls:
            return

    patched._ios_label_patched = True
    plist_client_cls.save_pair_record = patched


def _friendly_error(exc: BaseException) -> str:
    name = type(exc).__name__
    message = str(exc)
    mapping = {
        "NoDeviceConnectedError": "No iPhone is connected. Plug it in with USB and unlock it.",
        "ConnectionFailedToUsbmuxdError": "Cannot reach Apple Mobile Device Support. Install Apple Devices or iTunes, then retry.",
        "PasswordRequiredError": "Unlock the iPhone and tap Trust on the pairing prompt.",
        "FatalPairingError": "Unlock the iPhone and tap Trust, then try again.",
        "PairingError": "Unlock the iPhone and tap Trust, then try again.",
        "NotPairedError": "Unlock the iPhone and tap Trust, then try again.",
        "UserDeniedPairingError": "Tap Trust on the iPhone pairing prompt, then retry.",
        "PairingDialogResponsePendingError": "Unlock the iPhone and tap Trust, then retry.",
    }
    if name in mapping:
        return mapping[name]
    if name == "MuxException" and "183" in message:
        return (
            "Could not save the pairing record in Apple Mobile Device Support. "
            "Unlock the device, tap Trust, and retry."
        )
    if "No device" in message or "no device" in message.lower():
        return "No iPhone is connected. Plug it in with USB and unlock it."
    return message or name


def read_connected_device(platform: str = "apple") -> DeviceInfo:
    if platform == "samsung":
        from ios_label_printer.samsung import read_samsung_device

        return read_samsung_device()
    try:
        return asyncio.run(_fetch_pymobiledevice3())
    except Exception as exc:
        primary = _friendly_error(exc)
    if not shutil.which("ideviceinfo"):
        raise DeviceReadError(primary)
    try:
        return _fetch_libimobiledevice_cli()
    except Exception as exc:
        raise DeviceReadError(primary + " " + _friendly_error(exc)) from exc
