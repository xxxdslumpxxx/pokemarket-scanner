$ErrorActionPreference = "Stop"
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notlike "*Loopback*" -and $_.IPAddress -notlike "169.254.*" } | Select-Object -First 1 -ExpandProperty IPAddress)
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  PokéMarket Scanner — Avvio Server Mobile Webapp" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Locale (PC):      http://127.0.0.1:8765" -ForegroundColor Green
if ($ip) {
    Write-Host "Cellulare (Wi-Fi): http://${ip}:8765" -ForegroundColor Yellow
}
Write-Host ""
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8765 --reload
