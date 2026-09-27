param([string]$Source)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $project 'office-pilot-data\warehouse.sqlite3'
$localData = [Environment]::GetFolderPath('LocalApplicationData')
$backupDirectory = Join-Path $localData 'mold-warehouse-dev\backups'

if (Test-Path -LiteralPath $target) { throw "U 盘试点数据库已存在，绝不覆盖：$target" }
if (Get-NetTCPConnection -LocalPort 8000,5173,5174,5175 -State Listen -ErrorAction SilentlyContinue) {
    throw '仓库相关服务仍在运行。请先双击 stop-local.cmd 关闭服务；若是旧版服务无法确认身份，请重启电脑后再迁移。'
}

if (-not $Source) {
    $possible = @(
        (Join-Path $localData 'mold-warehouse-dev\warehouse.sqlite3'),
        (Join-Path $localData 'Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\mold-warehouse-dev\warehouse.sqlite3')
    )
    $choices = @($possible | Where-Object { Test-Path -LiteralPath $_ })
    if ($choices.Count -eq 0) { throw '当前电脑找不到原办公室数据库。请在保存旧库的办公室电脑上运行此文件。' }
    if ($choices.Count -eq 1) { $Source = $choices[0] }
    else {
        Write-Output '找到两份本机数据库，请选择原来实际使用的那份：'
        $inspector = (Get-Command python.exe -ErrorAction Stop).Source
        for ($index = 0; $index -lt $choices.Count; $index++) {
            $item = Get-Item -LiteralPath $choices[$index]
            Write-Output "$($index + 1). $($item.FullName)；最近修改：$($item.LastWriteTime)"
            & $inspector (Join-Path $project 'backend\pilot_storage.py') check $item.FullName
        }
        $selection = Read-Host '输入 1 或 2'
        if ($selection -notin @('1', '2')) { throw '未选择数据库，迁移已取消' }
        $Source = $choices[[int]$selection - 1]
    }
}
if (-not (Test-Path -LiteralPath $Source)) { throw "找不到原数据库：$Source" }

$python = (Get-Command python.exe -ErrorAction Stop).Source
& $python (Join-Path $project 'backend\pilot_storage.py') import $Source $target $backupDirectory
if ($LASTEXITCODE -ne 0) { throw '数据库迁移失败；原数据库保持不变，请检查上面的错误。' }
Write-Output '迁移完成。原电脑数据库未删除，U 盘试点库和电脑本地备份均已通过完整性检查。'
Write-Output '现在可双击 start-local.cmd 登录，原账号和原密码保持不变。'
