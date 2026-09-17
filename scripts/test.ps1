. "$PSScriptRoot/common.ps1"
Assert-Docker
Push-Location $ProjectRoot
try {
    Push-Location frontend
    try {
        foreach ($command in @('typecheck','build','test')) {
            & npm.cmd run $command
            if ($LASTEXITCODE -ne 0) { throw "Frontend $command failed" }
        }
    } finally { Pop-Location }
    Invoke-Docker compose config --quiet
    Invoke-Docker compose build api
    Invoke-Docker compose run --rm --no-deps --volume "${ProjectRoot}/doc:/doc:ro" api pytest -q
    Invoke-Docker compose run --rm --no-deps -e FM_INTEGRATION_TESTS=1 api pytest -q tests/test_integration.py
    Invoke-Docker compose run --rm --no-deps api ruff check .
    & "$PSScriptRoot/check.ps1"
} finally { Pop-Location }
