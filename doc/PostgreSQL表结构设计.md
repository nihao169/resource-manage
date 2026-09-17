# PostgreSQL 表结构设计

版本：1.0；基线：PostgreSQL 17；状态：开发契约，尚未实际建库。

关联文档：[架构](文件管理系统技术架构文档.md)、[对象规则](MinIO对象规则.md)、[API](前后端接口定义.md)。三份契约同版本生效，DDL 为类型、空值和默认值的最终依据。

## 1. 范围、约定与责任

- **MVP**：认证权限、空间目录、文件上传续传、元数据搜索、版本、回收站、审计、基础配置及备份记录。
- **后续**：完整标签、自定义字段、移动复制、保留策略管理、物理清理和高级管理界面。后续表一并设计，但未实现时不得开放对应接口。
- PostgreSQL负责人维护全部迁移和 Repository；MinIO负责人维护文件生命周期 Service；事务在 Service 开启与提交，存储适配器不提交数据库事务。
- 所有 ID 为 UUID；时间为 `timestamptz`，会话时区为 UTC；大小、配额为字节；金额类数值不存在。
- `id` 默认 `gen_random_uuid()`；用户名和目录/标签名称采用 `lower()` 唯一策略，不擅自裁剪用户输入。名称入库前 NFC 归一化、去除首尾空白，禁止控制字符。
- 根目录用 `directory_id=NULL` 表示，不建立伪根目录记录。同目录允许同名文件，文件由 ID 区分，上传不会自动覆盖同名文件。
- 全部现存版本（包括回收站）计入 `used_bytes`，只有物理清理才释放配额。去重不减少逻辑配额；新版本及历史恢复均增加配额。
- 正式内容为全局物理去重，业务权限始终针对逻辑文件。无秒传、无全局哈希查询。
- 本文的注释DDL同时是逐字段数据字典；`NOT NULL` 表示必填，没有 `DEFAULT` 表示由 Service 显式写入。

## 2. 表与关系

```text
users ── refresh_sessions / space_members
spaces ── directories ── files ── file_versions ── content_objects
                          │         └── restored_from_version_id（同文件历史版本）
                          ├── file_tags ── tags
                          └── file_metadata_values ── metadata_fields
upload_batches ── uploads ── upload_parts
idempotency_requests ── files / file_versions / confirmation_tokens（提交关联）
confirmation_tokens ── cleanup_attempts ── cleanup_items（历史快照，不随对象删除）
audit_events / backup_runs / system_settings
```

| 表 | 用途 | 交付阶段 |
| --- | --- | --- |
| users、refresh_sessions | 账号、可撤销会话 | MVP |
| spaces、space_members、directories | 空间、成员、逻辑目录 | MVP |
| files、file_versions、content_objects | 逻辑文件、不可变版本、物理引用 | MVP |
| upload_batches、uploads、upload_parts | 批次、上传状态、续传凭据 | MVP |
| idempotency_requests | 请求指纹和原子提交结果 | MVP |
| system_settings、audit_events、backup_runs | 配置、审计、备份清单 | MVP |
| tags、file_tags | 标签关联 | 后续 |
| metadata_fields、file_metadata_values | 类型化自定义元数据 | 后续 |
| confirmation_tokens、cleanup_attempts、cleanup_items | 二次确认、清理检查点 | 后续 |

`files.current_version_id` 与版本形成循环关联：先建文件表和版本表，再添加可延迟外键。历史目标的 UUID 快照不建立外键，避免被物理删除后丢失审计和重试信息。

## 3. 完整初始化 DDL 与字段字典

以下一个SQL块可在空数据库中按顺序执行；只能由迁移账号执行，不能直接覆盖已有数据库。DDL 不创建默认密码、运行任务或操作 MinIO。`pg_trgm` 需要部署环境允许安装该扩展。

