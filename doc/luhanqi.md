# luhanqi 开发日志

日期：2026-10-01  
分支：`feature/postgresql-luhanqi`  
负责模块：PostgreSQL / 元数据后端 / 后端公共集成

## 本次实现

- 完成 HS256 access token、Argon2id 密码校验、刷新会话轮换与撤销、会话绑定 CSRF、Origin 校验、安全 Cookie 和强制改密限制。
- 提供受控 `create-admin` 命令。管理员密码从文件读取，不在命令行、源码或日志中保存明文。
- 注册认证、空间/成员、目录、文件元数据、回收站、搜索、版本、审计、组件、设置与备份查询路由；统一沿用 `/api` 前缀及错误信封。
- 实现空间权限、文件所有者权限和管理员权限检查；实现目录同级冲突、文件软删除/恢复、版本恢复配额与引用计数事务。
- 补齐用户、会话、空间、目录、文件、版本、内容对象、上传、分片和审计 ORM 映射。ORM 仅作映射，不调用 `create_all`，首次迁移仍以 `0001_base.sql` 为唯一建表来源。
- 新增显式 Repository；Repository 不提交事务，由 Service 统一控制提交和回滚。
- 实现 `DatabaseContractService`，供 MinIO 模块调用：上传授权、上传记录、分片确认/续传、内容对象准备/就绪、上传提交、下载授权、文件 detach 和清理项完成。
- 上传提交事务会重新检查会话、目标、空间状态、配额和 ready 内容对象，并原子更新版本号、当前版本、引用计数、空间用量、上传结果、幂等结果和审计记录。
- Compose 为 API 挂载独立的 JWT、CSRF、确认令牌密钥；三个密钥继续由现有初始化脚本随机生成。
- 增加 PostgreSQL 后端单元/契约测试，覆盖 Argon2id、令牌算法与过期、CSRF 会话绑定、幂等键格式、名称规范化和 ORM 表映射。

## 验证结果

- `ruff check backend/app backend/tests`：通过。
- `pytest -q`：19 个测试通过，5 个真实依赖集成测试按设计跳过。
- FastAPI OpenAPI 构建：通过，共注册 30 条 API 路径。
- 首次迁移与文档 DDL 一致性测试：通过，仍为 22 张表。

## 联调说明

- 本机未安装 Docker，因此本次没有启动 PostgreSQL 17 / MinIO 容器；需要在具备 Docker 的环境运行 `scripts/init.ps1` 后，再设置 `FM_INTEGRATION_TESTS=1` 执行真实账号权限、迁移和 Bucket 集成测试。
- 上传二进制、MinIO 对象发布和下载流由 MinIO 负责人实现；其 Service 应使用同一个 pinned connection 调用 `DatabaseContractService`，并遵守 `contracts.py` 的锁与事务边界。
- 标签、自定义元数据、完整用户管理、目录移动/删除、保留策略和物理清理 HTTP 编排属于契约标记的延期功能，本次没有注册伪成功接口。
- 元数据修改端点强制校验 `Idempotency-Key`；上传最终提交和通用元数据写操作均原子写入幂等结果。

## 2026-10-07 补充开发

- 新增统一幂等 Repository，按 actor 与幂等键获取 advisory lock，并对 HTTP 方法、完整路径和规范化请求体计算 SHA-256 指纹。
- 空间、成员、目录、文件元数据、软删除/恢复和历史版本恢复已将业务变更、成功审计与结果快照放入同一事务。
- 相同键、相同请求返回首次结果并设置 `Idempotency-Replayed: true`；相同键用于不同方法、路径或请求体时返回 `IDEMPOTENCY_CONFLICT`。
- 重放前仍重新执行当前账号、空间和资源权限检查，不会在权限撤销后直接返回旧成功结果。
- 更新 README 的实现状态，移除骨架阶段“认证、搜索、版本均未实现”的过期说明。
- 新增 PostgreSQL 真实集成用例，验证 advisory lock、JSONB 结果快照、成功重放和请求指纹冲突；本地无 Docker 时按既有开关跳过。
- 本轮回归：`ruff` 通过，`pytest` 为 22 项通过、6 项真实依赖测试跳过，OpenAPI 仍为 30 条路径。
