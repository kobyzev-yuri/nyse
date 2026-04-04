import logging
import time
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from domain import CalendarEvent, CalendarEventImportance, Currency

logger = logging.getLogger(__name__)


class Source:
    ENDPOINT = "https://endpoints.investing.com/pd-instruments/v1/calendars/economic/events/occurrences"

    def __init__(self, currencies: List[Currency]):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://www.investing.com/economic-calendar/",
                "Origin": "https://www.investing.com",
            }
        )
        self.countries = {
            72: "Euro Zone",
            22: "France",
            5: "United States",
            10: "Italy",
            17: "Germany",
            37: "China",
            4: "United Kingdom",
            12: "Switzerland",
            6: "Canada",
            25: "Australia",
            52: "Saudi Arabia",
            170: "Qatar",
            143: "United Arab Emirates",
            35: "Japan",
        }

        self.currencies = currencies

    def get_calendar(self) -> List[CalendarEvent]:
        logger.info("Loading calendar: tickers=%s", [c.value for c in self.currencies])
        data = self._request_calendar_data()
        events = self._parse_calendar(data)
        events = self._only_currencies(events, self.currencies)
        self._sort_calendar_events(events)
        return events

    def _request_calendar_data(self) -> dict:
        now = datetime.now(timezone.utc)

        start = (now - timedelta(days=2)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        end = (now + timedelta(days=3)).replace(
            hour=23, minute=59, second=59, microsecond=999000
        )

        base_params = {
            "domain_id": 1,
            "limit": 500,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "country_ids": ",".join(map(str, self.countries.keys())),
        }

        events_by_id = {}
        all_occurrences = []
        cursor = None
        while True:
            params = dict(base_params)
            if cursor:
                params["cursor"] = cursor

            data = self._get_json_with_retries(params)
            for e in data.get("events", []):
                events_by_id[e["event_id"]] = e

            all_occurrences.extend(data.get("occurrences", []))
            cursor = data.get("next_page_cursor")
            if not cursor:
                break

        return {
            "events": list(events_by_id.values()),
            "occurrences": all_occurrences,
        }

    def _get_json_with_retries(self, params: dict) -> dict:
        """Повторы при 429/5xx (как в lse investing_calendar_parser)."""
        delays = (0, 4, 12)
        last_error: Exception | None = None
        for attempt, delay_sec in enumerate(delays):
            if delay_sec:
                time.sleep(delay_sec)
            try:
                response = self.session.get(
                    self.ENDPOINT, params=params, timeout=25
                )
                if response.status_code == 429 and attempt < len(delays) - 1:
                    logger.warning(
                        "Economic calendar 429, retry %s/%s",
                        attempt + 1,
                        len(delays),
                    )
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as e:
                last_error = e
                if attempt < len(delays) - 1:
                    logger.warning("Calendar request failed (%s), retrying", e)
                    continue
                raise
        assert last_error is not None
        raise last_error

    def _parse_calendar(self, data: dict) -> List[CalendarEvent]:
        events_meta = {e["event_id"]: e for e in data["events"]}

        events = []
        for occ in data["occurrences"]:
            meta = events_meta.get(occ["event_id"])
            if not meta:
                continue
            if not self._at_least_moderate(meta["importance"]):
                continue
            events.append(self._parse_event(meta, occ))

        return events

    def _parse_event(self, meta: dict, occ: dict) -> CalendarEvent:
        return CalendarEvent(
            name=meta["short_name"],
            category=meta["category"],
            time=self._parse_time(occ["occurrence_time"]),
            country=self.countries[meta["country_id"]],
            currency=self._to_model_currency(meta["currency"]),
            importance=self._to_model_importance(meta["importance"]),
            actual=self._parse_value(occ.get("actual"), occ.get("unit")),
            forecast=self._parse_value(occ.get("forecast"), occ.get("unit")),
            previous=self._parse_value(occ.get("previous"), occ.get("unit")),
        )

    def _parse_time(self, ts: str) -> datetime:
        if not ts:
            return datetime.now(timezone.utc)

        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def _parse_value(self, value, unit) -> Optional[str]:
        if value is None:
            return None

        if unit:
            return f"{value}{unit}"

        return str(value)

    def _only_currencies(
        self, events: List[CalendarEvent], currencies: List[Currency]
    ) -> List[CalendarEvent]:
        return [ev for ev in events if ev.currency in currencies]

    def _to_model_currency(self, currency: str) -> Currency:
        if currency == "USD":
            return Currency.USD
        if currency == "CHF":
            return Currency.CHF
        if currency == "GBP":
            return Currency.GBP
        if currency == "JPY":
            return Currency.JPY
        if currency == "EUR":
            return Currency.EUR

        return Currency.UNKNOWN

    def _to_model_importance(self, imp: str) -> CalendarEventImportance:
        value = imp.strip().lower()

        if "high" in value:
            return CalendarEventImportance.HIGH
        if "medium" in value or "moderate" in value:
            return CalendarEventImportance.MODERATE

        raise ValueError(f"unknown importance: {imp}")

    def _at_least_moderate(self, importance: str) -> bool:
        return importance not in ["low", "holiday"]

    def _sort_calendar_events(self, events: List[CalendarEvent]) -> None:
        events.sort(key=lambda e: e.time)
