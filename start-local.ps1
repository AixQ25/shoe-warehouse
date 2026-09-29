param([switch]$Lan, [switch]$OpenBrowser)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $project 'backend'
$frontend = Join-Path $project 'frontend'
$localData = [Environment]::GetFolderPath('LocalApplicationData')
$warehouseData = Join-Path $localData 'mold-warehouse-dev'
$warehouseDatabase = Join-Path $project 'office-pilot-data\warehouse.sqlite3'
$runtimeFile = Join-Path $warehouseData 'running-instance.json'
if (-not (Test-Path -LiteralPath $warehouseDatabase)) {
    Write-Output "U 盘试点数据库不存在：$warehouseDatabase。正在首次建立空试点库。"
    & (Join-Path $project 'initialize-office-pilot.ps1')
    if (-not (Test-Path -LiteralPath $warehouseDatabase)) { throw '试点库初始化未完成，请查看上面的错误。' }
}
$env:DATABASE_URL = 'sqlite+pysqlite:///' + ($warehouseDatabase -replace '\\','/')
$env:WAREHOUSE_ENV = 'development'
$venv = Join-Path $localData 'mold-warehouse-venv'
$python = Join-Path $venv 'Scripts\python.exe'
$webPort = if ($Lan) { 5174 } else { 5173 }
$webBind = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
$webUrl = "http://127.0.0.1:$webPort/"
$logDirectory = Join-Path $warehouseData 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$env:PYTHONUTF8 = '1'

$pythonForCheck = if (Test-Path -LiteralPath $python) { $python } else { & (Join-Path $project 'select-python.ps1') }
& $pythonForCheck (Join-Path $backend 'pilot_storage.py') check $warehouseDatabase
if ($LASTEXITCODE -ne 0) { throw 'U 盘数据库检查失败；不会启动服务或修改账号。' }

function Test-WarehouseEndpoint([string]$Url, [switch]$Health) {
    $response = $null
    $reader = $null
    try {
        # Local service checks must not go through the system HTTP proxy.
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Proxy = $null
        $request.Timeout = 2000
        $request.ReadWriteTimeout = 2000
        $response = $request.GetResponse()
        if ([int]$response.StatusCode -ne 200) { return $false }
        if ($Health) {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            $body = $reader.ReadToEnd() | ConvertFrom-Json
            return $body.status -eq 'ok'
        }
        return $true
    } catch { return $false }
    finally {
        if ($reader) { $reader.Dispose() }
        if ($response) { $response.Close() }
    }
}

function Get-WarehouseHealth([string]$Url) {
    $response = $null
    $reader = $null
    try {
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Proxy = $null
        $request.Timeout = 2000
        $response = $request.GetResponse()
        if ([int]$response.StatusCode -ne 200) { return $null }
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        return ($reader.ReadToEnd() | ConvertFrom-Json)
    } catch { return $null }
    finally {
        if ($reader) { $reader.Dispose() }
        if ($response) { $response.Close() }
    }
}

$apiHealth = Get-WarehouseHealth 'http://127.0.0.1:8000/api/health'
$apiReady = $apiHealth -and $apiHealth.status -eq 'ok'
if ($apiReady) {
    $running = if (Test-Path -LiteralPath $runtimeFile) { Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json } else { $null }
    if (-not $running -or $running.project -ne $project -or $running.database -ne $warehouseDatabase -or -not $apiHealth.instance_id -or $running.instance_id -ne $apiHealth.instance_id) {
        throw '8000 端口已有另一套仓库后端，不能确认其数据库。请先关闭旧服务（可双击 stop-local.cmd），再启动。'
    }
    Write-Output "已确认正在运行的后端使用本项目 U 盘试点库：$warehouseDatabase"
} elseif (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    throw '8000 端口被其他程序占用，已停止启动，避免登录到错误数据库。'
}
if (-not $apiReady) {
    & $pythonForCheck (Join-Path $backend 'pilot_storage.py') backup $warehouseDatabase (Join-Path $warehouseData 'backups')
    if ($LASTEXITCODE -ne 0) { throw '启动前本地备份失败；已停止启动，U 盘数据库未迁移。' }
}

