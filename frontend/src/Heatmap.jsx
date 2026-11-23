import { useState } from 'react'
import { PHASE, cellAt, evColor, evTextColor, fmt, idxAt, phaseAt, raceStatus } from './ev'

const PICK_MARK = { EXEC: '★', FINAL: '☆' }

// Floating card shown while hovering a cell (replaces the browser's plain title tooltip)
function Tip({ tip, thr }) {
  const { race: r, horse: h, c, x, y } = tip
  const ev = c.kind === 'ev' ? c.ev : null
  const left = Math.min(x, window.innerWidth - 270)
  return (
    <div className="tip" style={{ left, top: y }}>
      <div className="tip-race">{r.meeting} {r.rno}R{r.race_name ? ` ${r.race_name}` : ''}</div>
      <div className="tip-horse">
        <span className="tip-num">{h.num}</span>
        <b>{h.name ?? '（馬名なし）'}</b>
        {h.pick && <span className="pick-inline">{PICK_MARK[h.pick]}</span>}
      </div>
      <div className="tip-sub">
        {[h.sex_age, h.jockey, h.kinryo != null ? `${h.kinryo}kg` : null].filter(Boolean).join(' ・ ') || '出走表なし'}
      </div>
      <dl>
        <dt>EV</dt>
        <dd style={ev != null && ev >= thr ? { color: evColor(ev, thr), fontWeight: 700 } : undefined}>
          {c.kind === 'ev' ? fmt(ev) : '予測なし'}
        </dd>
        <dt>予測</dt>
        <dd>{c.phase ? PHASE[c.phase].label : r.tyb_at && r.tyb_at <= tip.cursor ? 'TYB到着済み（記録は締切約3分前）' : 'TYB 未着'}</dd>
        <dt>複勝率</dt><dd>{fmt(c.p, 3)}{c.p != null && c.phase !== 'final' && h.p_ens != null && <small> 確定 {fmt(h.p_ens, 3)}</small>}</dd>
        <dt>単勝</dt><dd>{fmt(c.win, 1)}</dd>
        <dt>複勝</dt><dd>{c.low == null ? '–' : `${fmt(c.low, 1)}–${fmt(c.high, 1)}`}</dd>
        {h.ev_screen != null && <><dt>本番EV</dt><dd>{fmt(h.ev_screen)} <small>T-15基準</small></dd></>}
      </dl>
      {h.pick && <div className="tip-pick">{h.pick === 'EXEC' ? '★ 購入した' : '☆ 最終通知した'}</div>}
    </div>
  )
}

function Cell({ race, horse, cursor, basis, hindsight, thr, onHover }) {
  if (!horse) return <td className="cell empty" />
  const c = cellAt(race, horse, idxAt(race.times, cursor), cursor, basis, hindsight)
  const mark = horse.pick ? <span className="pick">{PICK_MARK[horse.pick]}</span> : null
  if (c.kind === 'none') return <td className="cell none">{mark}</td>
  const hover = {
    onMouseEnter: (e) => {
      const b = e.currentTarget.getBoundingClientRect()
      onHover({ rid: race.race_id, num: horse.num, x: b.left, y: b.bottom + 6 })
    },
    onMouseLeave: () => onHover(null),
  }
  if (c.kind !== 'ev' || c.ev == null) {
    return (
      <td className={`cell pending${c.phase === 'pre' ? ' pre' : ''}`} {...hover}>
        <span className="odds">{fmt(c.low, 1)}</span>{mark}
      </td>
    )
  }
  const over = c.ev >= thr
  // 仮予測（TYB前）は縞模様にして光らせない。光るのは TYB 後・確定・後知恵だけ
  const pre = c.phase === 'pre'
  return (
    <td
      className={`cell ev${over ? (pre ? ' over-pre' : ' over') : ''}${pre ? ' pre' : ''}${c.hindsight ? ' hindsight' : ''}`}
      style={{ backgroundColor: evColor(c.ev, thr), color: evTextColor(c.ev, thr), '--glow': evColor(c.ev, thr) }}
      {...hover}
    >
      {fmt(c.ev)}{mark}
    </td>
  )
}

export default function Heatmap({ races, cursor, basis, hindsight, thr, selected, onSelect }) {
  const [tip, setTip] = useState(null)
  const maxN = Math.max(0, ...races.flatMap((r) => r.horses.map((h) => h.num)))
  const cols = Array.from({ length: maxN }, (_, k) => k + 1)
  // look the hovered cell up again on every render so replay and polling keep it current
  const tr = tip && races.find((r) => r.race_id === tip.rid)
  const th = tr && tr.horses.find((h) => h.num === tip.num)
  const live = th && { ...tip, cursor, race: tr, horse: th, c: cellAt(tr, th, idxAt(tr.times, cursor), cursor, basis, hindsight) }
  return (
    <div className="heatmap-wrap" onScroll={() => setTip(null)}>
      <table className="heatmap">
        <thead>
          <tr>
            <th className="rowhead">レース</th>
            {cols.map((n) => <th key={n}>{n}</th>)}
          </tr>
        </thead>
        <tbody>
          {races.map((r) => {
            const byNum = Object.fromEntries(r.horses.map((h) => [h.num, h]))
            const ri = idxAt(r.times, cursor)
            const st = raceStatus(r, ri)
            const ph = st.cls === 'done' ? null : phaseAt(r, ri) // 発走後は段階を出さない（どの行も「確定」になるだけ）
            return (
              <tr key={r.race_id} className={r.race_id === selected ? 'sel' : ''}
                  onClick={() => onSelect(r.race_id)}>
                <th className="rowhead"
                    title={[r.meeting, r.race_name, [r.course, r.ground].filter(Boolean).join(' ')].filter(Boolean).join('\n')}>
                  <span className="rlabel">{r.label}</span>
                  <span className="rtime">{r.hasso}</span>
                  <span className={`rstat ${st.cls}`}>{st.text}</span>
                  <span className={`phase ${ph ?? ''}`} title={ph ? PHASE[ph].title : undefined}>{ph ? PHASE[ph].badge : ''}</span>
                </th>
                {cols.map((n) => (
                  <Cell key={n} race={r} horse={byNum[n]} cursor={cursor}
                        basis={basis} hindsight={hindsight} thr={thr} onHover={setTip} />
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
      {live && live.c.kind !== 'none' && <Tip tip={live} thr={thr} />}
    </div>
  )
}