```sql
BEGIN;
SET LOCAL TIME ZONE 'UTC';
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 账号：禁止物理删除，停用使用 status。
CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), -- 账号编号
  username varchar(64) NOT NULL CHECK (length(btrim(username)) BETWEEN 3 AND 64),
  display_name varchar(100) NOT NULL, -- 展示名称
  password_hash text NOT NULL, -- Argon2id 编码串，绝不保存明文
  role varchar(10) NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
  status varchar(12) NOT NULL DEFAULT 'active' CHECK (status IN ('active','frozen','disabled')),
  token_version integer NOT NULL DEFAULT 0 CHECK (token_version >= 0),
  must_change_password boolean NOT NULL DEFAULT false,
  password_changed_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_users_username ON users (lower(username));
CREATE INDEX ix_users_status ON users (status, id);

-- 会话：access JWT 的 sid 指向 id；退出立即撤销此行。
CREATE TABLE refresh_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  token_hash varchar(64) NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  token_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(), -- 每次刷新轮换
  expires_at timestamptz NOT NULL, -- 登录时起7天，不滑动延长
  revoked_at timestamptz,
  last_used_at timestamptz NOT NULL DEFAULT now(),
  user_agent varchar(512), -- 截断并脱敏
  source_ip inet,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (expires_at > created_at)
);
CREATE INDEX ix_sessions_user ON refresh_sessions(user_id, expires_at) WHERE revoked_at IS NULL;

CREATE TABLE spaces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name varchar(100) NOT NULL CHECK (length(btrim(name)) > 0),
  quota_bytes bigint NOT NULL DEFAULT 10737418240 CHECK (quota_bytes BETWEEN 0 AND 9007199254740991),
  used_bytes bigint NOT NULL DEFAULT 0 CHECK (used_bytes >= 0),
  status varchar(12) NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  created_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (used_bytes <= quota_bytes)
);
CREATE UNIQUE INDEX uq_spaces_name ON spaces(lower(name)) WHERE status='active';

CREATE TABLE space_members (
  space_id uuid NOT NULL REFERENCES spaces(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  status varchar(12) NOT NULL DEFAULT 'active' CHECK (status IN ('active','removed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(space_id,user_id)
);
CREATE INDEX ix_members_user ON space_members(user_id,space_id) WHERE status='active';

CREATE TABLE directories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES spaces(id) ON DELETE RESTRICT,
  parent_id uuid, -- NULL 表示空间根层
  name varchar(100) NOT NULL CHECK (length(btrim(name)) > 0),
  path_key text NOT NULL, -- /祖先UUID/自身UUID/，不是对象存储路径
  status varchar(12) NOT NULL DEFAULT 'active' CHECK (status IN ('active','deleted')),
  created_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(space_id,id),
  UNIQUE(space_id,path_key),
  FOREIGN KEY(space_id,parent_id) REFERENCES directories(space_id,id) ON DELETE RESTRICT,
  CHECK (parent_id IS NULL OR parent_id <> id)
);
CREATE UNIQUE INDEX uq_directory_sibling ON directories(space_id,parent_id,lower(name))
  NULLS NOT DISTINCT WHERE status='active';
CREATE INDEX ix_directory_parent ON directories(space_id,parent_id) WHERE status='active';

CREATE TABLE idempotency_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  idempotency_key varchar(128) NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
  method varchar(6) NOT NULL CHECK (method IN ('POST','PUT','PATCH','DELETE')),
  path varchar(512) NOT NULL, -- 规范化完整API路径（含实际UUID）
  request_hash varchar(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  status varchar(12) NOT NULL DEFAULT 'processing' CHECK (status IN ('processing','completed')),
  http_status smallint CHECK (http_status BETWEEN 200 AND 599),
  response_data jsonb, -- 脱敏后的data，不保存Cookie、密码或确认令牌原文
  result_target_type varchar(32),
  result_target_id uuid, -- 结果目标快照，无外键
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL DEFAULT (now()+interval '7 days'),
  completed_at timestamptz,
  UNIQUE(actor_id,idempotency_key),
  CHECK (expires_at > created_at),
  CHECK ((status='processing' AND completed_at IS NULL) OR
         (status='completed' AND completed_at IS NOT NULL AND http_status IS NOT NULL AND response_data IS NOT NULL))
);
CREATE INDEX ix_idempotency_expiry ON idempotency_requests(expires_at);

-- staging 表示对象准备中；ready 才允许新版本引用；deleting 禁止增加引用。
CREATE TABLE content_objects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bucket varchar(63) NOT NULL DEFAULT 'contents' CHECK (bucket='contents'),
  object_key varchar(256) NOT NULL, -- hash前两位/hash/size/随机写入UUID，不含Bucket
  size bigint NOT NULL CHECK (size BETWEEN 0 AND 9007199254740991),
  sha256 varchar(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  reference_count bigint NOT NULL DEFAULT 0 CHECK (reference_count >= 0),
  status varchar(12) NOT NULL DEFAULT 'staging' CHECK (status IN ('staging','ready','deleting')),
  producer_upload_id uuid, -- 来源上传UUID快照，不用于授权
  last_error_code varchar(64),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(sha256,size),
  UNIQUE(bucket,object_key),
  CHECK (status='ready' OR reference_count=0)
);
CREATE INDEX ix_objects_state ON content_objects(status,updated_at);

CREATE TABLE files (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES spaces(id) ON DELETE RESTRICT,
  directory_id uuid,
  owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  name varchar(255) NOT NULL CHECK (length(btrim(name)) > 0),
  description varchar(2000) NOT NULL DEFAULT '',
  current_version_id uuid, -- 延迟外键在版本表之后创建
  status varchar(12) NOT NULL DEFAULT 'active' CHECK (status IN ('active','deleted')),
  deleted_at timestamptz,
  deleted_by uuid REFERENCES users(id) ON DELETE RESTRICT,
  creation_request_id uuid UNIQUE REFERENCES idempotency_requests(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(space_id,id),
  FOREIGN KEY(space_id,directory_id) REFERENCES directories(space_id,id) ON DELETE RESTRICT,
  CHECK ((status='active' AND deleted_at IS NULL AND deleted_by IS NULL) OR
         (status='deleted' AND deleted_at IS NOT NULL AND deleted_by IS NOT NULL))
);
CREATE INDEX ix_files_list ON files(space_id,status,updated_at DESC,id);
CREATE INDEX ix_files_directory ON files(space_id,directory_id,status);
CREATE INDEX ix_files_owner ON files(owner_id,status,updated_at DESC);
CREATE INDEX ix_files_name_trgm ON files USING gin(lower(name) gin_trgm_ops) WHERE status='active';
CREATE INDEX ix_files_desc_trgm ON files USING gin(lower(description) gin_trgm_ops) WHERE status='active';

CREATE TABLE file_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  file_id uuid NOT NULL REFERENCES files(id) ON DELETE RESTRICT,
  version_no integer NOT NULL CHECK (version_no > 0),
  version_note varchar(1000) NOT NULL DEFAULT '',
  original_name varchar(255) NOT NULL, -- 本次上传文件名快照
  extension varchar(32) NOT NULL DEFAULT '', -- 小写、不含点；格式筛选依据
  content_object_id uuid NOT NULL REFERENCES content_objects(id) ON DELETE RESTRICT,
  size bigint NOT NULL CHECK (size BETWEEN 0 AND 9007199254740991),
  sha256 varchar(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  mime varchar(127) NOT NULL,
  retained_until timestamptz,
  legal_hold boolean NOT NULL DEFAULT false,
  restored_from_version_id uuid,
  created_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  creation_request_id uuid UNIQUE REFERENCES idempotency_requests(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(file_id,version_no),
  UNIQUE(file_id,id),
  FOREIGN KEY(file_id,restored_from_version_id) REFERENCES file_versions(file_id,id)
    DEFERRABLE INITIALLY DEFERRED,
  CHECK (restored_from_version_id IS NULL OR restored_from_version_id<>id)
);
ALTER TABLE files ADD CONSTRAINT fk_file_current_version
  FOREIGN KEY(id,current_version_id) REFERENCES file_versions(file_id,id)
  DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX ix_versions_object ON file_versions(content_object_id);
CREATE INDEX ix_versions_creator ON file_versions(created_by,created_at DESC);
CREATE INDEX ix_versions_format ON file_versions(mime,extension);

CREATE TABLE tags (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES spaces(id) ON DELETE RESTRICT,
  name varchar(64) NOT NULL CHECK (length(btrim(name))>0),
  status varchar(12) NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  created_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(space_id,id)
);
CREATE UNIQUE INDEX uq_tag_name ON tags(space_id,lower(name)) WHERE status='active';
CREATE TABLE file_tags (
  space_id uuid NOT NULL,
  file_id uuid NOT NULL,
  tag_id uuid NOT NULL,
  created_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(file_id,tag_id),
  FOREIGN KEY(space_id,file_id) REFERENCES files(space_id,id) ON DELETE CASCADE,
  FOREIGN KEY(space_id,tag_id) REFERENCES tags(space_id,id) ON DELETE RESTRICT
);
CREATE INDEX ix_file_tags_reverse ON file_tags(tag_id,file_id);

CREATE TABLE metadata_fields (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES spaces(id) ON DELETE RESTRICT,
  name varchar(64) NOT NULL CHECK (length(btrim(name))>0),
  value_type varchar(10) NOT NULL CHECK (value_type IN ('text','number','date','boolean')),
  required boolean NOT NULL DEFAULT false,
  status varchar(12) NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  created_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(space_id,id,value_type)
);
CREATE UNIQUE INDEX uq_field_name ON metadata_fields(space_id,lower(name)) WHERE status='active';
CREATE TABLE file_metadata_values (
  space_id uuid NOT NULL,
  file_id uuid NOT NULL,
  field_id uuid NOT NULL,
  value_type varchar(10) NOT NULL,
  value_text varchar(2000),
  value_number numeric(20,6),
  value_date date,
  value_boolean boolean,
  updated_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(file_id,field_id),
  FOREIGN KEY(space_id,file_id) REFERENCES files(space_id,id) ON DELETE CASCADE,
  FOREIGN KEY(space_id,field_id,value_type) REFERENCES metadata_fields(space_id,id,value_type) ON DELETE RESTRICT,
  CHECK (
    (value_type='text' AND value_text IS NOT NULL AND value_number IS NULL AND value_date IS NULL AND value_boolean IS NULL) OR
    (value_type='number' AND value_number IS NOT NULL AND value_text IS NULL AND value_date IS NULL AND value_boolean IS NULL) OR
    (value_type='date' AND value_date IS NOT NULL AND value_text IS NULL AND value_number IS NULL AND value_boolean IS NULL) OR
    (value_type='boolean' AND value_boolean IS NOT NULL AND value_text IS NULL AND value_number IS NULL AND value_date IS NULL)
  )
);
CREATE INDEX ix_metadata_number ON file_metadata_values(field_id,value_number) WHERE value_type='number';
CREATE INDEX ix_metadata_date ON file_metadata_values(field_id,value_date) WHERE value_type='date';
CREATE INDEX ix_metadata_bool ON file_metadata_values(field_id,value_boolean) WHERE value_type='boolean';

CREATE TABLE upload_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  total_count integer NOT NULL CHECK (total_count BETWEEN 1 AND 100), -- 本批选择数量
  completed_count integer NOT NULL DEFAULT 0 CHECK (completed_count>=0),
  failed_count integer NOT NULL DEFAULT 0 CHECK (failed_count>=0),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (completed_count+failed_count<=total_count)
);
CREATE TABLE uploads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id uuid REFERENCES upload_batches(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  space_id uuid NOT NULL REFERENCES spaces(id) ON DELETE RESTRICT,
  directory_id uuid,
  target_file_id uuid, -- 新版本目标UUID快照；有意不加FK，保留清理后的历史
  mode varchar(12) NOT NULL CHECK (mode IN ('new_file','new_version')),
  original_name varchar(255) NOT NULL,
  description varchar(2000) NOT NULL DEFAULT '',
  version_note varchar(1000) NOT NULL DEFAULT '',
  tag_ids uuid[] NOT NULL DEFAULT '{}'::uuid[] CHECK (cardinality(tag_ids)<=20), -- 后续：同空间有效标签
  metadata_values jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(metadata_values)='array' AND jsonb_array_length(metadata_values)<=50), -- 后续：类型化值快照
  expected_size bigint NOT NULL CHECK (expected_size BETWEEN 0 AND 9007199254740991),
  actual_size bigint CHECK (actual_size>=0),
  expected_sha256 varchar(64) NOT NULL CHECK (expected_sha256 ~ '^[0-9a-f]{64}$'),
  actual_sha256 varchar(64) CHECK (actual_sha256 ~ '^[0-9a-f]{64}$'),
  mime varchar(127) NOT NULL, -- 服务端探测前为声明MIME，探测后存确认MIME
  storage_method varchar(12) NOT NULL CHECK (storage_method IN ('single','multipart')),
  part_size integer NOT NULL CHECK (part_size BETWEEN 8388608 AND 33554432),
  part_count integer NOT NULL CHECK (part_count BETWEEN 1 AND 10000),
  minio_upload_id text, -- multipart句柄，不能返回前端
  temp_object_key varchar(256) NOT NULL,
  status varchar(12) NOT NULL DEFAULT 'created' CHECK (status IN ('created','uploading','uploaded','committed','failed','expired')),
  checkpoint varchar(16) NOT NULL DEFAULT 'receiving' CHECK (checkpoint IN ('receiving','assembled','verified','object_ready','committed')),
  last_error_code varchar(64),
  expires_at timestamptz NOT NULL DEFAULT (now()+interval '24 hours'),
  idempotency_key varchar(128) NOT NULL,
  request_hash varchar(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  result_file_id uuid, -- 提交结果快照，文件清理后仍保留
  result_version_id uuid,
  result_snapshot jsonb, -- 仅公共FileCommit DTO
  temp_cleaned_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(user_id,idempotency_key),
  UNIQUE(temp_object_key),
  FOREIGN KEY(space_id,directory_id) REFERENCES directories(space_id,id) ON DELETE RESTRICT,
  CHECK ((mode='new_file' AND target_file_id IS NULL) OR (mode='new_version' AND target_file_id IS NOT NULL)),
  CHECK ((storage_method='single' AND part_count=1) OR storage_method='multipart'),
  CHECK (expires_at>created_at),
  CHECK (status<>'committed' OR (checkpoint='committed' AND result_file_id IS NOT NULL
         AND result_version_id IS NOT NULL AND result_snapshot IS NOT NULL))
);
CREATE INDEX ix_uploads_owner ON uploads(user_id,status,created_at DESC);
CREATE INDEX ix_uploads_expiry ON uploads(expires_at) WHERE status IN ('created','uploading','uploaded');
CREATE INDEX ix_uploads_target ON uploads(target_file_id,status);
CREATE INDEX ix_uploads_batch ON uploads(batch_id);
CREATE TABLE upload_parts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  upload_id uuid NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
  part_no integer NOT NULL CHECK (part_no BETWEEN 1 AND 10000),
  size integer NOT NULL CHECK (size BETWEEN 0 AND 33554432),
  etag varchar(256), -- 原样保留，不当成SHA-256
  checksum varchar(64) CHECK (checksum ~ '^[0-9a-f]{64}$'),
  status varchar(12) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','confirmed','failed')),
  confirmed_at timestamptz,
  UNIQUE(upload_id,part_no),
  CHECK (status<>'confirmed' OR (etag IS NOT NULL AND checksum IS NOT NULL AND confirmed_at IS NOT NULL))
);

CREATE TABLE confirmation_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), -- 签名确认令牌中的jti
  actor_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  action varchar(16) NOT NULL CHECK (action IN ('purge','cleanup_retry')),
  target_type varchar(20) NOT NULL CHECK (target_type IN ('file','cleanup_attempt')),
  target_id uuid NOT NULL, -- 历史目标快照
  creation_request_id uuid NOT NULL UNIQUE REFERENCES idempotency_requests(id) ON DELETE RESTRICT,
  expires_at timestamptz NOT NULL DEFAULT (now()+interval '5 minutes'),
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (expires_at>created_at),
  CHECK ((action='purge' AND target_type='file') OR (action='cleanup_retry' AND target_type='cleanup_attempt'))
);
CREATE TABLE cleanup_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  file_id uuid NOT NULL, -- 被清理文件UUID快照，无FK
  space_id uuid NOT NULL REFERENCES spaces(id) ON DELETE RESTRICT,
  file_name varchar(255) NOT NULL,
  requested_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  confirmation_id uuid NOT NULL UNIQUE REFERENCES confirmation_tokens(id) ON DELETE RESTRICT,
  status varchar(12) NOT NULL DEFAULT 'created' CHECK (status IN ('created','running','completed','failed')),
  checkpoint varchar(16) NOT NULL DEFAULT 'validated' CHECK (checkpoint IN ('validated','detached','objects_done','completed')),
  detached_bytes bigint NOT NULL DEFAULT 0 CHECK (detached_bytes>=0),
  failure_detail jsonb, -- 仅阶段和错误码，不存对象密钥或异常堆栈
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE UNIQUE INDEX uq_cleanup_unfinished ON cleanup_attempts(file_id) WHERE status<>'completed';
CREATE TABLE cleanup_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL REFERENCES cleanup_attempts(id) ON DELETE RESTRICT,
  content_object_id uuid NOT NULL, -- 对象UUID快照，无FK，完成后对象可删除
  bucket varchar(63) NOT NULL CHECK (bucket='contents'),
  object_key varchar(256) NOT NULL,
  sha256 varchar(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size bigint NOT NULL CHECK (size>=0),
  detached_references bigint NOT NULL CHECK (detached_references>0),
  status varchar(12) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','shared','deleted','failed')),
  last_error_code varchar(64),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(attempt_id,content_object_id)
);

CREATE TABLE system_settings (
  key varchar(64) PRIMARY KEY,
  value jsonb NOT NULL,
  value_type varchar(10) NOT NULL CHECK (value_type IN ('integer','boolean','string','array','object')),
  updated_by uuid REFERENCES users(id) ON DELETE RESTRICT, -- 初始化值为NULL
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((value_type='integer' AND jsonb_typeof(value)='number') OR
         (value_type='boolean' AND jsonb_typeof(value)='boolean') OR
         (value_type='string' AND jsonb_typeof(value)='string') OR
         (value_type='array' AND jsonb_typeof(value)='array') OR
         (value_type='object' AND jsonb_typeof(value)='object'))
);
CREATE TABLE audit_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id uuid REFERENCES users(id) ON DELETE RESTRICT, -- 登录失败/系统事件可为NULL
  action varchar(64) NOT NULL,
  target_type varchar(32) NOT NULL,
  target_id uuid, -- 删除后仍保留UUID
  request_id uuid NOT NULL,
  result varchar(12) NOT NULL CHECK (result IN ('success','denied','failed')),
  detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_ip inet,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_time ON audit_events(created_at DESC,id);
CREATE INDEX ix_audit_target ON audit_events(target_type,target_id,created_at DESC);
CREATE INDEX ix_audit_actor ON audit_events(actor_id,created_at DESC);
CREATE TABLE backup_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scope varchar(16) NOT NULL DEFAULT 'all' CHECK (scope='all'),
  requested_by uuid REFERENCES users(id) ON DELETE RESTRICT, -- 宿主机命令可为NULL
  status varchar(12) NOT NULL DEFAULT 'running' CHECK (status IN ('running','completed','failed')),
  checkpoint varchar(24) NOT NULL DEFAULT 'preparing',
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  checksum varchar(64) CHECK (checksum ~ '^[0-9a-f]{64}$'), -- manifest.json SHA-256
  remote_key varchar(512), -- 清单在异地存储的内部键，不返回普通用户
  artifacts jsonb NOT NULL DEFAULT '[]'::jsonb, -- 文件名、大小、哈希、内部键
  error_code varchar(64)
);
CREATE INDEX ix_backup_time ON backup_runs(started_at DESC,id);

-- 通用更新时间维护；不可变版本不使用此触发器。
CREATE FUNCTION fm_touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at=now(); RETURN NEW; END;
$$;
CREATE TRIGGER touch_users BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION fm_touch_updated_at();
CREATE TRIGGER touch_spaces BEFORE UPDATE ON spaces FOR EACH ROW EXECUTE FUNCTION fm_touch_updated_at();
CREATE TRIGGER touch_members BEFORE UPDATE ON space_members FOR EACH ROW EXECUTE FUNCTION fm_touch_updated_at();
CREATE TRIGGER touch_directories BEFORE UPDATE ON directories FOR EACH ROW EXECUTE FUNCTION fm_touch_updated_at();
CREATE TRIGGER touch_files BEFORE UPDATE ON files FOR EACH ROW EXECUTE FUNCTION fm_touch_updated_at();
CREATE TRIGGER touch_objects BEFORE UPDATE ON content_objects FOR EACH ROW EXECUTE FUNCTION fm_touch_updated_at();
CREATE TRIGGER touch_tags BEFORE UPDATE ON tags FOR EACH ROW EXECUTE FUNCTION fm_touch_updated_at();
CREATE TRIGGER touch_fields BEFORE UPDATE ON metadata_fields FOR EACH ROW EXECUTE FUNCTION fm_touch_updated_at();
CREATE TRIGGER touch_metadata BEFORE UPDATE ON file_metadata_values FOR EACH ROW EXECUTE FUNCTION fm_touch_updated_at();
CREATE TRIGGER touch_uploads BEFORE UPDATE ON uploads FOR EACH ROW EXECUTE FUNCTION fm_touch_updated_at();
CREATE TRIGGER touch_cleanup_items BEFORE UPDATE ON cleanup_items FOR EACH ROW EXECUTE FUNCTION fm_touch_updated_at();
CREATE TRIGGER touch_settings BEFORE UPDATE ON system_settings FOR EACH ROW EXECUTE FUNCTION fm_touch_updated_at();

CREATE FUNCTION fm_version_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (to_jsonb(OLD)-'retained_until'-'legal_hold') IS DISTINCT FROM
     (to_jsonb(NEW)-'retained_until'-'legal_hold') THEN
    RAISE EXCEPTION 'file_versions immutable fields cannot be updated';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_version BEFORE UPDATE ON file_versions
  FOR EACH ROW EXECUTE FUNCTION fm_version_immutable();

CREATE FUNCTION fm_audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_events are append-only'; END;
$$;
CREATE TRIGGER append_only_audit BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION fm_audit_append_only();

INSERT INTO system_settings(key,value,value_type) VALUES
 ('max_file_bytes','1073741824'::jsonb,'integer'),
 ('multipart_threshold_bytes','5242880'::jsonb,'integer'),
 ('part_size_bytes','8388608'::jsonb,'integer'),
 ('upload_concurrency','4'::jsonb,'integer'),
 ('upload_ttl_seconds','86400'::jsonb,'integer'),
 ('access_ttl_seconds','900'::jsonb,'integer'),
 ('refresh_ttl_seconds','604800'::jsonb,'integer'),
 ('complete_timeout_seconds','600'::jsonb,'integer'),
 ('backup_retention_days','30'::jsonb,'integer'),
 ('upload_policy','{"allowed_extensions":[],"blocked_extensions":["exe","dll","bat","cmd","ps1","sh"],"allowed_mimes":[],"blocked_mimes":[]}'::jsonb,'object'),
 ('password_policy','{"min_length":12,"max_length":128}'::jsonb,'object');
COMMIT;
```

