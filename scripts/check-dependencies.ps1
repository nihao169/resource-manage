. "$PSScriptRoot/common.ps1"
Assert-Docker
Push-Location $ProjectRoot
try {
    & "$PSScriptRoot/check.ps1"
    foreach ($dependency in @('postgres','minio')) {
        $code = if ($dependency -eq 'postgres') { 'DATABASE_UNAVAILABLE' } else { 'STORAGE_UNAVAILABLE' }
        Invoke-Docker compose stop $dependency
        try {
            $probe = @"
import json, urllib.request, urllib.error
assert urllib.request.urlopen('http://localhost:8000/api/health/live').status == 200
try:
    urllib.request.urlopen('http://localhost:8000/api/health/ready')
    raise AssertionError('ready incorrectly succeeded')
except urllib.error.HTTPError as error:
    payload = json.load(error)
    assert error.code == 503, payload
    assert payload['error']['code'] == '$code', payload
    print('live=200 ready=503 $code')
"@
            Invoke-Docker compose exec -T api python -c $probe
        } finally {
            Invoke-Docker compose up -d --wait $dependency
        }
    }
    & "$PSScriptRoot/check.ps1"
} finally { Pop-Location }
