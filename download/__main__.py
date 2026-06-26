import asyncio
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import aiofiles
import aiohttp

from merge.config import BUCKETS, SYNC_DIRS_NAME, Bucket

semaphore = asyncio.Semaphore(24)


def unzip(data: bytes) -> Iterator[tuple[bytes, str]]:
    with ZipFile(BytesIO(data)) as z:
        infos = z.infolist()
        root = infos[0].filename.split("/", 1)[0] + "/"

        if not any(i.filename.startswith(f"{root}bucket/") for i in infos):
            return

        for info in infos:
            rel: str = info.filename[len(root) :]
            if not rel or info.filename.endswith("/"):
                continue

            if not any(rel == d or rel.startswith(d + "/") for d in SYNC_DIRS_NAME):
                continue

            yield z.open(info).read(), rel


async def download(bucket: Bucket, session: aiohttp.ClientSession) -> None:
    async with semaphore:
        async with session.get(
            bucket.url.rstrip("/") + "/archive/HEAD.zip"
        ) as response:
            if response.status != 200:
                return
            data: bytes = await response.read()
            if not data.startswith(b"PK\x03\x04"):
                return
        for raw, rel in await asyncio.to_thread(unzip, data):
            dst: Path = bucket.repo_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)

            async with aiofiles.open(dst, "wb") as f:
                await f.write(raw)


async def main():
    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(download(b, session)) for b in BUCKETS]
        await asyncio.gather(*tasks)


asyncio.run(main())
