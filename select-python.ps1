# Return a stable Python executable for the local development environment.
$candidates = @()
if ($env:WAREHOUSE_PYTHON) { $candidates += $env:WAREHOUSE_PYTHON }
$installed = Get-Command python.exe -ErrorAction SilentlyContinue
if ($installed) { $candidates += $installed.Source }
$candidates += Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

foreach ($candidate in $candidates) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    $version = & $candidate -c 'import sys; print(sys.version_info.major, sys.version_info.minor, sep=chr(46))' 2>$null
    if ($LASTEXITCODE -eq 0 -and $version -in @('3.12', '3.13')) { return $candidate }
}
throw '未找到 Python 3.12 或 3.13。请安装稳定版 Python，或设置 WAREHOUSE_PYTHON 为其 python.exe 路径。'
