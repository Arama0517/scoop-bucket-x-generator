import contextlib
import io
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from requests.models import Response

from merge.config import BUCKETS, SYNC_DIRS_NAME, Bucket

session = requests.Session()


def download(bucket: Bucket):
    with contextlib.suppress(Exception):
        response: Response = session.get(
            bucket.url.rstrip("/") + "/archive/HEAD.zip", timeout=60
        )
        if response.status_code != 200:
            return

        z = zipfile.ZipFile(io.BytesIO(response.content))
        names: list[str] = z.namelist()
        root: str = names[0].split("/", 1)[0] + "/"

        bucket.repo_dir.mkdir(parents=True, exist_ok=True)

        for name in names:
            if not name.startswith(root):
                continue

            rel: str = name[len(root) :]
            if not rel or name.endswith("/"):
                continue

            if not any(rel == d or rel.startswith(d + "/") for d in SYNC_DIRS_NAME):
                continue

            dst: Path = bucket.repo_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(name))


with ThreadPoolExecutor() as executor:
    futures: list[Future[None]] = []
    for bucket in BUCKETS:
        futures.append(executor.submit(download, bucket))

    for future in as_completed(futures):
        future.result()
