// Liquidity Pulse: has trading the stock become cheaper or dearer? One word (Stronger / Weaker / Mixed / Steady), whether the
// change is market-wide or stock-specific, and the two measures behind it. The rule and all figures come from the Hub API
// (/companies/{isin}/pulse); the same function answers "Has our liquidity improved?" in the assistant.
import type { Pulse, PulseMetric } from '../api';
import { fmtDate, fmtEur, sourceLabel } from '../format';

const CONTEXT_TEXT: Record<string, string> = {
  'market-wide': 'Market-wide',
  'stock-specific': 'Stock-specific',
  'partly market-wide': 'Partly market-wide',
};

const fmtPct = (v: number | null) => (v === null ? 'n/a' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`);
const fmtLevel = (m: PulseMetric, v: number | null) => (v === null ? 'n/a' : m.unit === 'EUR' ? fmtEur(v) : `${v.toFixed(1)} bp`);

export default function LiquidityPulse({ pulse }: { pulse: Pulse | null }) {
  if (!pulse) return null;
  if (pulse.status !== 'found' || !pulse.state) {
    return (
      <section className="pulse pulse-none" aria-label="Liquidity Pulse">
        <div className="pulse-head"><span className="pulse-name">Liquidity Pulse</span><span className="pulse-state">Not available in this dataset</span></div>
        <p className="fact-src">{pulse.reason}</p>
      </section>
    );
  }
  return (
    <section className={`pulse pulse-${pulse.state}`} aria-label="Liquidity Pulse">
      <div className="pulse-head">
        <span className="pulse-name">Liquidity Pulse</span>
        <span className="pulse-state" title={pulse.rule}>{pulse.label}</span>
        {pulse.context && <span className="pulse-chip" title={`Compared with the median change of the ${pulse.index_members} ${pulse.index} stocks`}>{CONTEXT_TEXT[pulse.context]}</span>}
        {pulse.gap_pp != null && <span className="pulse-chip" title="Spread improvement and turnover change point in opposite directions; distance between the two">{pulse.gap_pp} pp apart</span>}
        <details className="pulse-rule">
          <summary>How it works</summary>
          <p>{pulse.rule}</p>
        </details>
      </div>
      <div className="pulse-measures">
        {pulse.metrics?.map((m) => (
          <div key={m.key} className={`pulse-measure ${m.direction ?? ''}`}>
            <div className="fact-label">{m.label}</div>
            <div className="pulse-change">{fmtPct(m.change_pct)}</div>
            <div className="fact-base">{fmtLevel(m, m.value)} vs {fmtLevel(m, m.baseline)} before · {pulse.index} median {fmtPct(m.index_median_change_pct)}</div>
          </div>
        ))}
      </div>
      <div className="fact-src">
        Last 20 trading days to {pulse.date ? fmtDate(pulse.date) : 'n/a'} vs the 60 before · Source: {pulse.metrics?.map((m) => sourceLabel(m.source)).join(', ')}
      </div>
    </section>
  );
}
