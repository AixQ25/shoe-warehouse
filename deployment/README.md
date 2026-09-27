# 部署与备份草案

这份配置用于开发完成后复制到仓库固定主机的本地磁盘，再完成局域网部署。当前 U 盘只携带源代码；不要在 U 盘上运行正式容器、保存 `.env`、数据库卷或备份。当前开发电脑没有 Docker，以下容器启动、HTTPS、备份恢复和手机访问步骤尚未实测。

## 先在办公室验证容器

在装有 Docker Compose 的开发电脑上，将 `.env.example` 复制为本机磁盘上的配置文件，修改为仅供开发使用的随机数据库密码，然后在项目根目录运行：

```powershell
docker compose --env-file C:\warehouse-dev.env -f compose.dev.yaml config
docker compose --env-file C:\warehouse-dev.env -f compose.dev.yaml up -d --build
```

打开 `http://localhost:8080`。此 Compose 项目名为 `mold-warehouse-dev`，数据库使用单独的 `postgres_dev_data` 命名卷，不与正式卷混用。开发容器启动时自动执行 Alembic 迁移；如需演示账号，仅在此开发库运行 `docker compose ... exec api python -m app.cli seed-demo --sets 5` 和创建账号命令。不要把演示资料复制到正式库。停服务使用 `docker compose ... down`，保留命名卷；`down -v` 会删除卷，不用于日常停止。

## 仓库主机首次部署

1. 在仓库固定主机的本地磁盘复制项目发布文件，安装 Docker Compose，安排主机上电自启、禁止工作时段休眠，并给仓库手机和看板电脑设置可稳定访问的内网名称或固定 IP。正式主机与开发电脑、U 盘完全分开。
2. 将 `.env.example` 的内容存到主机本地的私有 `.env` 文件，设置强随机 `POSTGRES_PASSWORD`，将 `WAREHOUSE_HOST` 改为实际访问名称或 IP。限制该文件的读取权限，不把密码写入源代码、二维码或截图。正式发布前锁定并核查 Docker 基础镜像的具体版本/摘要。
3. 在发布目录运行 `docker compose --env-file <主机本地.env路径> -f compose.yaml config` 检查配置，再运行 `docker compose --env-file <主机本地.env路径> -f compose.yaml up -d --build`。数据库只使用 Docker 主机本地的 `postgres_data` 命名卷；后端等待数据库健康检查通过，再自动执行迁移；前端及 API 只由 Web 服务对局域网暴露 80/443 端口。
4. 用 `docker compose ... ps` 检查服务状态。只在正式空库创建维护员、领用人员和只读看板账号，例如 `docker compose ... exec api python -m app.cli create-admin --username admin --person-name 维护员`；密码交互输入。不要在正式库运行 `seed-demo`。
5. Web 服务用 Caddy `tls internal` 为实际内网访问地址签发证书。将 `caddy_data` 卷内 `/data/caddy/pki/authorities/local/root.crt` 导出到受控位置，核对指纹后在固定安卓手机和看板电脑安装为信任根证书。所有设备用与证书一致的名称或 IP 访问 HTTPS；不要跳过证书警告。CA 私钥留在受保护的主机卷和加密备份中，不分发给手机。续期、换机或换主机后重新检查信任。Caddy 官方说明：其内部 CA 的根证书需要由管理者安装到其他设备的信任库，容器内自动安装也不能替代此步骤：https://caddyserver.com/docs/automatic-https#local-https 。
6. 放行局域网必要端口，限制外部网络访问。电脑及安卓浏览器登录后，按 `项目规划.md` 的验收用例用真实标签做扫码、领用、归还、盘点和弱网重试。确认无互联网时仍可工作，并断开开发 U 盘/关闭开发电脑再测。

`compose.yaml` 是正式配置，`compose.dev.yaml` 是办公室容器联调配置。两者不同时叠加使用。代码变更后的升级前先备份，再在可恢复的维护窗口执行 `up -d --build` 和迁移检查。正式 PostgreSQL 并发与手机摄像头尚未验证，不应只凭配置文件通过就视为可上线。

## 备份与试恢复

在仓库主机上用 `backup.ps1 -BackupDirectory <主机独立备份目录> -EnvFile <主机本地.env路径>` 生成 PostgreSQL 自定义格式备份、Caddy 数据卷压缩包及 SHA-256 校验文件。备份目录不得在项目工作区内；完成后把备份加密复制到另一台设备或独立存储，限制访问并检查校验值。数据库卷本身不是备份。建议每日运行一次，并定期在独立测试环境演练恢复；备份频率和保留期要按现场能接受的数据损失时间确认。

试恢复只在隔离的空测试库进行：先单独启动 `compose.dev.yaml` 的 `db` 服务；将 `.dump` 文件复制到容器的 `/tmp/restore.dump`，在空 `warehouse` 数据库执行 `pg_restore -U warehouse -d warehouse --no-owner --no-acl --exit-on-error /tmp/restore.dump`；再启动测试 API，核对套数、模具数、流水、账号与一次测试扫码。不要把测试恢复命令直接对正式库运行。正式灾难恢复前先确定目标库和停机窗口，并核对备份时间。Caddy 数据备份包含内部 CA 私钥，恢复时应保护文件权限；若未恢复原 CA，手机和看板电脑须重新安装并验证新根证书。PostgreSQL 的 `pg_dump`/`pg_restore` 用法以官方文档为准：https://www.postgresql.org/docs/17/app-pgdump.html 、https://www.postgresql.org/docs/17/app-pgrestore.html 。

现场验收至少记录：真实设备和浏览器版本、实际访问地址、证书指纹、扫码与打印结果、一次完整领还、盘点冻结/差异、设备撤销、数据库备份与试恢复、主机重启后自动恢复，以及断网和断开 U 盘后的运行情况。未完成的项目应标“未验证”，不得当作已通过。
