# MinIO 对象规则

版本：1.0；状态：开发契约，未启动存储服务；适用：单机、私有Bucket、FastAPI同步编排。

关联文档：[架构](文件管理系统技术架构文档.md)、[表结构](PostgreSQL表结构设计.md)、[API](前后端接口定义.md)。MinIO镜像由部署负责人固定到具体版本/摘要，不使用浮动latest；上线前验证SDK、multipart和复制行为。

## 1. 权威边界和交付范围

- MinIO保存字节，PostgreSQL保存业务身份、所有权、权限、版本、状态、上传进度和对象引用。
- 前端只调用FastAPI，不接触MinIO凭据、内部multipart ID、Bucket、object_key或预签名地址。
- **MVP**：私有Bucket、上传续传、校验、内容去重、版本/下载、临时清理、备份与恢复记录。
- **后续**：管理员物理清理、一致性维护界面、完整保留策略管理。未实现时不能绕过保留检查删除正式内容。
- 所有新内容必须实际上传并由服务端校验，无秒传、无哈希探测API。客户端声称已有内容不能成为下载或对象引用依据。

## 2. Bucket、对象键和权限

### 2.1 Bucket

| Bucket | 内容 | 自动生命周期规则 |
| --- | --- | --- |
| uploads | 小文件临时对象、multipart会话完成后的临时对象 | 默认不启用按年龄删除，由数据库状态驱动清理 |
| contents | 正式不可变内容，一份可被多个文件版本引用 | 禁止按年龄自动过期，必须检查实际引用 |
| backups | 数据库备份、对象清单、清单校验文件 | 由备份保留命令清理，默认保留30天 |

三个Bucket均禁止匿名列举、读取和写入。存储层versioning默认关闭，应用版本由file_versions管理；不得将此等同于备份。法律保留由业务Service检查，首期不把Object Lock当作业务冻结的实现。

### 2.2 对象键

Bucket与key为两个参数，key**不重复包含Bucket名称**：

| Bucket | object_key格式 | 生成方 |
| --- | --- | --- |
| uploads | `{user_id}/{upload_id}/{random_uuid}` | Upload Service创建会话时 |
| contents | `{sha256前2位}/{sha256}/{size}/{write_uuid}` | Object Service每次新写入尝试前 |
| backups | `{yyyy}/{mm}/{dd}/{backup_run_id}/{artifact_name}` | 受控备份命令 |

`sha256`为64位小写十六进制，`size`为十进制字节数，UUID为小写标准字符串；时间目录为UTC。临时对象键不能由用户文件名、目录名、用户提交的路径拼接。

例如：Bucket为`contents`，key为`aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/1234/70000000-0000-4000-8000-000000000001`。这是元数据格式示例，不表示存在实际对应文件。

随机write_uuid解决迟到写入/删除与新重试之间的隔离；全局去重通过数据库 `(sha256,size)` 唯一约束实现，不依赖确定性对象键。正式ready对象的键永不改变。staging且零引用时，失败重试可以分配新的key；旧尝试键进入孤立对象核对，不能因“数据库里没有”立即删除。

### 2.3 凭据和内部元数据

- bootstrap凭据仅创建Bucket、账号和策略，API不得使用root凭据。
- 业务账号仅访问uploads和contents；备份账号使用单独凭据，可读contents并读写backups及异地目标；凭据通过Docker secrets加载。
- 对象内部元数据允许：`sha256`、`size`、`producer-upload-id`、`write-id`、`created-at`；不得写入用户JWT、密码、目录权限或敏感自定义字段。
- 正式对象Content-Type由确认MIME设置，下载时再次由API设置安全响应头。
- 存储网络不公开9000/9001；不允许任意对象键操作API。

## 3. 上传协议

### 3.1 默认参数

