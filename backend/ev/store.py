"""公開版（Render）のデータ置き場。pandas を使わず、計算済みの JSON（gzip）を読み書きするだけ。

自宅PCの publish.py が計算した1日分を POST /api/push/<日付>/ で送ってくる。
それを PUSH_DIR に保存し、閲覧者にはそのまま返す。

- PUSH_DIR: 送られてきた当日分。Render の無料枠はディスクが一時的なので、再起動で消える
- GitHub の snapshots: デプロイ後に確定した分（remote.py）。再起動しても読み直せる
- SNAPSHOT_DIR: デプロイに同梱された過去分（snapshots/<日付>.json.gz）。GitHub に届かないときの控えも兼ねる
同じ日付があれば、この順に優先する。
gunicorn のワーカーが複数でも食い違わないよう、メモリではなくファイルを正とする。
"""
from __future__ import annotations

import gzip
import json
import os
import re
import zlib
from pathlib import Path

from django.conf import settings

from . import remote

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # data.py と同じ（pandas を読み込まないよう複製）
SUFFIX = ".json.gz"
MAX_JSON_BYTES = 20 * 1024 * 1024  # 展開後の上限（1日分は 0.5MB 前後）


def _dirs() -> list[Path]:
    return [Path(settings.KEIBA_EV_PUSH_DIR), Path(settings.KEIBA_EV_SNAPSHOT_DIR)]


def available_dates() -> list[str]:
    dates = set(remote.index())
    for d in _dirs():
        if d.is_dir():
            for p in d.glob(f"*{SUFFIX}"):
                name = p.name[: -len(SUFFIX)]
                if DATE_RE.match(name):
                    dates.add(name)
    return sorted(dates, reverse=True)


def read_gz(date: str) -> bytes | None:
    """gzip のバイト列をそのまま返す（ブラウザへ Content-Encoding: gzip で渡す）。"""
    if not DATE_RE.match(date):
        return None
    pushed, bundled = (d / f"{date}{SUFFIX}" for d in _dirs())
    if pushed.exists():
        return pushed.read_bytes()
    local = bundled.read_bytes() if bundled.exists() else None

    def check(gz: bytes) -> None:
        if decode(gz).get("date") != date:
            raise ValueError("payload date does not match the file name")

    return remote.read(date, local, check) or local


def decode(gz: bytes) -> dict:
    """gzip → dict。展開後のサイズに上限をかける（圧縮爆弾よけ）。"""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        raw = d.decompress(gz, MAX_JSON_BYTES + 1)
    except zlib.error as e:
        raise ValueError(f"bad gzip: {e}") from e
    if len(raw) > MAX_JSON_BYTES or d.unconsumed_tail:
        raise ValueError("payload too large")
    obj = json.loads(raw)
    if not isinstance(obj, dict) or not isinstance(obj.get("races"), list):
        raise ValueError("payload must be an object with a races list")
    return obj


def save_push(date: str, gz: bytes) -> dict:
    """検証してから PUSH_DIR/<date>.json.gz に原子的に書く（読み手が書きかけを掴まない）。"""
    if not DATE_RE.match(date):
        raise ValueError("date must be YYYY-MM-DD")
    obj = decode(gz)
    if obj.get("date") != date:
        raise ValueError("payload date does not match the URL")
    out = Path(settings.KEIBA_EV_PUSH_DIR)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / f".{date}.{os.getpid()}.tmp"
    tmp.write_bytes(gz)
    os.replace(tmp, out / f"{date}{SUFFIX}")
    return obj


def encode(payload: dict) -> bytes:
    """dict → gzip。publish.py と snapshot の書き出しで使う。mtime=0 で中身が同じなら同じバイト列になる。"""
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, mtime=0)