if (-not (Test-Path -LiteralPath $python)) {
    $sourcePython = & (Join-Path $project 'select-python.ps1')
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $sourcePython -m venv $venv
    } finally { $ErrorActionPreference = $previousPreference }
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
}
& $python (Join-Path $backend 'check_dependencies.py')
if ($LASTEXITCODE -ne 0) {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $python -m pip install -r (Join-Path $backend 'requirements.txt')
    } finally { $ErrorActionPreference = $previousPreference }
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
}

if (-not $apiReady) {
    Push-Location $backend
    try {
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $python -m alembic upgrade head
        } finally { $ErrorActionPreference = $previousPreference }
        if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    } finally { Pop-Location }
}

if (-not (Test-Path -LiteralPath (Join-Path $frontend 'node_modules\.bin\vite.cmd'))) {
    Push-Location $frontend
    try {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    } finally { Pop-Location }
}

if (-not $apiReady) {
    $env:WAREHOUSE_INSTANCE_ID = [guid]::NewGuid().ToString('N')
    $apiProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory $backend -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'backend.out.log') -RedirectStandardError (Join-Path $logDirectory 'backend.err.log')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        $apiHealth = Get-WarehouseHealth 'http://127.0.0.1:8000/api/health'
        $apiReady = $apiHealth -and $apiHealth.status -eq 'ok' -and $apiHealth.instance_id -eq $env:WAREHOUSE_INSTANCE_ID
        if ($apiReady -or $apiProcess.HasExited) { break }
    }
    if (-not $apiReady) { throw "Backend did not become ready on port 8000. See $logDirectory\backend.err.log" }
    $apiListener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop | Select-Object -First 1
    if (-not $apiListener) { throw 'Backend health check passed but the listening process could not be identified.' }
    @{ project = $project; database = $warehouseDatabase; instance_id = $env:WAREHOUSE_INSTANCE_ID; api_pid = $apiListener.OwningProcess } | ConvertTo-Json | Set-Content -LiteralPath $runtimeFile -Encoding UTF8
}

$webReady = Test-WarehouseEndpoint $webUrl
if (-not $webReady) {
    $webProcess = Start-Process -FilePath 'npm.cmd' -ArgumentList @('run', 'dev', '--', '--host', $webBind, '--port', "$webPort", '--strictPort') -WorkingDirectory $frontend -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory "frontend-$webPort.out.log") -RedirectStandardError (Join-Path $logDirectory "frontend-$webPort.err.log")
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        $webReady = Test-WarehouseEndpoint $webUrl
        if ($webReady -or $webProcess.HasExited) { break }
    }
    if (-not $webReady) { throw "Frontend did not become ready on port $webPort. See $logDirectory\frontend-$webPort.err.log" }
}

$proxiedHealth = Get-WarehouseHealth "${webUrl}api/health"
if (-not $proxiedHealth -or $proxiedHealth.status -ne 'ok' -or $proxiedHealth.instance_id -ne $apiHealth.instance_id) {
    throw "The page is reachable but its API connection failed. See logs in $logDirectory"
}
if ($webProcess) {
    $listener = Get-NetTCPConnection -LocalPort $webPort -State Listen -ErrorAction Stop | Select-Object -First 1
    $state = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
    $webPids = @{}
    if ($state.web_pids) { $state.web_pids.PSObject.Properties | ForEach-Object { $webPids[$_.Name] = $_.Value } }
    $webPids["$webPort"] = $listener.OwningProcess
    @{ project = $project; database = $warehouseDatabase; instance_id = $state.instance_id; api_pid = $state.api_pid; web_pids = $webPids } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $runtimeFile -Encoding UTF8
}
Write-Output "Open $webUrl and sign in with the existing account. Database: $warehouseDatabase"
if ($Lan) {
    [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) | Where-Object { $_.AddressFamily -eq 'InterNetwork' -and -not [System.Net.IPAddress]::IsLoopback($_) } | ForEach-Object { Write-Output "Phone on the same LAN: http://$($_.IPAddressToString):$webPort/?view=mobile" }
    Write-Output 'HTTP supports lookup and QR photo recognition. Live camera scanning requires trusted HTTPS.'
}
if ($OpenBrowser) { Start-Process $webUrl }