| 参数 | 默认 | 生效范围 |
| --- | --- | --- |
| max_file_bytes | 1 GiB = 1073741824 | 创建与最终提交均检查 |
| multipart_threshold_bytes | 5 MiB = 5242880 | 大于此值用multipart |
| part_size_bytes | 8 MiB = 8388608，可配8–32 MiB | 创建时快照，不中途修改 |
| upload_concurrency | 4个文件 | 同文件分片顺序发送，不并发 |
| upload_ttl_seconds | 86400（24小时） | 创建时快照，不因续传滑动延长 |
| complete_timeout_seconds | 600 | 单次完成请求的总预算 |

分片总数：small为1；multipart为 `ceil(expected_size/part_size)`，最多10000。非末片必须等于part_size，末片为剩余长度。零字节文件采用single、一个0字节分片，不调用multipart。

### 3.2 创建上传

1. 客户端通过Worker中的增量哈希实现计算expected_sha256，不能为了哈希把大文件一次读入内存；用户选中文件后先显示“准备中”。
2. `POST /api/uploads` 提交原文件名、大小、哈希、声明MIME、space_id、directory_id、可选target_file_id和批次。
3. Service校验账号会话、空间、目录、所有权、策略和当前配额。这里只预检查，不预扣配额，多个上传可以暂时超额排队，最终提交串行校验。
4. 创建uploads记录和随机临时键。multipart ID在首次分片前持upload锁懒初始化并存库，不返回前端。初始化存储成功但存库失败的悬挂会话通过维护核对发现。
5. 返回公共Upload DTO：upload_id、状态、期限、storage_method、分片大小/数量及已确认分片，不返回内部存储参数。

target_file_id为空表示新逻辑文件；非空表示追加该文件版本。新版本的space/directory从文件获取并核对输入，上传者不能更改owner。同名文件不合并。

### 3.3 分片与续传

- `PUT /api/uploads/{upload_id}/parts/{part_no}` 使用 `application/octet-stream`、准确Content-Length及`X-Part-SHA256`；仍需Cookie、CSRF和Origin校验。
- Service持upload session锁，重新鉴权，检查会话未过期和状态可接收，再检查分片编号与预期长度。
- 单次只缓冲当前分片，最大32 MiB；边读边计算SHA-256。在写入MinIO之前验证分片长度与哈希，避免错误重传覆盖已经确认的分片。API不缓存完整文件。
- single使用PutObject写临时键；multipart使用UploadPart，保存MinIO返回的原始ETag（含SDK需要的格式）及真实checksum。
- 确认分片记录在存储成功后提交。存储成功但数据库失败时，同一正确分片可重复写入并补记录，不算完成上传。
- 相同part_no、size、checksum已confirmed时返回原结果；不同校验值返回PART_MISMATCH，不替换已确认分片。
- 仅确认全部分片后状态为uploaded；此时checkpoint仍为receiving，表示等待组装与全文件验证。
- `GET /api/uploads/{id}`或`/parts`提供数据库已确认列表。前端重新选中文件后核对大小和全文件哈希，只补传缺失部分。
- ETag是存储协议结果，不当作全文件或分片SHA-256；SHA-256来自服务端实际读到的字节。

multipart完成需要完整的part_no和ETag列表；失败或取消需要AbortMultipartUpload，未完成会话不是普通对象，不能仅靠RemoveObject清理。[S3 multipart流程参考](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html)

### 3.4 完成上传

`POST /api/uploads/{id}/complete`按以下检查点运行，每个检查点独立短事务落库；存储网络操作不夹在配额/文件行锁事务中：

| checkpoint | 操作 | 崩溃/重试方式 |
| --- | --- | --- |
| receiving | 核对全部分片；multipart Complete或single HEAD | Complete响应丢失先HEAD临时键，已存在则验证；不存在且会话有效则重试 |
| assembled | GetObject流式重算大小和全文件SHA-256，探测MIME | 从完整临时对象重新读，不根据ETag猜测成功 |
| verified | 获取content锁，准备/复用正式内容 | 依据数据库对象状态和HEAD/内容校验恢复 |
| object_ready | 最终数据库事务提交文件、版本、引用、配额 | 再鉴权及检查配额，不重复写ready内容 |
| committed | 返回首次FileCommit，尝试清理临时对象 | 重试先读取result_snapshot，再重新授权；不再提交版本 |

