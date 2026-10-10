param([string]$Python = "py -3.10")

$venv = Join-Path $PSScriptRoot ".venv"
if (-not (Test-Path -LiteralPath (Join-Path $venv "Scripts\python.exe"))) {
    if ($Python -eq "py -3.10") {
        & py -3.10 -m venv $venv
    } else {
        & $Python -m venv $venv
    }
    if ($LASTEXITCODE -ne 0) { throw "Failed to create assistant virtual environment" }
}
& (Join-Path $venv "Scripts\python.exe") -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Failed to install assistant dependencies" }
Write-Host "Assistant environment ready: $venv"
