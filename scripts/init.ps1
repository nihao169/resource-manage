. "$PSScriptRoot/common.ps1"
if (-not (Test-Path -LiteralPath "$ProjectRoot/.env")) { Copy-Item -LiteralPath "$ProjectRoot/.env.example" -Destination "$ProjectRoot/.env" }
foreach ($directory in @('secrets','certs')) { New-Item -ItemType Directory -Force -Path "$ProjectRoot/$directory" | Out-Null }
foreach ($name in @('pg_bootstrap_password','pg_migrator_password','pg_app_password','minio_root_password','minio_api_password','minio_backup_password','jwt_key','csrf_key','confirmation_key')) {
    $target = "$ProjectRoot/secrets/$name"
    if (Test-Path -LiteralPath $target) {
        if ([string]::IsNullOrWhiteSpace([IO.File]::ReadAllText($target))) { throw "Empty existing secret: $name; repair manually" }
    } else {
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        [IO.File]::WriteAllText($target, [Convert]::ToBase64String($bytes), (New-Object Text.UTF8Encoding $false))
    }
}
Write-Host 'Missing configuration generated. Existing files preserved.'

