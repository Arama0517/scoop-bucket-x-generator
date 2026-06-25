import contextlib
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from tempfile import SpooledTemporaryFile

import requests
from requests.adapters import HTTPAdapter
from requests.models import Response

from merge.config import BUCKETS, SYNC_DIRS_NAME, Bucket

session = requests.Session()

adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=0)
session.mount("https://", adapter)
session.mount("http://", adapter)


def download(bucket: Bucket):
    with contextlib.suppress(Exception):
        response: Response = session.get(
            bucket.url.rstrip("/") + "/archive/HEAD.zip", stream=True, timeout=60
        )
        if response.status_code != 200:
            return

        with SpooledTemporaryFile(max_size=50 * 1024 * 1024) as tmp:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    tmp.write(chunk)

            tmp.seek(0)

            with zipfile.ZipFile(tmp) as z:
                names: list[str] = z.namelist()
                root: str = names[0].split("/", 1)[0] + "/"

                bucket.repo_dir.mkdir(parents=True, exist_ok=True)

                for name in names:
                    if not name.startswith(root):
                        continue

                    rel: str = name[len(root) :]
                    if not rel or name.endswith("/"):
                        continue

                    if not any(
                        rel == d or rel.startswith(d + "/") for d in SYNC_DIRS_NAME
                    ):
                        continue

                    dst: Path = bucket.repo_dir / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(z.read(name))


with ThreadPoolExecutor(16) as executor:
    futures: list[Future[None]] = []
    for bucket in BUCKETS:
        futures.append(executor.submit(download, bucket))

    for future in as_completed(futures):
        future.result()
