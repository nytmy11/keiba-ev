"""API。settings.KEIBA_EV_SOURCE で動き方が変わる。

- "local"（自宅PC・既定）: deepimpact の parquet をその場で読んで計算する
- "store"（公開版・Render）: 自宅PCから送られてきた計算済み JSON を返すだけ（pandas 不要）
"""
import gzip
import hmac
import logging
from datetime import date as _date

from django.conf import settings
from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from . import store

logger = logging.getLogger(__name__)
EV_THR_DEFAULT = 1.15  # data.EV_THR_DEFAULT と同じ（store モードで pandas を読まないよう複製）


def _is_store() -> bool:
    return settings.KEIBA_EV_SOURCE == "store"


class DatesView(APIView):
    def get(self, request):
        if _is_store():
            dates = store.available_dates()
        else:
            from . import data  # pandas を読むのはローカルのときだけ
            dates = data.available_dates()
        return Response({"dates": dates, "today": _date.today().isoformat(),
                         "ev_thr_default": EV_THR_DEFAULT,
                         "public": _is_store()})  # 公開版なら True（画面の説明文を切り替える）


class DayView(APIView):
    def get(self, request, date):
        if not store.DATE_RE.match(date):
            return Response({"detail": "date must be YYYY-MM-DD"}, status=400)
        if _is_store():
            gz = store.read_gz(date)
            if gz is None:
                return Response({"detail": "no data for this date"}, status=404)
            # 保存してある gzip をそのまま返す（展開・再圧縮しない）
            if "gzip" in request.headers.get("Accept-Encoding", ""):
                resp = HttpResponse(gz, content_type="application/json")
                resp["Content-Encoding"] = "gzip"
            else:  # gzip を受け付けないクライアント（curl の既定など）には展開して返す
                resp = HttpResponse(gzip.decompress(gz), content_type="application/json")
            resp["Cache-Control"] = "no-cache"
            return resp
        from . import data
        try:
            return Response(data.load_day(date))
        except Exception:
            logger.exception("load_day failed for %s", date)
            return Response({"detail": "failed to read data (see logs/)"}, status=500)


class PushView(APIView):
    """自宅PCの publish.py から当日分を受け取る。合言葉（KEIBA_EV_PUSH_TOKEN）が無ければ常に 403。"""

    def post(self, request, date):
        token = settings.KEIBA_EV_PUSH_TOKEN
        given = request.headers.get("X-Push-Token", "")
        if not token or not hmac.compare_digest(given.encode(), token.encode()):
            return Response({"detail": "forbidden"}, status=403)
        try:
            obj = store.save_push(date, request.body)
        except ValueError as e:  # gzip が壊れている・JSON の形が違う・日付が合わない
            return Response({"detail": str(e)}, status=400)
        logger.info("push %s: %d races, %d bytes", date, len(obj["races"]), len(request.body))
        return Response({"ok": True, "date": date, "races": len(obj["races"])})
