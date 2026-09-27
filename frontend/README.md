# 鞋模具仓库前端

React + TypeScript + Vite。电脑页面使用同一侧边栏、货架布局和共用表格、抽屉、状态徽章、空态与加载骨架，数据由后端提供。仓库布局按 A–J 区、每区 5 个货架和 3 层展示模具格位；流转记录提供搜索、类型筛选、套号、数量、去向和逐件明细。库位盘点、资料导入导出和二维码标签合并到“仓库工具”入口，进入后分别显示用途说明。没有浏览器内的另一套演示页面或数据源开关。

## 本机启动与登录

在项目根目录双击 `start-local.cmd`，会在前后端连接正常后打开登录页；也可运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1
```

首次使用前须在原办公室电脑双击 `import-office-data.cmd`，把既有试点库迁入 U 盘的 `office-pilot-data/warehouse.sqlite3`。此后双击 `start-local.cmd`，继续使用原账号和密码；启动不会创建新库、新账号或样例模具。浏览器打开 `http://127.0.0.1:5173/` 登录。脚本将 Vite 的 `/api` 代理到本机 `127.0.0.1:8000`。每日结束双击 `stop-local.cmd`，等待电脑本地备份完成后安全弹出 U 盘。完整步骤见[办公室试点操作说明](../办公室试点操作说明.md)。

电脑重启后服务进程会退出，需再次双击启动文件；登录页出现 502 通常表示后端未运行，并不意味着密码改变。启动脚本会核对正在运行的后端身份、U 盘数据库和页面代理；若身份不匹配会拒绝继续。服务日志在 `%LOCALAPPDATA%\mold-warehouse-dev\logs`。若只需手动启动前端，在后端运行后执行 `npm.cmd ci`、`npm.cmd run dev`。更多账号及迁移命令见 [后端说明](../backend/README.md)。`?page=records` 可直接打开流转记录；从该页的“登记流转”进入现场流转登记。旧链接的 `?demo=1` 或 `?source=demo` 参数会被移除。

页面登录使用后端会话。电脑端的领用、归还、移库和转线登记从“流转记录 → 登记流转”进入，不占用独立侧边栏入口；设备授权统一在“系统管理”处理。库存写操作仍需本人账号和已授权设备；维护员在系统管理中管理账号、设备与审计。安卓真机相机、局域网 HTTPS、标签打印和正式仓库主机尚待现场验证。

手机使用时，在项目根目录执行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1 -Lan`。手机连接与电脑同一路由器的 Wi-Fi，打开脚本输出的 `http://电脑局域网IP:5174/?view=mobile`，使用已有账号登录。手机页面可按模具编号、套号或型号查询；扫描模具后，在其详情下办理单件领用或完好归还。首次作业须在手机上登记设备，再由维护员在电脑端“系统管理”授权；读取状态后选择目标产线或库位并确认。异常归还仍在电脑端办理。普通 HTTP 显示“拍照扫码”，实时摄像头扫码需要手机信任的 HTTPS。电脑需保持开机并运行服务；若手机连不上，应检查 Wi-Fi 访客隔离和 Windows 防火墙对该端口的访问限制。

Android 实时扫码试点可在项目根目录运行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-mobile-https.ps1`。脚本启动现有服务并在 5175 端口提供局域网 HTTPS，证书私钥仅保存在 `%LOCALAPPDATA%\mold-warehouse-dev\certs`。先用手机的 HTTP 地址 `http://电脑局域网IP:5174/warehouse-pilot-ca.crt` 下载公开 CA 证书，在 Android 设置的“安全与隐私 → 更多安全设置 → 加密与凭据 → 安装证书 → CA 证书”中安装，再用 Chrome 打开脚本输出的 `https://电脑局域网IP:5175/?view=mobile`，允许相机权限。不同 Android 厂商的设置名称可能略有不同。若电脑换了网络，重新运行脚本会为新 IP 签发站点证书；CA 信任通常无须重新安装。试点结束后，可从手机的“用户凭据”中移除该 CA。请勿把 `.key` 私钥文件传给手机或他人。

```powershell
npm.cmd run lint
npm.cmd run build
```
