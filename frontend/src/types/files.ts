import type { UUID, UTC, UploadStatus } from './api'
export interface UserSummary { id: UUID; username: string; display_name: string }
export interface Version {
 version_id: UUID; file_id: UUID; version_no: number; version_note: string
 original_name: string; extension: string; mime: string; size: number; sha256: string
 retained_until: UTC | null; legal_hold: boolean; restored_from_version_id: UUID | null
 uploader: UserSummary; created_at: UTC
}
export interface Tag { tag_id: UUID; space_id: UUID; name: string; status: 'active' | 'disabled'; created_at: UTC; updated_at: UTC }
export interface MetadataValue { field_id: UUID; value_type: 'text' | 'number' | 'date' | 'boolean'; value: string | boolean }
export interface FileDTO {
 file_id: UUID; space_id: UUID; directory_id: UUID | null; directory_path: string
 owner: UserSummary; name: string; description: string; current_version: Version
 status: 'active' | 'deleted'; tags: Tag[]; metadata_values: MetadataValue[]
 deleted_at: UTC | null; deleted_by: UserSummary | null; created_at: UTC; updated_at: UTC
}
export interface Part { part_no: number; size: number; checksum: string; confirmed_at: UTC }
export interface Upload {
 upload_id: UUID; batch_id: UUID | null; mode: 'new_file' | 'new_version'; space_id: UUID
 directory_id: UUID | null; target_file_id: UUID | null; original_name: string
 expected_size: number; expected_sha256: string; mime: string; storage_method: 'single' | 'multipart'
 part_size: number; part_count: number; status: UploadStatus; confirmed_parts: Part[]
 confirmed_bytes: number; expires_at: UTC; last_error_code: string | null
 result_file_id: UUID | null; result_version_id: UUID | null
}
export interface FileCommit { upload_id: UUID | null; file: FileDTO; version: Version }
export interface Directory { directory_id: UUID; space_id: UUID; parent_id: UUID | null; name: string; display_path: string; created_at: UTC; updated_at: UTC }

