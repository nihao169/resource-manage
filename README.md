# 文件管理系统开发骨架

这是可启动的工程基础，不是业务 MVP。原有四份设计文档保留不变，作为业务开发契约：

- [架构](doc/文件管理系统技术架构文档.md)
- [数据库](doc/PostgreSQL表结构设计.md)
- [对象规则](doc/MinIO对象规则.md)
- [API](doc/前后端接口定义.md)

文档统一存放在 `doc/` 目录，README 保留在根目录作为入口。文档中的命令从项目根目录执行，除非另有说明。

## 首次启动（Windows PowerShell）

需要 Docker Desktop Linux Engine、Compose v2；本地前端开发建议 Node 24.15 或更高受支持版本。后端运行基线为容器 Python 3.12，不依赖本机 Python 3.13。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev-up.ps1
```

脚本检查 Docker，生成缺失的 .env 与随机密钥，构建 API，生成 localhost/127.0.0.1 SAN 自签名证书，启动存储，创建账号和三个私有 Bucket，执行 Alembic，启动 API 与 Nginx，然后冒烟检查。已有配置、密钥和数据不覆盖；已有证书必须完整、匹配、未过期。不会修改系统证书信任。

访问 https://localhost:8443；浏览器需手动接受本地自签名证书。http://localhost:8080 保留路径重定向到 HTTPS。仅监听宿主机回环地址。首次拉取镜像和安装依赖需要联网。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
docker compose ps
docker compose logs --tail 100 api nginx postgres minio
docker compose stop
```

停止不会删除数据；不要用 down -v 清除开发数据。项目名默认 fm-skeleton，数据卷为 fm-skeleton_postgres_data 和 fm-skeleton_minio_data。如已有同名项目，请首次启动前修改 .env 的 COMPOSE_PROJECT_NAME。改密码文件不会自动同步既有数据库账号，需负责人执行明确的凭据轮换。

## 三人开发目录与边界

详细模块、实际文件归属和 B/C 对接边界见 [三人成员分工说明](doc/三人成员分工说明.md)。

| 人员 | 主目录 | 职责 |
| --- | --- | --- |
| A 前端 / Nginx | frontend/、configs/nginx/ | Vue 页面、状态、HTTP 客户端、公共 DTO、前端镜像、HTTPS 和代理 |
| B PostgreSQL 后端 / 后端集成 | backend/app/core/、元数据 API/Service、repositories/、models/、schemas/、backend/migrations/、configs/postgres/ | 认证权限、元数据、搜索、事务、幂等、版本、清理引用及后端公共文件合并 |
| C MinIO 后端 / 部署 | backend/app/integrations/、上传/下载 Service 与路由、configs/minio/、compose*.yaml、scripts/ | 存储、校验、续传、对象补偿、对应 FastAPI 调用层、启动和部署维护 |

B、C 共同开发一个 FastAPI 服务，不是只操作数据库、不另建服务。上传 Service 的最终事务、锁顺序和权限由 B/C 协商，数据库方法契约在 app/services/contracts.py。传入同一 pinned Connection，由 Service 控制事务；Repository 与 MinIO 适配层不得自行 commit。上传状态仅使用 created/uploading/uploaded/committed/failed/expired。

只有已实现并通过测试的业务路由才在 `app/main.py` 注册；未完成模块继续返回统一 JSON 404，禁止用示例数据伪造成功结果。ORM 只映射既有迁移，不使用 autogenerate 或 `create_all`，DDL 仍以首次迁移和契约为准。

## 已实现基础能力

- 请求 UUID、统一错误信封、配置与 secret 文件读取、lifespan 连接资源释放。
- GET /api/health/live 只报告进程存活，不检查存储。
- GET /api/health/ready 校验 PostgreSQL 可用、0001_base 迁移版本、应用查询权限，以及 uploads/contents Bucket。backups 由一次性初始化检查创建，API 业务账号无备份权限。
- 仅 development 开启 /api/docs 与 /api/openapi.json。
- Vue 模块入口和真实 live 检查，无默认 Mock。
- Nginx 保留 /api 前缀代理，SPA 回退，34 MiB 请求上限，HTTP/1.1 流式传输；普通查询/分片/提交与清理/备份超时分别为 60/300/660/3660 秒。登录与刷新分别限流 10/30 次每分钟，普通 API 20 次每秒，分片每 IP 最多 4 个并发；413/429 返回 JSON。ready 对外 403。
- 首次迁移完整落地文档 22 张表、约束、函数、触发器和配置种子；启动 API 不执行迁移。
- 已实现认证 Cookie、会话撤销、CSRF/Origin 校验、空间与成员、目录、文件元数据、搜索、版本恢复、回收站、审计和配置/备份记录查询。
- 元数据修改使用 `Idempotency-Key` 请求指纹与结果快照；业务更新、审计和幂等完成记录在同一数据库事务提交，重放前重新检查当前权限。
- `DatabaseContractService` 提供上传记录、分片确认/续传、内容对象、上传提交、下载授权及清理检查点的数据库侧方法，供传输模块在 pinned connection 上调用。

