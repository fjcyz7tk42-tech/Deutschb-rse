// Labels and number formatting. Wording is descriptive only: no "good"/"bad", no forecasts,
// and a matched event is "nearby" (within the match window), never "because of".
// The Hub API matches events from 3 trading days before an unusual period to 2 after (config.yaml).
export const MATCH_WINDOW_TEXT = 'from 3 trading days before to 2 trading days after';
import type { Fact, Status } from './api';

export const METRICS: { key: string; label: string; short: string }[] = [
  { key: 'turnover_eur', label: 'Turnover (EUR)', short: 'Turnover' },
  { key: 'rel_volume', label: 'Turnover vs 20-day baseline', short: 'Rel. volume' },
  { key: 'xlm_bps', label: 'Spread, Xetra Liquidity Measure', short: 'Spread (XLM)' },
  { key: 'auction_share', label: 'Auction share of turnover', short: 'Auctions' },
  { key: 'abnormal_return', label: 'Return vs index median', short: 'Abn. return' },
  { key: 'mm_share', label: 'Market maker share of volume', short: 'Market makers' },
  { key: 'agent_share', label: 'Agency share of volume', short: 'Agency' },
  { key: 'prop_share', label: 'Proprietary share of volume', short: 'Proprietary' },
];

export const AUCTION_METRICS = [
  { key: 'auction_share_open', label: 'Opening' },
  { key: 'auction_share_midday', label: 'Midday' },
  { key: 'auction_share_close', label: 'Closing' },
];

export const ORDER_SIZES = [10000, 25000, 50000, 100000, 250000, 500000, 1000000];

export const FACT_LABELS: Record<string, string> = {
  rel_volume: 'Turnover vs baseline',
  return_1d: 'Share price change',
  market_return: 'Market part',
  sector_return: 'Sector part',
  company_return: 'Company-specific part',
  abnormal_return: 'Return vs index median',
  abnormal_return_5d: 'Return vs index, day 0 to +5',
  xlm_bps: 'Spread at EUR 25k (XLM)',
  opening_auction_turnover: 'Opening auction turnover',
  closing_auction_turnover: 'Closing auction turnover',
  open_gap: 'Opening gap',
  close_vs_vwap: 'Close vs VWAP',
  agent_share: 'Agency share',
  prop_share: 'Proprietary share',
  mm_share: 'Market maker share',
  agent_net_flow: 'Agency net flow',
  prop_net_flow: 'Proprietary net flow',
  mm_net_flow: 'Market maker net flow',
  days_to_normal: 'Days until turnover < 1.5x baseline',
  turnover_eur_trend: 'Turnover, median',
  xlm_bps_trend: 'Spread (XLM), median',
  auction_share_trend: 'Auction share, median',
};

export const SOURCE_LABELS: Record<string, string> = {
  XETRA_OHLC: 'Xetra OHLC',
  XLM: 'Xetra Liquidity Measure',
  XETRA_ONBOOK_TRADES: 'Xetra on-book trades',
  XETRA_FLOW_DYNAMICS_EQUITY: 'Xetra Flow Dynamics',
  index_constituents: 'Index constituents',
  manual_csv: 'Company IR website',
  eqs: 'EQS News',
  calendars: 'Public calendar',
  short_positions: 'Bundesanzeiger short positions',
  tagesschau: 'tagesschau.de (business news)',
};

export const EVENT_TYPE_LABELS: Record<string, string> = {
  earnings: 'Results',
  dividend: 'Dividend',
  ad_hoc: 'Ad hoc',
  press_release: 'Press release',
  m_and_a: 'M&A',
  index_change: 'Index change',
  directors_dealing: "Directors' dealing",
  voting_rights: 'Voting rights',
  short_position: 'Short position',
  news: 'News (tagesschau.de)',
  other: 'Other',
};

// Event types the /compare endpoint covers; the others have too few cases.
export const COMPARE_TYPES = ['index_change', 'earnings', 'press_release', 'ad_hoc', 'dividend'];

// Event types the /timing endpoint covers: those with a publication time.
export const TIMING_TYPES = ['earnings', 'ad_hoc', 'm_and_a', 'dividend', 'press_release'];

/** Date-only sources store 00:00 Europe/Berlin: that means "time not known", not midnight. */
export const hasKnownTime = (isoUtc: string | null | undefined) =>
  !!isoUtc && new Date(isoUtc).toLocaleTimeString('en-GB', { timeZone: 'Europe/Berlin', hour: '2-digit', minute: '2-digit' }) !== '00:00';

export const TIMING_METRICS: { key: string; label: string; short: string; note?: string }[] = [
  { key: 'open_gap_abs', label: 'Opening gap, size (absolute)', short: 'Opening gap',
    note: 'For publications during trading, the opening price was set before the announcement.' },
  { key: 'rel_volume', label: 'Turnover vs 20-day baseline', short: 'Turnover' },
  { key: 'abnormal_return_abs', label: 'Return vs index median, size (absolute)', short: 'Return vs index' },
  { key: 'xlm_ratio', label: 'Spread (XLM) vs 20-day baseline', short: 'Spread' },
  { key: 'open_auction_share', label: 'Opening auction share of turnover', short: 'Opening auction' },
  { key: 'close_auction_share', label: 'Closing auction share of turnover', short: 'Closing auction' },
];

