import EvChart, { ChartLegend } from './EvChart'
import { PHASE, cellAt, evColor, evTextColor, fmt, hasLive, idxAt, phaseAt, raceStatus, tybLead } from './ev'

// internal=false（公開版）では「本番EV」列と買い目の列を出さない
export default function RaceDetail({ race, cursor, basis, hindsight, thr, internal = true }) {
  const i = idxAt(race.times, cursor)
  const st = raceStatus(race, i)
  const ph = phaseAt(race, i)
  const live = hasLive(race)
  const lead = tybLead(race)
  const rows = race.horses
    .map((h) => ({ h, c: cellAt(race, h, i, cursor, basis, hindsight) }))
    .sort((a, b) => (b.c.ev ?? -1) - (a.c.ev ?? -1) || a.h.num - b.h.num)

  return (
    <section className="detail">
      <header>
        <h2>{race.label} <small>{race.hasso} 発走</small></h2>
        <span className={`rstat ${st.cls}`}>{st.text}</span>
        {ph && <span className={`phase ${ph}`} title={PHASE[ph].title}>{PHASE[ph].label}</span>}
      </header>
      <p className="raceinfo">
        {[race.meeting, race.race_name, race.course, race.ground].filter(Boolean).join(' ・ ')}
      </p>
      {race.tyb_at && (
        <p className="note">
          JRDB の TYB（パドック・馬体重など当日の情報）は <b>{race.tyb_at.slice(0, 5)}</b>
          {lead != null && lead >= 0 && `（発走約${lead}分前）`}に到着。
          {live
            ? <>ここからが<b>本予測</b>。それより前は TYB 抜き（98特徴量のうち9個が欠けた状態）の<b>仮予測</b>で、グラフは破線・セルは縞模様。</>
            : 'この日は確定前の予測を記録していないので、TYB 到着から確定までの予測は表示できない。'}
        </p>
      )}
      {race.audit_at ? (
        <p className="note">
          本番は {race.audit_at.slice(0, 5)}（締切約3分前）に p_ens を確定して記録した。
          {!live && <>それより前の区間（点線）は、確定した p_ens を過去のオッズに当てはめた<b>後知恵</b>の値。</>}
        </p>
      ) : (
        <p className="note warn">
          {live ? 'p_ens はまだ確定していない（締切約3分前）。' : 'このレースは p_ens が未記録（締切約3分前に確定するか、対象外のレース）。オッズのみ表示。'}
        </p>
      )}
      {(race.audit_at || live) && <>
        <EvChart race={race} cursor={cursor} basis={basis} thr={thr} />
        <ChartLegend live={live} />
      </>}
      <table className="horses">
        <thead>
          <tr><th>馬番</th><th className="txt">馬名</th><th className="txt">性齢</th><th className="txt">騎手</th><th>斤量</th><th title="選んだ時刻の予測（3着以内に入る確率）">複勝率</th><th>単勝</th><th>複勝</th><th>EV</th>{internal && <><th title="本番が買い判定に使う値（T-15の複勝オッズ基準）">本番EV</th><th /></>}</tr>
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
                <td className={c.phase === 'pre' ? 'pre-text' : undefined}>{fmt(c.p, 3)}</td>
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
