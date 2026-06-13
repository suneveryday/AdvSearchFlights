from __future__ import annotations

from adv_search_flights.domain.models import CombinedResult, OneWayOption


def combine_open_jaw_results(
    outbound_by_destination: dict[str, list[OneWayOption]],
    inbound_by_destination: dict[str, list[OneWayOption]],
) -> list[CombinedResult]:
    results: list[CombinedResult] = []
    for outbound_key, outbound_options in outbound_by_destination.items():
        for inbound_key, inbound_options in inbound_by_destination.items():
            for outbound in outbound_options:
                for inbound in inbound_options:
                    if outbound.price_cny is None or inbound.price_cny is None:
                        continue
                    results.append(
                        CombinedResult(
                            total_price_cny=outbound.price_cny + inbound.price_cny,
                            outbound_destination=outbound.destination,
                            inbound_origin=inbound.origin,
                            outbound=outbound,
                            inbound=inbound,
                        )
                    )
    return results