MinIO 二进制分片、对象发布和流式下载仍由传输负责人实现，相关空路由未注册。上传默认 8 MiB 分片、4 并发、24h 会话由传输 Service 读取已有 settings，并调用上述数据库契约完成最终提交。

## 凭据与存储

secrets/ 和 certs/ 被 Git 与 Docker 构建忽略。Compose 只挂载必要文件：

- fm_bootstrap：PostgreSQL 初始化账号，不给 API。
- fm_migrator：数据库/表所有者，只用于一次性迁移。
- fm_app：SELECT/INSERT/UPDATE/DELETE，审计只读/追加；无 DDL/TRUNCATE/表所有权/禁用触发器权限。
- fm_root：MinIO 初始化账号，不给 API。
- fm_api：uploads/contents 业务操作。
- fm_backup：读取 contents，管理 backups，仅备份流程使用。

三个 Bucket 均私有；正式对象没有日期自动过期规则。传输流程完成前不能手动写正式对象代替上传校验。数据存储于命名卷，账号初始化依赖 PostgreSQL 空卷初始化流程。密钥目录应只向项目开发者开放，不提交、不截图、不在日志打印。

MinIO 官方社区仓库目前归档，Docker Hub 历史镜像已不可直接依赖。本骨架固定 Quay 的历史服务端与 mc 镜像摘要，仅用于开发验证；上线前必须评估维护、安全与许可，不把历史镜像当作受维护的生产选择。参见 [MinIO 官方仓库](https://github.com/minio/minio)。镜像摘要与解析后 Python/Node 依赖均固定，升级需重新测试 S3 兼容性。

## 开发、构建与测试

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
npm.cmd run typecheck
npm.cmd run build
npm.cmd test
cd ..
docker compose build api
docker compose run --rm --no-deps api pytest -q
docker compose run --rm --no-deps api ruff check .
docker compose config --quiet
docker compose build nginx
docker compose up -d --wait nginx
```

存储初始化后可运行完整基础验证：powershell -ExecutionPolicy Bypass -File scripts/test.ps1。
真实存储测试只检查本项目表、账号权限和 Bucket 私有访问，不写入文件对象；默认 pytest 跳过这些集成检查，需 FM_INTEGRATION_TESTS=1 显式开启。

可选故障验证：powershell -ExecutionPolicy Bypass -File scripts/check-dependencies.ps1。该脚本会短暂停止本项目 PostgreSQL/MinIO，验证 live 仍为 200、ready 返回对应 503，并在 finally 中恢复服务；仅在无其他开发操作的本地环境运行。

Vite 开发代理到本地 HTTPS，开发环境仅该代理关闭证书验证；生产 Nginx 终止 TLS。前端变更后重建 nginx 镜像；修改后端后重建 api 并 docker compose up -d --wait api。容器不热挂源码。

新迁移显式执行：

```powershell
docker compose -f compose.yaml -f compose.init.yaml run --rm --no-deps api python -m app.cli migrate
```

compose.init.yaml 仅用于一次性任务，不能拿它启动常驻 API，否则会给 API 迁移账号。初始化命令不是常驻服务。首次迁移不支持 destructive downgrade，回退须使用评审后的备份恢复。

## 故障排查

- Docker 不可访问：确认 Docker Desktop 正在运行，启用 Linux Engine，并检查当前用户权限。
- 8443/8080 冲突：首次启动前修改 .env 对应端口；PUBLIC_HOST 默认 localhost，证书仅支持 localhost 与 127.0.0.1。
- 就绪 503：检查迁移是否执行、账号是否与现有卷一致、Bucket 是否初始化；错误响应不会暴露凭据。
- ready 对外 403 是预期；用 docker compose exec api 内部请求 ready。
- 首次初始化失败：查看日志后重试；不删除卷、不覆盖密钥。数据库 role 初始化只发生在空卷，若部分初始化异常需负责人手工修复。
- 404 是预期：骨架没有业务接口。没有登录账户种子，也没有绕过权限的演示登录。
- 自签名警告：仅本地浏览器接受；脚本不会添加根证书信任。
- MinIO 镜像不可拉取：检查 Quay 网络访问，禁止随意换成 latest；需明确固定、评审镜像。

实际验证结果见 [验证记录](doc/验证记录.md)；业务验收仍须按四份契约完成。
