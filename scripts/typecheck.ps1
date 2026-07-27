$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

& ".\.venv\Scripts\mypy.exe" --strict --no-incremental
exit $LASTEXITCODE
