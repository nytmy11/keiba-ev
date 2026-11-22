"""公開版（Render）のデータ置き場。pandas を使わず、計算済みの JSON（gzip）を読み書きするだけ。

自宅PCの publish.py が計算した1日分を POST /api/push/<日付>/ で送ってくる。
それを PUSH_DIR に保存し、閲覧者にはそのまま返す。

- PUSH_DIR: 送られてきた当日分。Render の無料枠はディスクが一時的なので、再起動で消える
- SNAPSHOT_DIR: リポジトリに入っている過去分（snapshots/<日付>.json.gz）。再起動しても残る
同じ日付が両方にあれば PUSH_DIR（新しい方）を優先する。
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

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # data.py と同じ（pandas を読み込まないよう複製）
SUFFIX = ".json.gz"
MAX_JSON_BYTES = 20 * 1024 * 1024  # 展開後の上限（1日分は 0.5MB 前後）


def _dirs() -> list[Path]:
    return [Path(settings.KEIBA_EV_PUSH_DIR), Path(settings.KEIBA_EV_SNAPSHOT_DIR)]


def available_dates() -> list[str]:
    dates = set()
    for d in _dirs():
        if d.is_dir():
            for p in d.glob(f"*{SUFFIX}"):
                name = p.name[: -len(SUFFIX)]
                if DATE_RE.match(name):
                    dates.add(name)
    return sorted(dates, reverse=True)


def find(date: str) -> Path | None:
    if not DATE_RE.match(date):
        return None
    for d in _dirs():
        p = d / f"{date}{SUFFIX}"
        if p.exists():
            return p
    return None


def read_gz(date: str) -> bytes | None:
    """保存されている gzip のバイト列をそのまま返す（ブラウザへ Content-Encoding: gzip で渡す）。"""
    p = find(date)
    return p.read_bytes() if p else None


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
