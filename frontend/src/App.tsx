import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getCases, getCompanies, getImpactDay, getImpactEvent, getSeries, getTrend,
  type Case, type Cases, type Company, type Fact, type Impact, type Series,
} from './api';
import StockSelector from './components/StockSelector';
import PriceChart, { type DayInfo } from './components/PriceChart';
import MetricChart from './components/MetricChart';
import PeersPanel from './components/PeersPanel';
import CasesPanel from './components/CasesPanel';
import ImpactCard from './components/ImpactCard';
import ComparePanel from './components/ComparePanel';
import TimingPanel from './components/TimingPanel';
import ReportView from './components/ReportView';
import LivePanel from './components/LivePanel';
import { useFetch } from './useFetch';
import {
  AUCTION_METRICS, COMPARE_TYPES, FACT_LABELS, TIMING_TYPES, METRICS, ORDER_SIZES, factCaption, fmtBaseline, fmtDate, fmtEur, fmtFact,
} from './format';
import './App.css';

export default function App() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [company, setCompany] = useState<Company | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  const [panel, setPanel] = useState<'overview' | 'events' | 'peers' | 'live'>('overview');
  const [metric, setMetric] = useState('xlm_bps');
  const [orderSize, setOrderSize] = useState(25000);

  // per-company data; each request is keyed, so a stock switch never shows the previous stock's figures
  const isin = company?.isin ?? null;
  const price = useFetch<Series>(isin && `${isin}|close`, () => getSeries(isin!, 'close')).data;
  const turnover = useFetch<Series>(isin && `${isin}|turnover`, () => getSeries(isin!, 'turnover_eur')).data;
  const cases = useFetch<Cases>(isin && `${isin}|cases`, () => getCases(isin!)).data;
  const trend = useFetch<Fact[]>(isin && `${isin}|trend`, () => getTrend(isin!)).data ?? [];
  const metricSeries = useFetch<Series>(isin && `${isin}|${metric}|${orderSize}`, () =>
    getSeries(isin!, metric, metric === 'xlm_bps' ? orderSize : undefined),
  ).data;

  const [hoverDay, setHoverDay] = useState<DayInfo | null>(null);
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);

  const [impact, setImpact] = useState<Impact | null>(null);
  const [impactLoading, setImpactLoading] = useState(false);
  const [impactError, setImpactError] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [compare, setCompare] = useState<{ type: string; eventId: number | null } | null>(null);
  const [timing, setTiming] = useState<{ type: string; eventId: number | null } | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const impactReq = useRef(0);

  const loadImpact = useCallback((load: () => Promise<Impact>) => {
    const req = ++impactReq.current;
    setCompare(null);
    setTiming(null);
    setImpactLoading(true);
    setImpactError(null);
    load()
      .then((d) => {
        if (req !== impactReq.current) return;
        setImpact(d);
        setSelectedDate(d.date);
      })
      .catch(() => req === impactReq.current && setImpactError('No impact card for this day (no trading data).'))
      .finally(() => req === impactReq.current && setImpactLoading(false));
  }, []);

  // Deep links: #CBK (stock), #CBK/2026-02-11 (impact card), #CBK/2026-02-11/report (card + report),
  // #CBK/report (IR snapshot), #CBK/compare/earnings (same-type comparison), #CBK/timing/earnings (publication timing).
  // ISIN works instead of ticker.
  useEffect(() => {
    getCompanies()
      .then((cs) => {
        setCompanies(cs);
        const [hIsin, hDay, hView] = decodeURIComponent(window.location.hash.slice(1)).split('/');
        const linked = cs.find((c) => c.isin === hIsin || c.ticker === hIsin);
        setCompany(linked ?? cs.find((c) => c.focus) ?? cs[0] ?? null);
        if (linked && hDay && /^\d{4}-\d{2}-\d{2}$/.test(hDay)) {
          setSelectedDate(hDay);
          loadImpact(() => getImpactDay(linked.isin, hDay));
          if (hView === 'report') setReportOpen(true);
        } else if (linked && (hDay === 'events' || hDay === 'peers' || hDay === 'live')) {
          setPanel(hDay);
        } else if (linked && hDay === 'report') {
          setReportOpen(true);
        } else if (linked && hDay === 'compare') {
          setCompare({ type: COMPARE_TYPES.includes(hView) ? hView : 'earnings', eventId: null });
        } else if (linked && hDay === 'timing') {
          setTiming({ type: TIMING_TYPES.includes(hView) ? hView : 'earnings', eventId: null });
        }
      })
      .catch(() => setApiError('Trading data is temporarily unavailable. Please try again shortly.'));
  }, [loadImpact]);

  // keep the address bar in sync, so a card can be shared or bookmarked
  useEffect(() => {
    if (!company) return;
    const view = timing ? `/timing/${timing.type}` : compare ? `/compare/${compare.type}`
      : impact ? `/${impact.date}` : panel !== 'overview' ? `/${panel}` : '';
    const hash = reportOpen
      ? `#${company.ticker}${impact ? `/${impact.date}` : ''}/report`
      : `#${company.ticker}${view}`;
    if (window.location.hash !== hash) window.history.replaceState(null, '', hash);
  }, [company, impact, compare, timing, panel, reportOpen]);

  const companyRef = useRef(company);
  useEffect(() => {
    companyRef.current = company;
  }, [company]);

  const openDay = useCallback(
    (date: string) => {
      const c = companyRef.current;
      if (!c) return;
      setSelectedDate(date);
      loadImpact(() => getImpactDay(c.isin, date));
    },
    [loadImpact],
  );

  const openCase = useCallback(
    (cs: Case) => {
      setSelectedDate(cs.peak_date);
      if (cs.kind === 'event' && cs.event) loadImpact(() => getImpactEvent(cs.event!.id));
      else openDay(cs.peak_date);
    },
    [loadImpact, openDay],
  );

  const openEventFromCompare = useCallback(
    (eventId: number, isin: string) => {
      if (companyRef.current?.isin !== isin) {
        const next = companies.find((c) => c.isin === isin);
        if (next) {
          setCompany(next);
          setRange(null);
          setHoverDay(null);
        }
      }
      loadImpact(() => getImpactEvent(eventId));
    },
    [companies, loadImpact],
  );

  const closeImpact = () => {
    impactReq.current++;
    setImpact(null);
    setImpactError(null);
    setImpactLoading(false);
    setSelectedDate(null);
  };

  const selectCompany = (c: Company) => {
    closeImpact();
    setCompare(null);
    setTiming(null);
    setPanel('overview');
    setRange(null);
    setHoverDay(null);
    setCompany(c);
  };

  const onHover = useCallback((d: DayInfo | null) => setHoverDay(d), []);
  const onRange = useCallback((r: { start: string; end: string } | null) => setRange(r), []);

  function rightPanel() {
    if (!company) return null;
    if (timing) {
      return (
        <TimingPanel
          key={`${timing.type}|${company.index}`}
          initialType={timing.type}
          initialIndex={company.index}
          isin={company.isin}
          ticker={company.ticker}
          selectedEventId={timing.eventId}
          onOpenEvent={openEventFromCompare}
          onClose={() => setTiming(null)}
        />
      );
    }
    if (compare) {
      return (
        <ComparePanel
          key={`${compare.type}|${company.index}`}
          initialType={compare.type}
          initialIndex={company.index}
          selectedEventId={compare.eventId}
          onOpenEvent={openEventFromCompare}
          onClose={() => setCompare(null)}
        />
      );
    }
    if (impact || impactLoading || impactError) {
      return (
        <ImpactCard
          data={impact}
          loading={impactLoading}
          error={impactError}
          ticker={company.ticker}
          onClose={closeImpact}
          onCompare={(type, eventId) => setCompare({ type: COMPARE_TYPES.includes(type) ? type : 'index_change', eventId })}
          onTiming={(type, eventId) => setTiming({ type, eventId })}
          onExport={() => setReportOpen(true)}
        />
      );
    }
    return (
      <>
        {(panel === 'overview' || panel === 'peers') && <PeersPanel isin={company.isin} ticker={company.ticker} range={range} />}
        {(panel === 'overview' || panel === 'events') && <CasesPanel data={cases} selectedDate={selectedDate} onOpen={openCase} />}
        {panel === 'live' && <LivePanel key={company.isin} isin={company.isin} ticker={company.ticker} />}
      </>
    );
  }

  const navigate = (view: 'overview' | 'events' | 'peers' | 'live' | 'compare' | 'timing') => {
    closeImpact();
    setCompare(view === 'compare' ? { type: 'earnings', eventId: null } : null);
    setTiming(view === 'timing' ? { type: 'earnings', eventId: null } : null);
    setPanel(view === 'compare' || view === 'timing' ? 'overview' : view);
  };
  const activeView = timing ? 'timing' : compare ? 'compare' : impact || impactLoading || impactError ? 'impact' : panel;
  const latest = price?.points.filter((p) => p.value !== null).at(-1);
  const navItems = [
    { key: 'overview', label: 'Overview' }, { key: 'events', label: 'Events' },
    { key: 'peers', label: 'Peer comparison' }, { key: 'compare', label: 'Compare events' },
    { key: 'timing', label: 'Publication timing' }, { key: 'live', label: 'Live & alerts' },
  ] as const;

  const isAuction = metric === 'auction_share' || metric.startsWith('auction_share_');

  return (
    <div className="app">
      <div className="utility-bar">
        <div className="page-width utility-inner"><span>Issuer intelligence · Xetra</span><span>{latest ? `Trading data through ${fmtDate(latest.date)}` : 'Loading trading data…'}</span></div>
      </div>
      <header className="app-header page-width">
        <a className="brand" href="#" onClick={(e) => { e.preventDefault(); navigate('overview'); }}>IssuerLens<span>Issuer Intelligence Hub</span></a>
        <StockSelector companies={companies} selected={company} onSelect={selectCompany} />
        <button className="btn export-snapshot" disabled={!company || impactLoading} onClick={() => setReportOpen(true)}>Export IR snapshot <span aria-hidden>↗</span></button>
      </header>
      <div className="workspace page-width">
        {apiError && <div className="api-error" role="alert">{apiError}</div>}
        <section className="company-heading" aria-label="Selected issuer">
          <div>
            <div className="eyebrow">{company ? `${company.index} · ${company.sector}` : 'Issuer overview'}</div>
            <h1>{company?.name ?? 'Select an issuer'}</h1>
            <div className="company-meta">{company ? `ISIN: ${company.isin}  ·  Ticker: ${company.ticker}` : 'Search by company name, ticker or ISIN'}</div>
          </div>
          {latest && <div className="latest-price"><span>Last available close</span><strong>€{latest.value?.toFixed(2)}</strong><span>{fmtDate(latest.date)} · Xetra</span></div>}
        </section>
        <nav className="workspace-nav" aria-label="Issuer views">
          {navItems.map(({ key, label }) => <button key={key} className={activeView === key ? 'on' : ''} aria-current={activeView === key ? 'page' : undefined} disabled={!company} onClick={() => navigate(key)}>{label}</button>)}
          {(impact || impactLoading || impactError) && <button className={activeView === 'impact' ? 'on' : ''} aria-current={activeView === 'impact' ? 'page' : undefined} onClick={() => { setCompare(null); setTiming(null); }}>Day analysis</button>}
        </nav>
        <section className="trend-strip" aria-label="Recent trading profile">
          {trend.map((f) => (
            <div className="trend" key={f.key} title={f.window}>
              <div className="fact-label">{FACT_LABELS[f.key]}</div>
              <div className="fact-value">{fmtFact(f)}</div>
              <div className="fact-base">Last 20 days · previous 60 days: {fmtBaseline(f) ?? 'n/a'}</div>
              <div className="fact-src">{factCaption(f)}</div>
            </div>
          ))}
        </section>
        <main className={`app-main ${activeView !== 'overview' ? 'focus-detail' : ''}`}>
          <div className="left">
          <section className="chart-area" aria-labelledby="price-title">
            <div className="section-head"><h2 id="price-title">Share price &amp; turnover</h2><span className="market-label">Xetra</span></div>
            <div className="header-day" aria-live="off">
              {range ? <><span className="hd-date">{fmtDate(range.start, false)} – {fmtDate(range.end)}</span><span>Peer figures for selected period</span><button className="text-button" onClick={() => setRange(null)}>Clear selection ×</button></>
                : hoverDay ? <><span className="hd-date">{fmtDate(hoverDay.date)}</span><span>Close <b>€{hoverDay.close?.toFixed(2)}</b></span>{hoverDay.change !== null && <span className={hoverDay.change >= 0 ? 'up' : 'down'}>{hoverDay.change >= 0 ? '+' : ''}{hoverDay.change.toFixed(2)}%</span>}<span>Turnover <b>{hoverDay.turnover !== null ? fmtEur(hoverDay.turnover) : 'n/a'}</b></span></>
                : <span>Click a day to explore its impact · drag to compare a period</span>}
            </div>
            <PriceChart
              price={price}
              turnover={turnover}
              cases={cases?.cases ?? []}
              selectedDate={selectedDate}
              range={range}
              onHover={onHover}
              onDayClick={openDay}
              onCaseClick={openCase}
              onRangeSelect={onRange}
            />
          </section>
          <section className="metric-area" aria-labelledby="metric-title">
            <div className="section-head"><h2 id="metric-title">Trading activity</h2><span className="muted small-note">Stock · baseline · peers</span></div>
            <div className="metric-tabs" aria-label="Trading metrics">
              {METRICS.map((m) => (
                <button
                  key={m.key}
                  className={(m.key === 'auction_share' ? isAuction : metric === m.key) ? 'on' : ''}
                  aria-pressed={m.key === 'auction_share' ? isAuction : metric === m.key}
                  onClick={() => setMetric(m.key)}
                  title={m.label}
                >
                  {m.short}
                </button>
              ))}
              <span className="spacer" />
              {metric === 'xlm_bps' && (
                <label className="inline-select">
                  Order size
                  <select value={orderSize} onChange={(e) => setOrderSize(Number(e.target.value))}>
                    {ORDER_SIZES.map((o) => <option key={o} value={o}>EUR {o.toLocaleString('en-GB')}</option>)}
                  </select>
                </label>
              )}
              {isAuction && (
                <div className="seg small">
                  <button className={metric === 'auction_share' ? 'on' : ''} onClick={() => setMetric('auction_share')}>All</button>
                  {AUCTION_METRICS.map((a) => (
                    <button key={a.key} className={metric === a.key ? 'on' : ''} onClick={() => setMetric(a.key)}>{a.label}</button>
                  ))}
                </div>
              )}
            </div>
            <MetricChart series={metricSeries} selectedDate={selectedDate} hoverDate={hoverDay?.date ?? null} onDayClick={openDay} />
          </section>
        </div>
        <aside className="right" aria-label="Issuer analysis">{rightPanel()}</aside>
      </main>
      <footer className="app-footer"><span>IssuerLens · Issuer Intelligence Hub</span><span>Trading data: Xetra · Publication times: Europe/Berlin</span></footer>
      </div>

      {reportOpen && company && (
        <ReportView company={company} trend={trend} cases={cases} impact={impact} onClose={() => setReportOpen(false)} />
      )}
    </div>
  );
}