总时限到达返回OPERATION_TIMEOUT并保存已完成检查点。重试在原expires_at前继续，不建立异步任务。若超出期限，未提交会话进入expired并由受控命令清理；已committed结果不因上传期限到达消失。

大小、全文件哈希不一致或类型策略拒绝：status=failed，不形成版本。存储暂时故障、最终配额不足：保留uploaded及last_error_code，可在有效期内重试。原文件/目标权限变化则最终事务拒绝，不能沿用创建会话时的授权结果。

## 4. 正式对象、去重和并发

### 4.1 新对象准备

1. 在持content session锁时按sha256+size查询content_objects。
2. ready且存在有效对象：校验记录与HEAD大小一致，复用，不返回是否“别人已上传”的额外信息。
3. deleting：返回OPERATION_IN_PROGRESS，不增加引用，也不由上传请求接管旧清理；受控清理完成后重试才能准备新对象。
4. 无记录：先短事务创建staging零引用行和随机候选key；有staging则检查候选。候选已经存在时流式验证后可复用；不存在或验证失败则分配新的write_uuid并更新staging key及producer_upload_id。
5. 将已验证临时内容服务端CopyObject到新候选键；SDK不存在“move”原子操作，复制与删除分开执行。写入尝试从不覆盖ready键。
6. HEAD核对大小，再流式复核候选SHA-256。成功短事务标记ready，上传checkpoint=object_ready。
7. 在最终数据库事务中增加引用、提交版本与配额；成功后只清理临时对象。

同hash+size出现内容不一致视为严重存储校验失败，不复用且告警。随机候选键若HEAD已经存在却不是本尝试对象，另生成键，不覆盖。

### 4.2 并发和锁失效

content锁定义、顺序见表结构文档。上传/复制/恢复/清理/维护全使用相同锁。只靠唯一约束或先查后写不够保护对象删除。

- 迟到CopyObject最多产生旧候选孤立对象，不会覆盖后来ready键。
- 旧清理请求最多删除旧write_uuid键，不能按哈希删除新候选。
- 专用数据库连接丢失时立即停止编排，不提交版本、不假定锁仍有效。新请求核对候选和检查点后恢复。
- 数据库最终事务失败时，ready零引用对象可供后续验证后复用，不立即“回滚删除”。任何删除都必须持content锁并检查状态和实际版本引用。
- 发现对象缺失但数据库有引用时不删除版本、不降低引用计数，返回STORAGE_UNAVAILABLE并告警，由备份恢复。

## 5. 下载和版本

- 下载必须先验证账号、sid、token_version、空间权限、文件active状态、version_id属于file_id及content ready。
- `GET /api/files/{file_id}/versions/{version_id}/download`流式返回内容，不返回JSON包装或预签名链接。
- 响应设置Content-Type、Content-Length、Content-Disposition attachment、nosniff、Cache-Control private/no-store、X-File-SHA256和X-File-Version。
- MVP支持单段Range，格式和416行为见API文档；多段Range不支持。下载记录开始/完成/中断事件，不伪称中断为成功。
- 对象响应句柄在finally关闭并释放连接；客户端中断时停止读取。
- 新版本内容可为任意允许格式，不建立不同类型处理链路；current指针只在版本事务中更新。
- 历史恢复创建新版本、增加引用和配额，来源version_id写入restored_from_version_id，不复制对象字节。
- 改名、移动、标签变化不修改对象键；软删除不删除对象、不释放配额。

## 6. 清理、一致性维护和保留

### 6.1 临时对象与过期上传

管理员受控命令扫描数据库created/uploading/uploaded且已过期的会话，逐个尝试upload锁，锁不到跳过；再次检查状态并标记expired。multipart执行Abort，再删除临时完整对象；成功写temp_cleaned_at。失败保留记录与错误，允许下一次命令重试。

