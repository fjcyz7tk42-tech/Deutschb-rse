// Event impact card: the reaction of one trading day. Every figure is a fact from the API and shows
// its date and source. A matched event is shown as "nearby" with its own day, never as the cause.
import type { Fact, Impact } from '../api';
import {
  FACT_LABELS, STATUS_COLORS, STATUS_LABELS, TIMING_TYPES, eventTitle, hasKnownTime, eventTypeLabel, factCaption, fmtBaseline, fmtBerlin,
  fmtDate, fmtFact, isTagesschau, sourceLabel, summaryText,
} from '../format';
import IntradayChart from './IntradayChart';

interface Props {
  data: Impact | null;
  loading: boolean;
  error: string | null;
  ticker: string;
  onClose: () => void;
  onCompare: (type: string, eventId: number) => void;
  onTiming: (type: string, eventId: number) => void;
  onExport: () => void;
}

const GROUPS: { title: string; keys: string[] }[] = [
  { title: 'Volume', keys: ['rel_volume', 'days_to_normal'] },
  { title: 'Price', keys: ['return_1d', 'abnormal_return', 'abnormal_return_5d', 'open_gap', 'close_vs_vwap'] },
  { title: 'Return split', keys: ['market_return', 'sector_return', 'company_return'] },
  { title: 'Liquidity & auctions', keys: ['xlm_bps', 'opening_auction_turnover', 'closing_auction_turnover'] },
  { title: 'Who traded (share of volume)', keys: ['agent_share', 'prop_share', 'mm_share'] },
  { title: 'Net flow (bought minus sold)', keys: ['agent_net_flow', 'prop_net_flow', 'mm_net_flow'] },
];

export function FactTile({ f, hero = false }: { f: Fact; hero?: boolean }) {
  const base = fmtBaseline(f);
  const missing = f.status !== 'found';
  const sign = f.status === 'found' && f.value !== null && ['%', 'pp', 'shares'].includes(f.unit)
    ? f.value > 0 ? 'up' : f.value < 0 ? 'down' : ''
    : '';
  return (
    <div className={`fact ${hero ? 'hero' : ''} ${missing ? 'missing' : ''}`} title={f.reason ?? undefined}>
      <div className="fact-label">{FACT_LABELS[f.key] ?? f.key}</div>
      <div className={`fact-value ${sign}`}>{fmtFact(f)}</div>
      {base && <div className="fact-base">baseline {base}</div>}
      {missing && f.reason && <div className="fact-base">{f.reason}</div>}
      <div className="fact-src">{factCaption(f)}</div>
    </div>
  );
}

export default function ImpactCard({ data, loading, error, ticker, onClose, onCompare, onTiming, onExport }: Props) {
  const facts = new Map((data?.facts ?? []).map((f) => [f.key, f]));
  const hero = ['rel_volume', 'abnormal_return', 'xlm_bps', 'closing_auction_turnover']
    .map((k) => facts.get(k))
    .filter((f): f is Fact => !!f);

  return (
    <div className="impact-card">
      <div className="card-head">
        <div>
          <div className="eyebrow">Impact card · {ticker}</div>
          <h2>{data ? fmtDate(data.date) : '…'}</h2>
        </div>
        <div className="card-actions">
          {data && <button className="btn" onClick={onExport}>Export report</button>}
          <button className="btn ghost" onClick={onClose} aria-label="Close">✕</button>
        </div>
      </div>

      {loading && <div className="muted pad">Building the card…</div>}
      {error && <div className="error pad">{error}</div>}

      {data && !loading && (
        <>
          {data.status && (
            <div className="status-pill" style={{ borderColor: STATUS_COLORS[data.status] }}>
              <i className="dot" style={{ background: STATUS_COLORS[data.status] }} />
              {STATUS_LABELS[data.status]}
            </div>
          )}

          {data.event ? (
            <div className="event-box">
              <div className="event-type">
                {eventTypeLabel(data.event.type)}
                {data.event.effective_trading_day && data.event.effective_trading_day !== data.date
                  ? <> · <b className="event-offset">event day {fmtDate(data.event.effective_trading_day)}, {data.event.effective_trading_day < data.date ? 'before' : 'after'} this day</b></>
                  : ' · same day'}
              </div>
              <div className="event-title">
                {data.event.url ? <a href={data.event.url} target="_blank" rel="noreferrer">{eventTitle(data.event)} ↗</a> : eventTitle(data.event)}
              </div>
              <div className="caption">
                {data.event.published_at_utc ? `Published ${fmtBerlin(data.event.published_at_utc)} · ` : ''}
                Source: {sourceLabel(data.event.source ?? '')}
              </div>
              {data.event.type && !isTagesschau(data.event) && (
                <button className="btn small" onClick={() => onCompare(data.event!.type, data.event!.id)}>
                  Compare with other {eventTypeLabel(data.event.type).toLowerCase()} events →
                </button>
              )}
              {TIMING_TYPES.includes(data.event.type) && hasKnownTime(data.event.published_at_utc) && (
                <button className="btn small ghost timing-link" onClick={() => onTiming(data.event!.type, data.event!.id)}>
                  By publication time →
                </button>
              )}
            </div>
          ) : (
            <div className="event-box empty">No company event found on this day.</div>
          )}
          {data.market_event && (
            <div className="market-box">
              On the same day, market-wide: {data.market_event.url ? <a href={data.market_event.url} target="_blank" rel="noreferrer">{data.market_event.label} ↗</a> : data.market_event.label}
            </div>
          )}

          <div className="hero-grid">{hero.map((f) => <FactTile key={f.key} f={f} hero />)}</div>

          {data.text && (
            <div className="ai-text">
              <div className="eyebrow">Summary (AI-written, figures checked against the facts)</div>
              <p>{summaryText(data.text, data.event)}</p>
            </div>
          )}

          <div className="block-head"><h3>Intraday, {fmtDate(data.date)} (Berlin time)</h3></div>
          <IntradayChart bars={data.intraday} />
          <div className="caption">5-minute bars, Xetra on-book trades. Shaded: continuous trading 09:00–17:30; highlighted bars: opening and closing auction.</div>

          {GROUPS.map((g) => {
            const fs = g.keys.map((k) => facts.get(k)).filter((f): f is Fact => !!f);
            if (!fs.length) return null;
            return (
              <div key={g.title} className="fact-group">
                <h4>{g.title}</h4>
                <div className="fact-grid">{fs.map((f) => <FactTile key={f.key} f={f} />)}</div>
              </div>
            );
          })}

          {(data.similar_groups ?? (data.similar ? [data.similar] : [])).length > 0 && (
            <div className="fact-group">
              <h4>Against events of the same type</h4>
              <div className="similar-list">
                {(data.similar_groups ?? [data.similar!]).map((s) => (
                  <div key={s.basis} className="similar-row">
                    <span>{s.basis === 'universe' ? 'All DAX/MDAX/SDAX' : s.group}</span>
                    <span className="pct-bar"><i style={{ width: `${s.percentile ?? 0}%` }} /></span>
                    <span>{s.percentile !== null ? `${s.percentile}th pct.` : 'n/a'} of {s.n}</span>
                  </div>
                ))}
              </div>
              <div className="caption">Percentile of turnover vs baseline among {eventTypeLabel(data.similar_groups?.[0]?.type ?? data.similar?.type ?? '').toLowerCase()} events in 2026.</div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
