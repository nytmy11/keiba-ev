"""公開版が、GitHub に push 済みの snapshots を読む（再デプロイなしで確定データが残るように）。

読むのは公開リポジトリの raw URL だけ。トークンも GitHub への権限も使わない。
GitHub API は未認証だと IP あたり毎時60回で、Render の送信元 IP は他人と共有なので使わない。

- <base>/index.json: {日付: git の blob ハッシュ（ファイル内容の指紋）}。publish.py が snapshot と同じコミットで更新する
- <base>/<日付>.json.gz: index に載っている日付だけを取りに行く（閲覧者の入力で URL を作らない）。指紋が合わなければ使わない
GitHub に届かないときは、最後に読めたもの → デプロイに同梱した snapshots の順で代用する。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import urllib.request
from typing import Callable

from django.conf import settings

logger = logging.getLogger(__name__)

INDEX_NAME = "index.json"
INDEX_TTL = 300         # 一覧を読み直す間隔（秒）。raw 側のキャッシュも5分
RETRY_SEC = 60          # 失敗したら、この間は取りに行かない
TIMEOUT = 3             # Render のヘルスチェック（5秒以内に応答）を落とさない長さ
MAX_INDEX_BYTES = 256 * 1024
MAX_BLOB_BYTES = 5 * 1024 * 1024
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SHA = re.compile(r"[0-9a-f]{40}")

_index_lock, _blob_lock = threading.Lock(), threading.Lock()
_index: dict[str, str] = {}
_index_next = 0.0
_blobs: dict[str, tuple[str, bytes]] = {}  # 日付 → (指紋, 中身)
_blob_next: dict[str, float] = {}


def reset() -> None:
    """キャッシュを捨てる（テスト用）。"""
    global _index, _index_next
    _index, _index_next = {}, 0.0
    _blobs.clear()
    _blob_next.clear()


def blob_sha(content: bytes) -> str:
    """git と同じ計算のハッシュ。"""
    head = f"blob {len(content)}".encode() + bytes(1)
    return hashlib.sha1(head + content, usedforsecurity=False).hexdigest()


def _get(name: str, limit: int) -> bytes:
    url = f"{settings.KEIBA_EV_REMOTE_URL.rstrip('/')}/{name}"
    with urllib.request.urlopen(url, timeout=TIMEOUT) as res:
        body = res.read(limit + 1)
    if len(body) > limit:
        raise ValueError(f"{name} is too large")
    return body


def index() -> dict[str, str]:
    global _index, _index_next
    if not settings.KEIBA_EV_REMOTE_URL:
        return {}
    with _index_lock:
        if time.monotonic() >= _index_next:
            try:
                obj = json.loads(_get(INDEX_NAME, MAX_INDEX_BYTES))
                if not isinstance(obj, dict):
                    raise ValueError("index must be an object")
                _index = {d: s for d, s in obj.items()
                          if _DATE.fullmatch(d) and isinstance(s, str) and _SHA.fullmatch(s)}
                _index_next = time.monotonic() + INDEX_TTL
            except Exception as e:  # 通信断・404・壊れた JSON。画面は手元の分で出し続ける
                logger.warning("remote index unavailable: %s", e)
                _index_next = time.monotonic() + RETRY_SEC
        return _index


def read(date: str, bundled: bytes | None, check: Callable[[bytes], object]) -> bytes | None:
    """GitHub 側の方が新しければその中身。同梱分で足りる・読めないなら None。"""
    sha = index().get(date)
    if not sha or (bundled is not None and blob_sha(bundled) == sha):
        return None
    with _blob_lock:
        cached = _blobs.get(date)
        if cached and cached[0] == sha:
            return cached[1]
        if time.monotonic() >= _blob_next.get(date, 0.0):
            try:
                body = _get(f"{date}.json.gz", MAX_BLOB_BYTES)
                if blob_sha(body) != sha:
                    raise ValueError("hash does not match the index")
                check(body)
                _blobs[date] = (sha, body)
                logger.info("remote snapshot %s loaded (%d bytes)", date, len(body))
                return body
            except Exception as e:
                logger.warning("remote snapshot %s unavailable: %s", date, e)
                _blob_next[date] = time.monotonic() + RETRY_SEC
        return cached[1] if cached else None
