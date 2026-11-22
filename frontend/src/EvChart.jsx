import { useState } from 'react'
import { evColor, fmt, idxAt } from './ev'

const W = 640, H = 300, M = { l: 40, r: 34, t: 14, b: 30 }

// runs of consecutive non-null points in ys[from..to]
function runs(xs, ys, from, to) {
  const out = []
  let cur = []
  for (let i = from; i <= to; i++) {
    if (ys[i] == null) {
      if (cur.length > 1) out.push(cur)
      cur = []
    } else cur.push([xs[i], ys[i]])
  }
  if (cur.length > 1) out.push(cur)
  return out
}

// split at the p_ens logging point so the hindsight part (before it) can be drawn dashed
function segments(xs, ys, cut) {
  return {
    pre: cut > 0 ? runs(xs, ys, 0, cut) : [],
    post: runs(xs, ys, Math.max(cut, 0), ys.length - 1),
  }
}

const d = (pts, sx, sy) => pts.map(([x, y], k) => `${k ? 'L' : 'M'}${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join('')

export default function EvChart({ race, cursor, basis, thr }) {
  const [hover, setHover] = useState(null)
  const xs = race.mins
  const vals = race.horses.flatMap((h) => h[basis]).filter((v) => v != null)
  const xMax = Math.max(...xs), xMin = Math.min(...xs)
  const yMax = Math.max(thr * 1.3, ...vals) * 1.05
  const sx = (m) => M.l + ((xMax - m) / (xMax - xMin || 1)) * (W - M.l - M.r)
  const sy = (v) => H - M.b - (v / yMax) * (H - M.t - M.b)
  const cut = race.audit_at ? idxAt(race.times, race.audit_at) : 0
  const ci = idxAt(race.times, cursor)
  const yTicks = [0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5].filter((v) => v <= yMax)
  const xTicks = []
  for (let m = Math.floor(xMax); m >= Math.ceil(xMin); m -= xMax - xMin > 20 ? 5 : 2) xTicks.push(m)

  // draw quiet lines first, hot ones on top
  const horses = race.horses
    .map((h) => ({ h, peak: Math.max(-1, ...h[basis].filter((v) => v != null)) }))
    .sort((a, b) => a.peak - b.peak)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" onMouseLeave={() => setHover(null)}>
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
      {race.audit_at && cut >= 0 && (
        <g>
          <line x1={sx(xs[cut])} x2={sx(xs[cut])} y1={M.t} y2={H - M.b} className="audit" />
          <text x={sx(xs[cut]) + 4} y={M.t + 10} className="audit-label">p_ens確定</text>
        </g>
      )}
      {horses.map(({ h, peak }) => {
        const hot = peak >= thr
        const color = hot ? evColor(peak, thr) : 'var(--line-cool)'
        const { pre, post } = segments(xs, h[basis], cut)
        const dim = hover != null && hover !== h.num
        const last = h[basis].findLastIndex((v) => v != null)
        return (
          <g key={h.num} opacity={dim ? 0.15 : 1} onMouseEnter={() => setHover(h.num)}>
            {pre.map((s, k) => <path key={`a${k}`} d={d(s, sx, sy)} stroke={color} className="ln pre" />)}
            {post.map((s, k) => <path key={`b${k}`} d={d(s, sx, sy)} stroke={color} className={`ln${hot ? ' hot' : ''}`} />)}
            {[...pre, ...post].map((s, k) => <path key={`h${k}`} d={d(s, sx, sy)} className="hit" />)}
            {(hot || hover === h.num) && last >= 0 && (
              <text x={sx(xs[last]) + 4} y={sy(h[basis][last]) + 4} className="end-label" fill={color}>{h.num}</text>
            )}
          </g>
        )
      })}
      {ci >= 0 && <line x1={sx(xs[ci])} x2={sx(xs[ci])} y1={M.t} y2={H - M.b} className="cursor" />}
      {hover != null && (() => {
        const h = race.horses.find((x) => x.num === hover)
        const v = ci >= 0 ? h[basis][ci] : null
        return <text x={M.l + 6} y={M.t + 12} className="hover-label">{`${hover} ${h.name ?? ''}（${[h.sex_age, h.jockey].filter(Boolean).join(' ')}）  EV ${fmt(v)}`}</text>
      })()}
    </svg>
  )
}
