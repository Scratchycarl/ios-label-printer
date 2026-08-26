from __future__ import annotations

import re
import time
from typing import Any

from ios_label_printer.device import DeviceReadError
from ios_label_printer.models import STANDARD_STORAGE_GB, DeviceInfo

# Identification queries only. Do not add reset, unlock, CSC-change, or ADB-enable commands.
_AT_PING = "AT"
_AT_DEVCONINFO = "AT+DEVCONINFO"
_AT_ANDROID_VERSION = "AT+VERSNAME=3,2,3"
_AT_FRP_STATUS = "AT+REACTIVE=1,0,0"
_AT_IMEI = "AT+IMEINUM"
_AT_STORAGE_COMMANDS = (
    "AT+SIZECHECK=?",
    "AT+SIZECHECK=1,0",
    "AT+SIZECHECK",
)

_DEVCON_PAIR = re.compile(r"([A-Z][A-Z0-9]*)\(([^)]*)\)")
_SAMSUNG_VID = "VID_04E8"
_SAMSUNG_VID_PYSERIAL = "VID:PID=04E8"

_MCC_COUNTRY = {
    "202": "GR",
    "204": "NL",
    "208": "FR",
    "214": "ES",
    "222": "IT",
    "226": "RO",
    "228": "CH",
    "230": "CZ",
    "231": "SK",
    "232": "AT",
    "234": "GB",
    "235": "GB",
    "238": "DK",
    "240": "SE",
    "242": "NO",
    "244": "FI",
    "246": "LT",
    "247": "LV",
    "248": "EE",
    "250": "RU",
    "255": "UA",
    "260": "PL",
    "262": "DE",
    "268": "PT",
    "272": "IE",
    "274": "IS",
    "286": "TR",
    "293": "SI",
    "297": "ME",
    "302": "CA",
    "310": "US",
    "311": "US",
    "312": "US",
    "313": "US",
    "314": "US",
    "315": "US",
    "316": "US",
    "334": "MX",
    "404": "IN",
    "405": "IN",
    "424": "AE",
    "430": "AE",
    "440": "JP",
    "441": "JP",
    "450": "KR",
    "454": "HK",
    "455": "MO",
    "460": "CN",
    "466": "TW",
    "502": "MY",
    "505": "AU",
    "510": "ID",
    "515": "PH",
    "520": "TH",
    "525": "SG",
    "530": "NZ",
    "655": "ZA",
    "724": "BR",
}


def parse_devconinfo(text: str) -> dict[str, str]:
    start = text.upper().find("+DEVCONINFO")
    body = text[start:] if start >= 0 else text
    values: dict[str, str] = {}
    for key, value in _DEVCON_PAIR.findall(body):
        values.setdefault(key.upper(), value.strip())
    return values


def parse_versname(text: str) -> str:
    for line in text.splitlines():
        if "+VERSNAME" not in line.upper():
            continue
        _, _, rest = line.partition(":")
        parts = [part.strip().strip('"') for part in rest.replace(";", ",").split(",") if part.strip()]
        versions = [part for part in parts if re.fullmatch(r"\d{1,2}", part) and 8 <= int(part) <= 16]
        if versions:
            return versions[-1]
        if parts:
            match = re.search(r"\d{1,2}", parts[-1])
            if match and 8 <= int(match.group()) <= 16:
                return match.group()
    return ""


def parse_reactive_status(text: str) -> str:
    for line in text.splitlines():
        if "+REACTIVE" not in line.upper():
            continue
        _, _, rest = line.partition(":")
        parts = [part.strip().strip('"') for part in rest.split(",") if part.strip()]
        if len(parts) >= 2:
            return parts[-1].upper()
        if parts:
            return parts[0].upper()
    upper = text.upper()
    if "UNLOCK" in upper:
        return "UNLOCK"
    if re.search(r"\bLOCK(?:ED)?\b", upper):
        return "LOCK"
    return ""


def parse_imeinum(text: str) -> str:
    for line in text.splitlines():
        if "+IMEINUM" not in line.upper() and "IMEI" not in line.upper():
            continue
        digits = re.sub(r"\D", "", line.split(":")[-1])
        if 14 <= len(digits) <= 16:
            return digits
    return ""


def _snap_storage_gb(gb: float) -> int | None:
    for size in STANDARD_STORAGE_GB:
        if size * 0.60 <= gb <= size * 1.08:
            return size
    return None


