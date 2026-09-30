$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $project 'backend'
$dataDirectory = Join-Path $project 'office-pilot-data'
$database = Join-Path $dataDirectory 'warehouse.sqlite3'
$localData = [Environment]::GetFolderPath('LocalApplicationData')
$venv = Join-Path $localData 'mold-warehouse-venv'
$python = Join-Path $venv 'Scripts\python.exe'

if (Test-Path -LiteralPath $database) {
    throw "U 盘试点数据库已存在，拒绝覆盖：$database"
}
if (Get-NetTCPConnection -LocalPort 8000,5173,5174,5175 -State Listen -ErrorAction SilentlyContinue) {
    throw '仓库服务或相关端口正在运行，请先关闭后再初始化。'
}

if (-not (Test-Path -LiteralPath $python)) {
    $sourcePython = & (Join-Path $project 'select-python.ps1')
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $sourcePython -m venv $venv
    } finally { $ErrorActionPreference = $previousPreference }
    if ($LASTEXITCODE -ne 0) { throw 'Python 虚拟环境创建失败。' }
}
& $python (Join-Path $backend 'check_dependencies.py')
if ($LASTEXITCODE -ne 0) {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $python -m pip install -r (Join-Path $backend 'requirements.txt')
    } finally { $ErrorActionPreference = $previousPreference }
    if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败。' }
}

New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
$temporary = Join-Path $dataDirectory ('.warehouse-' + [guid]::NewGuid().ToString('N') + '.sqlite3')
$previousDatabaseUrl = $env:DATABASE_URL
$previousWarehouseEnv = $env:WAREHOUSE_ENV
try {
    $env:DATABASE_URL = 'sqlite+pysqlite:///' + ($temporary -replace '\\','/')
    $env:WAREHOUSE_ENV = 'development'
    $env:PYTHONUTF8 = '1'
    Push-Location $backend
    try {
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $python -m alembic upgrade head
        } finally { $ErrorActionPreference = $previousPreference }
        if ($LASTEXITCODE -ne 0) { throw '空试点库迁移失败。' }
        Write-Output '请为新试点库设置 admin 密码（至少 6 个字符）。输入时会显示 *，输完按回车。'
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $python -m app.cli create-admin --username admin --person-name '维护员'
        } finally { $ErrorActionPreference = $previousPreference }
        if ($LASTEXITCODE -ne 0) { throw '管理员账号创建失败。' }
    } finally { Pop-Location }

    & $python (Join-Path $backend 'pilot_storage.py') check $temporary
    if ($LASTEXITCODE -ne 0) { throw '新试点库完整性检查失败。' }
    if (Test-Path -LiteralPath $database) { throw "目标数据库已出现，拒绝覆盖：$database" }
    Move-Item -LiteralPath $temporary -Destination $database -ErrorAction Stop
    Write-Output "新试点库已建立：$database。库存为空，可在页面维护资料或导入 CSV。"
} finally {
    $env:DATABASE_URL = $previousDatabaseUrl
    $env:WAREHOUSE_ENV = $previousWarehouseEnv
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
}
