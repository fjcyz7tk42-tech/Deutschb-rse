// Unusual days and company events, newest first. The count line is always shown.
import { useMemo, useState } from 'react';
import type { Case, Cases, Status } from '../api';
import { STATUS_COLORS, STATUS_LABELS, eventTitle, eventTypeLabel, fmtDate } from '../format';

interface Props {
  data: Cases | null;
  selectedDate: string | null;
  onOpen: (c: Case) => void;
}

const MINOR = ['voting_rights', 'directors_dealing', 'short_position'];

export default function CasesPanel({ data, selectedDate, onOpen }: Props) {
  const [filter, setFilter] = useState<Status | 'events' | 'all'>('all');

  const list = useMemo(() => {
    const all = (data?.cases ?? []).filter((c) => c.kind === 'episode' || !MINOR.includes(c.event?.type ?? ''));
    const f = all.filter((c) =>
      filter === 'all' ? true : filter === 'events' ? c.kind === 'event' : c.kind === 'episode' && c.status === filter,
    );
    return f.sort((a, b) => b.peak_date.localeCompare(a.peak_date));
  }, [data, filter]);

  return (
    <section className="panel-block cases">
      <div className="block-head">
        <h3>Unusual days &amp; events</h3>
      </div>
      {data && (
        <div className="count-line">
          {(['matched', 'market_day', 'unmatched'] as Status[]).map((s) => (
            <button key={s} className={`count ${filter === s ? 'on' : ''}`} onClick={() => setFilter(filter === s ? 'all' : s)}>
              <i className="dot" style={{ background: STATUS_COLORS[s] }} />
              <b>{data.counts[s]}</b> {STATUS_LABELS[s].toLowerCase()}
            </button>
          ))}
          <button className={`count ${filter === 'events' ? 'on' : ''}`} onClick={() => setFilter(filter === 'events' ? 'all' : 'events')}>
            <i className="dot ring" /> company events
          </button>
        </div>
      )}
      <div className="case-list">
        {!data && <div className="muted pad">Loading…</div>}
        {list.map((c) => (
          <div key={c.id} className={`case-item ${selectedDate === c.peak_date ? 'active' : ''}`}>
          <button className="case-row" onClick={() => onOpen(c)}>
            <i
              className={`dot ${c.kind === 'event' ? 'ring' : ''}`}
              style={c.kind === 'episode' ? { background: STATUS_COLORS[c.status] } : undefined}
            />
            <span className="case-date">{fmtDate(c.peak_date, false)}</span>
            <span className="case-body">
              <span className="case-title">
                {c.event ? eventTitle(c.event) : c.kind === 'episode' ? 'No company event found' : ''}
              </span>
              <span className="case-meta">
                {c.kind === 'episode' && <>Unusual {c.metrics.map((m) => m.replace(/_/g, ' ')).join(', ')}</>}
                {c.kind === 'episode' && c.event && ' · '}
                {c.event && eventTypeLabel(c.event.type)}
                {c.market_event && <> · market: {c.market_event.label}</>}
                {c.start !== c.end && <> · {fmtDate(c.start, false)}–{fmtDate(c.end, false)}</>}
              </span>
            </span>
          </button>
          {c.event?.url && (
            <a
              className="case-link"
              href={c.event.url}
              target="_blank"
              rel="noreferrer"
              title={`Open the source: ${new URL(c.event.url).hostname.replace(/^www\./, '')}`}
            >
              ↗
            </a>
          )}
          </div>
        ))}
        {data && list.length === 0 && <div className="muted pad">Nothing in this group</div>}
      </div>
    </section>
  );
}
