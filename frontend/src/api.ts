// Typed client for the team's Hub API (contract: futury_4_2026/docs/api_contract.md).
// Every number shown in this app comes from these responses; the frontend never computes figures
// that the API does not deliver, it only formats them.
import axios from 'axios';

const http = axios.create({ baseURL: '/api' });

export type Status = 'matched' | 'market_day' | 'sector_day' | 'unmatched';

export interface Company {
  isin: string;
  ticker: string;
  name: string;
  index: string;
  sector: string;
  focus: boolean;
  current?: boolean;
}

export interface Fact {
  key: string;
  value: number | null;
  unit: string;
  baseline: number | null;
  date: string;
  source: string;
  status: 'found' | 'not_found' | 'not_checked';
  reason: string | null;
  window?: string;
}

export interface SeriesPoint {
  date: string;
  value: number | null;
  baseline: number | null;
  peer_median: number | null;
  anomaly: boolean;
}

export interface Series {
  isin: string;
  metric: string;
  unit: string;
  source: string;
  order_size: number | null;
  points: SeriesPoint[];
}

export interface HubEvent {
  id: number;
  isin?: string;
  type: string;
  title: string;
  published_at_utc?: string | null;
  effective_trading_day?: string;
  source?: string;
  url: string | null;
}

export interface MarketEvent {
  label: string;
  source: string;
  url: string | null;
}

/** The stock's sector was unusual as a whole that day (computed from Xetra data, not a published event). */
export interface SectorEvent {
  label: string;
  source: string;
  url: string | null;
  sector: string;
  anomalous: number;
  members: number;
}

export interface Case {
  id: string;
  kind: 'episode' | 'event';
  start: string;
  end: string;
  peak_date: string;
  metrics: string[];
  score: number;
  status: Status;
  event: HubEvent | null;
  market_event: MarketEvent | null;
  sector_event?: SectorEvent | null;
}

export interface Cases {
  isin: string;
  counts: Record<Status, number>;
  cases: Case[];
}

export interface Peers {
  isin: string;
  basis: string;
  group: string;
  metric: string;
  unit: string;
  source: string;
  value: number | null;
  rank: number | null;
  of: number;
  median: number | null;
  distribution: { isin: string; ticker: string; value: number }[];
}

export interface SimilarGroup {
  type: string;
  basis: string;
  group: string;
  metric: string;
  n: number;
  percentile: number | null;
}

export interface Impact {
  isin: string;
  date: string;
  status: Status | null;
  event: HubEvent | null;
  market_event: MarketEvent | null;
  sector_event?: SectorEvent | null;
  facts: Fact[];
  intraday: { time: string; turnover: number; price: number | null; buy_share: number | null }[];
  similar: SimilarGroup | null;
  similar_groups?: SimilarGroup[];
  text: string | null;
}

export interface Compare {
  type: string;
  index: string | null;
  sector: string | null;
  metric: string;
  unit: string;
  n: number;
  median: number | null;
  p25: number | null;
  p75: number | null;
  items: { event_id: number; isin: string; ticker: string; date: string; value: number | null; percentile: number | null; selected: boolean }[];
}

export const getCompanies = () =>
  http.get<{ companies: Company[] }>('/companies').then((r) => r.data.companies);

export const getSeries = (isin: string, metric: string, orderSize?: number) =>
  http
    .get<Series>(`/companies/${isin}/timeseries`, { params: { metric, order_size: orderSize } })
    .then((r) => r.data);

export const getTrend = (isin: string) =>
  http.get<{ isin: string; facts: Fact[] }>(`/companies/${isin}/trend`).then((r) => r.data.facts);

export const getPeers = (isin: string, basis: string, metric: string, start?: string, end?: string) =>
  http.get<Peers>(`/companies/${isin}/peers`, { params: { basis, metric, start, end } }).then((r) => r.data);

export const getCases = (isin: string) =>
  http.get<Cases>(`/companies/${isin}/cases`).then((r) => r.data);

export const getImpactDay = (isin: string, day: string) =>
  http.get<Impact>(`/impact/day/${isin}/${day}`).then((r) => r.data);

export const getImpactEvent = (eventId: number) =>
  http.get<Impact>(`/impact/${eventId}`).then((r) => r.data);

export const getCompare = (params: { type: string; index?: string; sector?: string; metric?: string; selected?: number }) =>
  http.get<Compare>('/compare', { params }).then((r) => r.data);

export type TimingSlotKey = 'before_day' | 'pre_open' | 'trading';

export interface TimingStats {
  n: number;
  median: number | null;
  p25: number | null;
  p75: number | null;
}

export interface TimingItem {
  event_id: number;
  isin: string;
  ticker: string;
  date: string;
  published_at_utc: string;
  time_berlin: string;
  slot: TimingSlotKey;
  title: string;
  source: string;
  url: string | null;
  values: Record<string, number | null>;
}

export interface Timing {
  type: string;
  index: string | null;
  sector: string | null;
  n: number;
  n_time_unknown: number;
  time_source: string;
  slots: { key: TimingSlotKey; label: string; rule: string; n: number }[];
  metrics: { key: string; unit: string; source: string; by_slot: Record<TimingSlotKey, TimingStats> }[];
  items: TimingItem[];
}

export const getTiming = (params: { type: string; index?: string; sector?: string }) =>
  http.get<Timing>('/timing', { params }).then((r) => r.data);
