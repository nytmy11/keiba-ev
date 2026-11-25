"""自宅PCから公開版（Render）へ当日の EV を送る。deepimpact のデータは読むだけ。

使い方（.venv の python で実行する）:
  python publish.py live [--git-push]   開催日のループ。変化があれば送る。最終レース後に snapshots/ へ保存
  python publish.py push 2026-11-21     その日を1回だけ送る（動作確認用）
  python publish.py snapshot --all      snapshots/<日付>.json.gz を書き出す（リポジトリに入れる過去分）

送り先と合言葉は環境変数か、このフォルダの secrets.env（git に入れない）に書く:
  KEIBA_EV_PUSH_URL=https://<サービス名>.onrender.com
  KEIBA_EV_PUSH_TOKEN=<Render に設定したものと同じ文字列>

公開版へ送るのは data.PUBLIC_*_KEYS に載せた項目だけ（data.load_day(extras=False) → data.public_only）。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT / "backend"))
from ev import data, remote, store  # noqa: E402  (backend/ を path に足してから読む)

LOG_DIR = APP_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / f"publish_{datetime.now():%Y%m%d_%H%M%S}.log", encoding="utf-8"),
              logging.StreamHandler()],
)
logger = logging.getLogger("publish")

SNAPSHOT_DIR = APP_ROOT / "snapshots"
CHECK_SEC = 20            # deepimpact のファイルを見に行く間隔（オッズは約1分ごとに増える）
HEARTBEAT_SEC = 180       # 変化がなくてもこの間隔で送り直す（Render が再起動して消えた分を戻す）
GIVE_UP_AT = "12:30"      # ここまでに当日のオッズが出てこなければ「開催なし」として終わる
DONE_AFTER = "16:00"      # この時刻を過ぎ、かつ IDLE_DONE_MIN 分ファイルが増えなければ終了
IDLE_DONE_MIN = 30
HARD_STOP = "19:00"


def load_secrets() -> tuple[str, str]:
    env = APP_ROOT / "secrets.env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and not k.startswith("#"):
                os.environ.setdefault(k.strip(), v.strip())
    url = os.environ.get("KEIBA_EV_PUSH_URL", "").rstrip("/")
    token = os.environ.get("KEIBA_EV_PUSH_TOKEN", "")
    if not url or not token:
        sys.exit("KEIBA_EV_PUSH_URL と KEIBA_EV_PUSH_TOKEN を secrets.env か環境変数に設定してください")
    return url, token


def build(date: str) -> dict:
    """公開用の1日分。手元だけの追加表示は読まず、許可リストの項目だけにする。"""
    return data.public_only(data.load_day(date, extras=False))


def push(url: str, token: str, date: str, gz: bytes) -> bool:
    req = urllib.request.Request(
        f"{url}/api/push/{date}/", data=gz, method="POST",
        headers={"X-Push-Token": token, "Content-Type": "application/octet-stream"})
    try:
        # 無料枠はスリープから起きるのに最大1分ほどかかる
        with urllib.request.urlopen(req, timeout=90) as r:
            logger.info("push %s: %s (%d bytes)", date, r.read().decode()[:120], len(gz))
            return True
    except urllib.error.HTTPError as e:
        logger.error("push %s failed: HTTP %s %s", date, e.code, e.read().decode()[:200])
    except Exception as e:  # ネットワーク断・タイムアウト。次の周回でやり直す
        logger.warning("push %s failed: %s", date, e)
    return False


def write_snapshot(date: str, payload: dict) -> Path:
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    out = SNAPSHOT_DIR / f"{date}{store.SUFFIX}"
    out.write_bytes(store.encode(payload))
    return out


def git_push_snapshot(path: Path, date: str) -> None:
    """その日のスナップショットと一覧（index.json）を1コミットで push する。公開版は GitHub からこれを読む。"""
    def git(*args):
        # タスクスケジューラから pythonw で動くので、git のコンソール窓を出さない
        return subprocess.run(["git", "-C", str(APP_ROOT), *args], capture_output=True, text=True,
                              encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    rel = path.relative_to(APP_ROOT).as_posix()
    # 一覧は HEAD の中身＋この日の分だけで作る（手元にある未コミットの他の日を載せない）
    tree = git("ls-tree", "HEAD", "snapshots/")
    added = git("add", "--", rel)
    staged = git("rev-parse", f":{rel}")
    for r in (tree, added, staged):
        if r.returncode != 0:
            logger.error("snapshot index failed: %s", (r.stderr or r.stdout).strip()[:300])
            return
    shas = {}
    for line in tree.stdout.splitlines():
        _mode, _kind, sha, file = line.split(maxsplit=3)
        if file.endswith(store.SUFFIX):
            shas[file.rsplit("/", 1)[-1][: -len(store.SUFFIX)]] = sha
    shas[date] = staged.stdout.strip()
    index = path.parent / remote.INDEX_NAME
    index.write_bytes(json.dumps(shas, indent=1, sort_keys=True).encode())
    rels = (rel, index.relative_to(APP_ROOT).as_posix())
    git("add", "--", *rels)
    if git("diff", "--cached", "--quiet", "--", *rels).returncode == 0:
        logger.info("snapshot %s unchanged; nothing to commit", date)
        return
    # コミットはこの2ファイルだけに絞る（作業中の他の変更をうっかり公開しない）
    for args in (("commit", "-m", f"data: {date} のスナップショット", "--", *rels), ("push",)):
        r = git(*args)
        if r.returncode != 0:
            logger.error("git %s failed: %s", args[0], (r.stderr or r.stdout).strip()[:300])
            return
    logger.info("snapshot %s committed and pushed", date)


def source_mtime(date: str) -> int:
    paths = [src_file(date, "nk_odds_series"), src_file(date, "ev_audit")]
    return max((p.stat().st_mtime_ns for p in paths if p.exists()), default=0)


def src_file(date: str, kind: str) -> Path:
    return data.DATA_DIR / f"{kind}_{date}.parquet"


def hhmm() -> str:
    return datetime.now().strftime("%H:%M")


def live(git_push: bool) -> None:
    url, token = load_secrets()
    date = datetime.now().date().isoformat()
    logger.info("live loop for %s → %s", date, url)

    while not src_file(date, "nk_odds_series").exists():
        if hhmm() >= GIVE_UP_AT:
            logger.info("no odds series for %s by %s: no racing today", date, GIVE_UP_AT)
            return
        time.sleep(60)

    sent_core = b""          # 最後に送った中身（published_at を除く）
    sent_gz = b""            # 最後に送ったバイト列そのもの（ハートビートで再送する）
    sent_at = 0.0
    last_mtime, last_change = 0, time.time()
    payload = None
    while True:
        m = source_mtime(date)
        if m != last_mtime:
            last_mtime, last_change = m, time.time()
        try:
            payload = build(date)
        except Exception:
            logger.exception("build failed for %s; retry next round", date)
            time.sleep(CHECK_SEC)
            continue
        core = store.encode(payload)
        if core != sent_core:
            stamped = {**payload, "published_at": datetime.now().isoformat(timespec="seconds")}
            gz = store.encode(stamped)
            if push(url, token, date, gz):
                sent_core, sent_gz, sent_at = core, gz, time.time()
        elif time.time() - sent_at >= HEARTBEAT_SEC and sent_gz:
            if push(url, token, date, sent_gz):
                sent_at = time.time()

        idle_min = (time.time() - last_change) / 60
        if hhmm() >= HARD_STOP or (hhmm() >= DONE_AFTER and idle_min >= IDLE_DONE_MIN):
            break
        time.sleep(CHECK_SEC)

    logger.info("racing over for %s (idle %.0f min)", date, idle_min)
    # 最後の送信に失敗していても、確定版には最新の中身を残す（GitHub の分が公開版の正になる）
    final = store.decode(sent_gz) if core == sent_core else {**payload, "published_at": None}
    path = write_snapshot(date, final)
    logger.info("wrote %s (%d bytes)", path, path.stat().st_size)
    if git_push:
        git_push_snapshot(path, date)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_live = sub.add_parser("live", help="開催日のループ")
    p_live.add_argument("--git-push", action="store_true", help="最終レース後に snapshots をコミットして push する")
    p_push = sub.add_parser("push", help="指定日を1回だけ送る")
    p_push.add_argument("date")
    p_snap = sub.add_parser("snapshot", help="snapshots/ に書き出す")
    p_snap.add_argument("dates", nargs="*")
    p_snap.add_argument("--all", action="store_true", help="データのある全日")
    a = ap.parse_args()

    if a.cmd == "live":
        live(a.git_push)
    elif a.cmd == "push":
        url, token = load_secrets()
        payload = {**build(a.date), "published_at": datetime.now().isoformat(timespec="seconds")}
        sys.exit(0 if push(url, token, a.date, store.encode(payload)) else 1)
    else:
        dates = data.available_dates() if a.all else a.dates
        for d in dates:
            path = write_snapshot(d, build(d))
            logger.info("wrote %s (%d bytes)", path.name, path.stat().st_size)


if __name__ == "__main__":
    main()
