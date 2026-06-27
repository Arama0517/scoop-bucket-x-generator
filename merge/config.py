from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from re import IGNORECASE, MULTILINE, Match, Pattern, compile

import orjson

CURRENT_DIR: Path = Path.cwd()
BUCKETS_DIR: Path = CURRENT_DIR / "buckets"
RESULTS_DIR: Path = CURRENT_DIR / "results"

INDEX_BUCKETS_FILE: Path = CURRENT_DIR / "index_buckets.json"

GITHUB_URL: bytes = b"https://v4.gh-proxy.org"

INVALID_GITHUB_URL: list[bytes] = [
    b"https://ghfast.top",
    b"https://ghproxy.com",
    b"https://gh-proxy.com",
    b"https://ghproxy.net",
    b"https://mirror.ghproxy.com",
    b"https://ghp.ci",
    b"https://ghgo.xyz",
    b"https://gh-proxy.org",
    b"https://hk.gh-proxy.org",
    b"https://v6.gh-proxy.org",
    b"https://cdn.gh-proxy.org",
    b"https://edgeone.gh-proxy.org",
]

SOURCEFORGE_URL: bytes = b"https://v4.gh-proxy.org/sourceforge"

SYNC_DIRS_NAME: list[str] = ["bucket", "scripts"]

IGNORE_FILES_NAME: list[str] = [
    ".gitkeep",
    "readme",
    "__",
    "template",
    "模板",
    r"\(\d+\)",
]


@dataclass(frozen=True, slots=True)
class Bucket:
    url: str
    stars: int
    repo_dir: Path = field(init=False)

    def __post_init__(self):
        object.__setattr__(
            self,
            "repo_dir",
            BUCKETS_DIR / self.get_bucket_key(self.url).replace("/", "_"),
        )

    @staticmethod
    def get_bucket_key(url: str) -> str:
        return url.removeprefix("https://github.com/").rstrip("/").lower()


BUCKETS: list[Bucket] = []

if INDEX_BUCKETS_FILE.exists():
    cache_buckets = orjson.loads(INDEX_BUCKETS_FILE.read_bytes())
    for bucket in cache_buckets:
        BUCKETS.append(Bucket(bucket["url"], bucket["stars"]))

type Rule = tuple[Pattern[bytes] | bytes, bytes | Callable[[Match[bytes]], bytes]]


def _compile(pattern: str) -> Pattern[bytes]:
    return compile(pattern.encode("utf-8"), IGNORECASE | MULTILINE)


VERSION_PATTERN: Pattern[str] = compile(r"[^\d.]", IGNORECASE | MULTILINE)

DEFAULT_RULES: list[Rule] = [
    (_compile(r"\$bucketsdir\\\\[a-zA-Z0-9.-]+\\\\"), rb"$bucketsdir\\\\$bucket\\\\"),
    (
        _compile(
            r"Find-BucketDirectory\s*(?:\([a-zA-Z0-9.-]+\)|-Root\s+-Name\s+[a-zA-Z0-9.-]+)"
        ),
        rb"Find-BucketDirectory -Root -Name main",
    ),
    (
        _compile(r'"(?!\$)[a-zA-Z0-9._-]+\\\\scripts\\\\'),
        rb'"main\\\\scripts\\\\',
    ),
]

GITHUB_RULES: list[Rule] = [
    *[(url, GITHUB_URL) for url in INVALID_GITHUB_URL],
    (
        _compile(r"https://github\.com"),
        lambda m: GITHUB_URL + b"/" + m.group(0),
    ),
    (
        _compile(r"https://[a-zA-Z0-9.-]+\.githubusercontent.com"),
        lambda m: GITHUB_URL + b"/" + m.group(0),
    ),
    (GITHUB_URL + b"/" + GITHUB_URL, GITHUB_URL),
    (
        _compile(rf"https://[a-zA-Z0-9.-]+/{GITHUB_URL}/https:"),
        GITHUB_URL + rb"/https:",
    ),
]

SOURCEFORGE_RULES: list[Rule] = [
    (
        _compile(r"https://[a-zA-Z0-9.-]+.sourceforge.net"),
        lambda m: SOURCEFORGE_URL + b"/" + m.group(0),
    ),
    (SOURCEFORGE_URL + b"/" + SOURCEFORGE_URL, SOURCEFORGE_URL),
    (
        _compile(rf"https://[a-zA-Z0-9.-]+/{SOURCEFORGE_URL}/https:"),
        SOURCEFORGE_URL + rb"/https:",
    ),
]

PHP_RULES: list[Rule] = [
    (
        rb"bin\\postinstall.ps1",
        rb"bin\\php-postinstall.ps1",
    )
]

NODEJS_RULES: list[Rule] = [
    (
        rb"https://nodejs.org/dist/",
        rb"https://registry.npmmirror.com/-/binary/node/",
    )
]

__all__: list[str] = [
    "BUCKETS",
    "BUCKETS_DIR",
    "CURRENT_DIR",
    "DEFAULT_RULES",
    "GITHUB_RULES",
    "GITHUB_URL",
    "IGNORE_FILES_NAME",
    "INDEX_BUCKETS_FILE",
    "INVALID_GITHUB_URL",
    "NODEJS_RULES",
    "PHP_RULES",
    "RESULTS_DIR",
    "SOURCEFORGE_RULES",
    "SOURCEFORGE_URL",
    "SYNC_DIRS_NAME",
    "VERSION_PATTERN",
    "Bucket",
    "Rule",
]
