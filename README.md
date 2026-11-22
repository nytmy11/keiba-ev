# Keiba EV

競馬の**複勝の期待値（EV）を、レース×馬番のヒートマップで時刻ごとに表示する** Web アプリです。
開催日はオッズの動きに合わせて画面が更新され、期待値がしきい値を超えた馬のセルが黄→橙→赤に光ります。

- 公開版: （デプロイ後に URL を記載）
- 過去の開催日は、その日の記録を時刻スライダーで再生できます

## 期待値の考え方

```
EV(t) = p_ens × 複勝オッズ(t)
```

- `p_ens` … 自作の予測モデル（このリポジトリには含まれていません）が出す、その馬が3着以内に入る確率。
  発走の約3分前に、その時点の情報から1回だけ計算されます
- `複勝オッズ(t)` … 約1分ごとに記録している複勝オッズ。画面では「下限」と「下限と上限の中央値」を切り替えられます

`p_ens` が出る前の時刻はオッズだけを表示します（「後知恵モード」をオンにすると、確定後の `p_ens` を過去のオッズに当てはめて表示します）。

## 仕組み

モデルとデータは自宅の PC にしかないため、**自宅で計算した結果をクラウドへ送る（push 型）**構成にしています。

```
[自宅PC] 予測モデルの出力とオッズの記録（約1分ごと）
   ↓ 読むだけ
[自宅PC] publish.py live … 20秒ごとに確認し、変化があれば gzip した JSON を送信
   ↓ HTTPS POST /api/push/<日付>/（ヘッダーの合言葉で認証）
[Render] Django … 受け取った当日分と、リポジトリの snapshots/（過去分）を返す
   ↑ GET /api/day/<日付>/
[ブラウザ] React … 30秒ごとに取り直してヒートマップを描く
```

- その日の最終レースが終わると、自宅PCがその日の記録を `snapshots/<日付>.json.gz` に書き出してコミットします。
  Render の無料枠はディスクが再起動で消えますが、過去分はリポジトリに残ります
- 公開版のサーバーは計算をしないので、依存は Django・DRF・gunicorn・whitenoise だけです（`requirements-deploy.txt`）

## 技術構成

| 部分 | 使っているもの |
|---|---|
| 画面 | React 19 + Vite（グラフは SVG で自作。追加のライブラリなし） |
| API | Django 6 + Django REST framework（DB なし・ログインなし） |
| 配信 | gunicorn + whitenoise（React のビルド結果も Django から配る） |
| ホスティング | Render（無料枠・`render.yaml` の Blueprint で作成） |
| 自宅側の計算 | pandas（モデルの出力とオッズの記録を読んで EV を計算） |

## 手元で動かす（過去分の再生）

`snapshots/` に入っている過去の開催日を、公開版と同じ形で表示できます。

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-deploy.txt
cd frontend; npm ci; npm run build; cd ..
$env:KEIBA_EV_SOURCE = "store"
.\.venv\Scripts\python.exe backend\manage.py runserver
```

http://127.0.0.1:8000/ を開きます。

テストは計算ロジック（pandas）も含むので、`requirements.txt` を入れた環境で動かします。

```powershell
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python.exe backend\manage.py test ev   # テスト（計算ロジックと API）
```

## 主な API

| URL | 内容 |
|---|---|
| `GET /api/dates/` | データのある日付の一覧・既定のしきい値 |
| `GET /api/day/<YYYY-MM-DD>/` | その日の全レースの時刻・オッズ・`p_ens`・EV の推移 |
| `POST /api/push/<YYYY-MM-DD>/` | 自宅PCからの送信用。`X-Push-Token` が合わなければ 403 |

## 注意

このアプリは予測モデルの出力を可視化する学習用の制作物です。馬券の購入を勧めるものではありません。
