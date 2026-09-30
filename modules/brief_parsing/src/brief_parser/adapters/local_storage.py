"""Owned local upload and lifecycle storage for standalone mode."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePath

from brief_parser.errors import BriefParserError, ErrorCode

_SAFE_JOB_ID = re.compile(r"^job_[a-z0-9]{8,64}$")
_SUPPORTED_SUFFIXES = frozenset({".txt", ".docx", ".pdf"})


@dataclass(frozen=True, slots=True)
class IncomingUpload:
    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class StoredUpload:
    path: Path
    original_filename: str
    sha256: str
    byte_size: int


class StandaloneStorage:
    def __init__(self, root: Path, *, max_file_bytes: int) -> None:
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        self.root = root.resolve()
        self.upload_root = self.root / "uploads"
        self.artifact_root = self.root / "artifacts"
        self._max_file_bytes = max_file_bytes

    def initialize(self) -> None:
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def store_uploads(
        self,
        job_id: str,
        uploads: list[IncomingUpload],
    ) -> tuple[StoredUpload, ...]:
        self._validate_job_id(job_id)
        if not uploads:
            raise BriefParserError(ErrorCode.INVALID_REQUEST, "至少需要一个上传文件。")
        target = self.upload_root / job_id
        if target.exists():
            raise BriefParserError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Parse Job 上传目录已存在。",
            )
        temporary = Path(tempfile.mkdtemp(prefix=f".{job_id}.tmp-", dir=self.upload_root))
        stored: list[StoredUpload] = []
        try:
            for ordinal, upload in enumerate(uploads, start=1):
                filename = PurePath(upload.filename).name
                suffix = Path(filename).suffix.lower()
                if suffix not in _SUPPORTED_SUFFIXES:
                    raise BriefParserError(
                        ErrorCode.SOURCE_UNSUPPORTED,
                        "仅支持 UTF-8 TXT、DOCX 和具有文本层的 PDF。",
                    )
                if not upload.content:
                    raise BriefParserError(ErrorCode.INVALID_REQUEST, "上传文件不能为空。")
                if len(upload.content) > self._max_file_bytes:
                    raise BriefParserError(
                        ErrorCode.SOURCE_TOO_LARGE,
                        "上传文件超过允许的大小上限。",
                        details={"max_file_bytes": self._max_file_bytes},
                    )
                path = temporary / f"source_{ordinal:03d}{suffix}"
                with path.open("xb") as handle:
                    handle.write(upload.content)
                    handle.flush()
                    os.fsync(handle.fileno())
                stored.append(
                    StoredUpload(
                        path=path,
                        original_filename=filename,
                        sha256=sha256(upload.content).hexdigest(),
                        byte_size=len(upload.content),
                    )
                )
            temporary.rename(target)
            return tuple(
                StoredUpload(
                    path=target / item.path.name,
                    original_filename=item.original_filename,
                    sha256=item.sha256,
                    byte_size=item.byte_size,
                )
                for item in stored
            )
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def delete_job_data(self, *, upload_dir: Path, artifact_dir: Path) -> None:
        self._remove_owned(upload_dir, self.upload_root)
        self._remove_owned(artifact_dir, self.artifact_root)

    @staticmethod
    def fingerprint(
        uploads: tuple[StoredUpload, ...],
        *,
        parameters_json: str,
    ) -> str:
        digest = sha256(parameters_json.encode("utf-8"))
        for upload in uploads:
            digest.update(upload.sha256.encode("ascii"))
            digest.update(str(upload.byte_size).encode("ascii"))
        return digest.hexdigest()

    @staticmethod
    def _validate_job_id(job_id: str) -> None:
        if not _SAFE_JOB_ID.fullmatch(job_id):
            raise BriefParserError(ErrorCode.INVALID_REQUEST, "Job ID 格式无效。")

    @staticmethod
    def _remove_owned(path: Path, owner: Path) -> None:
        resolved = path.resolve()
        resolved_owner = owner.resolve()
        if resolved == resolved_owner or not resolved.is_relative_to(resolved_owner):
            raise RuntimeError("refusing to delete a path outside owned standalone storage")
        if resolved.exists():
            shutil.rmtree(resolved)