初始化策略中的空允许列表表示不额外限制允许范围，禁止列表仍生效；可执行文件默认禁止。策略必须在创建会话及完成上传时检查。整数配置还需 Service 校验整数性和允许范围，JSON 类型检查不是业务范围校验。

### 3.1 关键字段补充解释

| 字段组 | 约定 |
| --- | --- |
| 用户/会话 | `token_version` 冻结、改密、强制下线递增；`token_hash` 为高熵刷新令牌SHA-256；`sid` 检查撤销和绝对到期 |
| 文件所有权 | `owner_id` 创建时取操作者，不接受前端指定；版本 `created_by` 是实际发布者 |
| 格式快照 | `original_name/extension/mime` 来自该版本上传；逻辑文件重命名不改变格式筛选依据 |
| 内容对象 | `producer_upload_id` 用于追踪准备中对象；所有对外响应隐藏 `bucket/object_key/reference_count` |
| 请求关联 | `creation_request_id` 将业务记录与幂等请求绑定，响应完成必须与业务变更同事务提交 |
| 上传结果 | `result_file_id/result_version_id/result_snapshot` 永久绑定首次提交结果；文件被清理后返回 `RESULT_GONE`，不再次建文件 |
| 清理快照 | `file_id/file_name` 及 `cleanup_items` 在删除业务记录之前复制；对象被删后仍能审计和重试 |
| 时间字段 | `expires_at` 为服务端时间；前端倒计时仅展示，不决定有效性 |

