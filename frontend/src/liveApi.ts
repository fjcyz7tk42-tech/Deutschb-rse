// Client for the live feed service (live/app.py): newest EQS announcements and tagesschau.de business news.
// Separate from the Hub API: these announcements are newer than the trading data and are listed, not matched.
import axios from 'axios';

const http = axios.create({ baseURL: '/live' });

export interface LiveEvent {
  id: number;
  isin: string;
  ticker: string | null;
  name: string | null;
  source: 'eqs' | 'tagesschau';
  type: string;
  category: string | null;
  title: string;
  url: string;
  published_at_utc: string;
  fetched_at_utc: string;
}

export interface LiveSourceStatus {
  interval_s: number;
  last_poll: { at_utc: string; ok: number; items: number | null; matched: number | null; new: number | null; error: string | null } | null;
  last_ok_utc: string | null;
  next_poll_utc: string | null;
  events: number;
}

export interface LiveStatus {
  sources: Record<string, LiveSourceStatus>;
  companies: number;
  alerts?: MailInfo & { subscriptions: number };
}

export const getLiveEvents = (isin: string | null, limit = 30, minor = false) =>
  http
    .get<{ events: LiveEvent[] }>('/events', { params: { isin: isin ?? undefined, limit, minor } })
    .then((r) => r.data.events);

export const getLiveStatus = () => http.get<LiveStatus>('/status').then((r) => r.data);

// Mail alerts: addresses entered per stock get a mail for each new announcement (live/notify.py).
export interface Subscription {
  id: number;
  email: string;
  isin: string;
  created_at_utc: string;
}

export interface MailInfo {
  enabled: boolean;
  host: string | null;
  port: number | null;
  max_age_h: number;
}

export const getSubscriptions = (isin: string) =>
  http
    .get<{ subscriptions: Subscription[]; mail: MailInfo }>('/subscriptions', { params: { isin } })
    .then((r) => r.data);

export const addSubscription = (email: string, isin: string) =>
  http
    .post<{ subscription: Subscription; created: boolean; mail: MailInfo }>('/subscriptions', { email, isin })
    .then((r) => r.data);

export const removeSubscription = (id: number) => http.delete(`/subscriptions/${id}`).then(() => undefined);

export const sendTestAlert = (isin: string) =>
  http.post<{ sent: number; mail: MailInfo }>('/subscriptions/test', { isin }).then((r) => r.data);
