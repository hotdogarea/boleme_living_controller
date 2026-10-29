param(
    [string]$Python = "",
    [string]$Name = "BolemeLiveControl",
    [switch]$ReplaceExisting
)

if ($Name -notmatch '^BolemeLiveControl(?:-[A-Za-z0-9-]+)?$') {
    throw "Invalid build name: $Name"
}
if (-not $Python) { $Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe" }
$entry = Join-Path $PSScriptRoot "run.py"
$icon = Join-Path $PSScriptRoot "assets\boleme.ico"
$image = Join-Path $PSScriptRoot "assets\boleme.png"
if (-not (Test-Path -LiteralPath $icon) -or -not (Test-Path -LiteralPath $image)) {
    throw "Missing brand icon assets; restore assets/boleme.ico and assets/boleme.png from the repository."
}
$dist = Join-Path $PSScriptRoot "dist\$Name"
if (Test-Path -LiteralPath $dist) {
    if (-not $ReplaceExisting) {
        throw "Build output already exists: $dist. Pass -ReplaceExisting only for this generated output."
    }
    $resolved = (Resolve-Path -LiteralPath $dist).Path
    if ($resolved -ne $dist -or -not $resolved.StartsWith($PSScriptRoot + [IO.Path]::DirectorySeparatorChar)) {
        throw "Unexpected build output path: $resolved"
    }
    $names = @(Get-ChildItem -LiteralPath $resolved -Force | ForEach-Object Name)
    if (@($names | Where-Object { $_ -notin @('_internal', "${Name}.exe", 'logo.png', 'logo.ico') }).Count -gt 0) {
        throw "Build output contains unexpected files; refusing to replace it."
    }
    $running = Get-CimInstance Win32_Process -Filter "name = '${Name}.exe'" |
        Where-Object { $_.ExecutablePath -eq (Join-Path $dist "${Name}.exe") }
    if ($running) {
        throw "Build output is currently running; close it before replacing: $dist"
    }
}
& $Python -m PyInstaller --noconfirm --onedir --windowed --name $Name `
    --paths $PSScriptRoot --collect-all playwright --icon $icon `
    --hidden-import websockets.sync.server `
    --add-data "${image};assets" `
    --add-data "${icon};assets" `
    --add-data "$(Join-Path $PSScriptRoot 'LICENSE');." `
    --add-data "$(Join-Path $PSScriptRoot 'THIRD_PARTY_LICENSE.txt');." `
    --distpath (Join-Path $PSScriptRoot "dist") `
    --workpath (Join-Path $PSScriptRoot "build") `
    --specpath (Join-Path $PSScriptRoot "build") $entry
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with code $LASTEXITCODE" }
Copy-Item -LiteralPath $image -Destination (Join-Path $dist 'logo.png') -Force -ErrorAction Stop
Copy-Item -LiteralPath $icon -Destination (Join-Path $dist 'logo.ico') -Force -ErrorAction Stop
Write-Host "Built: $dist"