## 4. 约束与 Service 校验边界

| 规则 | 数据库保证 | Service还需保证 |
| --- | --- | --- |
| 同空间目录、标签、自定义字段 | 复合外键 | 关联实体状态有效，操作者有空间权限 |
| 当前版本属于文件 | 延迟复合外键 | 正常提交后指针非NULL；每次更新与版本提交同事务 |
| 恢复来源属于同文件 | 复合外键 | 来源版本存在且可读，引用对象ready |
| 类型化自定义值 | 类型复合外键、单值列CHECK | 必填、内容长度、字段停用；字段类型建立后不可修改 |
| 目录防循环 | 只禁止自身父级 | 锁空间行后递归检查目标不为子孙；原子更新子树path_key |
| 配额 | 非负及used不超过quota | 在空间行锁下计费；不依赖上传前预检查 |
| 内容引用计数 | 非负及非ready对象零引用 | 与版本新增/删除同事务更新，定期核对实际引用 |
| 版本不可变 | 更新触发器 | 删除仅限受控清理；保留字段变更仅管理员并审计 |
| 审计只追加 | 更新/删除触发器 | 无TRUNCATE权限；详情脱敏，不记录令牌或内容 |
| 新版本上传目标 | 历史快照无FK | 创建与提交均检查目标存在、同空间、有效、所有权 |
| 单文件清理 | 未完成attempt部分唯一索引 | 完成前禁止恢复/修改保留策略；失败时复用原attempt |

