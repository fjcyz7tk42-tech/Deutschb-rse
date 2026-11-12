import { useEffect, useMemo, useRef, useState } from 'react';
import type { Company } from '../api';

interface Props {
  companies: Company[];
  selected: Company | null;
  onSelect: (c: Company) => void;
}

const INDEX_ORDER = ['DAX', 'MDAX', 'SDAX'];

export default function StockSelector({ companies, selected, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const boxRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  // Current index members only (plus focus stocks); former members stay available for lookups.
  // Focus stocks are listed in their index like every other stock, without a group of their own.
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const pool = companies.filter((c) => c.current !== false || c.focus);
    const hits = q
      ? pool.filter((c) => [c.ticker, c.name, c.isin, c.sector].some((s) => s?.toLowerCase().includes(q)))
      : pool;
    const out: { label: string; items: Company[] }[] = [];
    for (const idx of INDEX_ORDER) {
      const items = hits
        .filter((c) => c.index === idx)
        .sort((a, b) => a.name.localeCompare(b.name));
      if (items.length) out.push({ label: idx, items });
    }
    return out;
  }, [companies, query]);

  return (
    <div className="stock-selector" ref={boxRef} onKeyDown={(e) => {
      if (e.key === 'Escape') { setOpen(false); triggerRef.current?.focus(); }
    }}>
      <button ref={triggerRef} className="selector-button" aria-expanded={open} aria-controls="issuer-search" aria-label="Select issuer" onClick={() => setOpen((o) => !o)}>
        {selected ? (
          <>
            <span className="sel-ticker">{selected.ticker}</span>
            <span className="sel-name">{selected.name}</span>
            <span className="badge">{selected.index}</span>
          </>
        ) : (
          'Select a stock'
        )}
        <span className="caret">▾</span>
      </button>
      {open && (
        <div className="selector-dropdown" id="issuer-search">
          <input
            autoFocus
            className="selector-search"
            aria-label="Search issuer by ticker, name, ISIN or sector"
            placeholder="Search ticker, name, ISIN, sector"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="selector-list">
            {groups.map((g) => (
              <div key={g.label}>
                <div className="selector-group">{g.label}</div>
                {g.items.map((c) => (
                  <button
                    key={c.isin}
                    className={`selector-item ${selected?.isin === c.isin ? 'active' : ''}`}
                    onClick={() => {
                      onSelect(c);
                      setOpen(false);
                      setQuery('');
                      triggerRef.current?.focus();
                    }}
                  >
                    <span className="sel-ticker">{c.ticker}</span>
                    <span className="sel-name">{c.name}</span>
                    <span className="sel-meta">{c.index} · {c.sector}</span>
                  </button>
                ))}
              </div>
            ))}
            {groups.length === 0 && <div className="muted pad">No match</div>}
          </div>
        </div>
      )}
    </div>
  );
}
