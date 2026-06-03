from __future__ import annotations

import json
from dataclasses import dataclass
from sqlite3 import Connection
from uuid import uuid4

from fly_on_the_wall.service_pricing import get_service_price


@dataclass(frozen=True)
class ServiceUsageRecord:
    id: str
    meeting_id: str | None
    provider_run_id: str | None
    provider: str
    model: str
    service: str
    unit: str
    input_quantity: float
    output_quantity: float
    estimated_cost_usd: float | None
    currency: str


def record_service_usage(
    connection: Connection,
    *,
    provider: str,
    model: str,
    service: str,
    unit: str,
    input_quantity: float = 0.0,
    output_quantity: float = 0.0,
    meeting_id: str | None = None,
    provider_run_id: str | None = None,
    cache_hit: bool = False,
    billable: bool = True,
    usage: dict | None = None,
) -> ServiceUsageRecord:
    price = get_service_price(connection, provider, model, service, unit)
    if price is None and provider == "openai":
        price = get_service_price(connection, provider, model, "chat", unit)
    input_unit_price = None if price is None else price.input_unit_price_usd
    output_unit_price = None if price is None else price.output_unit_price_usd
    pricing = {} if price is None else price.pricing | {"service_price_id": price.id}
    estimated_cost = None
    if billable and input_unit_price is not None:
        estimated_cost = input_quantity * input_unit_price
        if output_unit_price is not None:
            estimated_cost += output_quantity * output_unit_price

    record_id = str(uuid4())
    with connection:
        connection.execute(
            """
            INSERT INTO service_usage(
                id,
                meeting_id,
                provider_run_id,
                provider,
                model,
                service,
                unit,
                input_quantity,
                output_quantity,
                cache_hit,
                billable,
                input_unit_price_usd,
                output_unit_price_usd,
                estimated_cost_usd,
                currency,
                usage_json,
                pricing_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                meeting_id,
                provider_run_id,
                provider,
                model,
                service,
                unit,
                input_quantity,
                output_quantity,
                1 if cache_hit else 0,
                1 if billable else 0,
                input_unit_price,
                output_unit_price,
                estimated_cost,
                "USD",
                json.dumps(usage or {}, sort_keys=True),
                json.dumps(pricing, sort_keys=True),
            ),
        )
    return ServiceUsageRecord(
        id=record_id,
        meeting_id=meeting_id,
        provider_run_id=provider_run_id,
        provider=provider,
        model=model,
        service=service,
        unit=unit,
        input_quantity=input_quantity,
        output_quantity=output_quantity,
        estimated_cost_usd=estimated_cost,
        currency="USD",
    )


def record_openai_usage(
    connection: Connection,
    *,
    meeting_id: str,
    model: str,
    service: str,
    response: dict,
) -> ServiceUsageRecord:
    usage = response.get("usage") or {}
    return record_service_usage(
        connection,
        meeting_id=meeting_id,
        provider="openai",
        model=model,
        service=service,
        unit="token",
        input_quantity=float(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        output_quantity=float(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
        usage=usage,
    )


def cost_summary(connection: Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT provider,
               service,
               COUNT(*) AS calls,
               SUM(input_quantity) AS input_quantity,
               SUM(output_quantity) AS output_quantity,
               SUM(COALESCE(estimated_cost_usd, 0)) AS estimated_cost_usd
        FROM service_usage
        GROUP BY provider, service
        ORDER BY provider, service
        """
    ).fetchall()
    return [dict(row) for row in rows]


def meeting_cost_summary(connection: Connection, meeting_id_or_slug: str) -> list[dict]:
    rows = connection.execute(
        """
        SELECT service_usage.provider,
               service_usage.service,
               service_usage.model,
               COUNT(*) AS calls,
               SUM(service_usage.input_quantity) AS input_quantity,
               SUM(service_usage.output_quantity) AS output_quantity,
               SUM(COALESCE(service_usage.estimated_cost_usd, 0)) AS estimated_cost_usd
        FROM service_usage
        JOIN meetings ON meetings.id = service_usage.meeting_id
        WHERE meetings.id = ? OR meetings.slug = ?
        GROUP BY service_usage.provider, service_usage.service, service_usage.model
        ORDER BY service_usage.provider, service_usage.service, service_usage.model
        """,
        (meeting_id_or_slug, meeting_id_or_slug),
    ).fetchall()
    return [dict(row) for row in rows]
