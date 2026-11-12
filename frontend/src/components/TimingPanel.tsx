// Publication timing: all events of one type, grouped by when they were published (Europe/Berlin)
// relative to their trading day, and how trading looked on that day in each group.
// Historical description only: the groups differ in companies and news, so a difference is not an effect of the time.
import { useState } from 'react';
import { getTiming, type Timing, type TimingItem, type TimingSlotKey } from '../api';
import { useFetch } from '../useFetch';
import { TIMING_METRICS, TIMING_TYPES, eventTitle, eventTypeLabel, fmtBerlin, fmtDate, fmtValue, sourceLabel } from '../format';

const SLOT_COLORS: Record<TimingSlotKey, string> = {
  before_day: 'var(--slot-before)',
  pre_open: 'var(--slot-pre)',
  trading: 'var(--slot-trading)',
};
const FEW = 5; // groups below this size are marked "few events"

interface Props {
  initialType: string;
  initialIndex: string;
  isin: string;
  ticker: string;
  selectedEventId: number | null;
  onOpenEvent: (eventId: number, isin: string) => void;
  onClose: () => void;
}

const minutes = (hhmm: string) => {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + m;
};

// stable vertical jitter per event, so dots do not jump between renders
const jitter = (id: number) => ((id * 2654435761) % 1000) / 1000;

