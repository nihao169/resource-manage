#!/bin/sh
set -eu
mc alias set internal http://minio:9000 fm_root "$(cat /run/secrets/minio_root_password)" >/dev/null
for bucket in uploads contents backups; do
 mc mb --ignore-existing "internal/$bucket"
 mc anonymous set none "internal/$bucket"
done
mc admin user add internal fm_api "$(cat /run/secrets/minio_api_password)" >/dev/null
mc admin policy create internal fm-business /config/business-policy.json
mc admin policy attach internal fm-business --user fm_api
mc admin user add internal fm_backup "$(cat /run/secrets/minio_backup_password)" >/dev/null
mc admin policy create internal fm-backup /config/backup-policy.json
mc admin policy attach internal fm-backup --user fm_backup
