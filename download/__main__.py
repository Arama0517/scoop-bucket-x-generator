import contextlib
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import SpooledTemporaryFile
from zipfile import ZipFile, ZipInfo

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

            with ZipFile(tmp) as z:
                infos: list[ZipInfo] = z.infolist()
                root: str = infos[0].filename.split("/", 1)[0] + "/"

                if not any(i.filename.startswith(f"{root}bucket/") for i in infos):
                    return

                for info in infos:
                    rel: str = info.filename[len(root) :]
                    if not rel or info.filename.endswith("/"):
                        continue

                    if not any(
                        rel == d or rel.startswith(d + "/") for d in SYNC_DIRS_NAME
                    ):
                        continue

                    dst: Path = bucket.repo_dir / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src_f, dst.open("wb") as f:
                        shutil.copyfileobj(src_f, f, length=1024 * 1024)


with ThreadPoolExecutor(16) as executor:
    list(executor.map(download, BUCKETS))