数据库应用账号不得是表所有者或超级用户，不授予DDL、TRUNCATE、禁用触发器权限。清理需要的DELETE仅授予受控后端，授权仍在Service执行；不将数据库端口或账号交给前端。

## 5. 锁、事务及失败恢复

### 5.1 统一锁顺序

长存储操作不得在普通行锁事务内等待网络。使用**独占专用数据库连接的session advisory lock**跨短事务协调；连接不能在锁未释放时还给池。`finally` 显式解锁，异常时关闭连接；连接丢失立即中止存储编排，不能继续按已持锁处理。

同一编排的session锁、检查点及最终事务必须使用同一个专用连接，不能丢锁后另借连接提交。创建新版本上传会话的目标校验及插入同样在空间/文件行锁下完成，避免与清理detach竞争。

锁键定义：`hashtextextended('fm:'+namespace+':'+identity,0)` 的有符号bigint；namespace为 `idem`、`upload`、`cleanup`、`content`、`backup`。content identity为 `sha256+':'+size`。哈希碰撞只会额外串行，不会绕过检查。

顺序：幂等锁 → 上传锁或清理锁（二选一）→ 内容锁（按完整identity字典序）→ 短事务内空间行 → 文件行（UUID升序）→ 对象行（identity顺序）→ 其他业务行。无此类资源时跳过，不倒序获取。用户治理与认证刷新使用独立短事务，不在其中调用文件事务。

- session锁用 `pg_try_advisory_lock`，无法立即获得返回 `OPERATION_IN_PROGRESS`，不长期占用请求。
- 行锁等待最多5秒；死锁/序列化失败最多重试3次，仅重试数据库事务，不重复对象写入。
- 所有可能增加引用的操作（上传、复制、历史恢复）与删除对象都必须持有同一content锁。
- 内容集合在获取锁之前只读发现，锁后重新确认；集合发生变化释放锁并重新发现，不临时逆序加锁。
- 目录树变更统一先锁空间行；配额更新同样锁空间，因此防止并发超配额与目录循环。

