from __future__ import annotations

import json
from dataclasses import dataclass
from sqlite3 import Connection


@dataclass(frozen=True)
class ServicePrice:
    id: str
    provider: str
    model: str
    service: str
    unit: str
    input_unit_price_usd: float | None
    output_unit_price_usd: float | None
    cached_input_unit_price_usd: float | None
    currency: str
    source_name: str
    source_url: str | None
    pricing: dict
    active: bool


def list_service_prices(connection: Connection, active_only: bool = True) -> list[ServicePrice]:
    where = "WHERE active = 1" if active_only else ""
    rows = connection.execute(
        f"""
        SELECT * FROM service_prices
        {where}
        ORDER BY provider, model, service, unit
        """
    ).fetchall()
    return [_service_price_from_row(row) for row in rows]


def get_service_price(
    connection: Connection,
    provider: str,
    model: str,
    service: str,
    unit: str,
) -> ServicePrice | None:
    row = connection.execute(
        """
        SELECT * FROM service_prices
        WHERE provider = ?
          AND model = ?
          AND service = ?
          AND unit = ?
          AND active = 1
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (provider, model, service, unit),
    ).fetchone()
    return None if row is None else _service_price_from_row(row)


def _service_price_from_row(row) -> ServicePrice:
    return ServicePrice(
        id=row["id"],
        provider=row["provider"],
        model=row["model"],
        service=row["service"],
        unit=row["unit"],
        input_unit_price_usd=row["input_unit_price_usd"],
        output_unit_price_usd=row["output_unit_price_usd"],
        cached_input_unit_price_usd=row["cached_input_unit_price_usd"],
        currency=row["currency"],
        source_name=row["source_name"],
        source_url=row["source_url"],
        pricing=json.loads(row["pricing_json"]),
        active=bool(row["active"]),
    )