committed且temp_cleaned_at为空的会话同样可清临时对象，不能删除正式内容。failed/expired计入批次failed_count，只在首次终态转移计数。

默认不用Bucket年龄规则清理临时内容，避免误删仍在活动的会话；如部署启用自动abort悬挂multipart，期限必须大于上传TTL加安全余量，且先验证与SDK重试兼容。

### 6.2 正式对象物理清理（后续）

数据库detach和对象删除检查点严格遵循表结构文档。管理员需要二次确认、deleted文件、全部版本保留期到期且legal_hold=false。

每次删除前在content锁内重新核对：content_object_id、bucket、object_key、sha256、size与item快照相同，status=deleting，reference_count=0，实际版本引用=0。不相同或出现新引用时拒绝删除、记录一致性错误。对象404视为已删；存储403/5xx不是成功。

同哈希新对象的UUID/键与旧快照不同；重试不得删新对象。文件detach已提交后不重复扣减引用/配额；文件已不存在时通过cleanup_attempt_id继续重试，不重新创建清理。

若旧content_object_id已经不存在，HEAD旧快照键：404则直接标记item deleted；旧键仍存在时，在content锁下确认没有任何content_objects行引用此键后只删除旧键。不得把同哈希的新对象当成旧对象，更不能删除新对象行；旧ID存在但描述不匹配属于CONSISTENCY_ERROR。

### 6.3 孤立对象核对

受控命令先只读生成核对清单：

- 引用存在而对象缺失：告警并恢复，不删数据库业务记录。
- ready零引用或staging长时间未完成：content锁下查producer上传和所有版本，活动上传未过期则跳过。
- Bucket中无当前记录的候选对象：核对write-id、producer-upload-id、所有对象行及cleanup快照，至少晚于24小时安全余量，且关联上传已终态/过期；第一次只列出，管理员再次确认清单后删除。
- 不认识的对象、缺少内部元数据、时间无法确认：人工处理，不自动删除。

维护清单不是永久删除授权，执行时必须重新检查。内容对象的业务引用以file_versions为准，冗余计数异常先修复/告警，不单凭计数删除。

## 7. 备份与恢复

- backups是本地备份中转，不是contents灾难恢复的唯一副本；必须复制到异地S3兼容存储，凭据独立。
- 同步备份命令进入维护写屏障：API健康仍可读，业务修改返回MAINTENANCE_MODE；既有上传完成、清理、配置修改和版本事务全部排空后开始。退出/安全撤销允许继续，但不能改变文件引用。维护状态由部署命令控制并在finally解除，不设置后台任务。
- 获取全局backup session锁，执行pg_dump自定义格式、列举数据库引用对象并复制/验证、生成manifest和manifest.sha256、上传异地，更新backup_runs。
- manifest包含backup_run_id、UTC时间、数据库产物、每个引用对象的bucket/key/size/sha256、配置归档描述；不包含未加密密钥或密码。
- 对象备份可增量复用已经校验的不可变键，但清单必须完整。对全部产物记录哈希和大小；异地校验成功才标记completed。
- 配置与密钥另行加密归档，不写明文到backups。执行失败标记failed、不覆盖最近成功备份。
- 保留默认30天；清理前保护最近成功且完整的恢复点、法律保留及演练所需快照。
- 恢复在隔离环境：配置密钥 → 引用对象 → PostgreSQL → API/Nginx → 引用核对 → 登录/上传/下载/版本/搜索冒烟。
- 不从文件内容重建用户权限、逻辑目录或版本历史。恢复后实际流式校验对象SHA-256，而非把ETag当完整性证明。
- 隔离恢复后先撤销全部历史会话并递增token_version；未提交上传因临时内容不在恢复清单中统一标记failed/RESTORE_INTERRUPTED；快照中running备份标记failed/RESTORE_INTERRUPTED，并以恢复manifest记录本次恢复来源。必须用新登录执行冒烟测试。

