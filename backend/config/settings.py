"""Django settings for keiba-ev (read-only API; no database).

自宅PC（既定）と公開版（Render）を環境変数で切り替える。Render では環境変数 RENDER=true が自動で入る。

| 環境変数 | 自宅PC（未設定時） | 公開版 |
|---|---|---|
| KEIBA_EV_SOURCE | local（deepimpact を直接読む） | store（送られてきた JSON を返す） |
| DJANGO_DEBUG | 1 | 0（RENDER があれば既定で 0） |
| DJANGO_SECRET_KEY | 起動のたびに乱数で作る | Render が自動生成 |
| KEIBA_EV_PUSH_TOKEN | 空（＝受け取り無効） | 自宅PCと同じ合言葉 |
"""
import os
from datetime import datetime
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent
APP_ROOT = BASE_DIR.parent  # keiba-ev/
ON_RENDER = os.environ.get("RENDER") == "true"

DEBUG = os.environ.get("DJANGO_DEBUG", "0" if ON_RENDER else "1") == "1"
# 公開版では必ず環境変数で渡す。自宅PCは起動のたびに乱数で作る（セッションもログインも使わないので困らない）
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (get_random_secret_key() if DEBUG else "")
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DEBUG is off")

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):  # 例: keiba-ev.onrender.com（Render が自動で入れる）
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])
ALLOWED_HOSTS += [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

INSTALLED_APPS = ["rest_framework", "ev"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # React のビルド結果（frontend/dist）を / で配る。index.html とハッシュ付きの JS・CSS
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",  # 他サイトの iframe に埋め込ませない
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {}

STATIC_URL = "static/"
WHITENOISE_ROOT = APP_ROOT / "frontend" / "dist"
WHITENOISE_INDEX_FILE = True  # / → index.html
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # Render は手前で HTTPS を終端する
if ON_RENDER:  # HTTPS だけで使わせる（手元の http://127.0.0.1 での確認には効かせない）
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^api/dates/$"]  # Render のヘルスチェックは内部から http で来る
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True  # クッキーは使わないが、念のため

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

# データの出どころ（views.py の先頭の説明を参照）
KEIBA_EV_SOURCE = os.environ.get("KEIBA_EV_SOURCE", "local")
KEIBA_EV_PUSH_TOKEN = os.environ.get("KEIBA_EV_PUSH_TOKEN", "")
KEIBA_EV_PUSH_DIR = Path(os.environ.get("KEIBA_EV_PUSH_DIR", APP_ROOT / "pushed"))
KEIBA_EV_SNAPSHOT_DIR = Path(os.environ.get("KEIBA_EV_SNAPSHOT_DIR", APP_ROOT / "snapshots"))
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # push の本文（gzip で 1日 0.1MB 前後）

LANGUAGE_CODE = "ja"
TIME_ZONE = "Asia/Tokyo"  # Linux（Render）ではプロセスの時刻も日本時間になる＝「今日」がずれない
USE_I18N = False
USE_TZ = False

# 自宅PCでは logs/ にファイルでも残す。Render はディスクが消えるので画面（標準出力）だけ
_handlers = {"console": {"class": "logging.StreamHandler", "formatter": "std"}}
if not ON_RENDER:
    LOG_DIR = APP_ROOT / "logs"
    LOG_DIR.mkdir(exist_ok=True)
    _handlers["file"] = {"class": "logging.FileHandler", "encoding": "utf-8", "formatter": "std",
                         "filename": LOG_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"}
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"}},
    "handlers": _handlers,
    "loggers": {"ev": {"handlers": list(_handlers), "level": "INFO"}},
}
