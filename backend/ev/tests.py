import gzip
import json
import tempfile
from pathlib import Path

import pandas as pd
from django.test import SimpleTestCase, override_settings

from . import store
from .data import compute_day, strip_internal

RID = "202605040501"


def _series():
    rows = []
    for t, mins in (("2026-10-12T09:40:00", 9.0), ("2026-10-12T09:41:00", 8.0)):
        for num, low, high in ((1.0, 2.0, 4.0), (2.0, 10.0, 20.0)):
            rows.append({"polled_at": t, "race_id": RID, "horse_num": num, "win": low * 3,
                         "place_low": low + (mins == 8.0), "place_high": high,
                         "nk_official": t, "mins_to_hasso": mins})
    return pd.DataFrame(rows)


def _audit(logged_at, p1):
    return pd.DataFrame({"race_id": [RID, RID], "horse_num": [1.0, 2.0], "p_ens": [p1, 0.1],
                         "ev": [0.9, 1.2], "place_odds_pre": [2.2, 9.0], "logged_at": [logged_at] * 2})


class ComputeDayTests(SimpleTestCase):
    def test_ev_is_p_ens_times_place_odds(self):
        out = compute_day(_series(), _audit("2026-10-12T09:46:00", 0.5), None)
        r = out["races"][0]
        self.assertEqual(r["label"], "東京1R")
        self.assertEqual(r["hasso"], "09:49")
        self.assertEqual(r["audit_at"], "09:46:00")
        h1, h2 = r["horses"]
        self.assertEqual(h1["ev_low"], [1.0, 1.5])           # 0.5 * (2, 3)
        self.assertEqual(h1["ev_mid"], [1.5, 1.75])          # 0.5 * ((2+4)/2, (3+4)/2)
        self.assertEqual(h2["ev_low"], [1.0, 1.1])           # 0.1 * (10, 11)
        self.assertEqual(h2["ev_screen"], 1.2)

    def test_latest_audit_wins_when_logged_twice(self):
        audit = pd.concat([_audit("2026-10-12T09:45:00", 0.2), _audit("2026-10-12T09:46:00", 0.5)])
        h1 = compute_day(_series(), audit, None)["races"][0]["horses"][0]
        self.assertEqual(h1["p_ens"], 0.5)

    def test_duplicate_rows_in_one_audit_are_collapsed(self):
        # 2026-11-21 は同じ時刻・同じ馬が2行入っていた
        audit = pd.concat([_audit("2026-10-12T09:46:00", 0.5)] * 2)
        h1 = compute_day(_series(), audit, None)["races"][0]["horses"][0]
        self.assertEqual(h1["p_ens"], 0.5)

    def test_scratched_horse_sentinel_becomes_no_odds(self):
        series = _series()
        last = (series["polled_at"] == "2026-10-12T09:41:00") & (series["horse_num"] == 2.0)
        series.loc[last, ["win", "place_low", "place_high"]] = [999.9, -3.0, 999.9]
        h2 = compute_day(series, _audit("2026-10-12T09:46:00", 0.5), None)["races"][0]["horses"][1]
        self.assertEqual(h2["low"], [10.0, None])
        self.assertEqual(h2["win"], [30.0, None])
        self.assertEqual(h2["ev_low"], [1.0, None])

    def test_race_without_audit_has_no_ev(self):
        r = compute_day(_series(), None, None)["races"][0]
        self.assertIsNone(r["audit_at"])
        self.assertEqual(r["horses"][0]["ev_low"], [None, None])
        self.assertEqual(r["horses"][0]["low"], [2.0, 3.0])

    def test_exec_outranks_final_pick(self):
        ledger = pd.DataFrame({"race_id": [RID] * 3, "horse_num": [1.0, 1.0, 2.0],
                               "stage": ["FINAL", "EXEC", "PRELIM"]})
        hs = compute_day(_series(), None, ledger)["races"][0]["horses"]
        self.assertEqual([h["pick"] for h in hs], ["EXEC", None])

    def test_public_payload_has_no_internal_values(self):
        # 公開版: 印も、本番の買い判定に使う値（T-15 基準の EV と複勝オッズ）も残さない
        ledger = pd.DataFrame({"race_id": [RID], "horse_num": [1.0], "stage": ["EXEC"]})
        out = strip_internal(compute_day(_series(), _audit("2026-10-12T09:46:00", 0.5), ledger))
        for h in out["races"][0]["horses"]:
            self.assertIsNone(h["pick"])
            self.assertIsNone(h["ev_screen"])
            self.assertIsNone(h["place_pre"])
            self.assertIsNotNone(h["p_ens"])  # 画面に出す EV のもとは残す

    def test_race_card_and_meeting(self):
        entries = pd.DataFrame({
            "race_id": [RID, RID], "horse_num": [1, 2], "horse_name": ["アカ", "アオ"],
            "gender": ["牡", "牝"], "age": [3, 4], "weight": [57.0, 55.0], "jockey": ["武豊", "▲佐藤"],
            "race_name": ["2歳未勝利"] * 2, "course_len": [1400, 1400], "race_type": ["ダート"] * 2,
            "ground_state": ["良"] * 2})
        out = compute_day(_series(), None, None, entries)
        r = out["races"][0]
        self.assertEqual(out["meetings"], ["4回東京5日目"])
        self.assertEqual((r["meeting"], r["race_name"], r["course"]), ("4回東京5日目", "2歳未勝利", "ダ1400m"))
        h1, h2 = r["horses"]
        self.assertEqual((h1["name"], h1["sex_age"], h1["jockey"], h1["kinryo"]), ("アカ", "牡3", "武豊", 57.0))
        self.assertEqual(h2["sex_age"], "牝4")

    def test_missing_race_card_leaves_names_empty(self):
        h = compute_day(_series(), None, None, None)["races"][0]["horses"][0]
        self.assertIsNone(h["name"])


