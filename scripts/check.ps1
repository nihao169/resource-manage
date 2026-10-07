. "$PSScriptRoot/common.ps1"
Push-Location $ProjectRoot
try {
    $configuration = (docker compose config --format json | ConvertFrom-Json)
    if ($LASTEXITCODE -ne 0) { throw 'Invalid compose configuration' }
    $port = ($configuration.services.nginx.ports | Where-Object target -eq 443).published
    $base = "https://localhost:$port"
    foreach ($case in @(@('/',200),@('/api/health/live',200),@('/api/files',401),@('/api/health/ready',403),@('/uploads',200))) {
        $status = & curl.exe --noproxy '*' -k -s -o NUL -w '%{http_code}' "$base$($case[0])"
        if ($LASTEXITCODE -ne 0 -or [int]$status -ne $case[1]) { throw "Smoke failed: $($case[0]) ($status)" }
    }
    $live = (& curl.exe --noproxy '*' -k -s "$base/api/health/live" | ConvertFrom-Json)
    if ($live.data.status -ne 'live' -or -not $live.request_id) { throw 'Invalid live response' }
    Invoke-Docker compose exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health/ready').read().decode())"
    Write-Host "Smoke passed: $base (self-signed certificate; trust not modified)"
} finally { Pop-Location }