export default function TimingPanel({ initialType, initialIndex, isin, ticker, selectedEventId, onOpenEvent, onClose }: Props) {
  const [type, setType] = useState(initialType);
  const [index, setIndex] = useState(initialIndex);
  const [metric, setMetric] = useState('open_gap_abs');
  const req = useFetch<Timing>(`timing|${type}|${index}`, () =>
    getTiming({ type, index: index === 'all' ? undefined : index }),
  );
  const data = req.data;
  const own = data?.items.filter((i) => i.isin === isin) ?? [];
  const metricInfo = TIMING_METRICS.find((m) => m.key === metric)!;
  const m = data?.metrics.find((x) => x.key === metric);

  return (
    <div className="timing-panel">
      <div className="card-head">
        <div>
          <div className="eyebrow">Publication timing</div>
          <h2>{eventTypeLabel(type)} · {index === 'all' ? 'DAX, MDAX, SDAX' : index} · 2026</h2>
        </div>
        <button className="btn ghost" onClick={onClose} aria-label="Close">✕</button>
      </div>
      <p className="muted lead">
        How trading looked on the trading day of each announcement, grouped by when it was published (Europe/Berlin).
      </p>

      <div className="compare-controls">
        <select aria-label="Event type" value={type} onChange={(e) => setType(e.target.value)}>
          {TIMING_TYPES.map((t) => <option key={t} value={t}>{eventTypeLabel(t)}</option>)}
        </select>
        <select aria-label="Index" value={index} onChange={(e) => setIndex(e.target.value)}>
          {['DAX', 'MDAX', 'SDAX', 'all'].map((i) => <option key={i} value={i}>{i === 'all' ? 'All indices' : i}</option>)}
        </select>
      </div>

      {req.error && <div className="muted pad">No timing view available for this selection.</div>}
      {req.loading && <div className="muted pad">Loading…</div>}
      {data && data.n === 0 && <div className="muted pad">No {eventTypeLabel(type).toLowerCase()} events with a known publication time in this selection.</div>}
      {data && data.n > 0 && (
        <>
          <PublicationClock items={data.items} isin={isin} selectedEventId={selectedEventId} />

          <div className="slot-cards">
            {data.slots.map((s) => {
              const mine = own.filter((i) => i.slot === s.key).length;
              return (
                <div key={s.key} className="slot-card" title={s.rule} style={{ borderTopColor: SLOT_COLORS[s.key] }}>
                  <div className="slot-label">{s.label}</div>
                  <div className="big">{s.n}</div>
                  <div className="muted slot-rule">{s.rule}</div>
                  {mine > 0 && <div className="slot-own">{ticker}: {mine}</div>}
                </div>
              );
            })}
          </div>

          <div className="block-head"><h3>Median on the trading day</h3><span className="muted small-note">click a row for its distribution</span></div>
          <table className="timing-table">
            <colgroup><col className="c-metric" />{data.slots.map((s) => <col key={s.key} />)}</colgroup>
            <thead>
              <tr>
                <th />
                {data.slots.map((s) => <th key={s.key}><span className="dot" style={{ background: SLOT_COLORS[s.key] }} /> {s.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {TIMING_METRICS.map((tm) => {
                const row = data.metrics.find((x) => x.key === tm.key);
                if (!row) return null;
                return (
                  <tr key={tm.key} className={tm.key === metric ? 'on' : ''} onClick={() => setMetric(tm.key)} title={tm.label}>
                    <td className="t-metric"><button className="timing-metric-button" aria-pressed={tm.key === metric} onClick={() => setMetric(tm.key)}>{tm.short}</button></td>
                    {data.slots.map((s) => {
                      const st = row.by_slot[s.key];
                      return (
                        <td key={s.key} className={st.n < FEW ? 'few' : ''} title={`${st.n} events with a value`}>
                          <div className="t-median">{fmtValue(st.median, row.unit)}</div>
                          <div className="t-iqr">{st.n >= 2 ? `${fmtValue(st.p25, row.unit)} – ${fmtValue(st.p75, row.unit)}` : st.n === 0 ? 'no data' : 'one event'}</div>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="caption">Middle line: p25 – p75 (middle half of the events). Faded: fewer than {FEW} events.</div>

          {m && (
            <Distribution
              data={data}
              metricKey={metric}
              label={metricInfo.label}
              note={metricInfo.note}
              unit={m.unit}
              source={m.source}
              isin={isin}
              ticker={ticker}
              selectedEventId={selectedEventId}
              onOpenEvent={onOpenEvent}
            />
          )}

          <div className="block-head"><h3>{ticker}: {eventTypeLabel(type).toLowerCase()} in 2026</h3></div>
          {own.length === 0 ? (
            <div className="muted small-note">No {eventTypeLabel(type).toLowerCase()} events of {ticker} with a known time in this selection.</div>
          ) : (
            <div className="own-list">
              {own.map((i) => (
                <button key={i.event_id} className={`own-row ${i.event_id === selectedEventId ? 'selected' : ''}`} onClick={() => onOpenEvent(i.event_id, i.isin)} title={eventTitle(i)}>
                  <span className="dot" style={{ background: SLOT_COLORS[i.slot] }} />
                  <span className="own-date">{fmtDate(i.date, false)}</span>
                  <span className="own-time">{i.slot === 'before_day' ? fmtBerlin(i.published_at_utc) : `${i.time_berlin} Berlin`}</span>
                  <span className="own-slot muted">{data.slots.find((s) => s.key === i.slot)?.label}</span>
                </button>
              ))}
            </div>
          )}

          <div className="caption">
            Historical description of {data.n} events in 2026, not a forecast. The groups differ in companies and news content;
            a difference between groups is not an effect of the publication time.
            {data.n_time_unknown > 0 && ` ${data.n_time_unknown} events without a known publication time are not grouped.`}
            {' '}Publication times: {[...new Set(data.items.map((i) => sourceLabel(i.source)))].join(', ')}.
            Trading figures: {[...new Set(data.metrics.map((x) => sourceLabel(x.source)))].join(', ')}.
          </div>
        </>
      )}
    </div>
  );
}

/** 24-hour histogram of publication times (30-minute bins), stacked by group; trading hours shaded. */
function PublicationClock({ items, isin, selectedEventId }: { items: TimingItem[]; isin: string; selectedEventId: number | null }) {
  const W = 428, H = 112, top = 8, base = 78, binMin = 30, bins = (24 * 60) / binMin;
  const x = (min: number) => (min / (24 * 60)) * W;
  const counts = Array.from({ length: bins }, () => ({ before_day: 0, pre_open: 0, trading: 0 } as Record<TimingSlotKey, number>));
  for (const i of items) counts[Math.min(bins - 1, Math.floor(minutes(i.time_berlin) / binMin))][i.slot]++;
  const max = Math.max(1, ...counts.map((c) => c.before_day + c.pre_open + c.trading));
  const y = (n: number) => (n / max) * (base - top);
  const bw = W / bins;
  const own = items.filter((i) => i.isin === isin || i.event_id === selectedEventId);

  return (
    <div className="block">
      <div className="block-head"><h3>When the announcements were published</h3><span className="muted small-note">Europe/Berlin · 30-minute steps</span></div>
      <svg className="pub-clock" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Publication times over the day">
        <rect x={x(9 * 60)} y={top - 4} width={x(17 * 60 + 35) - x(9 * 60)} height={base - top + 4} className="session" />
        <text x={(x(9 * 60) + x(17 * 60 + 35)) / 2} y={top + 6} className="clock-session">Xetra trading 09:00 – 17:35</text>
        {counts.map((c, b) => {
          let acc = 0;
          return (['before_day', 'pre_open', 'trading'] as TimingSlotKey[]).map((s) => {
            if (!c[s]) return null;
            const h = y(c[s]);
            acc += h;
            return <rect key={`${b}${s}`} x={b * bw + 0.6} width={bw - 1.2} y={base - acc} height={h} fill={SLOT_COLORS[s]} rx={1}>
              <title>{`${String(Math.floor((b * binMin) / 60)).padStart(2, '0')}:${String((b * binMin) % 60).padStart(2, '0')}: ${c[s]} events`}</title>
            </rect>;
          });
        })}
        <line x1={0} x2={W} y1={base} y2={base} className="clock-axis" />
        {[0, 6, 9, 12, 15, 18, 21].map((h) => (
          <text key={h} x={x(h * 60)} y={base + 13} className="clock-tick" textAnchor={h === 0 ? 'start' : 'middle'}>{String(h).padStart(2, '0')}:00</text>
        ))}
        {own.map((i) => {
          const sel = i.event_id === selectedEventId;
          const cx = x(minutes(i.time_berlin));
          return (
            <path key={i.event_id} d={`M${cx} ${base + 18} l${sel ? 5 : 4} ${sel ? 9 : 7} h${sel ? -10 : -8} z`} className={sel ? 'own-mark sel' : 'own-mark'}>
              <title>{`${i.ticker} · ${fmtDate(i.date)} · published ${fmtBerlin(i.published_at_utc)}`}</title>
            </path>
          );
        })}
      </svg>
    </div>
  );
}

interface DistProps {
  data: Timing;
  metricKey: string;
  label: string;
  note?: string;
  unit: string;
  source: string;
  isin: string;
  ticker: string;
  selectedEventId: number | null;
  onOpenEvent: (eventId: number, isin: string) => void;
}

/** One strip per group: every event as a dot, the middle half as a box, the median as a line. */
function Distribution({ data, metricKey, label, note, unit, source, isin, ticker, selectedEventId, onOpenEvent }: DistProps) {
  const stats = data.metrics.find((x) => x.key === metricKey)!.by_slot;
  const vals = data.items.map((i) => i.values[metricKey]).filter((v): v is number => v !== null).sort((a, b) => a - b);
  // axis: 0 to the 95th percentile, so one extreme event does not squeeze the rest; dots beyond sit at the edge
  const p95 = vals.length ? vals[Math.floor(0.95 * (vals.length - 1))] : 1;
  const hi = Math.max(p95 * 1.1, ...Object.values(stats).map((s) => (s.p75 ?? 0) * 1.2), unit === 'x' ? 1.5 : 1e-9);
  const pos = (v: number) => Math.min(100, (v / hi) * 100);
  const baseline = unit === 'x' ? 1 : null;

  return (
    <div className="block">
      <div className="block-head"><h3>{label}</h3></div>
      {note && <div className="timing-note">{note}</div>}
      <div className="dist">
        {data.slots.map((s) => {
          const st = stats[s.key];
          const pts = data.items.filter((i) => i.slot === s.key && i.values[metricKey] !== null);
          return (
            <div key={s.key} className="dist-row">
              <div className="dist-label"><span className="dot" style={{ background: SLOT_COLORS[s.key] }} /> {s.label}<span className="muted"> · {st.n}</span></div>
              <div className="dist-track">
                {baseline !== null && <s className="dist-base" style={{ left: `${pos(baseline)}%` }} title="20-day baseline (1.0x)" />}
                {st.p25 !== null && st.p75 !== null && st.n >= 2 && (
                  <i className="dist-box" style={{ left: `${pos(st.p25)}%`, width: `${pos(st.p75) - pos(st.p25)}%`, borderColor: SLOT_COLORS[s.key] }} />
                )}
                {st.median !== null && <b className="dist-median" style={{ left: `${pos(st.median)}%`, background: SLOT_COLORS[s.key] }} title={`Median ${fmtValue(st.median, unit)}`} />}
                {pts.map((i) => {
                  const v = i.values[metricKey] as number;
                  const mine = i.isin === isin;
                  const sel = i.event_id === selectedEventId;
                  return (
                    <button
                      key={i.event_id}
                      className={`dist-dot ${mine ? 'own' : ''} ${sel ? 'sel' : ''} ${v > hi ? 'clip' : ''}`}
                      style={{ left: `${pos(v)}%`, top: `${6 + jitter(i.event_id) * 22}px`, ...(mine || sel ? {} : { background: SLOT_COLORS[s.key] }) }}
                      onClick={() => onOpenEvent(i.event_id, i.isin)}
                      title={`${i.ticker} · ${fmtDate(i.date)} · published ${fmtBerlin(i.published_at_utc)} · ${fmtValue(v, unit)}\n${eventTitle(i)}\nClick for the impact card`}
                      aria-label={`${i.ticker} ${fmtDate(i.date)}: ${fmtValue(v, unit)}`}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
        <div className="dist-axis">
          <span>{fmtValue(0, unit)}</span>
          <span>{fmtValue(hi / 2, unit)}</span>
          <span>{fmtValue(hi, unit)}+</span>
        </div>
      </div>
      <div className="caption">
        Dot = one event (click for its impact card) · <span className="legend-own">●</span> {ticker} · box = middle half · line = median.
        Values on the effective trading day. Source: {sourceLabel(source)}.
      </div>
    </div>
  );
}
