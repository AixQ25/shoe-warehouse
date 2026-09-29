$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$localData = [Environment]::GetFolderPath('LocalApplicationData')
$dataDirectory = Join-Path $localData 'mold-warehouse-dev'
$runtimeFile = Join-Path $dataDirectory 'running-instance.json'
$database = Join-Path $project 'office-pilot-data\warehouse.sqlite3'

function Get-WarehouseHealth {
    $response = $null
    $reader = $null
    try {
        $request = [System.Net.HttpWebRequest]::Create('http://127.0.0.1:8000/api/health')
        $request.Proxy = $null
        $request.Timeout = 2000
        $response = $request.GetResponse()
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        return ($reader.ReadToEnd() | ConvertFrom-Json)
    } catch { return $null }
    finally {
        if ($reader) { $reader.Dispose() }
        if ($response) { $response.Close() }
    }
}

$state = if (Test-Path -LiteralPath $runtimeFile) { Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json } else { $null }
$health = Get-WarehouseHealth
if (-not $health -and (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
    throw '8000 端口仍有程序运行且无法确认身份；已拒绝备份。请关闭该程序或重启电脑。'
}
if ($health) {
    if (-not $state -or $state.project -ne $project -or $state.database -ne $database -or $state.instance_id -ne $health.instance_id) {
        throw '8000 端口运行着无法确认身份的后端，已拒绝关闭。请关闭旧服务或重启电脑后再迁移/拔盘。'
    }
    if ($state.web_pids) {
        foreach ($entry in $state.web_pids.PSObject.Properties) {
            $port = [int]$entry.Name
            $pidToStop = [int]$entry.Value
            $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -eq $pidToStop } | Select-Object -First 1
            if ($listener) {
                Stop-Process -Id $pidToStop -ErrorAction Stop
                Write-Output "已关闭网页服务端口 $port"
            }
        }
    }
    $apiListener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $apiListener) { throw '无法确认后端监听进程，已拒绝结束进程；请重启电脑后再安全移除 U 盘。' }
    $apiPidToStop = [int]$apiListener.OwningProcess
    if ($apiPidToStop -ne [int]$state.api_pid) {
        # A Windows virtual environment may launch its base Python as a child.
        $apiProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$apiPidToStop" -ErrorAction Stop
        if (-not $apiProcess -or [int]$apiProcess.ParentProcessId -ne [int]$state.api_pid) {
            throw '后端监听进程与记录的启动进程不符，已拒绝结束进程。'
        }
    }
    Stop-Process -Id $apiPidToStop -ErrorAction Stop
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (-not (Get-WarehouseHealth)) { break }
        Start-Sleep -Milliseconds 250
    }
    if (Get-WarehouseHealth) { throw '后端仍在运行；请勿拔出 U 盘。' }
    Write-Output '已关闭仓库后端。'
} else {
    Write-Output '仓库后端未运行。'
}
foreach ($port in @(5173, 5174, 5175)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "端口 $port 还有网页服务在运行，不能确认其是否正在读取 U 盘。请关闭旧服务或重启电脑后再安全移除。"
    }
}
if ($state -and $state.project -eq $project -and $state.database -eq $database) { Remove-Item -LiteralPath $runtimeFile -Force }

if (Test-Path -LiteralPath $database) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
    & $python (Join-Path $project 'backend\pilot_storage.py') backup $database (Join-Path $dataDirectory 'backups')
    if ($LASTEXITCODE -ne 0) { throw '服务已关闭，但电脑本地备份失败。请先检查备份问题，再安全移除 U 盘。' }
    Write-Output 'U 盘试点库已备份到本机。现在可在 Windows 中“安全删除硬件”后拔出 U 盘。'
}
