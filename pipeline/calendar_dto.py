"""
DTO календарного агента — зеркало ``pystockinvest/agent/calendar/dto.py``.

Вход: ``CalendarAgentInput`` → ``model_dump_json`` в user-промпт.
Выход: ``CalendarSignalResponse`` — для ``with_structured_output``.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class CalendarSignalResponse(BaseModel):
    broad_equity_bias: float = Field(
        ge=-1.0,
        le=1.0,
        description=(
            "Expected directional effect of the macro calendar on broad equities, "
            "from -1 (strongly bearish) to 1 (strongly bullish)."
        ),
    )
    rates_pressure: float = Field(
        ge=-1.0,
        le=1.0,
        description=(
            "Interest-rate pressure implied by the calendar, from -1 "
            "(easing / lower rate pressure) to 1 (higher-for-longer / tighter pressure)."
        ),
    )
    macro_volatility_risk: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Expected volatility risk from the calendar, from 0 (very low) to 1 (very high)."
        ),
    )
    upcoming_event_risk: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Risk from important upcoming calendar releases that have not happened yet, "
            "from 0 (none) to 1 (very high)."
        ),
    )
    inflation_score: float = Field(
        ge=-1.0,
        le=1.0,
        description=(
            "Inflation-related calendar signal, from -1 (equity-negative inflation impulse) "
            "to 1 (equity-supportive disinflation impulse). Use 0 if there is little/no "
            "inflation information in the batch."
        ),
    )
    employment_score: float = Field(
        ge=-1.0,
        le=1.0,
        description=(
            "Employment-related calendar signal for equities, from -1 to 1. "
            "Use 0 if there is little/no employment information in the batch."
        ),
    )
    economic_activity_score: float = Field(
        ge=-1.0,
        le=1.0,
        description=(
            "Growth / activity-related calendar signal for equities, from -1 to 1. "
            "Use 0 if there is little/no activity information in the batch."
        ),
    )
    central_bank_score: float = Field(
        ge=-1.0,
        le=1.0,
        description=(
            "Directional central-bank effect on equities, from -1 to 1. "
            "-1 = clearly hawkish / restrictive for equities; "
            "0 = neutral, unchanged, mixed, or no clear directional signal; "
            "1 = clearly dovish / supportive for equities. "
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model confidence in the calendar interpretation.",
    )
    summary: List[str] = Field(
        min_length=2,
        max_length=4,
        description=(
            "2 to 4 concise sentences summarizing the macro calendar impact "
            "on broad equities and the target stock context."
        ),
    )

    @model_validator(mode="after")
    def validate_summary_items(self) -> CalendarSignalResponse:
        cleaned = [item.strip() for item in self.summary if item.strip()]
        if len(cleaned) != len(self.summary):
            raise ValueError("summary items must be non-empty strings")
        return self


class CalendarEventInput(BaseModel):
    event_index: int = Field(
        ge=1,
        description="1-based index of the event in the current input batch.",
    )
    name: str = Field(
        min_length=1,
        description="Name of the macroeconomic calendar event.",
    )
    category: str = Field(
        min_length=1,
        description="Macro category of the event, such as inflation, employment, rates, or activity.",
    )
    time: datetime = Field(
        description="Scheduled or actual event time in UTC.",
    )
    time_state: str = Field(
        description="Whether the event is already released or still upcoming at current_time.",
    )
    country: str = Field(
        min_length=1,
        description="Country associated with the event.",
    )
    currency: str = Field(
        min_length=1,
        description="Currency associated with the event.",
    )
    importance: str = Field(
        min_length=1,
        description="Importance level of the event from the calendar source.",
    )
    actual: Optional[str] = Field(
        default=None,
        description="Actual released value if available, otherwise null.",
    )
    forecast: Optional[str] = Field(
        default=None,
        description="Forecast or consensus value if available, otherwise null.",
    )
    previous: Optional[str] = Field(
        default=None,
        description="Previous reported value if available, otherwise null.",
    )


class CalendarAgentInput(BaseModel):
    target_ticker: str = Field(
        min_length=1,
        description="Ticker for which the macro calendar impact must be estimated.",
    )
    current_time: datetime = Field(
        description="Current UTC time at inference.",
    )
    events: List[CalendarEventInput] = Field(
        description="Calendar events to interpret for the current input batch.",
    )
