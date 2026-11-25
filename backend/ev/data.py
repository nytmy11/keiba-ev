"""Read deepimpact's parquet files (read-only) and recompute EV over time.

EV(t) = p_ens * place_odds(t)
  - p_ens: the model's place probability, logged once per race about
    3 minutes before the close (ev_audit_<date>.parquet)
  - place_odds(t): place odds recorded every ~1min
    (nk_odds_series_<date>.parquet; place_low = the lower bound,
    place_mid = midpoint of the low/high range)

p_ens is only known from that moment on, so EV before it is
"hindsight" (today's p_ens applied to earlier odds). The payload carries
audit_at so the UI can tell the two apart.

予測の段階（phase）: deepimpact の記録係（scripts/ops/viewer_snapshot.py）が
data/viewer/<日付>/<race_id>.parquet に、発走前の予測を数分ごとに残している。
  - S3/S4 = JRDB の TYB（パドック・馬体重など）が届く前の仮の予測 → phase "pre"
  - S5    = TYB が届いた後。本番のループと同じ入力 → phase "tyb"
  - 確定  = 本番が締切約3分前に記録した p_ens → phase "final"
tyb_at は TYB が届いた時刻（h14_shadow の first_seen_at と、記録係の最初の S5 の早い方）。

公開版へ送るのは PUBLIC_*_KEYS に載せた項目だけ（public_only）。
手元の画面にだけ出す追加の表示は ev/local_extras.py に置く（リポジトリには入れない。無くても動く）。

Horse names / sex-age / jockey and race names come from deepimpact's SQLite
DB (race_results_clean), opened read-only.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from datetime import date as _date
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 既定は keiba-ev から見た相対位置（…/project/deepimpact）。別の場所なら環境変数で指定する
_DEEPIMPACT = Path(__file__).resolve().parents[5] / "deepimpact"
DATA_DIR = Path(os.environ.get("KEIBA_EV_DATA", _DEEPIMPACT / "data" / "live_picks"))
DB_PATH = Path(os.environ.get("KEIBA_EV_DB", _DEEPIMPACT / "store" / "db" / "manage.db"))
VIEWER_DIR = Path(os.environ.get("KEIBA_EV_VIEWER", _DEEPIMPACT / "data" / "viewer"))
VIEWER_COLS = ["logged_at", "race_id", "horse_num", "p_place_prod", "stage"]  # 必要な列だけ読む（他の列は読まない）
VIEWER_MATCH = pd.Timedelta(minutes=6)  # 記録係は T-15 までは5分ごと。これより古い記録はその時刻の予測として使わない
PHASE = {"S3": "pre", "S4": "pre", "S5": "tyb"}
EV_THR_DEFAULT = 1.15  # 画面のしきい値の既定値
VENUE = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
         "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WEEKDAY = "月火水木金土日"
COURSE = {"芝": "芝", "ダート": "ダ", "障害": "障"}

# 公開版へ送ってよい項目（許可リスト）。ここに無い項目は public_only で落とす
PUBLIC_DAY_KEYS = frozenset({"date", "weekday", "meetings", "ev_thr_default", "races"})
PUBLIC_RACE_KEYS = frozenset({"race_id", "label", "venue", "rno", "meeting", "race_name", "course", "ground",
                              "hasso", "audit_at", "tyb_at", "phase", "times", "mins", "horses"})
PUBLIC_HORSE_KEYS = frozenset({"num", "name", "sex_age", "jockey", "kinryo", "p_ens",
                               "win", "low", "high", "ev_low", "ev_mid", "p"})

try:  # 手元（自宅PC）だけの追加表示。リポジトリには入れない（.gitignore）
    from . import local_extras
except ImportError:
    local_extras = None

_cache: dict[tuple[str, bool], tuple[tuple, dict]] = {}


def _path(kind: str, date: str) -> Path:
    return DATA_DIR / f"{kind}_{date}.parquet"


def available_dates() -> list[str]:
    dates = set()
    for kind in ("nk_odds_series", "ev_audit"):
        for p in DATA_DIR.glob(f"{kind}_*.parquet"):
            d = p.stem[len(kind) + 1:]
            if DATE_RE.match(d):
                dates.add(d)
    return sorted(dates, reverse=True)


def _read(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_parquet(path)


def load_entries(date: str) -> pd.DataFrame | None:
    """Race card (horse name, sex, age, jockey, race name) for the date; None if unavailable."""
    if not DB_PATH.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        try:
            return pd.read_sql_query(
                "SELECT race_id, horse_num, horse_name, gender, age, weight, jockey, "
                "race_name, course_len, race_type, ground_state "
                "FROM race_results_clean WHERE race_date = ?", con, params=(date,))
        finally:
            con.close()
    except Exception as e:  # DB locked or being rebuilt: show the heatmap without names
        logger.warning("race card unavailable for %s: %s", date, e)
        return None


def _viewer_files(date: str) -> list[Path]:
    return sorted((VIEWER_DIR / date).glob("2*.parquet"))


def load_viewer(files: list[Path]) -> pd.DataFrame | None:
    """記録係の予測（p_place_prod と段階だけ）。読めないファイルは飛ばす（書き込み中など）。"""
    frames = []
    for f in files:
        try:
            frames.append(pd.read_parquet(f, columns=VIEWER_COLS))
        except Exception as e:
            logger.warning("viewer file skipped %s: %s", f.name, e)
    return pd.concat(frames, ignore_index=True) if frames else None


def load_shadow(path: Path) -> pd.DataFrame | None:
    """本番の h14_shadow から、レースごとに TYB を最初に見た時刻だけ読む。"""
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path, columns=["race_id", "first_seen_at"]).drop_duplicates("race_id")
    except Exception as e:
        logger.warning("h14_shadow unavailable %s: %s", path.name, e)
        return None


def load_day(date: str, extras: bool = True) -> dict:
    """Payload for one race day, cached until any source file changes.

    extras=False は公開版へ送る用（publish.py）。local_extras があっても呼ばない。
    """
    use_extras = extras and local_extras is not None
    viewer_files = _viewer_files(date)
    paths = [_path("nk_odds_series", date), _path("ev_audit", date),
             DB_PATH, DB_PATH.with_name(DB_PATH.name + "-wal"),
             _path("h14_shadow", date), *viewer_files]
    if use_extras:
        paths += local_extras.files(date)
    # 記録係のファイルはレースごとに増えるので、パスもキーに入れる
    key = tuple((str(p), p.stat().st_mtime_ns if p.exists() else 0) for p in paths)
    hit = _cache.get((date, use_extras))
    if hit and hit[0] == key:
        return hit[1]
    try:
        series, audit = (_read(p) for p in paths[:2])
    except Exception as e:  # file caught mid-write by the live loop
        if hit:
            logger.warning("read failed for %s (%s); serving cached payload", date, e)
            return hit[1]
        raise
    payload = compute_day(series, audit, load_entries(date),
                          load_viewer(viewer_files), load_shadow(paths[4]))
    if use_extras:
        local_extras.annotate(payload, audit, date)
    payload["date"] = date
    payload["weekday"] = WEEKDAY[_date.fromisoformat(date).weekday()]
    _cache[(date, use_extras)] = (key, payload)
    logger.info("built %s: %d races, %d with p_ens", date,
                len(payload["races"]), sum(r["audit_at"] is not None for r in payload["races"]))
    return payload


def _num(x, nd: int):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def _arr(a: np.ndarray, nd: int) -> list:
    return [_num(v, nd) for v in a]


def race_label(rid: str) -> str:
    try:
        return f"{VENUE.get(rid[4:6], rid[4:6])}{int(rid[10:12])}R"
    except (ValueError, IndexError):
        return rid


def meeting(rid: str) -> str:
    """race_id -> '4回京都5日目' (kai = digits 7-8, nichi = digits 9-10)."""
    try:
        return f"{int(rid[6:8])}回{VENUE.get(rid[4:6], rid[4:6])}{int(rid[8:10])}日目"
    except (ValueError, IndexError):
        return ""


def _str(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else str(x)


def _race_card(entries: pd.DataFrame | None) -> dict[str, dict]:
    """race_id -> race info plus {horse_num: row} from the race_results_clean frame."""
    card: dict[str, dict] = {}
    if entries is None or entries.empty:
        return card
    for rid, e in entries.groupby("race_id"):
        r0 = e.iloc[0]
        course = None
        if pd.notna(r0["course_len"]):
            course = f"{COURSE.get(r0['race_type'], r0['race_type'] or '')}{int(r0['course_len'])}m"
        card[rid] = {"race_name": _str(r0["race_name"]), "course": course,
                     "ground": _str(r0["ground_state"]),
                     "horses": {float(h.horse_num): h for h in e.itertuples()}}
    return card


def _horse_card(e) -> dict:
    if e is None:
        return {"name": None, "sex_age": None, "jockey": None, "kinryo": None}
    return {"name": _str(e.horse_name),
            "sex_age": f"{e.gender or ''}{int(e.age)}" if pd.notna(e.age) else _str(e.gender),
            "jockey": _str(e.jockey),
            "kinryo": _num(e.weight, 1) if e.weight is not None else None}


def public_only(payload: dict) -> dict:
    """許可リスト（PUBLIC_*_KEYS）に載った項目だけの写しを返す。元の payload は書き換えない（キャッシュを守る）。"""
    def keep(d: dict, keys: frozenset) -> dict:
        return {k: v for k, v in d.items() if k in keys}
    out = keep(payload, PUBLIC_DAY_KEYS)
    out["races"] = [{**keep(r, PUBLIC_RACE_KEYS), "horses": [keep(h, PUBLIC_HORSE_KEYS) for h in r["horses"]]}
                    for r in payload["races"]]
    return out


def final_audit(audit: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    """レースごとに、最後に記録した時刻の行だけ（index は馬番）。ループが再起動すると2回記録されることがある。"""
    out: dict[str, pd.DataFrame] = {}
    if audit is None or audit.empty:
        return out
    a = audit.sort_values("logged_at")
    last = a.groupby("race_id")["logged_at"].transform("max")
    a = a[a["logged_at"] == last]
    # 同じ時刻の同じ馬が2行入る日がある（2026-11-21。原因は未確認）
    a = a.drop_duplicates(["race_id", "horse_num"], keep="last")
    for rid, g in a.groupby("race_id"):
        out[rid] = g.set_index("horse_num")
    return out


def _hms(ts) -> str:
    return pd.Timestamp(ts).strftime("%H:%M:%S")


def _phases(times: np.ndarray, v: pd.DataFrame | None, audit_ts) -> tuple[list, list, dict]:
    """オッズの各時刻に、その時点で出ていた予測を対応づける。

    返り値: (phase のリスト, 使った記録係の時刻のリスト（なければ None）, {記録係の時刻: {馬番: p}})
    """
    n = len(times)
    phase: list = [None] * n
    snap_at: list = [None] * n
    table: dict = {}
    if v is not None and not v.empty:
        snaps = v.groupby("logged_at")["stage"].first().sort_index()  # 段階は記録ごとに1つ（全馬同じ）
        table = {t: dict(zip(g["horse_num"].astype(float), g["p_place_prod"].astype(float)))
                 for t, g in v.groupby("logged_at")}
        st = snaps.index.to_numpy()
        k = np.searchsorted(st, times, side="right") - 1  # その時刻以前で最後の記録
        for i, j in enumerate(k):
            if j >= 0 and times[i] - st[j] <= VIEWER_MATCH and snaps.iloc[j] in PHASE:
                phase[i], snap_at[i] = PHASE[snaps.iloc[j]], snaps.index[j]
    if audit_ts is not None:
        for i in range(n):
            if times[i] >= audit_ts:
                phase[i], snap_at[i] = "final", None
    return phase, snap_at, table


def compute_day(series: pd.DataFrame | None, audit: pd.DataFrame | None,
                entries: pd.DataFrame | None = None,
                viewer: pd.DataFrame | None = None, shadow: pd.DataFrame | None = None) -> dict:
    """Pure transform: raw frames -> per-race time series of odds and EV.

    viewer は記録係の予測（VIEWER_COLS）、shadow は h14_shadow の race_id と first_seen_at。どちらも無くてよい。
    """
    if series is None or series.empty:
        return {"races": [], "meetings": [], "ev_thr_default": EV_THR_DEFAULT}
    card = _race_card(entries)
    s = series.copy()
    s["polled_at"] = pd.to_datetime(s["polled_at"])

    pens = final_audit(audit)  # p_ens per horse
    audit_at = {rid: str(g["logged_at"].iloc[0])[11:19] for rid, g in pens.items()}  # HH:MM:SS, same as times
    audit_ts = {rid: pd.Timestamp(g["logged_at"].iloc[0]) for rid, g in pens.items()}

    # 記録係の時刻は '2026-11-15 08:42:09'、オッズは '2026-11-15T09:10:52'。どちらも datetime にそろえる
    views: dict[str, pd.DataFrame] = {}
    tyb_first: dict[str, pd.Timestamp] = {}
    if viewer is not None and not viewer.empty:
        vw = viewer.dropna(subset=["p_place_prod"]).copy()
        vw["logged_at"] = pd.to_datetime(vw["logged_at"])
        views = {rid: g for rid, g in vw.groupby("race_id")}
        for rid, t in vw[vw["stage"] == "S5"].groupby("race_id")["logged_at"].min().items():
            tyb_first[rid] = t
    if shadow is not None and not shadow.empty:
        for r in shadow.dropna(subset=["first_seen_at"]).itertuples():
            t = pd.Timestamp(r.first_seen_at)
            tyb_first[r.race_id] = min(t, tyb_first.get(r.race_id, t))

    races = []
    for rid, g in s.groupby("race_id"):
        times = np.sort(g["polled_at"].unique())
        mins = g.groupby("polled_at")["mins_to_hasso"].first().reindex(times).to_numpy()
        hasso = (g["polled_at"] + pd.to_timedelta(g["mins_to_hasso"], unit="min")).median()
        wide = g.pivot_table(index="polled_at", columns="horse_num",
                             values=["win", "place_low", "place_high"], aggfunc="last")
        wide = wide.reindex(times)
        p = pens.get(rid)
        rc = card.get(rid, {})
        phase, snap_at, table = _phases(times, views.get(rid), audit_ts.get(rid))
        horses = []
        for num in sorted(g["horse_num"].unique()):
            low = wide[("place_low", num)].to_numpy(dtype=float, copy=True)
            high = wide[("place_high", num)].to_numpy(dtype=float, copy=True)
            win = wide[("win", num)].to_numpy(dtype=float, copy=True)
            # 取消・除外の馬は「単勝 999.9・複勝の下限 -3.0」で記録されている。オッズなしとして扱う
            gone = low < 0
            low[gone] = high[gone] = win[gone] = np.nan
            row = p.loc[num] if p is not None and num in p.index else None
            pe = float(row["p_ens"]) if row is not None else np.nan
            # その時刻に出ていた予測（仮・TYB後は記録係の値、確定後は p_ens）
            pt = [pe if ph == "final" else table.get(sa, {}).get(float(num), np.nan) if ph else np.nan
                  for ph, sa in zip(phase, snap_at)]
            horses.append({
                "num": int(num),
                **_horse_card(rc.get("horses", {}).get(float(num))),
                "p_ens": _num(pe, 4),
                "win": _arr(win, 1),
                "low": _arr(low, 1),
                "high": _arr(high, 1),
                "ev_low": _arr(pe * low, 4),
                "ev_mid": _arr(pe * (low + high) / 2, 4),
                "p": _arr(np.array(pt, dtype=float), 4),
            })
        races.append({
            "race_id": rid,
            "label": race_label(rid),
            "venue": VENUE.get(rid[4:6], rid[4:6]),
            "rno": int(rid[10:12]),
            "meeting": meeting(rid),
            "race_name": rc.get("race_name"),
            "course": rc.get("course"),
            "ground": rc.get("ground"),
            "hasso": hasso.strftime("%H:%M"),
            "audit_at": audit_at.get(rid),
            "tyb_at": _hms(tyb_first[rid]) if rid in tyb_first else None,
            "phase": phase,
            "times": [t.strftime("%H:%M:%S") for t in pd.to_datetime(times)],
            "mins": _arr(mins, 2),
            "horses": horses,
        })
    races.sort(key=lambda r: (r["hasso"], r["race_id"]))
    meetings = [meeting(k) for k in sorted({r["race_id"][:10] for r in races})]
    return {"races": races, "meetings": meetings, "ev_thr_default": EV_THR_DEFAULT}
