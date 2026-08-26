from __future__ import annotations

import time
from typing import Any

SAMSUNG_VID = 0x04E8
# Odin / download-mode PIDs — do not switch these.
_SKIP_PIDS = {0x685D, 0x6601, 0x685E}
_MODEM_INTERFACE_CLASSES = {0x02, 0x0A}  # CDC communications / CDC data


def _usb_backend():
    try:
        import libusb_package

        backend = libusb_package.get_libusb1_backend()
        if backend is not None:
            return backend
    except Exception:
        pass
    try:
        import libusb_package
        import usb.backend.libusb1

        return usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    except Exception:
        return None


def _find_samsung_usb_devices() -> list[Any]:
    try:
        import usb.core
    except ImportError:
        return []

    kwargs: dict[str, Any] = {"find_all": True, "idVendor": SAMSUNG_VID}
    backend = _usb_backend()
    if backend is not None:
        kwargs["backend"] = backend
    try:
        found = list(usb.core.find(**kwargs) or [])
    except Exception:
        found = []
    if found:
        return [dev for dev in found if int(getattr(dev, "idProduct", 0)) not in _SKIP_PIDS]

    if backend is not None:
        try:
            found = list(usb.core.find(find_all=True, idVendor=SAMSUNG_VID) or [])
        except Exception:
            found = []
        return [dev for dev in found if int(getattr(dev, "idProduct", 0)) not in _SKIP_PIDS]
    return []


def _config_has_modem(config) -> bool:
    try:
        for interface in config:
            if int(getattr(interface, "bInterfaceClass", 0)) in _MODEM_INTERFACE_CLASSES:
                return True
    except Exception:
        return False
    return False


def _configuration_values(dev) -> list[int]:
    values: list[int] = []
    try:
        count = int(getattr(dev, "bNumConfigurations", 0) or 0)
        for index in range(max(count, 0)):
            try:
                config = dev[index]
                value = int(config.bConfigurationValue)
            except Exception:
                continue
            if value not in values:
                values.append(value)
    except Exception:
        pass
    if 2 in values:
        values.remove(2)
        values.insert(0, 2)
    elif not values:
        values = [2, 1]
    return values


def _refind_device(old) -> Any:
    time.sleep(0.6)
    product = int(getattr(old, "idProduct", 0))
    for dev in _find_samsung_usb_devices():
        if int(getattr(dev, "idProduct", 0)) == product:
            return dev
    devices = _find_samsung_usb_devices()
    return devices[0] if devices else None


def _switch_one_device(dev) -> str:
    import usb.core
    import usb.util

    product = int(getattr(dev, "idProduct", 0))
    try:
        active = dev.get_active_configuration()
        if _config_has_modem(active):
            return f"{product:#06x} already exposing a modem interface"
    except Exception:
        active = None

    targets = _configuration_values(dev)
    last_error = "no configuration accepted"
    for value in targets:
        if active is not None and int(active.bConfigurationValue) == value and _config_has_modem(active):
            return f"{product:#06x} already on config {value}"
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass
        try:
            dev.reset()
            dev = _refind_device(dev) or dev
        except Exception:
            pass
        try:
            current = None
            try:
                current = dev.get_active_configuration()
            except Exception:
                current = None
            if current is None or int(current.bConfigurationValue) != value:
                dev.set_configuration(value)
            return f"{product:#06x} switched to USB config {value}"
        except usb.core.USBError as exc:
            last_error = str(exc)
            continue
        except Exception as exc:
            last_error = str(exc)
            continue
    return f"{product:#06x} USB switch failed: {last_error}"


def switch_samsung_to_at_config() -> list[str]:
    """Expose the Samsung AT modem the same way SamFw does: USB configuration 2.

    This is a host-side USB SET_CONFIGURATION. It does not unlock the phone or
    change FRP. Windows may need a second or two afterwards for the COM port.
    """
    devices = _find_samsung_usb_devices()
    if not devices:
        return ["No Samsung USB device visible to libusb"]
    notes: list[str] = []
    for dev in devices:
        try:
            notes.append(_switch_one_device(dev))
        except Exception as exc:
            product = int(getattr(dev, "idProduct", 0))
            notes.append(f"{product:#06x} USB switch failed: {exc}")
    time.sleep(1.2)
    return notes
