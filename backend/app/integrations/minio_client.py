"""C: storage foundation; authorization happens in Service, never in this adapter."""
from contextlib import contextmanager
from minio import Minio
from urllib3 import PoolManager, Retry, Timeout
from app.core.config import Settings

APP_BUCKETS = ("uploads", "contents")  # backups belongs to the separate backup account.

class MinioAdapter:
    def __init__(self, settings: Settings):
        self.http = PoolManager(timeout=Timeout(connect=2, read=2),
                                retries=Retry(total=1, backoff_factor=0.1))
        try:
            self.client = Minio(settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.read_secret(settings.minio_secret_key_file),
                secure=settings.minio_secure, http_client=self.http)
        except Exception:
            self.http.clear()
            raise

    def check_buckets(self):
        for bucket in APP_BUCKETS:
            if not self.client.bucket_exists(bucket):
                raise RuntimeError("Required application bucket missing")

    @contextmanager
    def open_stream(self, bucket: str, key: str, offset: int = 0, length: int = 0):
        response = self.client.get_object(bucket, key, offset=offset, length=length)
        try:
            yield response
        finally:
            try:
                response.close()
            finally:
                response.release_conn()

    def put_part(self, *args, **kwargs):
        raise NotImplementedError("C: implement verified multipart adapter, not private SDK calls.")

    def initiate_upload(self, *args, **kwargs):
        raise NotImplementedError("C: storage session creation awaits business implementation.")

    def complete_upload(self, *args, **kwargs):
        raise NotImplementedError("C: verify content before publishing; no fake completion.")

    def publish_content(self, *args, **kwargs):
        raise NotImplementedError("C: immutable object creation requires B/C locking contract.")

    def abort_upload(self, *args, **kwargs):
        raise NotImplementedError("C: cleanup must follow checkpoints and pinned locks.")

    def close(self):
        self.http.clear()
