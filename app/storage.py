import io
import json
import os
import random
import shutil
import zipfile
from pathlib import Path
from typing import Optional, Tuple, AsyncGenerator, List
import aiofiles
from app.config import settings

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    ClientError = Exception


class StorageManager:
    def __init__(self):
        self.local_image_dir = settings.DATA_DIR / "images"
        self.local_submission_dir = settings.DATA_DIR / "submissions"
        
        # Ensure directories exist
        (self.local_image_dir / "train").mkdir(parents=True, exist_ok=True)
        (self.local_image_dir / "test").mkdir(parents=True, exist_ok=True)
        (self.local_submission_dir / "train").mkdir(parents=True, exist_ok=True)
        (self.local_submission_dir / "test").mkdir(parents=True, exist_ok=True)

        self._s3_client = None
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            self._s3_client = boto3.client(
                "s3",
                region_name=settings.AWS_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
            )
        elif settings.is_s3_enabled:
            # Assume IAM Role or AWS CLI env credentials
            self._s3_client = boto3.client("s3", region_name=settings.AWS_REGION)

    def _get_local_images(self, mode: str) -> List[Path]:
        target_dir = self.local_image_dir / mode
        extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        files = [p for p in target_dir.iterdir() if p.is_file() and p.suffix.lower() in extensions]
        return sorted(files)

    def get_image_info(self, mode: str) -> Tuple[str, Path, str]:
        """
        Select an image for the given mode.
        Returns: (file_name, local_file_path, content_type)
        """
        files = self._get_local_images(mode)
        if not files:
            # If no images found, create a sample test image on the fly
            sample_img = self._create_sample_image_if_empty(mode)
            files = [sample_img]

        # Randomly select an image from the pool
        selected_file = random.choice(files)
        suffix = selected_file.suffix.lower()
        content_type = "image/png" if suffix == ".png" else "image/jpeg"
        return selected_file.name, selected_file, content_type

    def _create_sample_image_if_empty(self, mode: str) -> Path:
        """Creates a tiny 1x1 valid PNG image if the pool is empty."""
        sample_path = self.local_image_dir / mode / f"sample_{mode}_image.png"
        if not sample_path.exists():
            # Minimal 1x1 PNG bytes
            tiny_png = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff"
                b"?\x00\x05\xfe\x02\xfe\xa74X\x97\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            with open(sample_path, "wb") as f:
                f.write(tiny_png)
        return sample_path

    async def stream_file_chunks(self, file_path: Path) -> AsyncGenerator[bytes, None]:
        """Async generator that streams file chunks of configured size."""
        async with aiofiles.open(file_path, mode="rb") as f:
            while chunk := await f.read(settings.STREAM_CHUNK_SIZE):
                yield chunk

    async def save_submission(
        self,
        mode: str,
        team_name: str,
        img_id: str,
        timestamp_str: str,
        payload: dict
    ) -> str:
        """
        Persist submission JSON to local storage and optionally S3.
        Returns the primary storage URI/path.
        """
        safe_team = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in team_name)
        team_folder = self.local_submission_dir / mode / safe_team
        team_folder.mkdir(parents=True, exist_ok=True)

        file_name = f"{img_id}_{timestamp_str}.json"
        local_file_path = team_folder / file_name

        payload_bytes = json.dumps(payload, indent=2).encode("utf-8")

        # 1. Dual-write to local disk buffer
        async with aiofiles.open(local_file_path, "wb") as f:
            await f.write(payload_bytes)

        stored_location = str(local_file_path.relative_to(settings.BASE_DIR))

        # 2. Backup to S3 if configured
        if self._s3_client and settings.S3_SUBMISSION_BUCKET:
            s3_key = f"submissions/{mode}/{safe_team}/{file_name}"
            try:
                self._s3_client.put_object(
                    Bucket=settings.S3_SUBMISSION_BUCKET,
                    Key=s3_key,
                    Body=payload_bytes,
                    ContentType="application/json"
                )
                stored_location = f"s3://{settings.S3_SUBMISSION_BUCKET}/{s3_key}"
            except Exception as e:
                # Log warning, local disk still preserves data
                print(f"[StorageWarning] Failed to backup to S3: {e}")

        return stored_location

    def build_export_zip(self) -> io.BytesIO:
        """Packages all submissions into an in-memory zip archive for admin download."""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for root, _, files in os.walk(self.local_submission_dir):
                for file in files:
                    full_path = Path(root) / file
                    arcname = full_path.relative_to(self.local_submission_dir)
                    zip_file.write(full_path, arcname=str(arcname))
        zip_buffer.seek(0)
        return zip_buffer


storage_manager = StorageManager()