def _storage_from_df(text: str) -> int | None:
    """Parse AT+SIZECHECK df output. Values are 1K-blocks (1024-byte)."""
    data_kb: int | None = None
    total_kb = 0
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        upper = chunk.upper()
        if upper.startswith("AT+") or upper.startswith("FILESYSTEM") or upper.startswith("+CME"):
            continue
        if upper in {"OK", "ERROR"}:
            continue
        parts = chunk.split(":")
        if len(parts) < 6:
            continue
        fs = parts[0].strip()
        try:
            blocks = int(parts[1])
        except ValueError:
            continue
        mount = re.sub(r"[\r\n].*", "", ":".join(parts[5:])).strip()
        fs_l = fs.lower()
        mount_l = mount.lower()
        if blocks <= 0:
            continue
        if fs_l.startswith("tmpfs") or "loop" in fs_l:
            continue
        if mount_l.startswith("/apex") or mount_l.startswith("/mnt"):
            continue
        if "/dev/block/" not in fs_l:
            continue
        total_kb += blocks
        if mount_l == "/data" or mount_l.startswith("/data/"):
            data_kb = blocks
    kb = data_kb if data_kb is not None else total_kb
    if not kb:
        return None
    return _snap_storage_gb(kb * 1024 / 1000**3)


def parse_samsung_storage_gb(text: str) -> int | None:
    """NAND size from SIZECHECK df output, or an explicit GB/MB unit."""
    if not text:
        return None
    if "1K-blocks" in text or "Filesystem" in text:
        return _storage_from_df(text)
    found: list[int] = []
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(GiB|GB|MiB|MB|KiB|KB|bytes)\b", text, re.I):
        number = float(match.group(1))
        unit = match.group(2).upper()
        if unit in {"GIB", "GB"}:
            gb = number
        elif unit in {"MIB", "MB"}:
            gb = number * 1024**2 / 1000**3
        elif unit in {"KIB", "KB"}:
            gb = number * 1024 / 1000**3
        else:
            gb = number / 1000**3
        snapped = _snap_storage_gb(gb)
        if snapped:
            found.append(snapped)
    return max(found) if found else None


def parse_storage_bytes(text: str) -> int | None:
    gb = parse_samsung_storage_gb(text)
    if gb is None:
        return None
    return int(gb) * (1000**3)


def _first(*values: str) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text.upper() not in {"UNKNOWN", "NULL"}:
            return text
    return ""


def device_info_from_samsung_values(
    values: dict[str, str],
    extra: dict[str, Any] | None = None,
) -> DeviceInfo:
    extra = extra or {}
    model = _first(values.get("MN"), extra.get("model", ""))
    serial = _first(values.get("SN"), extra.get("serial", ""))
    imei = _first(values.get("IMEI"), extra.get("imei", ""))
    csc = _first(values.get("PRD"), values.get("CSC"), extra.get("csc", ""))
    country = _first(values.get("CC"), extra.get("country", ""))
    mcc = _first(values.get("MCC"))
    if not country and mcc in _MCC_COUNTRY:
        country = _MCC_COUNTRY[mcc]
    storage = extra.get("storage_gb")
    return DeviceInfo(
        platform="samsung",
        model=model or serial or "Samsung",
        product_type=model,
        storage_gb=storage,
        ios_version=_first(extra.get("android_version", "")),
        serial=serial,
        imei=imei,
        region=csc,
        frp_status=_first(extra.get("frp_status", "")),
        csc=csc,
        unique_number=_first(values.get("UN"), extra.get("unique_number", "")),
        phone_number=_first(values.get("PN"), extra.get("phone_number", "")),
        country=country,
        source=str(extra.get("source", "samsung-at")),
    )


def _port_blob(info) -> str:
    return " ".join(
        filter(None, [info.device, info.description, info.hwid, info.manufacturer, info.name])
    ).upper()


def _is_samsung_port(info) -> bool:
    blob = _port_blob(info)
    return "SAMSUNG" in blob or _SAMSUNG_VID in blob or _SAMSUNG_VID_PYSERIAL in blob


def _port_rank(info) -> tuple[int, str]:
    blob = _port_blob(info)
    description = (info.description or "").upper()
    if "MOBILE USB MODEM" in description:
        return (0, info.device)
    if "MODEM" in blob:
        return (1, info.device)
    if "USB SERIAL" in description:
        return (2, info.device)
    if _is_samsung_port(info):
        return (3, info.device)
    return (9, info.device)


def find_samsung_modem_ports() -> list[Any]:
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise DeviceReadError("pyserial is not installed") from exc

    matches = [info for info in list_ports.comports() if _is_samsung_port(info)]
    matches.sort(key=_port_rank)
    return matches


def _looks_complete(text: str) -> bool:
    upper = text.upper().replace("\r", "\n")
    return any(token in upper for token in ("\nOK", "#OK#", "\nERROR", "+CME ERROR"))


