// Live feed: newest announcements for the selected stock or all index stocks, refreshed every 30 s.
// tagesschau.de items show only a link (their content may not be republished). Below: mail alerts for the stock.
import { useCallback, useEffect, useState } from 'react';
import { getLiveEvents, getLiveStatus, type LiveEvent, type LiveStatus } from '../liveApi';
import { TAGESSCHAU_LINK_TEXT, eventTypeLabel, fmtBerlin } from '../format';
import MailAlerts from './MailAlerts';

const REFRESH_MS = 30_000;
const NEW_MS = 3 * 60 * 60 * 1000; // "new" badge: published in the last 3 hours

interface Props {
  isin: string;
  ticker: string;
}

function ago(isoUtc: string | null | undefined, now: number): string {
  if (!isoUtc) return 'never';
  const s = Math.max(0, Math.round((now - new Date(isoUtc).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

export default function LivePanel({ isin, ticker }: Props) {
  const [scope, setScope] = useState<'stock' | 'all'>('stock');
  const [minor, setMinor] = useState(false);
  const [events, setEvents] = useState<LiveEvent[] | null>(null);
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [offline, setOffline] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(() => {
    Promise.all([getLiveEvents(scope === 'stock' ? isin : null, scope === 'stock' ? 15 : 25, minor), getLiveStatus()])
      .then(([ev, st]) => {
        if (!Array.isArray(ev) || !st?.sources) throw new Error('unexpected live response');
        setEvents(ev);
        setStatus(st);
        setOffline(false);
        setNow(Date.now());
      })
      .catch(() => setOffline(true));
  }, [isin, scope, minor]);

  useEffect(() => {
    const first = setTimeout(load, 0);
    const t = setInterval(load, REFRESH_MS);
    const clock = setInterval(() => setNow(Date.now()), 10_000); // keeps "x min ago" current
    return () => {
      clearTimeout(first);
      clearInterval(t);
      clearInterval(clock);
    };
  }, [load]);

  const eqs = status?.sources.eqs;
  const ts = status?.sources.tagesschau;

  return (
    <section className="panel-block live">
      <div className="block-head">
        <h3><span className={`live-dot ${offline ? 'off' : ''}`} /> Live announcements</h3>
        <div className="seg">
          <button className={scope === 'stock' ? 'on' : ''} onClick={() => setScope('stock')}>{ticker}</button>
          <button className={scope === 'all' ? 'on' : ''} onClick={() => setScope('all')}>All index stocks</button>
        </div>
      </div>

      {offline ? (
        <div className="muted pad">Live announcements are temporarily unavailable. We’ll check again automatically.</div>
      ) : (
        <>
          <div className="live-status">
            EQS News checked {ago(eqs?.last_ok_utc, now)}{eqs?.last_poll && !eqs.last_poll.ok ? ' (last attempt failed)' : ''}
            {' · '}tagesschau.de {ago(ts?.last_ok_utc, now)}
            <label className="minor-toggle">
              <input type="checkbox" checked={minor} onChange={(e) => setMinor(e.target.checked)} />
              Holding notices
            </label>
          </div>
          <div className="live-list">
            {events === null && <div className="muted pad">Loading…</div>}
            {events?.length === 0 && (
              <div className="muted pad">
                {scope === 'stock' ? `No new announcements for ${ticker} since the feed started.` : 'No announcements yet.'}
              </div>
            )}
            {events?.map((e) => {
              const isNew = now - new Date(e.published_at_utc).getTime() < NEW_MS;
              const title = e.source === 'tagesschau' ? TAGESSCHAU_LINK_TEXT : e.title;
              return (
                <a key={e.id} className="live-row" href={e.url} target="_blank" rel="noreferrer">
                  <span className="live-time">{fmtBerlin(e.published_at_utc)}</span>
                  <span className="live-body">
                    <span className="live-title">
                      {isNew && <b className="live-new">NEW</b>}
                      {scope === 'all' && e.ticker && <b className="live-ticker">{e.ticker}</b>}
                      {title} ↗
                    </span>
                    <span className="case-meta">
                      {eventTypeLabel(e.type)} · {e.source === 'eqs' ? 'EQS News' : 'tagesschau.de'}
                    </span>
                  </span>
                </a>
              );
            })}
          </div>
          <div className="caption">
            Announcements after 30 Oct 2026 have no trading data in this prototype yet: they are listed, not matched to
            unusual days.
          </div>
          <MailAlerts key={isin} isin={isin} ticker={ticker} />
        </>
      )}
    </section>
  );
}
