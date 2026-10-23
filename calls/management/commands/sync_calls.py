"""
python manage.py sync_calls                   # sync today (and finish off recent days that still need it)
python manage.py sync_calls --date 2026-10-05 # sync one day (05-10-2026 works too)
python manage.py sync_calls --days 30         # backfill the last 30 days (incl. today)
python manage.py sync_calls --from 2026-01-01 # backfill from a date to today (add --to 2026-06-30 to stop earlier)
python manage.py sync_calls --loop 300        # keep syncing every 300 seconds (Ctrl+C to stop)

A "management command" is a script that runs with all of Django loaded
(settings, database, models), so it can use the same code as the website.
"""
import logging
import time
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from calls.sync import days_needing_sync, sync_agents_if_due, sync_day

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Copy calls from HoduCC into the dashboard database."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="One day to sync, as YYYY-MM-DD")
        parser.add_argument("--days", type=int, help="Sync this many days back from today")
        parser.add_argument("--from", dest="start", help="First day of a range to sync (YYYY-MM-DD)")
        parser.add_argument("--to", dest="end", help="Last day of that range (default: today)")
        parser.add_argument("--loop", type=int, metavar="SECONDS", help="Repeat every N seconds")

    def handle(self, *args, **options):
        if options["days"] is not None and options["days"] < 1:
            raise CommandError("--days must be 1 or more")

        if options["loop"]:
            if options["loop"] < 60:
                raise CommandError("Use --loop 60 or more, to be kind to HoduCC's server.")
            self.stdout.write(f"Syncing every {options['loop']} seconds. Press Ctrl+C to stop.")
            while True:
                try:
                    self._sync(days_needing_sync(timezone.localdate()))
                except Exception as exc:  # e.g. the database was busy; try again next time round
                    log.exception("Sync loop hit a problem")
                    self.stdout.write(self.style.ERROR(f"FAIL {type(exc).__name__}: {exc}"))
                time.sleep(options["loop"])

        today = timezone.localdate()
        if options["start"]:
            start = self._parse_date(options["start"])
            end = self._parse_date(options["end"]) if options["end"] else today
            if end < start:
                raise CommandError("--to must be on or after --from")
            days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
        elif options["date"]:
            days = [self._parse_date(options["date"])]
        elif options["days"]:
            days = [today - timedelta(days=n) for n in range(options["days"])][::-1]
        else:
            days = days_needing_sync(today)

        failed = self._sync(days)
        if failed:
            raise CommandError(f"{failed} day(s) failed. See messages above or the Sync runs page in /admin.")

    @staticmethod
    def _parse_date(value):
        """2026-10-05 or 05-10-2026 (day first, as HoduCC writes it)."""
        for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                pass
        raise CommandError("Dates must look like 2026-10-05 or 05-10-2026")

    def _sync(self, days):
        sync_agents_if_due()  # keep agent names up to date (at most once an hour)
        failed = 0
        for day in days:
            run = sync_day(day)
            offers = "-" if run.offers_received is None else run.offers_received
            line = f"{day}: {run.calls_received} calls, {offers} offers"
            if run.ok:
                self.stdout.write(self.style.SUCCESS(f"OK   {line}"))
            else:
                failed += 1
                self.stdout.write(self.style.ERROR(f"FAIL {line}"))
            for note in filter(None, run.message.splitlines()):
                self.stdout.write(self.style.WARNING(f"     {note}"))
        return failed
