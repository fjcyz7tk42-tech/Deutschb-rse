// Shareable IR snapshot. Opens as a preview; "Print / Save as PDF" uses the browser's print dialog,
// and the print stylesheet shows only this report.
import { useEffect, useRef, useState } from 'react';
import { getPeers, type Cases, type Company, type Fact, type Impact, type Peers } from '../api';
import {
  FACT_LABELS, MATCH_WINDOW_TEXT, STATUS_LABELS, eventTitle, eventTypeLabel, summaryText, fmtBaseline, fmtBerlin, fmtDate, fmtFact, fmtValue, sourceLabel,
} from '../format';

interface Props {
  company: Company;
  trend: Fact[];
  cases: Cases | null;
  impact: Impact | null;
  onClose: () => void;
}

const PEER_METRICS = ['turnover_eur', 'xlm_bps', 'auction_share'];
const PEER_LABELS: Record<string, string> = { turnover_eur: 'Turnover per day', xlm_bps: 'Spread (XLM, EUR 25k)', auction_share: 'Auction share' };

export default function ReportView({ company, trend, cases, impact, onClose }: Props) {
  const [peers, setPeers] = useState<Peers[]>([]);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialogRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
    return () => { document.body.style.overflow = overflow; previous?.focus(); };
  }, []);

  useEffect(() => {
    Promise.all(PEER_METRICS.map((m) => getPeers(company.isin, 'index', m).catch(() => null))).then((r) =>
      setPeers(r.filter((p): p is Peers => !!p)),
    );
  }, [company.isin]);

  const episodes = (cases?.cases ?? [])
    .filter((c) => c.kind === 'episode')
    .sort((a, b) => b.peak_date.localeCompare(a.peak_date))
    .slice(0, 12);

  return (
    <div className="report-overlay" ref={dialogRef} role="dialog" aria-modal="true" aria-label="Report preview" onKeyDown={(e) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose(); }
      if (e.key === 'Tab') {
        const items = dialogRef.current?.querySelectorAll<HTMLElement>('button, a[href]');
        if (!items?.length) return;
        const first = items[0]; const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }}>
      <div className="report-toolbar no-print">
        <span>Report preview</span>
        <button className="btn" onClick={() => window.print()}>Print / Save as PDF</button>
        <button className="btn ghost" onClick={onClose}>Close</button>
      </div>
      <article className="report">
        <header className="r-head">
          <div>
            <div className="r-eyebrow">IssuerLens · IR snapshot</div>
            <h1>{company.name}</h1>
            <div className="r-meta">{company.ticker} · {company.isin} · {company.index} · {company.sector}</div>
          </div>
          <div className="r-meta r-date">Generated {fmtBerlin(new Date().toISOString())}<br />Data: Xetra, 2026</div>
        </header>

        {impact && (
          <section>
            <h2>Impact card, {fmtDate(impact.date)}</h2>
            <p className="r-event">
              {impact.status ? <b>{STATUS_LABELS[impact.status]}. </b> : null}
              {impact.event ? (
                <>
                  {impact.event.effective_trading_day && impact.event.effective_trading_day !== impact.date
                    ? `Nearby, event day ${fmtDate(impact.event.effective_trading_day)}: `
                    : 'On the same day: '}
                  {eventTypeLabel(impact.event.type)}, “{eventTitle(impact.event)}”{impact.event.url ? ` (${impact.event.url})` : ''}.
                </>
              ) : 'No company event found on this day.'}
              {impact.market_event ? ` Market-wide: ${impact.market_event.label}.` : ''}
            </p>
            {impact.text && <p className="r-text">{summaryText(impact.text, impact.event)}</p>}
            <FactTable facts={impact.facts} />
          </section>
        )}

        <section>
          <h2>Trading profile: recent trend</h2>
          <FactTable facts={trend} />
          {trend[0]?.window && <p className="r-note">{trend[0].window}</p>}
        </section>

        <section>
          <h2>Peer comparison, {company.index} members, 2026</h2>
          <table className="r-table">
            <thead><tr><th>Metric</th><th>{company.ticker}</th><th>Index median</th><th>Rank (1 = lowest)</th><th>Source</th></tr></thead>
            <tbody>
              {peers.map((p) => (
                <tr key={p.metric}>
                  <td>{PEER_LABELS[p.metric] ?? p.metric}</td>
                  <td>{fmtValue(p.value, p.unit)}</td>
                  <td>{fmtValue(p.median, p.unit)}</td>
                  <td>{p.rank ?? 'n/a'} of {p.of}</td>
                  <td>{sourceLabel(p.source)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {cases && (
          <section>
            <h2>Unusual days in 2026</h2>
            <p>
              {cases.counts.matched} with a company event nearby ({MATCH_WINDOW_TEXT}), {cases.counts.market_day} on market-wide days,
              {' '}{cases.counts.unmatched} without an event found.
            </p>
            <table className="r-table">
              <thead><tr><th>Day</th><th>Unusual</th><th>Status</th><th>Event nearby</th></tr></thead>
              <tbody>
                {episodes.map((c) => (
                  <tr key={c.id}>
                    <td>{fmtDate(c.peak_date)}</td>
                    <td>{c.metrics.map((m) => m.replace(/_/g, ' ')).join(', ')}</td>
                    <td>{STATUS_LABELS[c.status]}</td>
                    <td>{c.event ? `${eventTypeLabel(c.event.type)}: ${eventTitle(c.event)}` : c.market_event?.label ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <footer className="r-foot">
          Descriptive figures only, no forecasts. An event shown “nearby” lies {MATCH_WINDOW_TEXT} the unusual period;
          it is a match in time, not a cause.
          Sources: Deutsche Börse Xetra OHLC, on-book trades, Flow Dynamics and Xetra Liquidity Measure (XLM); events from
          index constituents, company IR websites and EQS News. Baselines are the median of the previous 20 trading days.
        </footer>
      </article>
    </div>
  );
}

function FactTable({ facts }: { facts: Fact[] }) {
  return (
    <table className="r-table">
      <thead><tr><th>Figure</th><th>Value</th><th>Baseline</th><th>Date</th><th>Source</th></tr></thead>
      <tbody>
        {facts.map((f) => (
          <tr key={f.key}>
            <td>{FACT_LABELS[f.key] ?? f.key}</td>
            <td>{fmtFact(f)}</td>
            <td>{fmtBaseline(f) ?? '–'}</td>
            <td>{fmtDate(f.date)}</td>
            <td>{sourceLabel(f.source)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
