import os
import re
import sqlite3
import time
from re import Match
from sqlite3 import Cursor
from typing import Any
from urllib.parse import urljoin

import orjson
import requests
from requests import Response, Session

from merge.config import CACHE_BUCKETS_FILE, CURRENT_DIR, Bucket

buckets: dict[str, Bucket] = {}

# Scoop Directory
with sqlite3.connect(CURRENT_DIR / "scoop_directory.db") as connect:
    cursor: Cursor = connect.cursor()
    cursor.execute("SELECT bucket_url, stars FROM buckets")
    for url, stars in cursor.fetchall():
        buckets[Bucket.get_bucket_key(url)] = Bucket(url, stars)

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


def get_github_stars(session: Session, url: str) -> int:
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

    return response.json()["stargazers_count"]


def get_azure_stars(session: Session, url: str) -> int:
    for i in range(3):
        response: Response = session.post(
            "https://scoopsearch.search.windows.net/indexes/apps/docs/search?api-version=2020-06-30",
            json={
                "search": f'"{url}"',
                "select": "Metadata/RepositoryStars",
                "top": 1,
            },
            headers={"api-key": AZURE_SEARCH_KEY},
            timeout=60,
        )

        if response.status_code == 200:
            return response.json()["value"][0]["Metadata"]["RepositoryStars"]

        if response.status_code in (429, 503):
            time.sleep(2**i)
            continue

        response.raise_for_status()

    raise RuntimeError("azure failed")


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

    use_azure = True

    for repo in repos:
        url = repo["value"]
        if not url:
            continue

        if official:
            stars = 90000
        else:
            try:
                if use_azure:
                    stars: int = get_azure_stars(session, url)
                else:
                    raise RuntimeError()
            except Exception:
                use_azure = False
                stars: int = get_github_stars(session, url)

        buckets[Bucket.get_bucket_key(url)] = Bucket(url, stars)


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
    buckets[Bucket.get_bucket_key(url)] = Bucket(url, stars)

# 防止重复
buckets.pop(Bucket.get_bucket_key("https://github.com/Arama0517/scoop-bucket-x"), None)

result: list[dict[str, str | int]] = []
for bucket in sorted(buckets.values(), key=lambda b: b.stars, reverse=True):
    result.append({"url": bucket.url, "stars": bucket.stars})

CACHE_BUCKETS_FILE.write_bytes(orjson.dumps(result))
