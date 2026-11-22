import EvChart from './EvChart'
import { cellAt, evColor, evTextColor, fmt, idxAt, raceStatus } from './ev'

// internal=false（公開版）では「本番EV」列と買い目の列を出さない
export default function RaceDetail({ race, cursor, basis, hindsight, thr, internal = true }) {
  const i = idxAt(race.times, cursor)
  const st = raceStatus(race, i)
  const rows = race.horses
    .map((h) => ({ h, c: cellAt(race, h, i, cursor, basis, hindsight) }))
    .sort((a, b) => (b.c.ev ?? -1) - (a.c.ev ?? -1) || a.h.num - b.h.num)

  return (
    <section className="detail">
      <header>
        <h2>{race.label} <small>{race.hasso} 発走</small></h2>
        <span className={`rstat ${st.cls}`}>{st.text}</span>
      </header>
      <p className="raceinfo">
        {[race.meeting, race.race_name, race.course, race.ground].filter(Boolean).join(' ・ ')}
      </p>
      {race.audit_at ? (
        <p className="note">
          p_ens は {race.audit_at.slice(0, 5)}（締切約3分前）に確定。それより前の区間（点線）は、
          確定した p_ens を過去のオッズに当てはめた<b>後知恵</b>の値。
        </p>
      ) : (
        <p className="note warn">このレースは p_ens が未記録（締切約3分前に確定するか、対象外のレース）。オッズのみ表示。</p>
      )}
      {race.audit_at && <EvChart race={race} cursor={cursor} basis={basis} thr={thr} />}
      <table className="horses">
        <thead>
          <tr><th>馬番</th><th className="txt">馬名</th><th className="txt">性齢</th><th className="txt">騎手</th><th>斤量</th><th>p_ens</th><th>単勝</th><th>複勝</th><th>EV</th>{internal && <><th title="本番が買い判定に使う値（T-15の複勝オッズ基準）">本番EV</th><th /></>}</tr>
        </thead>
        <tbody>
          {rows.map(({ h, c }) => {
            const ev = c.kind === 'ev' ? c.ev : null
            return (
              <tr key={h.num} className={ev != null && ev >= thr ? 'over' : ''}>
                <td className="num">{h.num}</td>
                <td className="txt name">{h.name ?? '–'}</td>
                <td className="txt">{h.sex_age ?? '–'}</td>
                <td className="txt">{h.jockey ?? '–'}</td>
                <td>{fmt(h.kinryo, 1)}</td>
                <td>{fmt(h.p_ens, 3)}</td>
                <td>{fmt(c.win, 1)}</td>
                <td>{c.low == null ? '–' : `${fmt(c.low, 1)}–${fmt(c.high, 1)}`}</td>
                <td className="evcell" style={{ background: evColor(ev, thr) ?? 'transparent', color: evTextColor(ev, thr) }}>
                  {fmt(ev)}
                </td>
                {internal && <>
                  <td style={{ color: h.ev_screen != null && h.ev_screen >= thr ? 'var(--hot)' : undefined }}>{fmt(h.ev_screen)}</td>
                  <td>{h.pick === 'EXEC' ? '★購入' : h.pick === 'FINAL' ? '☆通知' : ''}</td>
                </>}
              </tr>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}
