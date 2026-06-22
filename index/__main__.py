import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from re import Match
from sqlite3 import Cursor
from typing import Any
from urllib.parse import urljoin

import orjson
import requests
from requests import Response, Session

from merge.config import CACHE_BUCKETS_FILE, CURRENT_DIR, Bucket

buckets: dict[str, Bucket] = {}

placehold_time: datetime = datetime.now(UTC) + timedelta(days=30 * 365)

# Scoop Directory
with sqlite3.connect(CURRENT_DIR / "scoop_directory.db") as connect:
    cursor: Cursor = connect.cursor()
    cursor.execute("SELECT bucket_url, stars, updated FROM buckets")
    for url, stars, updated in cursor.fetchall():
        updated = updated.replace("&#x2011;", "-")
        buckets[Bucket.get_bucket_key(url)] = Bucket(
            url,
            stars,
            datetime.strptime(updated, "%y-%m-%d").astimezone(UTC),
        )

# Scoop Search
base_url = "https://scoop.sh"
response: Response = requests.get(f"{base_url}/#/apps", timeout=60)
response.raise_for_status()

match_str: Match[str] | None = re.search(
    r'<script type="module" crossorigin src="(.*?)"></script>', response.text
)
if not match_str:
    raise ValueError("JavaScript file not found.")

script_url: str | Any = match_str.group(1)
if not script_url.startswith("http"):
    script_url: str = urljoin(base_url, script_url)


response: Response = requests.get(script_url, timeout=60)
response.raise_for_status()

match_key: Match[str] | None = re.search(
    r'VITE_APP_AZURESEARCH_KEY:"(.*?)"', response.text
)
if not match_key:
    raise ValueError("Key not found.")
AZURE_SEARCH_KEY: str = match_key.group(1)


def from_scoop_sh(official: bool, count: int = 100000):
    session = Session()
    response: Response = session.post(
        "https://scoopsearch.search.windows.net/indexes/apps/docs/search?api-version=2020-06-30",
        json={
            "facets": [f"Metadata/Repository,count:{count}"],
            "filter": f"Metadata/OfficialRepositoryNumber eq {1 if official else 0}",
            "top": 0,
        },
        headers={"api-key": AZURE_SEARCH_KEY},
        timeout=60,
    )
    response.raise_for_status()
    repos = response.json()["@search.facets"]["Metadata/Repository"]

    for repo in repos:
        url = repo["value"]
        if not url:
            continue

        if official:
            stars = 90000
            updated_time: datetime = placehold_time
        else:
            repo = url.replace("https://github.com/", "")

            response: Response = session.get(
                f"https://api.github.com/repos/{repo}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                },
                timeout=30,
            )

            response.raise_for_status()
            data: Any = response.json()
            stars = data["stargazers_count"]
            updated_time: datetime = datetime.fromisoformat(
                data["updated_at"].replace("Z", "+00:00")
            ).astimezone(UTC)
        buckets[Bucket.get_bucket_key(url)] = Bucket(url, stars, updated_time)


from_scoop_sh(True)
from_scoop_sh(False)


# 预定义
predefine_buckets: dict[str, int] = {
    "https://github.com/Arama0517/scoop-bucket-x-generator": 100000,
    "https://github.com/anderlli0053/DEV-tools": -60000,
    "https://github.com/kkzzhizhou/scoop-apps": -70000,
    "https://github.com/cmontage/scoopbucket-third": -80000,
    "https://github.com/lzwme/scoop-proxy-cn": -90000,
    "https://github.com/okibcn/ScoopMaster": -100000,
}
for url, stars in predefine_buckets.items():
    buckets[Bucket.get_bucket_key(url)] = Bucket(url, stars, placehold_time)

# 防止重复
buckets.pop(Bucket.get_bucket_key("https://github.com/Arama0517/scoop-bucket-x"), None)

result: list[dict[str, str | int | datetime]] = []
for bucket in sorted(buckets.values(), key=lambda b: b.stars, reverse=True):
    result.append({
        "url": bucket.url,
        "stars": bucket.stars,
        "updated_time": bucket.updated_time,
    })

CACHE_BUCKETS_FILE.write_bytes(orjson.dumps(result))