session与transaction advisory lock生命周期不同，不能混用。[PostgreSQL锁文档](https://www.postgresql.org/docs/17/explicit-locking.html)

### 5.2 上传和版本提交

1. 持幂等及upload锁；已committed先重新鉴权，再返回首次结果，不再读内容。
2. 完成临时对象，流式重算大小、SHA-256、MIME；checkpoint依次为assembled、verified。
3. 获取content锁。在短事务中创建或检查staging对象记录；复制并校验正式对象后，短事务标记ready、upload checkpoint=object_ready。
4. 在最终事务中锁空间、目标文件、对象；重新检查账号会话、成员、目录状态、策略、配额和ready状态。
5. 新文件创建files及V1；新版本在文件行锁下使用 `max(version_no)+1`。同时更新current指针、引用计数、used_bytes、上传结果、批次计数、幂等响应和成功审计。
6. 提交后清理临时对象。清理失败不改成功结果，保留 `temp_cleaned_at=NULL` 和告警。

校验不一致为终态failed；配额不足或存储临时故障可保留uploaded供有效期内重试。最终事务失败的ready零引用对象不能在未持content锁且未重查引用时直接删除；优先留待受控孤立对象核对。

### 5.3 复制与历史恢复（复制为后续）

获取对应content锁，再锁空间、源/目标文件和对象。复制创建新文件及V1，新所有者为操作者，复用源当前版本内容及格式快照；可选复制标签/元数据，但重新检查有效字段。历史恢复创建同文件下一版本并记录来源。两者均按版本大小增加配额和引用，幂等结果同事务完成。v1只支持同空间复制和移动。

### 5.4 清理检查点（后续）

清理不是在长事务中边删数据库边删对象：

1. 持清理锁、全部content锁；短事务锁空间和文件，重新鉴权、检查deleted及保留策略，确认无活动新版本上传。消费二次确认，创建attempt和items快照。
2. **detach事务**：清空current指针，删除标签/元数据和全部版本，按对象扣减引用及空间用量，删除files；对实际零引用对象标记deleting，仍共享的items标记shared。checkpoint=detached与全部更新同事务提交。
3. 在仍持content锁时对deleting且实际零引用对象执行MinIO删除；短事务删除对象行、标记item deleted。404视为已删除，禁止删除ready共享对象。
4. 全部items为shared/deleted后，checkpoint=completed、status=completed并写审计；失败保存阶段与错误码。
5. detach后文件不可恢复，只能从备份恢复；重试通过attempt_id，重新确认并获取相同content锁，不重复扣减配额或引用。

进程在detach前退出可从validated恢复；在detach后退出从items恢复。不存在以“失败就恢复文件记录”的补偿方式，否则可能指向已经删除的内容。

## 6. 查询、配置与数据维护

- 列表/搜索只连接当前版本；每个文件只出现一次，用EXISTS匹配标签和自定义值避免JOIN放大分页。
- MVP关键词匹配名称、描述、目录名、所有者/当前版本上传者名称及MIME；后续增加标签和文本型自定义值。过滤先应用账号空间、有效文件状态。
- 包含匹配使用转义后的ILIKE；相关度按API定义的固定元数据权重。禁止字符串拼接SQL，排序与字段均用白名单。
- 文件created_at为首次创建时间；updated_at为元数据或current版本变更时间；版本created_at为发布时间。
- 批次计数只在上传第一次进入committed/failed/expired时更新；以事务锁批次行保证不重复计数。聚合核对可修复冗余计数。
- 同空间移动不释放配额；软删除/恢复不调整引用或配额。停用空间不删除数据，管理员仍可检查与管理，使用者不可访问。
- 设置值影响新会话；已有上传的part_size/part_count/expires_at按快照继续。允许类型和max_file_bytes在提交时重新检查，降低配额不得低于used_bytes。
- 初始化管理员通过受控CLI生成密码哈希；不在文档写死账户密码。管理员冻结/降权操作需串行治理锁，保证至少一个active管理员。
- 维护由管理员受控命令同步执行：过期上传清理、零引用对象核对、配额重算、幂等过期记录清理、备份；不设常驻任务。
- 幂等记录至少保证7天。受控清理只删除已过期且无业务外键引用的行；被files/file_versions/confirmation_tokens引用的行长期保留，不置空关联或强删。上传首次结果同样长期保留。

## 7. MVP责任与验收

| 能力 | 主负责人 | 验收 |
| --- | --- | --- |
| 认证/空间/目录/搜索 | PostgreSQL | 撤销会话立即拒绝、越权拒绝、目录循环拒绝、分页无重复 |
| 上传/版本/引用提交 | MinIO（数据库方法由PostgreSQL提供） | 重复完成仅一个版本，并发编号唯一，哈希错不提交 |
| 前端契约 | 前端 | 正确区分文件所有者与版本上传者，支持续传和错误提示 |
| 部署/审计/备份 | Nginx与集成 | 迁移可重建、只读探针成功、备份恢复引用一致 |

数据库验收用例：

1. 插入跨空间目录、标签和值时外键拒绝；当前版本指向其他文件时提交拒绝。
2. 根层同名目录大小写冲突拒绝；同目录同名文件允许。
3. 更新版本size/sha256/mime拒绝；管理员保留字段更新经Service审计后允许。
4. 两个并发版本提交获得不同版本号，current指向后提交版本，引用/配额无丢失。
5. 两个上传争抢剩余配额，仅符合配额的事务成功，另一上传保留可重试状态。
6. 同内容两份逻辑文件拥有独立权限；删除一个引用不删共享对象。
7. SQL事务回滚不产生已committed上传；提交后临时清理失败仍返回原成功结果。
8. 清理在validated/detached/对象删除之后分别中断，重试均不重复扣费。
9. 停用账号、撤销成员、撤销会话后，普通请求及幂等重放均重新授权。
10. JSONB与索引只保存元数据，没有正文、分块或内容处理字段。

**验证状态**：交付时执行静态关系/DDL检查；本任务不启动数据库，尚未在PostgreSQL 17上实际执行。部署负责人须在隔离空库执行本节SQL并运行上述用例后，才能标记迁移验证通过。

## 8. 技术参考

- [PostgreSQL 17约束](https://www.postgresql.org/docs/17/ddl-constraints.html)：主外键、唯一约束与CHECK的适用边界。
- [PostgreSQL 17显式锁](https://www.postgresql.org/docs/17/explicit-locking.html)：行锁、死锁和advisory lock。
- [PostgreSQL pg_trgm](https://www.postgresql.org/docs/17/pgtrgm.html)：元数据名称/描述索引。


## 9. 逐字段数据字典

以下从同一DDL逐项列出全部字段。空值规则已包含内联或复合主键隐含的NOT NULL；“无”表示无默认值，不表示可空。复合外键、部分索引和跨表Service规则仍以第3–5节为准。

### users

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| username | `varchar(64)` | 否 | 无 | 登录用户名（大小写不敏感唯一） |
| display_name | `varchar(100)` | 否 | 无 | 用户展示名称 |
| password_hash | `text` | 否 | 无 | Argon2id密码哈希编码 |
| role | `varchar(10)` | 否 | `'user'` | 管理员或使用者角色 |
| status | `varchar(12)` | 否 | `'active'` | 记录状态，允许值见本表DDL |
| token_version | `integer` | 否 | `0` | 会话整体撤销版本 |
| must_change_password | `boolean` | 否 | `false` | 是否必须先修改密码 |
| password_changed_at | `timestamptz` | 否 | `now()` | 最后改密时间 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |
| updated_at | `timestamptz` | 否 | `now()` | 记录更新时间（UTC） |

### refresh_sessions

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| user_id | `uuid` | 否 | 无 | 关联账号编号 |
| token_hash | `varchar(64)` | 否 | 无 | 高熵刷新令牌的SHA-256 |
| token_id | `uuid` | 否 | `gen_random_uuid()` | 轮换刷新令牌的内部标识 |
| expires_at | `timestamptz` | 否 | 无 | 绝对到期时间（UTC） |
| revoked_at | `timestamptz` | 是 | 无 | 撤销时间；NULL为未撤销 |
| last_used_at | `timestamptz` | 否 | `now()` | 最近使用时间 |
| user_agent | `varchar(512)` | 是 | 无 | 截断后的客户端信息 |
| source_ip | `inet` | 是 | 无 | 内部来源地址，对外需脱敏 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |

### spaces

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| name | `varchar(100)` | 否 | 无 | 实体显示名称 |
| quota_bytes | `bigint` | 否 | `10737418240` | 空间配额（逻辑字节） |
| used_bytes | `bigint` | 否 | `0` | 现存全部版本占用（含回收站） |
| status | `varchar(12)` | 否 | `'active'` | 记录状态，允许值见本表DDL |
| created_by | `uuid` | 否 | 无 | 创建或版本发布操作者编号 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |
| updated_at | `timestamptz` | 否 | `now()` | 记录更新时间（UTC） |

### space_members

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| space_id | `uuid` | 否 | 无 | 所属空间编号 |
| user_id | `uuid` | 否 | 无 | 关联账号编号 |
| status | `varchar(12)` | 否 | `'active'` | 记录状态，允许值见本表DDL |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |
| updated_at | `timestamptz` | 否 | `now()` | 记录更新时间（UTC） |

### directories

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| space_id | `uuid` | 否 | 无 | 所属空间编号 |
| parent_id | `uuid` | 是 | 无 | 父目录编号；NULL为根层 |
| name | `varchar(100)` | 否 | 无 | 实体显示名称 |
| path_key | `text` | 否 | 无 | 祖先UUID及自身UUID组成的内部目录路径 |
| status | `varchar(12)` | 否 | `'active'` | 记录状态，允许值见本表DDL |
| created_by | `uuid` | 否 | 无 | 创建或版本发布操作者编号 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |
| updated_at | `timestamptz` | 否 | `now()` | 记录更新时间（UTC） |

### idempotency_requests

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| actor_id | `uuid` | 否 | 无 | 执行请求的账号编号 |
| idempotency_key | `varchar(128)` | 否 | 无 | 客户端幂等键 |
| method | `varchar(6)` | 否 | 无 | 规范化HTTP方法 |
| path | `varchar(512)` | 否 | 无 | 规范化API路径，含实际参数 |
| request_hash | `varchar(64)` | 否 | 无 | 规范化请求的SHA-256指纹 |
| status | `varchar(12)` | 否 | `'processing'` | 记录状态，允许值见本表DDL |
| http_status | `smallint` | 是 | 无 | 原始HTTP结果状态 |
| response_data | `jsonb` | 是 | 无 | 脱敏结果；确认令牌由记录重签不存原文 |
| result_target_type | `varchar(32)` | 是 | 无 | 结果实体种类 |
| result_target_id | `uuid` | 是 | 无 | 结果实体编号快照 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |
| expires_at | `timestamptz` | 否 | `(now()+interval '7 days')` | 绝对到期时间（UTC） |
| completed_at | `timestamptz` | 是 | 无 | 幂等结果完成时间 |

### content_objects

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| bucket | `varchar(63)` | 否 | `'contents'` | 内部存储Bucket，不能对外泄露 |
| object_key | `varchar(256)` | 否 | 无 | 内部对象键，不包含Bucket名 |
| size | `bigint` | 否 | 无 | 对象、版本或分片字节数 |
| sha256 | `varchar(64)` | 否 | 无 | 实际完整内容SHA-256 |
| reference_count | `bigint` | 否 | `0` | 现存版本引用数量冗余计数 |
| status | `varchar(12)` | 否 | `'staging'` | 记录状态，允许值见本表DDL |
| producer_upload_id | `uuid` | 是 | 无 | 来源上传编号快照 |
| last_error_code | `varchar(64)` | 是 | 无 | 最近可公开业务错误码 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |
| updated_at | `timestamptz` | 否 | `now()` | 记录更新时间（UTC） |

### files

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| space_id | `uuid` | 否 | 无 | 所属空间编号 |
| directory_id | `uuid` | 是 | 无 | 所在目录；NULL为根层 |
| owner_id | `uuid` | 否 | 无 | 逻辑文件所有者编号 |
| name | `varchar(255)` | 否 | 无 | 实体显示名称 |
| description | `varchar(2000)` | 否 | `''` | 逻辑文件描述 |
| current_version_id | `uuid` | 是 | 无 | 当前版本；延迟外键保证同文件 |
| status | `varchar(12)` | 否 | `'active'` | 记录状态，允许值见本表DDL |
| deleted_at | `timestamptz` | 是 | 无 | 软删除时间 |
| deleted_by | `uuid` | 是 | 无 | 软删除操作者 |
| creation_request_id | `uuid` | 是 | 无 | 创建操作的幂等请求记录编号 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |
| updated_at | `timestamptz` | 否 | `now()` | 记录更新时间（UTC） |

### file_versions

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| file_id | `uuid` | 否 | 无 | 逻辑文件编号；清理历史表中为快照 |
| version_no | `integer` | 否 | 无 | 从1递增的版本号 |
| version_note | `varchar(1000)` | 否 | `''` | 创建时固定的版本说明 |
| original_name | `varchar(255)` | 否 | 无 | 上传时原文件名快照 |
| extension | `varchar(32)` | 否 | `''` | 原文件扩展名，小写且不含点 |
| content_object_id | `uuid` | 否 | 无 | 物理对象编号；清理项中为快照 |
| size | `bigint` | 否 | 无 | 对象、版本或分片字节数 |
| sha256 | `varchar(64)` | 否 | 无 | 实际完整内容SHA-256 |
| mime | `varchar(127)` | 否 | 无 | 声明或服务端确认的MIME |
| retained_until | `timestamptz` | 是 | 无 | 禁止物理删除截止时间 |
| legal_hold | `boolean` | 否 | `false` | 是否无限期合规冻结 |
| restored_from_version_id | `uuid` | 是 | 无 | 恢复来源版本编号 |
| created_by | `uuid` | 否 | 无 | 创建或版本发布操作者编号 |
| creation_request_id | `uuid` | 是 | 无 | 创建操作的幂等请求记录编号 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |

### tags

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| space_id | `uuid` | 否 | 无 | 所属空间编号 |
| name | `varchar(64)` | 否 | 无 | 实体显示名称 |
| status | `varchar(12)` | 否 | `'active'` | 记录状态，允许值见本表DDL |
| created_by | `uuid` | 否 | 无 | 创建或版本发布操作者编号 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |
| updated_at | `timestamptz` | 否 | `now()` | 记录更新时间（UTC） |

### file_tags

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| space_id | `uuid` | 否 | 无 | 所属空间编号 |
| file_id | `uuid` | 否 | 无 | 逻辑文件编号；清理历史表中为快照 |
| tag_id | `uuid` | 否 | 无 | 标签编号 |
| created_by | `uuid` | 否 | 无 | 创建或版本发布操作者编号 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |

### metadata_fields

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| space_id | `uuid` | 否 | 无 | 所属空间编号 |
| name | `varchar(64)` | 否 | 无 | 实体显示名称 |
| value_type | `varchar(10)` | 否 | 无 | 受控值类型 |
| required | `boolean` | 否 | `false` | 新文件是否必须提供字段值 |
| status | `varchar(12)` | 否 | `'active'` | 记录状态，允许值见本表DDL |
| created_by | `uuid` | 否 | 无 | 创建或版本发布操作者编号 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |
| updated_at | `timestamptz` | 否 | `now()` | 记录更新时间（UTC） |

### file_metadata_values

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| space_id | `uuid` | 否 | 无 | 所属空间编号 |
| file_id | `uuid` | 否 | 无 | 逻辑文件编号；清理历史表中为快照 |
| field_id | `uuid` | 否 | 无 | 自定义字段编号 |
| value_type | `varchar(10)` | 否 | 无 | 受控值类型 |
| value_text | `varchar(2000)` | 是 | 无 | 文本型值 |
| value_number | `numeric(20,6)` | 是 | 无 | 精确十进制值，API使用字符串 |
| value_date | `date` | 是 | 无 | 日期型值（非时间戳） |
| value_boolean | `boolean` | 是 | 无 | 布尔型值 |
| updated_by | `uuid` | 否 | 无 | 最后修改操作者 |
| updated_at | `timestamptz` | 否 | `now()` | 记录更新时间（UTC） |

### upload_batches

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| user_id | `uuid` | 否 | 无 | 关联账号编号 |
| total_count | `integer` | 否 | 无 | 本批选择文件数量 |
| completed_count | `integer` | 否 | `0` | 第一次成功提交的文件数量 |
| failed_count | `integer` | 否 | `0` | 第一次失败或过期的文件数量 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |

### uploads

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| batch_id | `uuid` | 是 | 无 | 所属选择批次；NULL为无批次 |
| user_id | `uuid` | 否 | 无 | 关联账号编号 |
| space_id | `uuid` | 否 | 无 | 所属空间编号 |
| directory_id | `uuid` | 是 | 无 | 所在目录；NULL为根层 |
| target_file_id | `uuid` | 是 | 无 | 新版本目标UUID快照；新文件为NULL |
| mode | `varchar(12)` | 否 | 无 | new_file或new_version |
| original_name | `varchar(255)` | 否 | 无 | 上传时原文件名快照 |
| description | `varchar(2000)` | 否 | `''` | 逻辑文件描述 |
| version_note | `varchar(1000)` | 否 | `''` | 创建时固定的版本说明 |
| tag_ids | `uuid[]` | 否 | `'{}'::uuid[]` | 新文件提交时的标签意图快照 |
| metadata_values | `jsonb` | 否 | `'[]'::jsonb` | 新文件提交时的类型化值意图快照 |
| expected_size | `bigint` | 否 | 无 | 客户端声明的全文件字节数 |
| actual_size | `bigint` | 是 | 无 | 服务端实测全文件字节数 |
| expected_sha256 | `varchar(64)` | 否 | 无 | 客户端增量计算的全文件SHA-256 |
| actual_sha256 | `varchar(64)` | 是 | 无 | 服务端流式计算的全文件SHA-256 |
| mime | `varchar(127)` | 否 | 无 | 声明或服务端确认的MIME |
| storage_method | `varchar(12)` | 否 | 无 | single或multipart存储方案 |
| part_size | `integer` | 否 | 无 | 创建会话时固定的分片字节数 |
| part_count | `integer` | 否 | 无 | 计划分片数，零字节文件仍为1 |
| minio_upload_id | `text` | 是 | 无 | 内部multipart句柄，禁止返回前端 |
| temp_object_key | `varchar(256)` | 否 | 无 | 内部临时对象键 |
| status | `varchar(12)` | 否 | `'created'` | 记录状态，允许值见本表DDL |
| checkpoint | `varchar(16)` | 否 | `'receiving'` | 可恢复处理阶段，允许值见DDL |
| last_error_code | `varchar(64)` | 是 | 无 | 最近可公开业务错误码 |
| expires_at | `timestamptz` | 否 | `(now()+interval '24 hours')` | 绝对到期时间（UTC） |
| idempotency_key | `varchar(128)` | 否 | 无 | 客户端幂等键 |
| request_hash | `varchar(64)` | 否 | 无 | 规范化请求的SHA-256指纹 |
| result_file_id | `uuid` | 是 | 无 | 首次提交的逻辑文件编号快照 |
| result_version_id | `uuid` | 是 | 无 | 首次提交的版本编号快照 |
| result_snapshot | `jsonb` | 是 | 无 | 首次公共FileCommit结果快照 |
| temp_cleaned_at | `timestamptz` | 是 | 无 | 临时对象成功清理时间 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |
| updated_at | `timestamptz` | 否 | `now()` | 记录更新时间（UTC） |

### upload_parts

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| upload_id | `uuid` | 否 | 无 | 所属上传会话编号 |
| part_no | `integer` | 否 | 无 | 从1起的分片序号 |
| size | `integer` | 否 | 无 | 对象、版本或分片字节数 |
| etag | `varchar(256)` | 是 | 无 | MinIO原始ETag，不等于SHA-256 |
| checksum | `varchar(64)` | 是 | 无 | 实际分片SHA-256或备份清单SHA-256 |
| status | `varchar(12)` | 否 | `'pending'` | 记录状态，允许值见本表DDL |
| confirmed_at | `timestamptz` | 是 | 无 | 分片确认落库时间 |

### confirmation_tokens

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| actor_id | `uuid` | 否 | 无 | 执行请求的账号编号 |
| action | `varchar(16)` | 否 | 无 | 操作名称或确认动作 |
| target_type | `varchar(20)` | 否 | 无 | 目标实体类型 |
| target_id | `uuid` | 否 | 无 | 目标实体编号快照 |
| creation_request_id | `uuid` | 否 | 无 | 创建操作的幂等请求记录编号 |
| expires_at | `timestamptz` | 否 | `(now()+interval '5 minutes')` | 绝对到期时间（UTC） |
| consumed_at | `timestamptz` | 是 | 无 | 二次确认首次消费时间 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |

### cleanup_attempts

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| file_id | `uuid` | 否 | 无 | 逻辑文件编号；清理历史表中为快照 |
| space_id | `uuid` | 否 | 无 | 所属空间编号 |
| file_name | `varchar(255)` | 否 | 无 | 被清理逻辑文件名称快照 |
| requested_by | `uuid` | 否 | 无 | 请求操作的账号编号；受控命令可空 |
| confirmation_id | `uuid` | 否 | 无 | 原始二次确认记录编号 |
| status | `varchar(12)` | 否 | `'created'` | 记录状态，允许值见本表DDL |
| checkpoint | `varchar(16)` | 否 | `'validated'` | 可恢复处理阶段，允许值见DDL |
| detached_bytes | `bigint` | 否 | `0` | 首次detach实际释放的逻辑字节数 |
| failure_detail | `jsonb` | 是 | 无 | 脱敏失败阶段与业务码 |
| started_at | `timestamptz` | 否 | `now()` | 操作开始时间 |
| finished_at | `timestamptz` | 是 | 无 | 操作结束时间 |

### cleanup_items

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| attempt_id | `uuid` | 否 | 无 | 所属物理清理记录编号 |
| content_object_id | `uuid` | 否 | 无 | 物理对象编号；清理项中为快照 |
| bucket | `varchar(63)` | 否 | 无 | 内部存储Bucket，不能对外泄露 |
| object_key | `varchar(256)` | 否 | 无 | 内部对象键，不包含Bucket名 |
| sha256 | `varchar(64)` | 否 | 无 | 实际完整内容SHA-256 |
| size | `bigint` | 否 | 无 | 对象、版本或分片字节数 |
| detached_references | `bigint` | 否 | 无 | 该文件detach移除的此对象引用数量 |
| status | `varchar(12)` | 否 | `'pending'` | 记录状态，允许值见本表DDL |
| last_error_code | `varchar(64)` | 是 | 无 | 最近可公开业务错误码 |
| updated_at | `timestamptz` | 否 | `now()` | 记录更新时间（UTC） |

### system_settings

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| key | `varchar(64)` | 否 | 无 | 受控配置键 |
| value | `jsonb` | 否 | 无 | 类型化JSON配置值 |
| value_type | `varchar(10)` | 否 | 无 | 受控值类型 |
| updated_by | `uuid` | 是 | 无 | 最后修改操作者 |
| updated_at | `timestamptz` | 否 | `now()` | 记录更新时间（UTC） |

### audit_events

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| actor_id | `uuid` | 是 | 无 | 执行请求的账号编号 |
| action | `varchar(64)` | 否 | 无 | 操作名称或确认动作 |
| target_type | `varchar(32)` | 否 | 无 | 目标实体类型 |
| target_id | `uuid` | 是 | 无 | 目标实体编号快照 |
| request_id | `uuid` | 否 | 无 | 本次请求关联UUID |
| result | `varchar(12)` | 否 | 无 | 审计成功、拒绝或失败 |
| detail | `jsonb` | 否 | `'{}'::jsonb` | 白名单脱敏审计详情 |
| source_ip | `inet` | 是 | 无 | 内部来源地址，对外需脱敏 |
| created_at | `timestamptz` | 否 | `now()` | 记录创建时间（UTC） |

### backup_runs

| 字段 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| id | `uuid` | 否 | `gen_random_uuid()` | 本表记录编号 |
| scope | `varchar(16)` | 否 | `'all'` | 备份范围，固定all |
| requested_by | `uuid` | 是 | 无 | 请求操作的账号编号；受控命令可空 |
| status | `varchar(12)` | 否 | `'running'` | 记录状态，允许值见本表DDL |
| checkpoint | `varchar(24)` | 否 | `'preparing'` | 可恢复处理阶段，允许值见DDL |
| started_at | `timestamptz` | 否 | `now()` | 操作开始时间 |
| finished_at | `timestamptz` | 是 | 无 | 操作结束时间 |
| checksum | `varchar(64)` | 是 | 无 | 实际分片SHA-256或备份清单SHA-256 |
| remote_key | `varchar(512)` | 是 | 无 | 异地清单内部键，禁止普通响应泄露 |
| artifacts | `jsonb` | 否 | `'[]'::jsonb` | 备份内部产物清单，对外过滤内部键 |
| error_code | `varchar(64)` | 是 | 无 | 备份失败业务码 |
