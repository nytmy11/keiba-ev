// Pure helpers: colour scale and "what does this cell show at time T"

const GRAD_SPAN = 0.6 // EV above the threshold by this much reaches the hottest colour

// Below threshold: dark slate that brightens as EV approaches it.
// At/above threshold: amber -> orange -> red -> crimson.
export function evColor(ev, thr) {
  if (ev == null) return null
  if (ev < thr) {
    const r = clamp01((ev / thr - 0.4) / 0.6)
    return `hsl(215 ${12 + r * 28}% ${17 + r * 21}%)`
  }
  const r = clamp01((ev - thr) / GRAD_SPAN)
  const h = (50 - r * 62 + 360) % 360
  return `hsl(${h} 95% ${58 - r * 14}%)`
}

export function evTextColor(ev, thr) {
  if (ev == null || ev < thr) return 'var(--fg-dim)'
  return (ev - thr) / GRAD_SPAN < 0.45 ? '#1a1205' : '#fff'
}

export const clamp01 = (x) => Math.max(0, Math.min(1, x))

// last poll index at or before the cursor (times are 'HH:MM:SS' strings, so string order works)
export function idxAt(times, cursor) {
  let lo = -1
  for (let i = 0; i < times.length; i++) {
    if (times[i] <= cursor) lo = i
    else break
  }
  return lo
}

// Is p_ens usable at the cursor? It is logged once at the FINAL stage (~T-3min).
export function pensKnown(race, cursor, hindsight) {
  return race.audit_at != null && (hindsight || cursor >= race.audit_at)
}

// 予測の段階（API の phase）: 'pre' = TYB 前の仮予測 / 'tyb' = TYB 後 / 'final' = 本番が記録した p_ens。
// 古いデータ（phase なし）や記録係を動かしていない日は null で、従来どおり p_ens の確定時刻だけで分ける
export const phaseAt = (race, i) => race.phase?.[i] ?? null
export const isLivePhase = (ph) => ph === 'pre' || ph === 'tyb'

export const PHASE = {
  pre: { badge: '仮', label: '仮予測（TYB前）', title: 'JRDB の TYB（パドック・馬体重など）が届く前の予測。98特徴量のうち9個が欠けている' },
  tyb: { badge: '本', label: '本予測（TYB後）', title: 'TYB が届いた後の予測。本番のループと同じ入力' },
  final: { badge: '確定', label: '確定（本番の p_ens）', title: '本番が締切約3分前に記録した p_ens' },
  hindsight: { badge: '', label: '後知恵', title: '確定した p_ens を、それより前のオッズに当てはめた値' },
}

// basis（ev_low / ev_mid）に対応する複勝オッズ
export function oddsFor(basis, low, high) {
  if (low == null) return null
  if (basis !== 'ev_mid') return low
  return high == null ? null : (low + high) / 2
}

export function cellAt(race, horse, i, cursor, basis, hindsight) {
  if (i < 0) return { kind: 'none' }
  const odds = { low: horse.low[i], high: horse.high[i], win: horse.win[i] }
  const phase = phaseAt(race, i)
  if (isLivePhase(phase)) {
    // 確定前でも、記録係がその時刻に出した予測があればそれで EV を出す
    const p = horse.p?.[i] ?? null
    const o = oddsFor(basis, odds.low, odds.high)
    if (p == null || o == null) return { kind: 'pending', phase, p, ...odds }
    return { kind: 'ev', ev: p * o, p, phase, ...odds }
  }
  if (race.audit_at == null) return { kind: 'nopens', phase, ...odds }
  if (!pensKnown(race, cursor, hindsight)) return { kind: 'pending', phase, ...odds }
  const hs = cursor < race.audit_at
  return { kind: 'ev', ev: horse[basis][i], p: horse.p_ens, phase: hs ? 'hindsight' : 'final', hindsight: hs, ...odds }
}

// グラフ用: 時刻ごとの EV と、その値の出どころ（pre / tyb / final / hindsight）
export function evSeries(race, horse, basis) {
  return race.times.map((t, i) => {
    const ph = phaseAt(race, i)
    if (isLivePhase(ph)) {
      const p = horse.p?.[i]
      const o = oddsFor(basis, horse.low[i], horse.high[i])
      return { v: p == null || o == null ? null : p * o, ph }
    }
    const final = race.audit_at != null && t >= race.audit_at
    return { v: horse[basis][i], ph: final ? 'final' : 'hindsight' }
  })
}

const secs = (hms) => {
  const [h, m, s = 0] = hms.split(':').map(Number)
  return h * 3600 + m * 60 + s
}

// その時刻の「発走までの分」。オッズの記録の間は直線で補う。記録より前・後なら null
export function minsAt(race, hms) {
  const k = idxAt(race.times, hms)
  if (k < 0 || race.mins[k] == null) return null
  if (k === race.times.length - 1 || race.mins[k + 1] == null) return race.times[k] === hms ? race.mins[k] : null
  const a = secs(race.times[k]), b = secs(race.times[k + 1])
  return race.mins[k] + ((secs(hms) - a) / (b - a || 1)) * (race.mins[k + 1] - race.mins[k])
}

// TYB 到着が発走の何分前か（発走時刻 HH:MM から数える）
export const tybLead = (race) => (race.tyb_at ? Math.round((secs(race.hasso) - secs(race.tyb_at)) / 60) : null)

export const hasLive = (race) => (race.phase ?? []).some(isLivePhase)

export function raceStatus(race, i) {
  if (i < 0) return { text: '未取得', cls: 'idle' }
  const m = race.mins[i]
  if (m == null) return { text: '', cls: 'idle' }
  if (m < 0) return { text: '発走済', cls: 'done' }
  return { text: `${Math.ceil(m)}分前`, cls: m <= 3.2 ? 'hot' : 'live' }
}

export const fmt = (x, nd = 2) => (x == null ? '–' : x.toFixed(nd))

// '2026-10-12' -> '月' (local date, so no UTC shift)
export const weekday = (d) => '日月火水木金土'[new Date(`${d}T00:00:00`).getDay()]

