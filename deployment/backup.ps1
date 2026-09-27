param(
    [Parameter(Mandatory = $true)][string]$BackupDirectory,
    [Parameter(Mandatory = $true)][string]$EnvFile
)

$ErrorActionPreference = 'Stop'
$projectDirectory = [System.IO.Path]::GetFullPath((Resolve-Path (Join-Path $PSScriptRoot '..')).Path).TrimEnd('\') + '\'
$backupPath = [System.IO.Path]::GetFullPath($BackupDirectory)
$envPath = [System.IO.Path]::GetFullPath($EnvFile)
if ($backupPath.Equals($projectDirectory.TrimEnd('\'), [System.StringComparison]::OrdinalIgnoreCase) -or $backupPath.StartsWith($projectDirectory, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw '备份目录不能位于项目工作区内；请使用仓库主机的独立备份磁盘或目录。'
}
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) { throw '找不到本机环境配置文件。' }
New-Item -ItemType Directory -Path $backupPath -Force | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$databaseFile = Join-Path $backupPath "warehouse-$stamp.dump"
$caddyFile = Join-Path $backupPath "caddy-data-$stamp.tar.gz"
$composeFile = Join-Path $projectDirectory 'compose.yaml'
$composeArgs = @('compose', '--env-file', $envPath, '-f', $composeFile)

& docker @composeArgs exec -T db pg_dump -U warehouse -d warehouse -Fc -f /tmp/warehouse.dump
if ($LASTEXITCODE -ne 0) { throw '数据库备份失败。' }
& docker @composeArgs cp db:/tmp/warehouse.dump $databaseFile
if ($LASTEXITCODE -ne 0) { throw '数据库备份复制到主机失败。' }
& docker @composeArgs exec -T db rm -f /tmp/warehouse.dump
if ($LASTEXITCODE -ne 0) { throw '数据库临时备份文件清理失败。' }

& docker @composeArgs exec -T web tar -czf /tmp/caddy-data.tar.gz -C /data .
if ($LASTEXITCODE -ne 0) { throw '内网证书数据备份失败。' }
& docker @composeArgs cp web:/tmp/caddy-data.tar.gz $caddyFile
if ($LASTEXITCODE -ne 0) { throw '内网证书数据复制到主机失败。' }
& docker @composeArgs exec -T web rm -f /tmp/caddy-data.tar.gz
if ($LASTEXITCODE -ne 0) { throw '证书临时备份文件清理失败。' }

Get-FileHash -Algorithm SHA256 -LiteralPath $databaseFile, $caddyFile | ForEach-Object { "$($_.Hash)  $($_.Path)" } | Set-Content -LiteralPath (Join-Path $backupPath "checksums-$stamp.txt") -Encoding UTF8
Write-Output "备份已写入 $backupPath；请另行复制到独立设备并定期试恢复。"
