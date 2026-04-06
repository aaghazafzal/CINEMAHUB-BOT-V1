# ============================================
# CinemaHub Bot - Start with ngrok tunnel
# Run this INSTEAD of running bot.py directly
# ============================================

Write-Host "`n🚇 Starting ngrok tunnel on port 8080..." -ForegroundColor Cyan

# Kill any existing ngrok & python
taskkill /F /IM ngrok.exe 2>$null | Out-Null
taskkill /F /IM python.exe 2>$null | Out-Null
Start-Sleep 1

# Start ngrok in background
$ngrokJob = Start-Process -FilePath "ngrok" -ArgumentList "http 8080 --log=stdout" -PassThru -WindowStyle Hidden
Start-Sleep 4

# Get the public URL from ngrok API
$maxRetries = 10
$tunnel = $null
for ($i = 0; $i -lt $maxRetries; $i++) {
    try {
        $api = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -ErrorAction Stop
        $tunnel = ($api.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1).public_url
        if ($tunnel) { break }
    } catch {}
    Write-Host "⏳ Waiting for tunnel... ($($i+1)/$maxRetries)"
    Start-Sleep 2
}

if (-not $tunnel) {
    Write-Host "❌ Could not get ngrok URL. Make sure ngrok is authenticated!" -ForegroundColor Red
    Write-Host "   Run: ngrok config add-authtoken YOUR_TOKEN" -ForegroundColor Yellow
    Write-Host "   Get free token at: https://dashboard.ngrok.com" -ForegroundColor Yellow
    exit 1
}

# Extract host (remove https://)
$fqdn = $tunnel -replace "https://", ""
Write-Host "`n✅ Tunnel URL: $tunnel" -ForegroundColor Green
Write-Host "   FQDN set to: $fqdn`n" -ForegroundColor Green

# Update .env file with new FQDN and SSL settings
$envPath = ".env"
$content = Get-Content $envPath -Raw

# Replace or add FQDN
if ($content -match "FQDN=") {
    $content = $content -replace "FQDN=.*", "FQDN=$fqdn"
} else {
    $content += "`nFQDN=$fqdn"
}

# Ensure HAS_SSL=True for ngrok (ngrok gives https)
if ($content -match "HAS_SSL=") {
    $content = $content -replace "HAS_SSL=.*", "HAS_SSL=True"
} else {
    $content += "`nHAS_SSL=True"
}

# Ensure STREAM_MODE=True
if ($content -match "STREAM_MODE=") {
    $content = $content -replace "STREAM_MODE=.*", "STREAM_MODE=True"
} else {
    $content += "`nSTREAM_MODE=True"
}

Set-Content $envPath $content -NoNewline
Write-Host "📝 .env updated with ngrok URL" -ForegroundColor Cyan

# Start the bot
Write-Host "🤖 Starting CinemaHub Bot...`n" -ForegroundColor Cyan
$env:PORT = "8080"
.\venv\Scripts\python -u bot.py
