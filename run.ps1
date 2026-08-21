$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    python -m venv .venv
    & .\.venv\Scripts\python.exe -m pip install -e .
}
& .\.venv\Scripts\python.exe -m ios_label_printer
