"""
Download / update NIFTY + SENSEX weekly option data from Dhan into data/options/.

Run it whenever you want fresh data -- it only fetches months that aren't complete yet
(plus the current month), then rebuilds the daily tables.

    python3 sync_options.py                      # both indices, all available history -> today
    python3 sync_options.py --underlying NIFTY
    python3 sync_options.py --from 2024-01-01 --to 2024-06-30 --refetch
    python3 sync_options.py --daily-only         # just rebuild daily parquet from raw
    python3 sync_options.py --status             # show what's on disk
    python3 sync_options.py --fill-days 2025-02-01,2026-02-01   # back-fill specific sessions

Auth: put DHAN_CLIENT_ID + DHAN_PIN + DHAN_TOTP_SECRET in .env (a fresh token is minted each
run, same flow as data-syncer; DHAN_TOKEN_FILE reuses an already-minted token), or a fresh
DHAN_ACCESS_TOKEN (expires ~24h).

First full run: ~45k API calls (Dhan allows <=2 dates per call), ~5 hours (Dhan caps ~10k calls/hour).
It is resumable - stop any time and re-run the same command.

See src/option_store.py for the storage layout and column definitions.
"""
import argparse
import sys
from datetime import date

from config import DHAN_CLIENT_ID, check_config, get_access_token, logger
from src import option_store as store


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--underlying", nargs="+", default=["NIFTY", "SENSEX"], choices=list(store.UNDERLYINGS))
    p.add_argument("--from", dest="from_date", type=date.fromisoformat, help="YYYY-MM-DD, whole months (default: 5y back)")
    p.add_argument("--to", dest="to_date", type=date.fromisoformat, help="YYYY-MM-DD (default: today)")
    p.add_argument("--refetch", action="store_true", help="re-download months even if marked complete")
    p.add_argument("--rps", type=float, default=2.5, help="max API requests/second (default 2.5 - Dhan allows ~10k calls per rolling hour; faster just hits a block)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--daily-only", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--fill-days", type=lambda v: [date.fromisoformat(x) for x in v.split(",")],
                   help="comma-separated YYYY-MM-DD dates to (re)fetch and merge, e.g. missed special sessions")
    a = p.parse_args()

    if a.status:
        print(store.status().to_string(index=False))
        return

    if not a.daily_only:
        errs = check_config()
        if errs:
            for e in errs:
                logger.error(e)
            sys.exit(1)
        client = store.RollingOptionClient(get_access_token(), DHAN_CLIENT_ID, rps=a.rps)
        try:
            if a.fill_days:
                for und in a.underlying:
                    store.fill_days(client, und, a.fill_days, workers=a.workers)
                results = []
            else:
                results = store.sync(client, a.underlying, a.from_date, a.to_date,
                                     refetch=a.refetch, workers=a.workers)
        except store.AuthError as e:
            logger.error(f"{e}\nRefresh credentials in .env and re-run; completed months are kept.")
            sys.exit(2)
        failed = [r for r in results if r.error and r.error != "nothing to fetch"]
        logger.info(f"Download finished: {len(results)} months processed, {len(failed)} failed, "
                    f"{client.calls} API calls")

    for und in a.underlying:
        out = store.build_daily(und)
        if out:
            logger.info(f"[{und}] daily table -> {out}")
    print(store.status().to_string(index=False))
    if not a.daily_only and failed:
        logger.warning("Some months failed -- re-run the same command to retry them.")
        sys.exit(3)


if __name__ == "__main__":
    main()
