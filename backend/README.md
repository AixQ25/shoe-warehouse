# 后端开发说明

这里是开发代码和办公室试点。唯一活动 SQLite 数据库在项目内的 `office-pilot-data/warehouse.sqlite3`；项目从 U 盘整包搬到电脑时，这份文件也随之移动。本机安全备份独立保存。正式部署方案尚需按这一决定调整并完成现场验证。

## 在开发电脑启动

直接运行项目根目录的 `start-local.cmd`。若数据库不存在，启动脚本会先在项目内创建空库并交互式建立 `admin` 账号；已有数据库不会被覆盖。随后检查、备份、迁移并启动前后端。每次结束运行 `stop-local.cmd` 关闭服务并备份，再安全弹出 U 盘。非技术步骤见[办公室试点操作说明](../办公室试点操作说明.md)。

建议在开发电脑本地磁盘建立 Python 3.13 虚拟环境，不要把虚拟环境和数据库放在 U 盘。以下命令在 `backend` 目录运行，PowerShell 示例：

```powershell
python -m venv "$env:LOCALAPPDATA\mold-warehouse-venv"
& "$env:LOCALAPPDATA\mold-warehouse-venv\Scripts\python.exe" -m pip install -r requirements.txt
$env:DATABASE_URL = 'sqlite+pysqlite:///' + (((Resolve-Path '..\office-pilot-data\warehouse.sqlite3').Path) -replace '\\','/')
& "$env:LOCALAPPDATA\mold-warehouse-venv\Scripts\python.exe" -m alembic upgrade head
& "$env:LOCALAPPDATA\mold-warehouse-venv\Scripts\python.exe" -m app.cli create-worker --username worker01 --person-name 张三
& "$env:LOCALAPPDATA\mold-warehouse-venv\Scripts\python.exe" -m app.cli create-readonly --username warehouse-view
& "$env:LOCALAPPDATA\mold-warehouse-venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

这些手工命令仅供开发维护；日常试点直接使用根目录启动/停止文件。必须明确设置 `DATABASE_URL`，后端不再默认连接电脑本地库。`bootstrap-local` 只用于单独建立的空开发库，不应用于既有办公室试点库。交互式开户命令要求至少 12 字符密码，不写入源文件。API 文档位于本机 `http://127.0.0.1:8000/docs`。前端开发服务器可代理 `/api` 到本机 8000 端口。

新建的试点库为空，不需要清空样例。`prepare_pilot.py` 仅保留给符合旧样例结构的已有开发库使用，不用于新库。可通过前端 CSV 模板导入真实试点资料，填写要求见[试点导入说明](../试点导入说明.md)。

从另一台电脑继续办公室试点时，U 盘携带源码和同一份数据库；每台电脑独立安装依赖并把日志、安全备份存放在本机 `%LOCALAPPDATA%\mold-warehouse-dev`。不得在多台电脑同时打开同一数据库。现有 `WAREHOUSE_ENV=production` 仍拒绝非 PostgreSQL 数据库；整包搬迁方案要在正式部署前另行适配，不能直接使用旧 Compose 草案。

项目根目录现有区分开发与正式的 Compose 配置，仓库主机部署和备份步骤见[部署与备份草案](../deployment/README.md)。当前电脑未安装 Docker，容器、HTTPS、备份恢复及现场网络尚未运行验证。

## 已提供接口

