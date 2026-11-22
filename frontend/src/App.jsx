import { useEffect, useMemo, useState } from 'react'
import Heatmap from './Heatmap'
import RaceDetail from './RaceDetail'
import { cellAt, evColor, idxAt, weekday } from './ev'

const POLL_MS = 30_000
const store = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d } catch { return d } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* private mode */ } },
}

function Legend({ thr }) {
  const lo = thr * 0.4, hi = thr + 0.7
  const stops = Array.from({ length: 40 }, (_, k) => {
    const v = lo + ((hi - lo) * k) / 39
    return `${evColor(v, thr)} ${((k / 39) * 100).toFixed(1)}%`
  })
  const at = ((thr - lo) / (hi - lo)) * 100
  return (
    <div className="legend">
      <div className="bar" style={{ background: `linear-gradient(90deg, ${stops.join(',')})` }}>
        <span className="mark" style={{ left: `${at}%` }} />
      </div>
      <div className="labels">
        <span>{lo.toFixed(2)}</span>
        <span style={{ left: `${at}%` }} className="thr">しきい値 {thr.toFixed(2)}</span>
        <span>{hi.toFixed(2)}+</span>
      </div>
    </div>
  )
}

export default function App() {
  const [meta, setMeta] = useState(null)
  const [date, setDate] = useState(null)
  const [day, setDay] = useState(null)
  const [error, setError] = useState(null)
  const [fetchedAt, setFetchedAt] = useState(null)
  const [thr, setThr] = useState(() => store.get('thr', 1.15))
  const [basis, setBasis] = useState(() => store.get('basis', 'ev_low'))
  const [hindsight, setHindsight] = useState(() => store.get('hindsight', false))
  const [cursor, setCursor] = useState(null) // null = follow the latest poll
  const [playing, setPlaying] = useState(false)
  const [selected, setSelected] = useState(null)

  useEffect(() => { store.set('thr', thr) }, [thr])
  useEffect(() => { store.set('basis', basis) }, [basis])
  useEffect(() => { store.set('hindsight', hindsight) }, [hindsight])

  useEffect(() => {
    fetch('/api/dates/').then((r) => r.json()).then((m) => {
      setMeta(m)
      setDate(m.dates[0] ?? null)
    }).catch((e) => setError(String(e)))
  }, [])

  const isToday = meta != null && date === meta.today
  const isPublic = meta?.public === true // 公開版（Render）。買い目は送られてこないので説明も出さない
  useEffect(() => {
    if (!date) return
    let alive = true
    const load = () => fetch(`/api/day/${date}/`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => { if (alive) { setDay(d); setError(null); setFetchedAt(new Date()) } })
      .catch((e) => alive && setError(String(e)))
    load()
    const id = isToday ? setInterval(load, POLL_MS) : null
    return () => { alive = false; if (id) clearInterval(id) }
  }, [date, isToday])

  const races = useMemo(() => day?.races ?? [], [day])
  const allTimes = useMemo(() => [...new Set(races.flatMap((r) => r.times))].sort(), [races])
  const cur = cursor ?? allTimes.at(-1) ?? '00:00:00'
  const curIdx = Math.max(0, allTimes.findIndex((t) => t >= cur))

  // replay: step the cursor forward; at the end it drops back to null (= follow the latest poll)
  const isPlaying = playing && cursor != null
  useEffect(() => {
    if (!isPlaying) return
    const id = setInterval(() => setCursor((c) => {
      const k = allTimes.indexOf(c)
      return k >= 0 && k < allTimes.length - 1 ? allTimes[k + 1] : null
    }), 80)
    return () => clearInterval(id)
  }, [isPlaying, allTimes])

  const hot = useMemo(() => {
    const out = []
    for (const r of races) {
      const i = idxAt(r.times, cur)
      for (const h of r.horses) {
        const c = cellAt(r, h, i, cur, basis, hindsight)
        if (c.kind === 'ev' && c.ev != null && c.ev >= thr) out.push(`${r.label}-${h.num}`)
      }
    }
    return out
  }, [races, cur, basis, hindsight, thr])

  const selRace = races.find((r) => r.race_id === selected) ?? null

  return (
    <div className="app">
      <header className="top">
        <h1>🏇 Keiba EV <small>期待値ヒートマップ</small></h1>
        <div className="controls">
          <label>開催日
            <select value={date ?? ''} onChange={(e) => { setDate(e.target.value); setCursor(null); setSelected(null) }}>
              {meta?.dates.map((d) => <option key={d} value={d}>{d}（{weekday(d)}）{d === meta.today ? ' 今日' : ''}</option>)}
            </select>
          </label>
          <label>しきい値
            <input type="range" min="0.8" max="2" step="0.01" value={thr} onChange={(e) => setThr(+e.target.value)} />
            <input type="number" min="0.5" max="5" step="0.01" value={thr} onChange={(e) => setThr(+e.target.value || 1.15)} className="thr-num" />
            {thr !== meta?.ev_thr_default && <button className="link" onClick={() => setThr(meta?.ev_thr_default ?? 1.15)}>{isPublic ? '既定値に戻す' : '本番値に戻す'}</button>}
          </label>
          <label>オッズ基準
            <select value={basis} onChange={(e) => setBasis(e.target.value)}>
              <option value="ev_low">{isPublic ? '複勝の下限' : '複勝の下限（本番と同じ）'}</option>
              <option value="ev_mid">複勝の中央値（楽観的）</option>
            </select>
          </label>
          <label className="check" title="p_ens は締切約3分前に1回だけ記録される。オンにすると、それ以前の時刻にも確定後の p_ens を当てはめて表示する">
            <input type="checkbox" checked={hindsight} onChange={(e) => setHindsight(e.target.checked)} />
            後知恵モード
          </label>
        </div>
      </header>

      {day?.date === date && (
        <div className="dayinfo">
          <span className="dayinfo-date">{date.replaceAll('-', '/')}（{day.weekday}）</span>
          {day.meetings.map((m) => <span key={m} className="meeting">{m}</span>)}
          <span className="dayinfo-n">{races.length}レース</span>
        </div>
      )}

      <div className="timebar">
        <button onClick={() => { if (!isPlaying && cursor == null) setCursor(allTimes[0]); setPlaying(!isPlaying) }} disabled={!allTimes.length}>
          {isPlaying ? '⏸' : '▶'}
        </button>
        <input type="range" min="0" max={Math.max(0, allTimes.length - 1)} value={curIdx}
               onChange={(e) => { setPlaying(false); setCursor(allTimes[+e.target.value]) }} />
        <span className="clock">{cur.slice(0, 5)}</span>
        {cursor == null
          ? <span className={`live ${isToday ? 'on' : ''}`}>{isToday ? '● LIVE' : '最新'}</span>
          : <button className="link" onClick={() => { setPlaying(false); setCursor(null) }}>最新へ</button>}
        <span className="summary">
          しきい値超え <b>{hot.length}</b> 頭
          {hot.length > 0 && <span className="hotlist">（{hot.slice(0, 6).join(' / ')}{hot.length > 6 ? ' …' : ''}）</span>}
        </span>
        <span className="fetched">
          {isPublic && day?.published_at && `データ ${day.published_at.slice(11, 19)} ・`}
          {fetchedAt && `取得 ${fetchedAt.toLocaleTimeString('ja-JP')}`}{isToday && ' ・30秒ごとに更新'}
        </span>
      </div>

      <Legend thr={thr} />
      {error && <p className="error">{error}</p>}

      <main className={selRace ? 'split' : ''}>
        {races.length
          ? <Heatmap races={races} cursor={cur} basis={basis} hindsight={hindsight} thr={thr}
                     selected={selected} onSelect={(id) => setSelected(id === selected ? null : id)} />
          : <p className="empty-msg">{day ? 'この日のオッズ時系列はまだありません。' : '読み込み中…'}</p>}
        {selRace && <RaceDetail race={selRace} cursor={cur} basis={basis} hindsight={hindsight} thr={thr} internal={!isPublic} />}
      </main>

      <footer>
        EV = p_ens（モデルの複勝確率）× 複勝オッズ。セルの数字は選んだ時刻の EV、灰色の数字は p_ens 未確定のため複勝オッズのみ。
        {isPublic
          ? '開催日はオッズ（約1分ごと）とモデルの出力を自宅PCで計算し、この画面へ送っている。過去の日は記録の再生。'
          : '★ 購入 / ☆ 最終通知。データ: deepimpact/data/live_picks（読み取り専用）'}
      </footer>
    </div>
  )
}
