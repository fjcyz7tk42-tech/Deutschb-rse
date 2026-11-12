// Intraday 5-minute bars of the card's day: turnover bars and the price line. Times are Europe/Berlin.
import { useEffect, useRef } from 'react';
import * as d3 from 'd3';
import type { Impact } from '../api';
import { useSize } from '../useSize';
import { compactNumber } from '../format';

const M = { top: 8, right: 50, bottom: 20, left: 40 };

export default function IntradayChart({ bars }: { bars: Impact['intraday'] }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const { width, height } = useSize(wrapRef);

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();
    if (!bars.length || width < 50) return;
    const w = width - M.left - M.right;
    const h = height - M.top - M.bottom;
    svg.attr('width', width).attr('height', height);
    const g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`);

    const toMin = (t: string) => {
      const [hh, mm] = t.split(':').map(Number);
      return hh * 60 + mm;
    };
    const first = Math.min(toMin(bars[0].time), 8 * 60);
    const last = Math.max(toMin(bars[bars.length - 1].time) + 5, 17 * 60 + 40);
    const x = d3.scaleLinear().domain([first, last]).range([0, w]);
    const yt = d3.scaleLinear().domain([0, d3.max(bars, (b) => b.turnover) || 1]).range([h, 0]);
    const prices = bars.map((b) => b.price).filter((p): p is number => p !== null);
    const [plo, phi] = d3.extent(prices) as [number, number];
    const ppad = (phi - plo) * 0.1 || 0.1;
    const yp = d3.scaleLinear().domain([plo - ppad, phi + ppad]).range([h, 0]);

    // Xetra continuous trading 09:00-17:30 shaded; auctions at the edges
    g.append('rect').attr('class', 'session').attr('x', x(9 * 60)).attr('width', x(17 * 60 + 30) - x(9 * 60)).attr('y', 0).attr('height', h);

    const bw = Math.max(1, x(first + 5) - x(first) - 0.5);
    g.append('g')
      .selectAll('rect')
      .data(bars)
      .join('rect')
      .attr('class', (b) => {
        const m = toMin(b.time);
        return m < 9 * 60 + 2 || (m >= 17 * 60 + 30 && m <= 17 * 60 + 40) ? 'ibar auction' : 'ibar';
      })
      .attr('x', (b) => x(toMin(b.time)))
      .attr('width', bw)
      .attr('y', (b) => yt(b.turnover))
      .attr('height', (b) => h - yt(b.turnover))
      .append('title')
      .text((b) => `${b.time}: turnover ${compactNumber(b.turnover, 'EUR')} EUR${b.price ? `, price €${b.price}` : ''}`);

    const line = d3
      .line<Impact['intraday'][0]>()
      .defined((b) => b.price !== null)
      .x((b) => x(toMin(b.time)) + bw / 2)
      .y((b) => yp(b.price as number));
    g.append('path').datum(bars).attr('class', 'ln-value').attr('d', line);

    const step = Math.max(1, Math.ceil((last - first) / 60 / Math.max(2, Math.floor(w / 52))));
    const hours = d3.range(Math.ceil(first / 60), Math.floor(last / 60) + 1).filter((hr) => hr % step === 0);
    g.append('g')
      .attr('class', 'axis')
      .attr('transform', `translate(0,${h})`)
      .call(d3.axisBottom(x).tickValues(hours.map((hr) => hr * 60)).tickFormat((v) => `${Math.floor(Number(v) / 60)}:00`));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(yt).ticks(3).tickFormat((v) => compactNumber(Number(v), 'EUR')));
    g.append('g').attr('class', 'axis').attr('transform', `translate(${w},0)`).call(d3.axisRight(yp).ticks(3).tickFormat((v) => `€${Number(v).toFixed(2)}`));
  }, [bars, width, height]);

  return (
    <div className="intraday" ref={wrapRef}>
      <svg ref={svgRef} role="img" aria-label="Intraday turnover and share price in Berlin time" />
      {!bars.length && <div className="chart-empty">No intraday data</div>}
    </div>
  );
}
