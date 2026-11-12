// Peer benchmarking: where the stock sits in its index, sector or size cohort, as computed by the API.
import { useState } from 'react';
import { getPeers, type Peers } from '../api';
import { useFetch } from '../useFetch';
import { fmtDate, fmtValue, sourceLabel } from '../format';

const BASES = [
  { key: 'index', label: 'Index' },
  { key: 'sector', label: 'Sector' },
  { key: 'size', label: 'Size' },
];
const PEER_METRICS = [
  { key: 'turnover_eur', label: 'Turnover' },
  { key: 'xlm_bps', label: 'Spread' },
  { key: 'auction_share', label: 'Auctions' },
];

interface Props {
  isin: string;
  ticker: string;
  range: { start: string; end: string } | null;
}

export default function PeersPanel({ isin, ticker, range }: Props) {
  const [basis, setBasis] = useState('index');
  const [metric, setMetric] = useState('xlm_bps');
  const req = useFetch<Peers>(`${isin}|${basis}|${metric}|${range?.start ?? ''}|${range?.end ?? ''}`, () =>
    getPeers(isin, basis, metric, range?.start, range?.end),
  );
  const data = req.data;
  const error = req.error ? 'Peer data not available' : null;

  const dist = data?.distribution ?? [];
  const max = Math.max(...dist.map((d) => d.value), data?.value ?? 0, 1e-9);

  return (
    <section className="panel-block">
      <div className="block-head">
        <h3>Peer comparison</h3>
        <div className="seg">
          {BASES.map((b) => (
            <button key={b.key} className={basis === b.key ? 'on' : ''} onClick={() => setBasis(b.key)}>{b.label}</button>
          ))}
        </div>
      </div>
      <div className="seg small">
        {PEER_METRICS.map((m) => (
          <button key={m.key} className={metric === m.key ? 'on' : ''} onClick={() => setMetric(m.key)}>{m.label}</button>
        ))}
      </div>
      {error && <div className="muted">{error}</div>}
      {data && (
        <>
          <div className="peer-summary">
            <div>
              <div className="big">{fmtValue(data.value, data.unit)}</div>
              <div className="muted">{ticker}, median {range ? `${fmtDate(range.start, false)} – ${fmtDate(range.end)}` : '2026'}</div>
            </div>
            <div>
              <div className="big">{data.rank ?? 'n/a'}<span className="of"> / {data.of}</span></div>
              <div className="muted">rank in {data.group} (1 = lowest)</div>
            </div>
            <div>
              <div className="big">{fmtValue(data.median, data.unit)}</div>
              <div className="muted">group median</div>
            </div>
          </div>
          <div className="peer-strip" title="Each tick is one peer; the highlighted tick is the selected stock">
            {dist.map((d) => (
              <span
                key={d.isin}
                className={`tick ${d.isin === isin ? 'self' : ''}`}
                style={{ left: `${(d.value / max) * 100}%` }}
                title={`${d.ticker}: ${fmtValue(d.value, data.unit)}`}
              />
            ))}
            {data.median !== null && <span className="tick median" style={{ left: `${(data.median / max) * 100}%` }} title="Group median" />}
          </div>
          <div className="caption">Source: {sourceLabel(data.source)}{metric === 'xlm_bps' ? ', order size EUR 25,000' : ''}</div>
        </>
      )}
    </section>
  );
}
