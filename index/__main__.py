import os
import re
import time
from datetime import UTC, datetime, timedelta
from re import Match
from typing import Any, Literal
from urllib.parse import urljoin

import orjson
import requests
from requests import Response, Session

from merge.config import INDEX_BUCKETS_FILE, Bucket

buckets: dict[str, Bucket] = {}


class GitHubClient:
    def __init__(self, token: str):
        self.session = Session()
        self.token: str = token

        self.use_graphql = True

        self.rest_remaining = None
        self.rest_reset = 0

        self.graphql_remaining = None
        self.graphql_reset = 0

    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
        }

    def _sleep_if_needed(self):
        now: int | float = time.time()

        if self.use_graphql:
            if self.graphql_remaining is not None and self.graphql_remaining <= 0:
                wait: int | float = self.graphql_reset - now
                if wait > 0:
                    time.sleep(wait + 1)
        else:
            if self.rest_remaining is not None and self.rest_remaining <= 0:
                wait: int | float = self.rest_reset - now
                if wait > 0:
                    time.sleep(wait + 1)

    def _switch(self):
        now: int | float = time.time()

        if self.use_graphql:
            if self.graphql_remaining is not None and self.graphql_remaining <= 2:
                self.use_graphql = False
            if self.graphql_reset and now >= self.graphql_reset:
                self.graphql_remaining = None
        else:
            if self.rest_remaining is not None and self.rest_remaining <= 2:
                self.use_graphql = True
            if self.rest_reset and now >= self.rest_reset:
                self.rest_remaining = None

    def rest_repo(self, full_name: str):
        self._switch()
        self._sleep_if_needed()

        resp = self.session.get(
            f"https://api.github.com/repos/{full_name}",
            headers=self.headers(),
            timeout=30,
        )

        self.rest_remaining = int(resp.headers.get("X-RateLimit-Remaining", 0) or 0)
        self.rest_reset = int(resp.headers.get("X-RateLimit-Reset", 0) or 0)

        if resp.status_code == 404:
            raise ValueError("not found")

        if resp.status_code in (403, 429):
            self.use_graphql = True
            raise RuntimeError("REST rate limited")

        return resp.json()

    def graphql_repo(self, owner: str, name: str):
        self._switch()
        self._sleep_if_needed()

        query = """
        query($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            stargazerCount
            updatedAt
          }
          rateLimit {
            remaining
            resetAt
          }
        }
        """

        response: Response = self.session.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": {"owner": owner, "name": name}},
            headers=self.headers(),
            timeout=30,
        )

        data = response.json()

        rate_limit = data.get("data", {}).get("rateLimit")
        if rate_limit:
            self.graphql_remaining = rate_limit.get("remaining", 0)
            self.graphql_reset: int | float = datetime.strptime(
                rate_limit["resetAt"], "%Y-%m-%dT%H:%M:%SZ"
            ).timestamp()

        if response.status_code in (403, 429) or "errors" in data:
            self.use_graphql = False
            raise RuntimeError("GraphQL rate limited")

        repo = data.get("data", {}).get("repository")
        if repo is None:
            raise ValueError("not found")

        repo = data["data"]["repository"]
        return {
            "stars": repo["stargazerCount"],
            "updated_at": repo["updatedAt"],
        }

    def get_repo(self, full_name: str):
        try:
            if self.use_graphql:
                owner, name = full_name.split("/")
                return self.graphql_repo(owner, name)
        except ValueError:
            return {}
        except Exception:
            pass

        data = self.rest_repo(full_name)
        return {
            "stars": data["stargazers_count"],
            "updated_at": data["updated_at"],
        }


client = GitHubClient(os.environ["GITHUB_TOKEN"])

session = Session()

search_terms: list[str] = [
    "topic:scoop-bucket",
    "scoop-bucket",
    "scoop bucket",
    "scoop",
]

SLEEP_SECONDS = 60
MAX_SLEEP_SECONDS: Literal[3840] = SLEEP_SECONDS * 64

for search in search_terms:
    for page in range(1, 7):
        sleep_seconds: Literal[60] = SLEEP_SECONDS
        while sleep_seconds <= MAX_SLEEP_SECONDS:
            response = session.get(
                "https://api.github.com/search/repositories",
                params={
                    "q": search,
                    "per_page": 100,
                    "page": page,
                },
                headers=client.headers(),
                timeout=30,
            )

            # 422: reached 1,000 search limit
            if response.status_code < 300 or response.status_code == 422:
                break

            if response.status_code == 403:
                limit = int(response.headers["X-RateLimit-Limit"])
                remaining = int(response.headers["X-RateLimit-Remaining"])
                reset = int(response.headers["X-RateLimit-Reset"])
                waitSeconds: int | float = float(reset) - time.time()
                if remaining < 1 and waitSeconds > sleep_seconds:
                    sleep_seconds: int | float = waitSeconds
                time.sleep(sleep_seconds)
                sleep_seconds: int | float = sleep_seconds * 2
                continue

        items = response.json().get("items", [])

        for repo in items:
            url = repo["html_url"]
            buckets[Bucket.get_bucket_key(url)] = Bucket(
                url,
                repo["stargazers_count"],
                datetime.strptime(repo["updated_at"], "%Y-%m-%dT%H:%M:%SZ").astimezone(
                    UTC
                ),
            )

placehold_time: datetime = datetime.now(UTC) + timedelta(days=365 * 20)

base_url = "https://scoop.sh"
response: Response = requests.get(f"{base_url}/#/apps", timeout=60)
response.raise_for_status()

match_str: Match[str] | None = re.search(
    r'<script type="module" crossorigin src="(.*?)"></script>', response.text
)

if not match_str:
    raise ValueError("JavaScript file not found.")

script_url = match_str.group(1)

if not script_url.startswith("http"):
    script_url = urljoin(base_url, script_url)

response = requests.get(script_url, timeout=60)
response.raise_for_status()

match_key: Match[str] | None = re.search(
    r'VITE_APP_AZURESEARCH_KEY:"(.*?)"', response.text
)

if not match_key:
    raise ValueError("Key not found.")

AZURE_SEARCH_KEY = match_key.group(1)


def from_scoop_sh(official: bool, count: int = 100000):
    session = Session()

    response = session.post(
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
            updated_time = placehold_time
        else:
            repo_full = url.replace("https://github.com/", "")

            not_found = False
            for _ in range(3):
                try:
                    data = client.get_repo(repo_full)
                    if not data:
                        not_found = True
                        break
                    stars = data["stars"]
                    updated_time = datetime.fromisoformat(
                        data["updated_at"].replace("Z", "+00:00")
                    ).astimezone(UTC)
                    break
                except Exception:
                    continue
            if not_found:
                continue

        buckets[Bucket.get_bucket_key(url)] = Bucket(url, stars, updated_time)


from_scoop_sh(True)
from_scoop_sh(False)


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

for bucket in sorted(buckets.values(), key=lambda b: b.url, reverse=True):
    result.append({
        "url": bucket.url,
        "stars": bucket.stars,
        "updated_time": bucket.updated_time,
    })

INDEX_BUCKETS_FILE.write_bytes(orjson.dumps(result))