export const STATUS_LABELS: Record<Status, string> = {
  matched: 'Event nearby',
  market_day: 'Market-wide day',
  unmatched: 'No event found',
};

export const STATUS_COLORS: Record<Status, string> = {
  matched: 'var(--matched)',
  market_day: 'var(--market)',
  unmatched: 'var(--unmatched)',
};

export const sourceLabel = (s: string) => SOURCE_LABELS[s] ?? s;

/** tagesschau.de content may not be republished: show only a link to their article, never the headline. */
export const isTagesschau = (ev: { url?: string | null; source?: string } | null | undefined) =>
  !!ev && (ev.source === 'tagesschau' || !!ev.url?.includes('tagesschau.de'));

export const TAGESSCHAU_LINK_TEXT = 'Article on tagesschau.de';

export const eventTitle = (ev: { title: string; url?: string | null; source?: string }) =>
  isTagesschau(ev) ? TAGESSCHAU_LINK_TEXT : ev.title;

/** The API's summary quotes the event title; for tagesschau.de events the headline is replaced by a reference. */
export function summaryText(text: string, ev: { title: string; url?: string | null; source?: string } | null): string {
  if (!ev || !isTagesschau(ev) || !ev.title) return text;
  return text.split(`"${ev.title}"`).join('(article on tagesschau.de)').split(ev.title).join('(article on tagesschau.de)');
}
export const eventTypeLabel = (t: string) => EVENT_TYPE_LABELS[t] ?? t;
export const metricLabel = (m: string) =>
  METRICS.find((x) => x.key === m)?.label ?? FACT_LABELS[m] ?? m;

const de = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 2 });

export function fmtEur(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e9) return `EUR ${(v / 1e9).toFixed(2)}bn`;
  if (a >= 1e6) return `EUR ${(v / 1e6).toFixed(1)}m`;
  if (a >= 1e3) return `EUR ${(v / 1e3).toFixed(0)}k`;
  return `EUR ${v.toFixed(0)}`;
}

export function fmtValue(v: number | null | undefined, unit: string, signed = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return 'n/a';
  const sign = signed && v > 0 ? '+' : '';
  switch (unit) {
    case 'EUR':
      return fmtEur(v);
    case '%':
      return `${sign}${v.toFixed(1)}%`;
    case 'pp':
      return `${sign}${v.toFixed(1)} pp`;
    case 'bp':
      return `${v.toFixed(1)} bp`;
    case 'x':
      return `${v.toFixed(2)}x`;
    case 'shares':
      return `${sign}${de.format(Math.round(v))} shares`;
    case 'days':
      return `${v} ${v === 1 ? 'day' : 'days'}`;
    default:
      return `${sign}${de.format(v)} ${unit}`.trim();
  }
}

// Signed units: a "+" helps reading returns and flows.
const SIGNED_KEYS = new Set([
  'return_1d', 'market_return', 'sector_return', 'company_return', 'abnormal_return',
  'abnormal_return_5d', 'open_gap', 'close_vs_vwap', 'agent_net_flow', 'prop_net_flow', 'mm_net_flow',
]);

export function fmtFact(f: Fact): string {
  if (f.status !== 'found') return f.status === 'not_checked' ? 'not checked' : 'no data';
  return fmtValue(f.value, f.unit, SIGNED_KEYS.has(f.key));
}

export function fmtBaseline(f: Fact): string | null {
  if (f.status !== 'found' || f.baseline === null || f.baseline === undefined) return null;
  if (f.unit === 'x' && f.baseline === 1) return null; // rel_volume baseline is 1 by definition
  return fmtValue(f.baseline, f.unit);
}

/** Trading days are plain dates; format them without timezone shifts. */
export function fmtDate(iso: string, withYear = true): string {
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', ...(withYear ? { year: 'numeric' } : {}), timeZone: 'UTC',
  });
}

/** UTC timestamps are shown in Europe/Berlin. */
export function fmtBerlin(isoUtc: string): string {
  return new Date(isoUtc).toLocaleString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    timeZone: 'Europe/Berlin', timeZoneName: 'short',
  });
}

export function factCaption(f: Fact): string {
  return `${fmtDate(f.date)} · ${sourceLabel(f.source)}`;
}

export function compactNumber(v: number, unit: string): string {
  if (unit === 'EUR') return fmtEur(v).replace('EUR ', '');
  if (unit === '%') return `${v.toFixed(0)}%`;
  if (unit === 'bp') return `${v.toFixed(0)}`;
  if (unit === 'x') return `${v.toFixed(1)}x`;
  if (unit === 'pp') return `${v.toFixed(0)}`;
  return de.format(v);
}