## 8. 内部方法契约与人员对接

方法名为协作边界建议，不是额外HTTP服务。数据库方法接受Service传入的connection/transaction，不自行commit。

| 方法 | 输入 | 结果 | 主负责人 |
| --- | --- | --- | --- |
| authorize_upload | actor/session、space/directory、可选target_file_id、大小 | 允许的目标与策略快照或业务异常 | PostgreSQL |
| create_upload_record | 规范化请求、幂等指纹、临时key、分片方案 | Upload内部记录 | PostgreSQL |
| confirm_part | upload_id、part_no、真实size/checksum/etag | 已确认分片、是否全部齐全 | PostgreSQL |
| get_upload_resume | actor/session、upload_id | 公共Upload及confirmed parts | PostgreSQL |
| prepare_content_record | sha256、size、候选key、producer_upload_id | staging/ready/deleting对象 | PostgreSQL |
| mark_object_ready | object_id、已校验候选描述 | ready对象记录 | PostgreSQL |
| commit_upload | actor/session、upload_id、ready object、request_id/idem id | FileCommit，首次结果快照 | PostgreSQL提供事务方法，MinIO编排 |
| authorize_download | actor/session、file_id、version_id | 内部对象描述与公共版本头 | PostgreSQL |
| detach_file | actor、file_id、confirmation、attempt/items | 已提交清理检查点 | PostgreSQL（后续） |
| finalize_cleanup_item | attempt/item、删除结果 | item状态与完成汇总 | PostgreSQL（后续） |
| put_part / assemble_temp | 内部upload、已验证分片 / 完整ETag列表 | 存储ETag / 临时对象描述 | MinIO |
| verify_temp / prepare_content | 内部对象描述 | 实测大小、SHA-256、MIME / ready候选 | MinIO |
| stream_download / remove_object | 已授权对象描述、Range / 精确候选描述 | 字节流 / 存储删除结果 | MinIO |

补偿归属：存储失败由MinIO负责人编排重试与记录；数据库一致性由PostgreSQL负责人提供原子方法；Nginx负责人验证代理、超时及维护命令；前端仅按公开状态重试，不自行操作对象。

## 9. 验收清单和验证状态

| 场景 | 预期 | 阶段 |
| --- | --- | --- |
| 0字节/小文件/跨阈值文件 | 分片方案、哈希、下载一致 | MVP |
| 分片响应丢失与续传 | 相同分片返回原结果，不同哈希拒绝 | MVP |
| Complete响应丢失 | HEAD确认临时对象，最终只提交一个版本 | MVP |
| 同内容并发上传 | 独立文件、一个ready内容记录、正确引用计数 | MVP |
| 事务失败后另一个上传引用 | 不回滚删除共享对象 | MVP |
| 数据库连接断开与迟到复制 | 不覆盖新ready键，孤立候选可核对 | MVP |
| 账号冻结、空间权限撤销 | 完成/下载阶段重新拒绝 | MVP |
| 上传过期 | 不再接收或完成；临时会话可清理 | MVP |
| 下载中断、Range | 句柄释放，字节范围与响应头正确 | MVP |
| 清理与同哈希重传竞争 | 旧item不删新对象，计数不重复扣减 | 后续 |
| 备份后物理删除、隔离恢复 | 备份恢复点内容与元数据一致 | MVP |

**验证状态**：只定义协议和进行文档静态检查，尚未连接MinIO执行上述用例。部署负责人必须验证固定镜像及客户端SDK的Put/Get/Copy/Multipart/Abort/Range和错误语义；不依赖未验证的目的对象条件复制特性。

## 10. 参考

- [S3 multipart上传概述](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html)：完成、分片ETag及中止会话的协议依据。
- [MinIO开发者文档](https://docs.min.io/aistor/developers/)：部署所选发行版及SDK以对应版本文档为准，不能把S3所有扩展特性默认视为已支持。
