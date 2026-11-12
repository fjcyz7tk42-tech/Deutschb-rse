"""python -m backend.fetcher: fetch all sources and write data/reference/events.csv."""
import logging
from collections import Counter

from backend.fetcher import EVENTS_CSV, run_all

logging.basicConfig(level=logging.INFO, format="%(message)s")
events = run_all()
print(f"{len(events)} events written to {EVENTS_CSV.relative_to(EVENTS_CSV.parents[2])}")
for (isin, t), n in sorted(Counter((e.isin, e.type) for e in events).items()):
    print(f"  {isin}  {t:<18} {n}")