def _send_at(serial_port, command: str, timeout: float = 3.0) -> str:
    serial_port.reset_input_buffer()
    payload = command if command.endswith("\r") else command + "\r\n"
    serial_port.write(payload.encode("ascii", errors="ignore"))
    serial_port.flush()
    deadline = time.monotonic() + timeout
    chunks: list[bytes] = []
    while time.monotonic() < deadline:
        waiting = serial_port.in_waiting
        if waiting:
            chunks.append(serial_port.read(waiting))
            text = b"".join(chunks).decode("latin-1", errors="replace")
            if _looks_complete(text):
                time.sleep(0.05)
                if serial_port.in_waiting:
                    chunks.append(serial_port.read(serial_port.in_waiting))
                break
        else:
            time.sleep(0.03)
    return b"".join(chunks).decode("latin-1", errors="replace")


def _open_samsung_port(port: str):
    import serial

    kwargs = dict(
        port=port,
        baudrate=115200,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.4,
        write_timeout=2,
        dsrdtr=True,
        rtscts=False,
    )
    try:
        opened = serial.Serial(exclusive=True, **kwargs)
    except TypeError:
        opened = serial.Serial(**kwargs)
    try:
        opened.dtr = True
        opened.rts = True
    except Exception:
        pass
    time.sleep(0.15)
    return opened


def _query_samsung_port(info) -> DeviceInfo:
    import serial

    port = info.device
    try:
        serial_port = _open_samsung_port(port)
    except serial.SerialException as exc:
        message = str(exc)
        if "Permission" in message or "Access is denied" in message or "FileNotFound" in message:
            raise DeviceReadError(
                f"{port} is busy or missing. Close SamFw and other phone tools, then retry."
            ) from exc
        raise DeviceReadError(f"Could not open {port}: {message}") from exc

    try:
        _send_at(serial_port, _AT_PING, timeout=1.5)
        identity = _send_at(serial_port, _AT_DEVCONINFO, timeout=8.0)
        values = parse_devconinfo(identity)
        if not values.get("MN") and not values.get("SN") and not values.get("IMEI"):
            identity = _send_at(serial_port, _AT_DEVCONINFO, timeout=8.0)
            values = parse_devconinfo(identity)
        if not values.get("MN") and not values.get("SN") and not values.get("IMEI"):
            raise DeviceReadError(
                f"Connected to {port}, but AT+DEVCONINFO returned no device info."
            )

        extra: dict[str, Any] = {
            "source": info.description or f"samsung-at ({port})",
        }
        android = parse_versname(_send_at(serial_port, _AT_ANDROID_VERSION, timeout=3.0))
        extra["android_version"] = android
        extra["frp_status"] = parse_reactive_status(_send_at(serial_port, _AT_FRP_STATUS, timeout=3.0))

        if not values.get("IMEI"):
            extra["imei"] = parse_imeinum(_send_at(serial_port, _AT_IMEI, timeout=3.0))

        for command in _AT_STORAGE_COMMANDS:
            storage_text = _send_at(serial_port, command, timeout=3.0)
            storage_gb = parse_samsung_storage_gb(storage_text)
            if storage_gb:
                extra["storage_gb"] = storage_gb
                break

        return device_info_from_samsung_values(values, extra)
    finally:
        serial_port.close()


def _read_from_available_ports(errors: list[str]) -> DeviceInfo | None:
    ports = find_samsung_modem_ports()
    for info in ports:
        try:
            return _query_samsung_port(info)
        except DeviceReadError as exc:
            errors.append(f"{info.device}: {exc}")
        except Exception as exc:
            errors.append(f"{info.device}: {exc}")
    return None


def read_samsung_device() -> DeviceInfo:
    from ios_label_printer.samsung_usb import switch_samsung_to_at_config

    errors: list[str] = []
    info = _read_from_available_ports(errors)
    if info is not None:
        return info

    switch_notes = switch_samsung_to_at_config()
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        info = _read_from_available_ports(errors)
        if info is not None:
            return info
        time.sleep(0.5)

    detail = " ".join(errors)
    switch_detail = "; ".join(switch_notes) if switch_notes else "USB switch was not possible"
    if not find_samsung_modem_ports():
        raise DeviceReadError(
            "No Samsung USB modem showed up. Tried SamFw-style USB config switch "
            f"({switch_detail}). Close SamFw if it is open. Samsung USB drivers must be installed. "
            "If it still fails, File transfer is the fallback."
        )
    raise DeviceReadError(
        "Could not read the Samsung phone after waking the USB modem. "
        f"{detail} USB switch: {switch_detail}"
    )
