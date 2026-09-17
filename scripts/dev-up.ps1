. "$PSScriptRoot/common.ps1"
Assert-Docker
& "$PSScriptRoot/init.ps1"
Push-Location $ProjectRoot
try {
    Invoke-Docker compose build api
    Invoke-Docker compose run --rm --no-deps --user 0 --volume "${ProjectRoot}/certs:/bootstrap/certs" api python -m app.cli certificate --directory /bootstrap/certs
    Invoke-Docker compose up -d --wait postgres minio
    Invoke-Docker compose -f compose.yaml -f compose.init.yaml run --rm --no-deps storage_init
    Invoke-Docker compose -f compose.yaml -f compose.init.yaml run --rm --no-deps api python -m app.cli migrate
    Invoke-Docker compose up -d --build --wait api nginx
    & "$PSScriptRoot/check.ps1"
} finally { Pop-Location }

