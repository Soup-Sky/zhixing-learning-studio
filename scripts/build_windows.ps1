param([string]$PackageName = '', [switch]$SkipChecks)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

if (-not (Test-Path '.venv\Scripts\python.exe')) { throw 'Python environment is missing.' }
# Version has one source: learning/version.py.
$version = (& '.\.venv\Scripts\python.exe' -c 'from learning.version import VERSION; print(VERSION)').Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) { throw 'Cannot read learning/version.py.' }
if (-not $PackageName) { $PackageName = "ZhixingLearningStudio-Windows-$version.zip" }

if (-not $SkipChecks) {
    # Gate: never package a build whose tests fail or whose frontend is stale.
    & '.\.venv\Scripts\python.exe' -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
    Push-Location frontend
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
    $nodeTests = @(Get-ChildItem -Path (Join-Path 'frontend' 'tests') -Filter '*.test.mjs' | ForEach-Object { $_.FullName })
    if ($nodeTests.Count) {
        node --test @nodeTests
        if ($LASTEXITCODE -ne 0) { throw 'Frontend unit tests failed.' }
    }
}
if (-not (Test-Path 'frontend\dist\index.html')) { throw 'Frontend build is missing.' }

& '.\.venv\Scripts\python.exe' -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller install failed.' }

$release = Join-Path $root 'release'
$work = Join-Path $release 'build'
$out = Join-Path $release 'app'
$bundleName = 'ZhixingLearningStudio'

# Only the in-app report page is needed at runtime; docs/ also holds ~80 MB of defense material.
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name $bundleName --distpath $out --workpath $work `
    --specpath $release `
    --add-data "$root\frontend\dist;frontend\dist" `
    --add-data "$root\knowledge\calculus.json;knowledge" `
    --add-data "$root\docs\项目汇报.html;docs" `
    --add-data "$root\evidence\acceptance-deepseek-synthetic.json;evidence" `
    --add-data "$root\evidence\deepseek-remedial-browser.json;evidence" `
    desktop.py
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }

$folder = Join-Path $out $bundleName
Copy-Item -LiteralPath 'docs\用户指南.md' -Destination (Join-Path $folder '用户指南.md') -Force
$zip = Join-Path $release $PackageName
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -LiteralPath $folder -DestinationPath $zip -CompressionLevel Optimal
$sha = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
Write-Output "Customer preview package: $zip"
Write-Output "SHA256: $sha"
