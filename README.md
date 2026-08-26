# iOS Label Printer

Desktop app for printing high-resolution iPhone and Samsung inventory labels. It reads a connected iPhone over USB using the same lockdown / diagnostics services as libimobiledevice, or a Galaxy over the Samsung USB modem AT interface (the same identity path SamFw uses in MTP info mode), then lays out a 40×30 mm label you can rearrange and save.

## Download

Get the Windows build from [Releases](https://github.com/Scratchycarl/ios-label-printer/releases). Unzip `ios-label-printer-windows.zip` and run `ios-label-printer.exe`. Keep the whole folder together.

You still need **Apple Devices** or **iTunes** for iPhones. For Samsung, install Samsung USB drivers so Windows shows **SAMSUNG Mobile USB Modem**.

## What it prints

- Device model
- Battery health (iPhone)
- Storage
- iOS / Android version
- Serial number
- IMEI
- FRP status (Samsung)
- QR code with all of the above

Default size is **40 mm × 30 mm** at **600 DPI**. Size, DPI, and margins are adjustable. The designer shows a live layout plus a high-res print preview.

## Requirements

- Windows with Python 3.10+
- For Apple: a USB-connected iPhone that you have tapped **Trust** on
- For Apple: **Apple Devices** or **iTunes** so Apple Mobile Device Support is running (this is the Windows usbmux / libimobiledevice transport)
- For Samsung: a USB-connected Galaxy in **File transfer (MTP)** mode, unlocked, with Samsung USB drivers installed. No computer-trust prompt is required.
- Optional: `ideviceinfo` from libimobiledevice on PATH as a fallback

## Run from source

```powershell
cd $env:USERPROFILE\Projects\ios-label-printer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m ios_label_printer
```

Or `.\run.ps1`.

## Build a Windows zip

```powershell
.\packaging\build.ps1
```

That writes `dist\ios-label-printer-windows.zip`.

## Templates

Layouts are JSON. The working copy lives in:

`%APPDATA%\ios-label-printer\templates\default.json`

Drag fields onto the label, resize with the blue handle, or nudge with the arrow keys (Shift for 1 mm). **Save template** keeps that layout so it does not disappear the way 3uTools templates can.

## Printing

Use **Print** for a 40×30 mm page, or **Save PNG** for a 600 DPI image you can send to a thermal printer.
