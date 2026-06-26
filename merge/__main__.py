import os
import re
from _thread import lock
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from re import Pattern
from threading import Lock
from typing import Any

import orjson
from orjson import (
    OPT_NON_STR_KEYS,
    JSONDecodeError,
    JSONEncodeError,
)

from merge.config import (
    BUCKETS,
    DEFAULT_RULES,
    GITHUB_RULES,
    IGNORE_FILES_NAME,
    NODEJS_RULES,
    PHP_RULES,
    RESULTS_DIR,
    SOURCEFORGE_RULES,
    SYNC_DIRS_NAME,
    VERSION_PATTERN,
    Bucket,
    Rule,
)


class SemverStatus(IntEnum):
    GREATER = 1  # a > b
    EQUAL = 0  # a == b
    LESS = -1  # a < b


def to_num(s: str) -> int:
    if not s or s.strip() == "":
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def semver_compare(old: str, new: str) -> SemverStatus:
    old: str = VERSION_PATTERN.sub("", str(old or "").replace("-", "."))
    new: str = VERSION_PATTERN.sub("", str(new or "").replace("-", "."))

    old_segments, new_segments = old.split("."), new.split(".")

    count: int = max(len(old_segments), len(new_segments), 3)

    for i in range(count):
        old_num: int = to_num(s=old_segments[i]) if i < len(old_segments) else 0
        new_num: int = to_num(s=new_segments[i]) if i < len(new_segments) else 0

        if old_num > new_num:
            return SemverStatus.GREATER
        elif new_num > old_num:
            return SemverStatus.LESS
    return SemverStatus.EQUAL


@dataclass
class FileInfo:
    bucket: Bucket
    version: str
    path: Path
    file_lock: lock


keep_files: dict[Path, FileInfo] = {}
keep_files_lock: lock = Lock()


def fix_depends(val: str | list[str]) -> Any:
    if isinstance(val, str) and "/" in val:
        return "main/" + val.split("/", 1)[1]
    if isinstance(val, list):
        return [
            "main/" + item.split("/", 1)[1] if "/" in item else item for item in val
        ]
    return val


def copy(args: tuple[Path, Path, Path, Bucket, bool, bool]) -> None:
    src, dst, key, bucket, is_manifest, only_sync = args

    version: str = "unknown"
    content_json: dict[str, Any] | None = None

    try:
        content: bytes = src.read_bytes().replace(b"\r\n", b"\n").strip()
        if is_manifest:
            content_json: Any = orjson.loads(content)
            if not isinstance(content_json, dict) or "version" not in content_json:
                return
            version: str = content_json["version"]
    except JSONDecodeError, JSONEncodeError:
        return

    with keep_files_lock:
        info: FileInfo | None = keep_files.get(key)
        if info is None:
            file_lock: lock = Lock()
            info = FileInfo(
                path=dst, bucket=bucket, version=version, file_lock=file_lock
            )
            keep_files[key] = info
        else:
            file_lock: lock = info.file_lock
            if (
                bucket.stars < info.bucket.stars
                and bucket.updated_time < info.bucket.updated_time
            ):
                return

            if (
                is_manifest
                and info.bucket.stars == bucket.stars
                and info.bucket.updated_time == bucket.updated_time
            ):
                status: SemverStatus = semver_compare(info.version, version)
                if status in (SemverStatus.GREATER, SemverStatus.EQUAL):
                    return

            # 更新 metadata
            info.bucket = bucket
            info.version = version
            info.path = dst

    with file_lock:
        rules: list[Rule] = DEFAULT_RULES[:]

        if not only_sync:
            if b"github.com" in content or b"githubusercontent.com" in content:
                rules += GITHUB_RULES
            if b"sourceforge.net" in content:
                rules += SOURCEFORGE_RULES
            if "nodejs" in src.name:
                rules += NODEJS_RULES

        if "php" in src.name:
            rules += PHP_RULES

        for pattern, replace in rules:
            if isinstance(pattern, Pattern):
                content: bytes = pattern.sub(replace, content)
            elif isinstance(pattern, bytes) and isinstance(replace, bytes):
                content: bytes = content.replace(pattern, replace)

        # 处理manifest
        if is_manifest and content_json:
            result_json: Any = orjson.loads(content)
            result_json["from"] = bucket.url

            if "depends" in content_json:
                raw_depends: str | list[str] = content_json["depends"]
                depends: list[str] = (
                    [raw_depends] if isinstance(raw_depends, str) else list(raw_depends)
                )
                result_json["depends"] = [fix_depends(d) for d in depends]

            if "suggest" in content_json:
                suggest: str | dict[str, str] = content_json["suggest"]
                if isinstance(suggest, dict):
                    result_json["suggest"] = {
                        k: fix_depends(v) for k, v in suggest.items()
                    }
                elif isinstance(suggest, str):
                    result_json["suggest"] = fix_depends(suggest)

            if "homepage" in content_json:
                result_json["homepage"] = content_json["homepage"]

            if "bin" in content_json:
                result_json["bin"] = content_json["bin"]

            content: bytes = orjson.dumps(result_json, option=OPT_NON_STR_KEYS)

        dst.write_bytes(content)


def main() -> None:
    need_work_dirs: list[tuple[Path, Bucket]] = []
    for bucket in BUCKETS:
        if not bucket.repo_dir.exists():
            continue
        for sync_dir_name in SYNC_DIRS_NAME:
            if not (bucket.repo_dir / sync_dir_name).exists():
                continue
            need_work_dirs.append((bucket.repo_dir / sync_dir_name, bucket))

    only_sync = bool(int(os.environ["ONLY_SYNC"]))
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures: list[Future[None]] = []
        for sync_dir, bucket in need_work_dirs:
            for src in sync_dir.rglob("*"):
                if not src.is_file() or any(
                    re.search(name, src.name.lower()) for name in IGNORE_FILES_NAME
                ):
                    continue
                rel_path: Path = src.relative_to(bucket.repo_dir)
                is_manifest: bool = rel_path.parts[0] == "bucket"
                if is_manifest:
                    if src.suffix.lower() != ".json":
                        continue
                    else:
                        rel_path: Path = Path(rel_path.parts[0]) / rel_path.name
                dst: Path = RESULTS_DIR / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                futures.append(
                    executor.submit(
                        copy,
                        (
                            src,
                            dst,
                            Path(*[path.lower() for path in rel_path.parts]),
                            bucket,
                            is_manifest,
                            only_sync,
                        ),
                    )
                )

        for future in as_completed(futures):
            future.result()

    for file in RESULTS_DIR.rglob("*"):
        if not file.is_file():
            continue
        key = Path(*[path.lower() for path in file.relative_to(RESULTS_DIR).parts])
        if key not in keep_files or keep_files[key].path != file:
            file.unlink()


main()