- `/api/auth`：登录、当前账号、退出；写操作用 `X-CSRF-Token`。
- `/api/auth/users`、`/api/auth/audit`：维护员开户、停用/启用、密码重置与最近审计；停用或重置会撤销既有登录和设备授权。
- `/api/devices`：作业设备登记、当前浏览器状态查询、维护员授权及撤销。登录和已授权设备同时有效才允许库存写操作。
- `/api/people`、`/api/locations`、`/api/models`、`/api/sets`、`/api/molds`：基础资料查询和维护员建档。
- `PATCH /api/people/{id}/active`、`PATCH /api/sets/{id}/default-location`：带原因停用/启用人员及调整套的默认库位；修改默认库位不会移动实物。
- `/api/scan/resolve`：解析模具码和库位码。
- `/api/dashboard`、`/api/set-matrix`、`/api/production-lines/summary`：看板汇总。
- `/api/operations`：领用、归还、移库、转线，含请求编号幂等校验；列表与单据详情。归还可在同一单内逐件选择完好、待检或送修，异常件单独指定实际位置和原因，整单原子提交。
- `POST /api/operations/{id}/corrections`：维护员以新单据补偿更正尚无后续变化的领还、移库或转线记录；要求原因与请求编号。整套完好归还须专项核查，不能直接冲销。
- `/api/stocktakes`：库位盘点建单与冻结、期初快照、库位核对、扫码、提交、退回、关闭和取消。维护员可用带版本号及请求编号的核查单据处理“未找到”和部分在库错位；未知码不会自动建档。
- `/api/molds/{id}/transition`：异常归还待检、送修、维修完成、检验通过、报废及盘点待核查模具找回。状态与目标位置、版本和盘点冻结均由后端校验；报废与找回仅维护员可执行。
- `/api/imports/template`、`preview`、`commit`：维护员下载 CSV 模板、逐行预览校验、确认后整批初始建档。每套生成一张初始化流水；原始套号和模具编号不可覆盖。确认请求可用同一预览编号重试，预览有效期 30 分钟。
- `/api/exports/inventory`、`operations`：维护员导出全量有效库存与逐件流水；领用人员可导出库存和自己的流水，只读账号不可导出。CSV 为 UTF-8 BOM，危险公式开头的文本会被转义。
- `/api/labels/preview`、`print-record`、`print-records`：维护员和领用人员生成单模具/库位标签资料、记录打印请求并查看日志。模具码固定为 `MOLD:编号`，位置码固定为 `LOC:编号`；补打需填写原因，同一请求编号重试不会重复记账。记录仅证明发起过打印请求，不能证明纸张已经印出。

`/api/operations` 的领用人员取当前登录账号关联的人员。每件模具提交 `mold_id` 和查询时的 `expected_version`。一次提交使用新的 UUID `request_id`；超时后先用 `/api/operations/by-request/{request_id}` 查询结果，不要换号盲目重交。

混合归还时，每个 `items` 元素可另填 `return_condition`（`READY`、`PENDING_INSPECTION` 或 `IN_REPAIR`）；后两者必须同时填写 `exception_location_id` 和至少 3 个字的 `note`。待检目标必须是待检区，送修目标必须是维修区。顶层 `target_location_id` 是完好件的普通库位；如果全批没有完好件，则填任意一件的异常目标位置。逐件实际去向和原因写入流水，整套默认库位只在 10 个当前模具全部完好归还时变化。

批量建档模板列名依次为 `model_code`（型号编号）、`model_name`（型号名称）、`set_code`（套号）、`default_location_code`（默认普通库位）、`mold_code`（单模具编号）、`size_label`（尺码）、`status`（`READY` 或 `PENDING_INSPECTION`）、`current_location_code`（当前位置）、`original_code`（可选原编号）。每套填写 10 行且尺码不重复；默认库位必须是已维护的普通货架，当前位置须与状态相容。先在维护界面创建真实库位，再导入真实资产。CSV 需保存为 UTF-8，可带 BOM，单次上限 3 MB、5,000 行。预览只保存待确认批次，不建立库存；确认时会再次校验库位及编号，整批提交或整批回滚。系统不会把演示资料自动迁入正式库。

## 验证

```powershell
python -m unittest discover -s tests -v
```

测试使用独立 SQLite，不写开发库。覆盖设备授权、领还及版本冲突、整套换位、混合归还、补偿更正、账号管理、盘点、CSV 导入导出与标签记录等。迁移使用临时 SQLite 验证升级和回退。PostgreSQL 仍需同版本环境验证。
