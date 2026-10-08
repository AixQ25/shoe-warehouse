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

这些手工命令仅供开发维护；日常试点直接使用根目录启动/停止文件。必须明确设置 `DATABASE_URL`，后端不再默认连接电脑本地库。`bootstrap-local` 只用于单独建立的空开发库，不应用于既有办公室试点库。交互式开户命令要求至少 6 位密码，不写入源文件。API 文档位于本机 `http://127.0.0.1:8000/docs`。前端开发服务器可代理 `/api` 到本机 8000 端口。

新建的试点库为空，不需要清空样例。`prepare_pilot.py` 仅保留给符合旧样例结构的已有开发库使用，不用于新库。可通过前端 CSV 模板导入真实试点资料，填写要求见[试点导入说明](../试点导入说明.md)。

从另一台电脑继续办公室试点时，U 盘携带源码和同一份数据库；每台电脑独立安装依赖并把日志、安全备份存放在本机 `%LOCALAPPDATA%\mold-warehouse-dev`。不得在多台电脑同时打开同一数据库。现有 `WAREHOUSE_ENV=production` 仍拒绝非 PostgreSQL 数据库；整包搬迁方案要在正式部署前另行适配，不能直接使用旧 Compose 草案。

项目根目录现有区分开发与正式的 Compose 配置，仓库主机部署和备份步骤见[部署与备份草案](../deployment/README.md)。当前电脑未安装 Docker，容器、HTTPS、备份恢复及现场网络尚未运行验证。

## 已提供接口

- `/api/auth`：登录、当前账号、退出；写操作用 `X-CSRF-Token`。
- `/api/auth/users`、`/api/auth/audit`：维护员开户、停用/启用、密码重置与最近审计；停用或重置会撤销既有登录和设备授权。
- `/api/devices`：作业设备登记、当前浏览器状态查询、维护员授权及撤销。登录和已授权设备同时有效才允许库存写操作。
- `/api/people`、`/api/locations`、`/api/models`、`/api/sets`、`/api/molds`：基础资料查询和维护员建档。
- `DELETE /api/locations/{id}`：维护员可删除任意产线，包括有流转、标签记录或仍有模具的产线。产线以 `active=false` 保留档案，管理列表、产线看板和新作业目标不再显示；历史单据与导出仍保留原产线编号，原有模具可继续归还或转出。`GET /api/locations` 保留这些档案供历史详情解析；原编号继续保留。其他位置仍仅允许删除尚无业务引用的档案。
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

混合归还时，每个 `items` 元素可另填 `return_condition`（`READY`、`PENDING_INSPECTION` 或 `IN_REPAIR`）；后两者需填写 `exception_location_id` 和至少三个字的 `note`。完好件去顶层目标普通库位，全批异常则用任意异常件目标。逐件去向和原因写入流水；只有该套计划码数已齐、所有当前件全部完好归还时才修改默认库位。历史未分类套仍按十件判断。整套归还补偿更正继续要求专项核查。

新批量模板列为 `mold_number`、`shoe_type`、`mold_category`、`set_sizes`、`size_label`、`default_location_code`、`status`、`current_location_code` 和五项标签资料（manufacturer、pairs_per_mold、sole_material、initial_quarter、opened_on）。shoe_type 为男鞋/女鞋/男童/女童，留空兼容旧版默认男鞋；set_sizes 为顿号等分隔的清单，留空用相应鞋类默认十码。每款类别需完整包含清单，且各行鞋类、清单和默认库位一致。身份自动生成，普通库位容量十件。UTF-8，可带 BOM，最多 3 MB/5,000 行；预览保存批次，确认重新校验，整批提交或回滚。兼容原 model_code/model_name/set_code/mold_code 格式和旧预览，不覆盖已有模具。

## 验证

标签资料新增 `manufacturer`、`mold_category`、`pairs_per_mold`、`sole_material`、`initial_quarter`、`opened_on` 六个可空字段，类别用于整套身份，其余五项支持建档和按件补录，旧模板兼容。排模双数为 1～99 的整数，季度为两位年份 + Q + 1～4，日期支持 YYYY-MM-DD / YYYY.M.D，保存为日期值。模具详情、扫码解析、标签预览与库存导出包含新增资料；二维码协议不变。

`PATCH /api/molds/{id}/metadata` 仅维护员可调用，提交需要 `expected_version` 和至少三个字的 `reason`。可部分更新五项标签资料，显式传 null 可清空；已有 A/B 套不能逐件改变或清空类别；不能通过此接口改编号、尺码、位置或状态。修改记录审计并更新模具版本，盘点冻结或版本冲突返回 409。升级迁移依次为 `b18d6f024c91`（标签字段）、`c29a7d103e82`（套级类别与款号/类别唯一约束）和 `d3b8a29401f6`（款式鞋类、套内码数方案）；先停止现有服务再按根目录启动流程备份和迁移。有标签、A/B 套、鞋类或码数方案资料时，相应迁移的直接降级会被拒绝。

```powershell
python -m unittest discover -s tests -v
```

测试使用独立 SQLite，不写开发库。覆盖设备授权、领还及版本冲突、整套换位、混合归还、补偿更正、账号管理、盘点、CSV 导入导出与标签记录等。迁移使用临时 SQLite 验证升级和回退。PostgreSQL 仍需同版本环境验证。

SQLite 的 API 写事务在业务读取前使用 `BEGIN IMMEDIATE`，串行保护库位容量、盘点快照和冻结；锁等待失败返回 `503 DATABASE_BUSY` 及 `Retry-After`，客户端应保留原请求重试。盘点列表始终包含未结束任务，并补充最近 50 条记录。HTTPS 代理请求的会话和设备 Cookie 使用 Secure；本机 5173 仅绑定回环地址，可信局域网测试的手机默认走 5174 HTTP，可选 HTTPS 入口为 5175。

`POST /api/mold-sets` 为整套/单个建档入口，仅维护员且需 CSRF：提交 `mold_number`、`shoe_type`（男鞋/女鞋/女童/男童，默认男鞋）、`mold_category`（默认 A模）、`default_location_id` 和五项标签资料。`mode=SET`（默认）建立计划中缺少的码数；`mode=SINGLE` 必须带 `size_label`，只建立一个码数。可传 `size_labels` 自定义 1～100 个不重复整数/半码，未传采用鞋类默认模板；已有套使用原计划，显式传不同计划返回 409。同款鞋类不一致返回 409，已建码数不重复，已有件资料与默认库位不变。本次新增及初始化流水单一事务提交，回包有 created_count、expected_size_count、size_count、complete。旧 models/sets/molds 接口保留兼容。详情、套列表、齐套矩阵及产线返回 shoe_type；库存导出新增鞋类。二维码仍使用单件 code，八行标签不增加鞋类行。

码段默认值及官方参考来源见根目录 README；均为可调整模板。升级前已明确 A/B 的套曾限定男鞋十码，迁移只对关联款式标记男鞋；未分类历史套的鞋类仍为空，编号、码数、位置、版本和流水不改。
