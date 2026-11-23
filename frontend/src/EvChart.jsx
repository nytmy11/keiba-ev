import { useState } from 'react'
import { evColor, evSeries, fmt, idxAt, minsAt } from './ev'

const W = 640, H = 300, M = { l: 40, r: 34, t: 14, b: 30 }

// 出どころ（ph）が同じ点の連なりに分ける。段階が変わる所は、前の点から新しい線種で描いてつなげる
function runs(xs, ser) {
  const out = []
  let cur = null
  for (let i = 0; i < ser.length; i++) {
    const { v, ph } = ser[i]
    if (v == null) {
      if (cur && cur.pts.length > 1) out.push(cur)
      cur = null
      continue
    }
    if (cur && cur.ph !== ph) {
      const last = cur.pts.at(-1)
      if (cur.pts.length > 1) out.push(cur)
      cur = { ph, pts: [last] }
    }
    if (!cur) cur = { ph, pts: [] }
    cur.pts.push([xs[i], v])
  }
  if (cur && cur.pts.length > 1) out.push(cur)
  return out
}

const d = (pts, sx, sy) => pts.map(([x, y], k) => `${k ? 'L' : 'M'}${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join('')

export default function EvChart({ race, cursor, basis, thr }) {
  const [hover, setHover] = useState(null)
  const xs = race.mins
  const series = race.horses.map((h) => ({ h, ser: evSeries(race, h, basis) }))
  const vals = series.flatMap(({ ser }) => ser.map((s) => s.v)).filter((v) => v != null)
  const xMax = Math.max(...xs), xMin = Math.min(...xs)
  const yMax = Math.max(thr * 1.3, ...vals) * 1.05
  const sx = (m) => M.l + ((xMax - m) / (xMax - xMin || 1)) * (W - M.l - M.r)
  const sy = (v) => H - M.b - (v / yMax) * (H - M.t - M.b)
  const cut = race.audit_at ? idxAt(race.times, race.audit_at) : -1
  const ci = idxAt(race.times, cursor)
  // TYB 到着の位置。グラフの左端より前に届いていたら左端に寄せる（オッズの記録は発走30分前から）
  const tybM = race.tyb_at ? (race.tyb_at < race.times[0] ? xMax : minsAt(race, race.tyb_at)) : null
  const yTicks = [0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5].filter((v) => v <= yMax)
  const xTicks = []
  for (let m = Math.floor(xMax); m >= Math.ceil(xMin); m -= xMax - xMin > 20 ? 5 : 2) xTicks.push(m)

  // draw quiet lines first, hot ones on top
  const horses = series
    .map((x) => ({ ...x, peak: Math.max(-1, ...x.ser.map((s) => s.v).filter((v) => v != null)) }))
    .sort((a, b) => a.peak - b.peak)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" onMouseLeave={() => setHover(null)}>
      {tybM != null && tybM < xMax && (
        <rect x={M.l} y={M.t} width={sx(tybM) - M.l} height={H - M.t - M.b} className="prezone" />
      )}
      {yTicks.map((v) => (
        <g key={v}>
          <line x1={M.l} x2={W - M.r} y1={sy(v)} y2={sy(v)} className="grid" />
          <text x={M.l - 6} y={sy(v) + 4} className="tick" textAnchor="end">{v}</text>
        </g>
      ))}
      {xTicks.map((m) => (
        <text key={m} x={sx(m)} y={H - 10} className="tick" textAnchor="middle">
          {m === 0 ? '発走' : m > 0 ? `-${m}分` : `+${-m}`}
        </text>
      ))}
      <rect x={M.l} y={M.t} width={W - M.l - M.r} height={Math.max(0, sy(thr) - M.t)} className="hotzone" />
      <line x1={M.l} x2={W - M.r} y1={sy(thr)} y2={sy(thr)} className="thr" />
      <text x={W - M.r + 3} y={sy(thr) + 4} className="thr-label">{thr.toFixed(2)}</text>
      {xMin <= 0 && <line x1={sx(0)} x2={sx(0)} y1={M.t} y2={H - M.b} className="post" />}
      {tybM != null && (
        <g>
          <line x1={sx(tybM)} x2={sx(tybM)} y1={M.t} y2={H - M.b} className="tyb" />
          <text x={sx(tybM) + 4} y={M.t + 22} className="tyb-label">TYB到着 {race.tyb_at.slice(0, 5)}</text>
        </g>
      )}
      {cut >= 0 && (
        <g>
          <line x1={sx(xs[cut])} x2={sx(xs[cut])} y1={M.t} y2={H - M.b} className="audit" />
          <text x={sx(xs[cut]) + 4} y={M.t + 10} className="audit-label">p_ens確定</text>
        </g>
      )}
      {horses.map(({ h, ser, peak }) => {
        const hot = peak >= thr
        const color = hot ? evColor(peak, thr) : 'var(--line-cool)'
        const segs = runs(xs, ser)
        const dim = hover != null && hover !== h.num
        const last = ser.findLastIndex((s) => s.v != null)
        return (
          <g key={h.num} opacity={dim ? 0.15 : 1} onMouseEnter={() => setHover(h.num)}>
            {segs.map((s, k) => (
              <path key={`s${k}`} d={d(s.pts, sx, sy)} stroke={color}
                    className={`ln ph-${s.ph}${hot && s.ph !== 'hindsight' ? ' hot' : ''}`} />
            ))}
            {segs.map((s, k) => <path key={`h${k}`} d={d(s.pts, sx, sy)} className="hit" />)}
            {(hot || hover === h.num) && last >= 0 && (
              <text x={sx(xs[last]) + 4} y={sy(ser[last].v) + 4} className="end-label" fill={color}>{h.num}</text>
            )}
          </g>
        )
      })}
      {ci >= 0 && <line x1={sx(xs[ci])} x2={sx(xs[ci])} y1={M.t} y2={H - M.b} className="cursor" />}
      {hover != null && (() => {
        const { h, ser } = series.find((x) => x.h.num === hover)
        const v = ci >= 0 ? ser[ci].v : null
        return <text x={M.l + 6} y={M.t + 12} className="hover-label">{`${hover} ${h.name ?? ''}（${[h.sex_age, h.jockey].filter(Boolean).join(' ')}）  EV ${fmt(v)}`}</text>
      })()}
    </svg>
  )
}

// グラフの線種の説明（RaceDetail の下に出す）
export function ChartLegend({ live }) {
  const items = [
    ...(live ? [['ph-pre', '仮予測（TYB前）'], ['ph-tyb', '本予測（TYB後）']] : []),
    ['ph-final', '確定（本番の p_ens）'],
    ['ph-hindsight', '後知恵（確定値を過去に当てはめ）'],
  ]
  return (
    <div className="chart-legend">
      {items.map(([cls, label]) => (
        <span key={cls}>
          <svg width="26" height="8"><line x1="1" x2="25" y1="4" y2="4" className={`ln ${cls}`} stroke="#cfd6e3" /></svg>
          {label}
        </span>
      ))}
      {live && <span><i className="prezone-swatch" />TYB が届く前の区間</span>}
    </div>
  )
}
