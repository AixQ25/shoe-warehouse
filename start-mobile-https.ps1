param([switch]$OpenBrowser)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontend = Join-Path $project 'frontend'
$dataDirectory = Join-Path $env:LOCALAPPDATA 'mold-warehouse-dev'
$certDirectory = Join-Path $dataDirectory 'certs'
$logDirectory = Join-Path $dataDirectory 'logs'
$python = Join-Path $env:LOCALAPPDATA 'mold-warehouse-venv\Scripts\python.exe'
$gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
$opensslCommand = Get-Command openssl.exe -ErrorAction SilentlyContinue
$opensslCandidates = @()
if ($opensslCommand) { $opensslCandidates += $opensslCommand.Source }
if ($gitCommand) {
    $gitRoot = Split-Path -Parent (Split-Path -Parent $gitCommand.Source)
    $opensslCandidates += Join-Path $gitRoot 'mingw64\bin\openssl.exe'
    $opensslCandidates += Join-Path $gitRoot 'usr\bin\openssl.exe'
}
$opensslCandidates += 'C:\Program Files\Git\mingw64\bin\openssl.exe'
$openssl = $opensslCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$caKey = Join-Path $certDirectory 'pilot-ca.key'
$caCert = Join-Path $certDirectory 'pilot-ca.crt'
$serverKey = Join-Path $certDirectory 'lan-server.key'
$serverCert = Join-Path $certDirectory 'lan-server.crt'
$serverRequest = Join-Path $certDirectory 'lan-server.csr'
$extensions = Join-Path $certDirectory 'lan-server.ext'
$webPort = 5175

if (-not $openssl) { throw 'OpenSSL was not found. Install Git for Windows and ensure git.exe or openssl.exe is on PATH.' }
& (Join-Path $project 'start-local.ps1')
New-Item -ItemType Directory -Path $certDirectory, $logDirectory -Force | Out-Null

$lanIps = @([System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
    Where-Object { $_.AddressFamily -eq 'InterNetwork' -and -not [System.Net.IPAddress]::IsLoopback($_) } |
    ForEach-Object { $_.IPAddressToString } | Select-Object -Unique)
if ($lanIps.Count -eq 0) { throw 'No LAN IPv4 address found. Connect this computer to Wi-Fi first.' }

if ((Test-Path -LiteralPath $caKey) -xor (Test-Path -LiteralPath $caCert)) {
    throw "The local CA files are incomplete. Check $certDirectory before replacing the CA trusted by the phone."
}
if (-not (Test-Path -LiteralPath $caCert)) {
    & $openssl req -x509 -newkey rsa:3072 -noenc -sha256 -days 730 -keyout $caKey -out $caCert -subj '/CN=Mold Warehouse Pilot CA' -addext 'basicConstraints=critical,CA:TRUE' -addext 'keyUsage=critical,keyCertSign,cRLSign'
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the pilot CA certificate.' }
}

$regenerateServer = -not (Test-Path -LiteralPath $serverCert) -or -not (Test-Path -LiteralPath $serverKey)
if (-not $regenerateServer) {
    & $openssl x509 -in $serverCert -noout -checkend 604800 *> $null
    if ($LASTEXITCODE -ne 0) { $regenerateServer = $true }
    else {
        $san = (& $openssl x509 -in $serverCert -noout -ext subjectAltName) -join ' '
        foreach ($ip in $lanIps) {
            if (-not $san.Contains("IP Address:$ip")) { $regenerateServer = $true; break }
        }
    }
}

if ($regenerateServer) {
    $altNames = @('DNS.1 = localhost', 'IP.1 = 127.0.0.1')
    for ($index = 0; $index -lt $lanIps.Count; $index++) { $altNames += "IP.$($index + 2) = $($lanIps[$index])" }
    @('[v3_server]', 'basicConstraints = critical,CA:FALSE', 'keyUsage = critical,digitalSignature,keyEncipherment', 'extendedKeyUsage = serverAuth', 'subjectAltName = @alt_names', '[alt_names]') + $altNames | Set-Content -LiteralPath $extensions -Encoding ascii
    & $openssl req -new -newkey rsa:2048 -noenc -keyout $serverKey -out $serverRequest -subj "/CN=$($lanIps[0])"
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the HTTPS server key.' }
    & $openssl x509 -req -in $serverRequest -CA $caCert -CAkey $caKey -CAcreateserial -out $serverCert -days 365 -sha256 -extfile $extensions -extensions v3_server
    if ($LASTEXITCODE -ne 0) { throw 'Could not issue the LAN HTTPS certificate.' }
}

function Test-WarehouseHttps {
    $code = @'
import sys, httpx
try:
    response = httpx.get(sys.argv[1], verify=sys.argv[2], trust_env=False, timeout=2)
    sys.exit(0 if response.status_code == 200 else 1)
except Exception:
    sys.exit(1)
'@
    & $python -c $code 'https://127.0.0.1:5175/api/health' $caCert *> $null
    return $LASTEXITCODE -eq 0
}

if ($regenerateServer) {
    $listener = Get-NetTCPConnection -LocalPort $webPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        if ($process.CommandLine -notmatch 'vite' -or $process.CommandLine -notmatch '5175') { throw "Port $webPort is used by another process." }
        Stop-Process -Id $listener.OwningProcess
    }
}

if (-not (Test-WarehouseHttps)) {
    $env:WAREHOUSE_HTTPS_CERT = $serverCert
    $env:WAREHOUSE_HTTPS_KEY = $serverKey
    $webProcess = Start-Process -FilePath 'npm.cmd' -ArgumentList @('run', 'dev', '--', '--host', '0.0.0.0', '--port', "$webPort", '--strictPort') -WorkingDirectory $frontend -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'frontend-5175.out.log') -RedirectStandardError (Join-Path $logDirectory 'frontend-5175.err.log')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        if ((Test-WarehouseHttps) -or $webProcess.HasExited) { break }
    }
    if (-not (Test-WarehouseHttps)) { throw "HTTPS page did not start. Check $logDirectory\frontend-5175.err.log" }
    $runtimeFile = Join-Path $dataDirectory 'running-instance.json'
    $state = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
    $webPids = @{}
    if ($state.web_pids) { $state.web_pids.PSObject.Properties | ForEach-Object { $webPids[$_.Name] = $_.Value } }
    $listener = Get-NetTCPConnection -LocalPort $webPort -State Listen -ErrorAction Stop | Select-Object -First 1
    $webPids["$webPort"] = $listener.OwningProcess
    @{ project = $state.project; database = $state.database; instance_id = $state.instance_id; api_pid = $state.api_pid; web_pids = $webPids } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $runtimeFile -Encoding UTF8
}

foreach ($ip in $lanIps) { Write-Output "Android live scan: https://${ip}:$webPort/?view=mobile" }
Write-Output "请通过 USB 或其他可信方式把此 CA 证书传到手机并安装（不要传 .key 私钥）：$caCert"
& $openssl x509 -in $caCert -noout -fingerprint -sha256
Write-Output 'Never share private .key files from the certs directory.'
if ($OpenBrowser) { Start-Process "https://127.0.0.1:$webPort/?view=mobile" }
