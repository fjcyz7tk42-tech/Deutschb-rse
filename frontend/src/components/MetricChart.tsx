// One metric over time: the stock, its own 20-day baseline and the median of its index peers.
// Days the API marks as unusual get a dot. Click a day to open its impact card.
import { useEffect, useRef } from 'react';
import * as d3 from 'd3';
import type { Series } from '../api';
import { useSize } from '../useSize';
import { compactNumber, fmtDate, fmtValue, sourceLabel } from '../format';

interface Props {
  series: Series | null;
  selectedDate: string | null;
  hoverDate: string | null;
  onDayClick: (date: string) => void;
}

const M = { top: 10, right: 16, bottom: 22, left: 52 };

export default function MetricChart({ series, selectedDate, hoverDate, onDayClick }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const { width, height } = useSize(wrapRef);

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();
    if (!series || width < 50 || height < 40) return;
    const pts = series.points.map((p) => ({ ...p, d: new Date(`${p.date}T00:00:00Z`) }));
    if (!pts.length) return;

    const w = width - M.left - M.right;
    const h = height - M.top - M.bottom;
    svg.attr('width', width).attr('height', height);
    const g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`);

    const vals = pts.flatMap((p) => [p.value, p.baseline, p.peer_median]).filter((v): v is number => v !== null);
    const [lo, hi] = d3.extent(vals) as [number, number];
    const x = d3.scaleTime().domain(d3.extent(pts, (p) => p.d) as [Date, Date]).range([0, w]);
    const y = d3.scaleLinear().domain([Math.min(0, lo), hi * 1.05 || 1]).nice().range([h, 0]);

    g.append('g').attr('class', 'grid').call(d3.axisLeft(y).ticks(4).tickSize(-w).tickFormat(() => ''));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(4).tickFormat((v) => compactNumber(Number(v), series.unit)));
    g.append('g')
      .attr('class', 'axis')
      .attr('transform', `translate(0,${h})`)
      .call(d3.axisBottom(x).ticks(Math.max(3, Math.floor(w / 90))).tickFormat(d3.timeFormat('%b') as never));

    type P = (typeof pts)[0];
    const mk = (acc: (p: P) => number | null) =>
      d3.line<P>().defined((p) => acc(p) !== null).x((p) => x(p.d)).y((p) => y(acc(p) as number));

    g.append('path').datum(pts).attr('class', 'ln-peer').attr('d', mk((p) => p.peer_median));
    g.append('path').datum(pts).attr('class', 'ln-base').attr('d', mk((p) => p.baseline));
    g.append('path').datum(pts).attr('class', 'ln-value').attr('d', mk((p) => p.value));

    g.append('g')
      .selectAll('circle')
      .data(pts.filter((p) => p.anomaly && p.value !== null))
      .join('circle')
      .attr('class', 'anomaly-dot')
      .attr('cx', (p) => x(p.d))
      .attr('cy', (p) => y(p.value as number))
      .attr('r', 3.2)
      .on('click', (_e, p) => onDayClick(p.date))
      .append('title')
      .text((p) => `${fmtDate(p.date)}: ${fmtValue(p.value, series.unit)} (unusual) – click for impact card`);

    const byDate = new Map(pts.map((p) => [p.date, p]));
    for (const [d, cls] of [[selectedDate, 'selected-day'], [hoverDate, 'crosshair']] as const) {
      if (d && byDate.has(d)) {
        const sx = x(byDate.get(d)!.d);
        g.append('line').attr('class', cls).attr('x1', sx).attr('x2', sx).attr('y1', 0).attr('y2', h);
      }
    }

    // click anywhere = that day
    const bisect = d3.bisector<P, Date>((p) => p.d).center;
    g.append('rect')
      .attr('width', w)
      .attr('height', h)
      .attr('fill', 'transparent')
      .style('cursor', 'pointer')
      .lower()
      .on('click', (event: MouseEvent) => {
        const [mx] = d3.pointer(event);
        onDayClick(pts[bisect(pts, x.invert(mx))].date);
      });
  }, [series, width, height, selectedDate, hoverDate, onDayClick]);

  const hoverPoint = hoverDate ? series?.points.find((p) => p.date === hoverDate) : null;

  return (
    <div className="metric-chart">
      <div className="metric-readout">
        <span className="lg value">Stock {hoverPoint ? fmtValue(hoverPoint.value, series!.unit) : ''}</span>
        <span className="lg base">20-day baseline {hoverPoint ? fmtValue(hoverPoint.baseline, series!.unit) : ''}</span>
        <span className="lg peer">Index peer median {hoverPoint ? fmtValue(hoverPoint.peer_median, series!.unit) : ''}</span>
        <span className="lg anomaly">Unusual day</span>
        {series && <span className="src">Source: {sourceLabel(series.source)}{series.order_size ? ` · order size EUR ${series.order_size.toLocaleString('en-GB')}` : ''}</span>}
      </div>
      <div className="metric-svg" ref={wrapRef}>
        <svg ref={svgRef} role="img" aria-label="Selected trading metric, 20-day baseline and index peer median" />
        {!series && <div className="chart-empty">Loading…</div>}
      </div>
    </div>
  );
}