class ApiTests(SimpleTestCase):
    def test_bad_date_is_400(self):
        self.assertEqual(self.client.get("/api/day/2026-1-1/").status_code, 400)

    def test_dates(self):
        res = self.client.get("/api/dates/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["ev_thr_default"], 1.15)


def _payload(date, races=1):
    return {"date": date, "weekday": "土", "meetings": [], "ev_thr_default": 1.15,
            "races": [{"race_id": RID, "horses": []}] * races}


class StoreApiTests(SimpleTestCase):
    """公開版（KEIBA_EV_SOURCE=store）の受け取りと配信。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.push_dir, self.snap_dir = Path(tmp.name, "pushed"), Path(tmp.name, "snapshots")
        self.snap_dir.mkdir()
        (self.snap_dir / "2026-11-15.json.gz").write_bytes(store.encode(_payload("2026-11-15", 2)))
        cm = override_settings(KEIBA_EV_SOURCE="store", KEIBA_EV_PUSH_TOKEN="secret",
                               KEIBA_EV_PUSH_DIR=self.push_dir, KEIBA_EV_SNAPSHOT_DIR=self.snap_dir)
        cm.enable()
        self.addCleanup(cm.disable)

    def _push(self, date, body, token="secret"):
        return self.client.post(f"/api/push/{date}/", body, content_type="application/octet-stream",
                                headers={"X-Push-Token": token})

    def test_snapshot_is_served_gzipped(self):
        res = self.client.get("/api/day/2026-11-15/", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Encoding"], "gzip")
        self.assertEqual(len(json.loads(gzip.decompress(res.content))["races"]), 2)

    def test_plain_json_without_accept_encoding(self):
        res = self.client.get("/api/day/2026-11-15/")
        self.assertEqual(len(res.json()["races"]), 2)

    def test_push_then_dates_and_day(self):
        self.assertEqual(self._push("2026-11-21", store.encode(_payload("2026-11-21", 3))).status_code, 200)
        meta = self.client.get("/api/dates/").json()
        self.assertEqual(meta["dates"], ["2026-11-21", "2026-11-15"])
        self.assertTrue(meta["public"])
        self.assertEqual(len(self.client.get("/api/day/2026-11-21/").json()["races"]), 3)

    def test_push_overrides_snapshot_of_same_day(self):
        self._push("2026-11-15", store.encode(_payload("2026-11-15", 5)))
        self.assertEqual(len(self.client.get("/api/day/2026-11-15/").json()["races"]), 5)

    def test_wrong_token_is_403(self):
        res = self._push("2026-11-21", store.encode(_payload("2026-11-21")), token="nope")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(self.push_dir.exists())

    @override_settings(KEIBA_EV_PUSH_TOKEN="")
    def test_push_disabled_without_token(self):
        self.assertEqual(self._push("2026-11-21", store.encode(_payload("2026-11-21")), token="").status_code, 403)

    def test_date_mismatch_and_bad_gzip_are_400(self):
        self.assertEqual(self._push("2026-11-21", store.encode(_payload("2026-11-22"))).status_code, 400)
        self.assertEqual(self._push("2026-11-21", b"not gzip").status_code, 400)
        self.assertEqual(self._push("2026-11-21", gzip.compress(b"[1,2]")).status_code, 400)

    def test_missing_day_is_404(self):
        self.assertEqual(self.client.get("/api/day/2026-01-01/").status_code, 404)
