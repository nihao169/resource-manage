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

