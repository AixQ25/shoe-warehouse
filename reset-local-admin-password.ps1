$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$localData = [Environment]::GetFolderPath('LocalApplicationData')
$python = Join-Path $localData 'mold-warehouse-venv\Scripts\python.exe'
$backend = Join-Path $project 'backend'
$database = Join-Path $project 'office-pilot-data\warehouse.sqlite3'
$backupDirectory = Join-Path $localData 'mold-warehouse-dev\backups'
if (-not (Test-Path -LiteralPath $python)) { throw "本机 Python 环境不存在：$python。请先运行 start-local.cmd。" }
if (-not (Test-Path -LiteralPath $database)) { throw "U 盘试点数据库不存在：$database" }
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { throw '请先双击 stop-local.cmd 关闭仓库服务，再重置密码。' }
Push-Location $backend
try {
    & $python 'reset_local_admin.py' $database $backupDirectory
    if ($LASTEXITCODE -ne 0) { throw '密码重置失败；请查看上面的错误。' }
}
finally { Pop-Location }
