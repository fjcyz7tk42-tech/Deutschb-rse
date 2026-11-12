// Each day's event marker sits on its closing price. Days with several entries offer a picker.
// Click a day or marker for its impact card; drag across the chart to select a period.
import { useEffect, useMemo, useRef, useState } from 'react';
import * as d3 from 'd3';
import type { Case, Series } from '../api';
import { useSize } from '../useSize';
import { STATUS_COLORS, STATUS_LABELS, eventTitle, eventTypeLabel, fmtDate, fmtEur } from '../format';

export interface DayInfo {
  date: string;
  close: number | null;
  change: number | null;
  turnover: number | null;
  anomaly: boolean;
}

interface Props {
  price: Series | null;
  turnover: Series | null;
  cases: Case[];
  selectedDate: string | null;
  range: { start: string; end: string } | null;
  onHover: (day: DayInfo | null) => void;
  onDayClick: (date: string) => void;
  onCaseClick: (c: Case) => void;
  onRangeSelect: (range: { start: string; end: string } | null) => void;
}

const M = { top: 14, right: 60, bottom: 26, left: 16 };

export default function PriceChart({ price, turnover, cases, selectedDate, range, onHover, onDayClick, onCaseClick, onRangeSelect }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);
  const { width, height } = useSize(wrapRef);
  const [showMinor, setShowMinor] = useState(false);
  const [pickedDay, setPickedDay] = useState<{ isin: string; date: string } | null>(null);

  const rows = useMemo(() => {
    if (!price) return [];
    const tv = new Map((turnover?.points ?? []).map((p) => [p.date, p]));
    return price.points
      .filter((p) => p.value !== null)
      .map((p, i, arr) => {
        const prev = i > 0 ? arr[i - 1].value : null;
        const t = tv.get(p.date);
        return {
          date: p.date,
          d: new Date(`${p.date}T00:00:00Z`),
          close: p.value as number,
          change: prev ? ((p.value as number) / prev - 1) * 100 : null,
          turnover: t?.value ?? null,
          anomaly: t?.anomaly ?? false,
        };
      });
  }, [price, turnover]);

  // Holding notices (voting rights, directors' dealings, short positions) are many and small;
  // they are hidden unless the user asks for them.
  const visibleCases = useMemo(
    () =>
      cases.filter(
        (c) =>
          c.kind === 'episode' ||
          showMinor ||
          !['voting_rights', 'directors_dealing', 'short_position'].includes(c.event?.type ?? ''),
      ),
    [cases, showMinor],
  );

  const dayCases = pickedDay?.isin === price?.isin
    ? visibleCases.filter((c) => c.peak_date === pickedDay?.date)
    : [];

  useEffect(() => {
    if (!pickedDay) return;
    pickerRef.current?.querySelector<HTMLButtonElement>('.chart-day-choice')?.focus();
    const closeOutside = (e: PointerEvent) => {
      if (!pickerRef.current?.contains(e.target as Node)) setPickedDay(null);
    };
    document.addEventListener('pointerdown', closeOutside);
    return () => document.removeEventListener('pointerdown', closeOutside);
  }, [pickedDay]);

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();
    if (!rows.length || width < 50 || height < 50) return;

    const w = width - M.left - M.right;
    const h = height - M.top - M.bottom;
    const priceH = h * 0.72;
    const volTop = priceH + h * 0.06;
    const volH = h - volTop;

    svg.attr('width', width).attr('height', height);
    const g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`);

    const x = d3.scaleTime().domain(d3.extent(rows, (r) => r.d) as [Date, Date]).range([0, w]);
    const [lo, hi] = d3.extent(rows, (r) => r.close) as [number, number];
    const pad = (hi - lo) * 0.08 || 1;
    const y = d3.scaleLinear().domain([lo - pad, hi + pad]).range([priceH, 0]);
    const yv = d3.scaleLinear().domain([0, d3.max(rows, (r) => r.turnover ?? 0) || 1]).range([volH, 0]);

    // grid + axes
    g.append('g')
      .attr('class', 'grid')
      .call(d3.axisLeft(y).ticks(6).tickSize(-w).tickFormat(() => ''));
    g.append('g')
      .attr('class', 'axis')
      .attr('transform', `translate(${w},0)`)
      .call(d3.axisRight(y).ticks(6).tickSize(0).tickPadding(8).tickFormat((v) => `€${Number(v).toFixed(Number(v) < 20 ? 1 : 0)}`));
    g.append('g')
      .attr('class', 'axis')
      .attr('transform', `translate(0,${h})`)
      .call(d3.axisBottom(x).ticks(Math.max(3, Math.floor(w / 90))).tickFormat(d3.timeFormat('%b') as never));
    g.append('g')
      .attr('class', 'axis')
      .attr('transform', `translate(${w},${volTop})`)
      .call(d3.axisRight(yv).ticks(2).tickSize(0).tickPadding(8).tickFormat((v) => fmtEur(Number(v)).replace('EUR ', '')));

    g.append('g').attr('class', 'grid').attr('transform', `translate(0,${priceH})`)
      .call(d3.axisBottom(x).ticks(Math.max(3, Math.floor(w / 90))).tickSize(-priceH).tickFormat(() => ''));

    // Turnover: direction uses the same close-to-close change shown in the readout.
    const bw = Math.max(1, (w / rows.length) * 0.7);
    g.append('g')
      .selectAll('rect')
      .data(rows.filter((r) => r.turnover !== null))
      .join('rect')
      .attr('x', (r) => x(r.d) - bw / 2)
      .attr('width', bw)
      .attr('y', (r) => volTop + yv(r.turnover as number))
      .attr('height', (r) => volH - yv(r.turnover as number))
      .style('fill', (r) => (r.anomaly ? 'var(--matched)' : r.change === null ? 'var(--bar)' : r.change >= 0 ? 'var(--bar-up)' : 'var(--bar-down)'));

    // A plain price line on a white plot, with the latest available close on the axis.
    const line = d3.line<(typeof rows)[0]>().x((r) => x(r.d)).y((r) => y(r.close));
    g.append('path').datum(rows).attr('d', line).attr('class', 'ln-value');
    const last = rows[rows.length - 1];
    const lastY = y(last.close);
    g.append('line').attr('class', 'last-price-line').attr('x1', 0).attr('x2', w).attr('y1', lastY).attr('y2', lastY);
    const label = g.append('g').attr('class', 'last-price-label').attr('transform', `translate(${w + 2},${lastY})`);
    label.append('rect').attr('x', 0).attr('y', -10).attr('width', 54).attr('height', 20);
    label.append('text').attr('x', 27).attr('dy', '.35em').attr('text-anchor', 'middle').text(last.close.toFixed(2));

    // selected day marker
    const byDate = new Map(rows.map((r) => [r.date, r]));
    if (selectedDate && byDate.has(selectedDate)) {
      const sx = x(byDate.get(selectedDate)!.d);
      g.append('line').attr('x1', sx).attr('x2', sx).attr('y1', 0).attr('y2', h).attr('class', 'selected-day');
    }

    // crosshair
    const cross = g.append('line').attr('class', 'crosshair').attr('y1', 0).attr('y2', h).style('display', 'none');

    // brush (drag = period, click = day)
    const bisect = d3.bisector<(typeof rows)[0], Date>((r) => r.d).center;
    const snap = (px: number) => rows[Math.max(0, Math.min(rows.length - 1, bisect(rows, x.invert(px))))];
    let moving = false;
    const brush = d3
      .brushX()
      .extent([[0, 0], [w, h]])
      .on('end', function (event) {
        if (moving) return;
        if (!event.selection) {
          if (event.sourceEvent) {
            const [mx] = d3.pointer(event.sourceEvent, g.node());
            onDayClick(snap(mx).date);
          }
          return;
        }
        const [x0, x1] = event.selection as [number, number];
        const a = snap(x0);
        const b = snap(x1);
        moving = true;
        if (a.date === b.date) {
          d3.select(this).call(brush.move as never, null);
          onRangeSelect(null);
        } else {
          d3.select(this).call(brush.move as never, [x(a.d), x(b.d)]);
          onRangeSelect({ start: a.date, end: b.date });
        }
        moving = false;
      });
    const bg = g.append('g').attr('class', 'brush').call(brush);
    if (range && byDate.has(range.start) && byDate.has(range.end)) {
      moving = true;
      bg.call(brush.move, [x(byDate.get(range.start)!.d), x(byDate.get(range.end)!.d)]);
      moving = false;
    }
    bg.select('.overlay')
      .style('cursor', 'crosshair')
      .on('mousemove.hover', (event: MouseEvent) => {
        const [mx] = d3.pointer(event);
        const r = snap(mx);
        cross.attr('x1', x(r.d)).attr('x2', x(r.d)).style('display', null);
        onHover({ date: r.date, close: r.close, change: r.change, turnover: r.turnover, anomaly: r.anomaly });
      })
      .on('mouseleave.hover', () => {
        cross.style('display', 'none');
        onHover(null);
      });

    // The marker uses exactly the price line's coordinates. Group coincident entries
    // instead of shifting them away from the price or covering up their click targets.
    const tip = tipRef.current;
    if (tip) tip.style.display = 'none';
    const grouped = d3.group(visibleCases
      .filter((c) => byDate.has(c.peak_date))
      .sort((a, b) => (a.kind === b.kind ? b.score - a.score : a.kind === 'episode' ? -1 : 1)), (c) => c.peak_date);
    const dots = [...grouped.values()].map((entries) => {
      const c = entries[0];
      const r = byDate.get(c.peak_date)!;
      return { c, entries, cx: x(r.d), cy: y(r.close) };
    });
    const openMarker = (d: (typeof dots)[number]) => {
      if (tip) tip.style.display = 'none';
      if (d.entries.length > 1 && price) setPickedDay({ isin: price.isin, date: d.c.peak_date });
      else { setPickedDay(null); onCaseClick(d.c); }
    };

    g.append('g')
      .selectAll('circle')
      .data(dots)
      .join('circle')
      .attr('class', (d) => `case-dot ${d.c.kind}`)
      .attr('tabindex', 0)
      .attr('role', 'button')
      .attr('aria-label', (d) => `${fmtDate(d.c.peak_date)}: ${d.entries.length > 1 ? `choose from ${d.entries.length} entries` : d.c.event ? eventTitle(d.c.event) : STATUS_LABELS[d.c.status]}`)
      .attr('cx', (d) => d.cx)
      .attr('cy', (d) => d.cy)
      .attr('r', (d) => (d.c.kind === 'episode' ? Math.min(6, 3 + d.c.score / 12) : 3))
      .style('fill', (d) => (d.c.kind === 'episode' ? STATUS_COLORS[d.c.status] : 'var(--panel)'))
      .style('stroke', (d) => (d.c.kind === 'episode' ? 'var(--bg)' : 'var(--event)'))
      .on('click', (_e, d) => openMarker(d))
      .on('keydown', (e: KeyboardEvent, d) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openMarker(d); }
      })
      .on('mouseenter', (_event: MouseEvent, d) => {
        if (!tip) return;
        const title = d.c.event ? `${eventTypeLabel(d.c.event.type)}: ${eventTitle(d.c.event)}` : 'No company event found in the window';
        const head = d.c.kind === 'episode'
          ? `Unusual ${d.c.metrics.join(', ').replace(/_/g, ' ')} · ${STATUS_LABELS[d.c.status]}`
          : 'Company event';
        tip.innerHTML = `<div class="tip-date">${fmtDate(d.c.peak_date)}</div><div class="tip-head">${escapeHtml(head)}</div><div>${escapeHtml(title)}</div>${
          (d.c.market_event ? `<div class="tip-market">Market: ${escapeHtml(d.c.market_event.label)}</div>` : '') +
          (d.c.sector_event && !d.c.event ? `<div class="tip-market">Sector: ${escapeHtml(d.c.sector_event.label)}</div>` : '')
        }${d.entries.length > 1 ? `<div class="tip-head">${d.entries.length} entries on this day · click to choose</div>` : ''}`;
        tip.style.display = 'block';
        const left = M.left + d.cx + (d.cx > w / 2 ? -270 : 12);
        tip.style.left = `${Math.max(4, Math.min(width - Math.min(260, width - 8) - 4, left))}px`;
        tip.style.top = `${M.top + d.cy - 10}px`;
      })
      .on('mouseleave', () => {
        if (tip) tip.style.display = 'none';
      });
  }, [rows, price, visibleCases, width, height, selectedDate, range, onHover, onDayClick, onCaseClick, onRangeSelect]);

  return (
    <div className="price-chart">
      <div className="price-plot" ref={wrapRef}>
        <svg ref={svgRef} role="img" aria-label="Share price and daily turnover. Select an event from the events list for a keyboard-accessible analysis." />
        <div className="chart-tip" ref={tipRef} style={{ display: 'none' }} />
        {!price && <div className="chart-empty">Loading share price…</div>}
      </div>
      {pickedDay && dayCases.length > 1 && (
        <div className="chart-day-picker" ref={pickerRef} role="dialog" aria-label={`Events on ${fmtDate(pickedDay.date)}`} onKeyDown={(e) => {
          if (e.key === 'Escape') { e.stopPropagation(); setPickedDay(null); }
        }}>
          <div className="chart-day-head"><strong>{fmtDate(pickedDay.date)} · {dayCases.length} entries</strong><button className="btn ghost small" aria-label="Close event selection" onClick={() => setPickedDay(null)}>×</button></div>
          <div className="chart-day-list">
            {dayCases.map((c) => <button className="chart-day-choice" key={c.id} onClick={() => { setPickedDay(null); onCaseClick(c); }}>
              <i className={`dot ${c.kind === 'event' ? 'ring' : ''}`} style={c.kind === 'episode' ? { background: STATUS_COLORS[c.status] } : undefined} />
              <span><b>{c.event ? eventTitle(c.event) : 'No company event found'}</b><small>{c.kind === 'episode' ? `Unusual ${c.metrics.join(', ').replace(/_/g, ' ')}` : eventTypeLabel(c.event?.type ?? 'other')}</small></span>
            </button>)}
          </div>
        </div>
      )}
      <div className="chart-legend">
        <span><i className="dot" style={{ background: 'var(--matched)' }} />Unusual day, event nearby</span>
        <span><i className="dot" style={{ background: 'var(--market)' }} />Market-wide day</span>
        <span><i className="dot" style={{ background: 'var(--sector)' }} />Sector-wide day</span>
        <span><i className="dot" style={{ background: 'var(--unmatched)' }} />No event found</span>
        <span><i className="dot ring" />Company event</span>
        <span><i className="bar" />Unusual turnover</span>
        <label className="minor-toggle">
          <input type="checkbox" checked={showMinor} onChange={(e) => setShowMinor(e.target.checked)} />
          Holding notices
        </label>
      </div>
    </div>
  );
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]!);
}
