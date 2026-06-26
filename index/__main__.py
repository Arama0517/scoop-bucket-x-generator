import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import orjson
from requests import Response, Session

from merge.config import INDEX_BUCKETS_FILE, Bucket

buckets: dict[str, Bucket] = {}


class GitHubClient:
    session: Session

    def __init__(self, token: str):
        self.session = Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        })

    def get_enumerable(self, search: str):
        page = 1
        pages_total = 10000

        while page < pages_total:
            for _ in range(3):
                response: Response = self.session.get(
                    "https://api.github.com/search/repositories",
                    params={
                        "q": search,
                        "per_page": 100,
                        "page": page,
                        "sort": "updated",
                    },
                )

                if response.status_code == 403:
                    time.sleep(
                        int(response.headers["X-RateLimit-Reset"]) - time.time() + 2
                    )
                    continue

                # Only the first 1000 search results are available
                if response.status_code == 422:
                    return

                if response.status_code == 200:
                    data = response.json()
                    pages_total: int | float = int(data["total_count"]) / 100

                    yield from data["items"]
                    break
            page += 1
            time.sleep(2)


# from https://github.com/ScoopInstaller/scoopinstaller.github.io-indexer/blob/main/src/ScoopSearch.Indexer/appsettings.json
create_times: list[str] = ["created:<2020-01-01"]

now: datetime = datetime.now(UTC)
for year in range(2020, now.year):
    create_times.append(f"created:{year}-01-01..{year}-06-30")
    create_times.append(f"created:{year}-07-01..{year}-12-31")

today: str = now.strftime("%Y-%m-%d")
if now > datetime(now.year, 7, 1, tzinfo=UTC):
    create_times.append(f"created:{now.year}-01-01..{now.year}-06-30")
    create_times.append(f"created:{now.year}-07-01..{today}")
else:
    create_times.append(f"created:{now.year}-01-01..{today}")

create_times.reverse()

search_terms: list[str] = ["topic:scoop-bucket"]
for create_time in create_times:
    search_terms.append(f"scoop-bucket {create_time}")
    search_terms.append(f"scoop bucket {create_time}")
    search_terms.append(f"scoop {create_time}")


client = GitHubClient(os.environ["GITHUB_TOKEN"])

for search in search_terms:
    for repo in client.get_enumerable(search):
        url = repo["html_url"]
        buckets[Bucket.get_bucket_key(url)] = Bucket(
            url,
            repo["stargazers_count"],
            datetime.strptime(repo["updated_at"], "%Y-%m-%dT%H:%M:%SZ").astimezone(UTC),
        )

placehold_time: datetime = datetime.now(UTC) + timedelta(days=365 * 20)


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

buckets.pop(
    Bucket.get_bucket_key("https://github.com/Arama0517/scoop-bucket-x"),
    None,
)


result: list[dict[str, Any]] = []

for bucket in sorted(buckets.values(), key=lambda b: b.stars, reverse=True):
    result.append({
        "url": bucket.url,
        "stars": bucket.stars,
        "updated_time": bucket.updated_time,
    })

INDEX_BUCKETS_FILE.write_bytes(orjson.dumps(result))
