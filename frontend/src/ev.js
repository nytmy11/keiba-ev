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

export function cellAt(race, horse, i, cursor, basis, hindsight) {
  if (i < 0) return { kind: 'none' }
  const odds = { low: horse.low[i], high: horse.high[i], win: horse.win[i] }
  if (race.audit_at == null) return { kind: 'nopens', ...odds }
  if (!pensKnown(race, cursor, hindsight)) return { kind: 'pending', ...odds }
  return { kind: 'ev', ev: horse[basis][i], hindsight: cursor < race.audit_at, ...odds }
}

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

