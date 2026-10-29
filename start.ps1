$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw '未找到 Python。请先安装 Python 3.11 或更高版本，并勾选“Add python.exe to PATH”。' }
$supported = & python -c "import sys; print('1' if sys.version_info >= (3, 11) else '0')" 2>$null
if ($LASTEXITCODE -ne 0 -or $supported.Trim() -ne '1') {
    throw '需要 Python 3.11 或更高版本。'
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 虚拟环境失败。' }
}
& '.\.venv\Scripts\python.exe' -c 'import fastapi,uvicorn,httpx,sympy,pypdf,docx,multipart' 2>$null
if ($LASTEXITCODE -ne 0) {
    & '.\.venv\Scripts\python.exe' -m pip install --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络后重新启动。' }
}

if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) { throw '缺少前端构建产物，且未找到 Node.js 20+。请安装 Node.js 后重试，或直接使用 GitHub Release 的 Windows 免安装包。' }
    Push-Location frontend
    try {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败。' }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
    } finally { Pop-Location }
}

& '.\.venv\Scripts\python.exe' scripts/launch.py
