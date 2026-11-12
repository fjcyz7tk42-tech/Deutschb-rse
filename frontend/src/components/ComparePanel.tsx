// Same-type comparison: one bar per event of the chosen type, e.g. all results days in the DAX in 2026.
import { useState } from 'react';
import { getCompare, type Compare } from '../api';
import { useFetch } from '../useFetch';
import { COMPARE_TYPES, eventTypeLabel, fmtDate, fmtValue } from '../format';

const COMPARE_METRICS = [
  { key: 'rel_volume', label: 'Turnover vs baseline' },
  { key: 'abnormal_return', label: 'Return vs index' },
  { key: 'car_5', label: 'Return vs index, 5 days' },
  { key: 'xlm_bps', label: 'Spread' },
  { key: 'opening_auction_turnover', label: 'Opening auction' },
  { key: 'closing_auction_turnover', label: 'Closing auction' },
];

interface Props {
  initialType: string;
  initialIndex: string;
  selectedEventId: number | null;
  onOpenEvent: (eventId: number, isin: string) => void;
  onClose: () => void;
}

export default function ComparePanel({ initialType, initialIndex, selectedEventId, onOpenEvent, onClose }: Props) {
  const [type, setType] = useState(initialType);
  const [index, setIndex] = useState(initialIndex);
  const [metric, setMetric] = useState('rel_volume');
  // The parent remounts this panel (key) when the starting type or index changes.
  const req = useFetch<Compare>(`${type}|${index}|${metric}|${selectedEventId ?? ''}`, () =>
    getCompare({ type, metric, index: index === 'all' ? undefined : index, selected: selectedEventId ?? undefined }),
  );
  const data = req.data;
  const error = req.error ? 'No comparison available for this selection' : null;

  const items = [...(data?.items ?? [])].filter((i) => i.value !== null).sort((a, b) => (b.value as number) - (a.value as number));
  const vals = items.map((i) => i.value as number);
  const lo = Math.min(0, ...vals);
  const hi = Math.max(...vals, 1e-9);
  const pos = (v: number) => ((v - lo) / (hi - lo || 1)) * 100;

  return (
    <div className="compare-panel">
      <div className="card-head">
        <div>
          <div className="eyebrow">Event comparison</div>
          <h2>{eventTypeLabel(type)} · {index === 'all' ? 'DAX, MDAX, SDAX' : index} · 2026</h2>
        </div>
        <button className="btn ghost" onClick={onClose} aria-label="Close">✕</button>
      </div>

      <div className="compare-controls">
        <select aria-label="Event type" value={type} onChange={(e) => setType(e.target.value)}>
          {COMPARE_TYPES.map((t) => <option key={t} value={t}>{eventTypeLabel(t)}</option>)}
        </select>
        <select aria-label="Index" value={index} onChange={(e) => setIndex(e.target.value)}>
          {['DAX', 'MDAX', 'SDAX', 'all'].map((i) => <option key={i} value={i}>{i === 'all' ? 'All indices' : i}</option>)}
        </select>
        <select aria-label="Comparison metric" value={metric} onChange={(e) => setMetric(e.target.value)}>
          {COMPARE_METRICS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
        </select>
      </div>

      {error && <div className="muted pad">{error}</div>}
      {!data && !error && <div className="muted pad">Loading…</div>}
      {data && (
        <>
          <div className="peer-summary">
            <div><div className="big">{data.n}</div><div className="muted">events</div></div>
            <div><div className="big">{fmtValue(data.median, data.unit)}</div><div className="muted">median</div></div>
            <div><div className="big small">{fmtValue(data.p25, data.unit)} – {fmtValue(data.p75, data.unit)}</div><div className="muted">middle half (p25–p75)</div></div>
          </div>
          <div className="compare-list">
            {items.map((i) => (
              <button
                key={i.event_id}
                className={`compare-row ${i.selected || i.event_id === selectedEventId ? 'selected' : ''}`}
                onClick={() => onOpenEvent(i.event_id, i.isin)}
                title="Open the impact card of this event"
              >
                <span className="c-label"><b>{i.ticker}</b> {fmtDate(i.date, false)}</span>
                <span className="c-track">
                  <i style={{ left: `${pos(Math.min(0, i.value as number))}%`, width: `${Math.abs(pos(i.value as number) - pos(0))}%` }} />
                  {data.median !== null && <s style={{ left: `${pos(data.median)}%` }} title="Median" />}
                </span>
                <span className="c-val">{fmtValue(i.value, data.unit)}</span>
              </button>
            ))}
          </div>
          <div className="caption">Sources: Xetra OHLC, Xetra on-book trades, XLM; events from index constituents, company IR sites and EQS News.</div>
        </>
      )}
    </div>
  );
}
