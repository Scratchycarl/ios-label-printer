$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    python -m venv .venv
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
    & $Python -m pip install -U pip
    & $Python -m pip install -e .
}

& $Python -m pip install -e . pyinstaller
if (Test-Path (Join-Path $Root "build")) {
    Remove-Item -Recurse -Force (Join-Path $Root "build")
}
if (Test-Path (Join-Path $Root "dist")) {
    Remove-Item -Recurse -Force (Join-Path $Root "dist")
}

& $Python -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\ios_label_printer.spec")

$AppDir = Join-Path $Root "dist\ios-label-printer"
$Readme = @"
iOS Label Printer
=================

1. Keep this whole folder together. Run ios-label-printer.exe.
2. Install Apple Devices (or iTunes) so Apple Mobile Device Support is running.
3. Plug in an iPhone with USB, unlock it, and tap Trust.
4. For Samsung, install Samsung USB drivers, set USB to File transfer, unlock the phone, switch the app to Samsung, and press Read device.

Templates are saved under:
%APPDATA%\ios-label-printer\templates\
"@
Set-Content -Path (Join-Path $AppDir "README.txt") -Value $Readme -Encoding UTF8

$Zip = Join-Path $Root "dist\ios-label-printer-windows.zip"
if (Test-Path $Zip) {
    Remove-Item -Force $Zip
}
Compress-Archive -Path (Join-Path $AppDir "*") -DestinationPath $Zip -CompressionLevel Optimal
Get-Item $Zip | Select-Object FullName, Length, LastWriteTime
