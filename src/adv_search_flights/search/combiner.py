from __future__ import annotations

import heapq

from adv_search_flights.domain.models import CombinedResult, OneWayOption


def combine_open_jaw_results(
    outbound_by_destination: dict[str, list[OneWayOption]],
    inbound_by_destination: dict[str, list[OneWayOption]],
    limit: int | None = None,
) -> list[CombinedResult]:
    """Return globally cheapest directed round-trip and open-jaw combinations."""
    results: list[CombinedResult] = []
    outbound_groups = [(key, _priced_options(options)) for key, options in outbound_by_destination.items()]
    inbound_groups = [(key, _priced_options(options)) for key, options in inbound_by_destination.items()]
    heap: list[tuple[int, int, int, int, int]] = []
    seen_by_pair: dict[tuple[int, int], set[tuple[int, int]]] = {}

    for outbound_group_index, (_, outbound_options) in enumerate(outbound_groups):
        if not outbound_options:
            continue
        for inbound_group_index, (_, inbound_options) in enumerate(inbound_groups):
            if not inbound_options:
                continue
            pair = (outbound_group_index, inbound_group_index)
            seen_by_pair[pair] = {(0, 0)}
            heapq.heappush(
                heap,
                (
                    _total_price(outbound_options[0], inbound_options[0]),
                    outbound_group_index,
                    inbound_group_index,
                    0,
                    0,
                ),
            )

    while heap and (limit is None or len(results) < limit):
        total_price, outbound_group_index, inbound_group_index, outbound_index, inbound_index = heapq.heappop(heap)
        _, outbound_options = outbound_groups[outbound_group_index]
        _, inbound_options = inbound_groups[inbound_group_index]
        outbound = outbound_options[outbound_index]
        inbound = inbound_options[inbound_index]
        results.append(
            CombinedResult(
                total_price_cny=total_price,
                outbound_destination=outbound.destination,
                inbound_origin=inbound.origin,
                outbound=outbound,
                inbound=inbound,
            )
        )

        pair = (outbound_group_index, inbound_group_index)
        seen = seen_by_pair[pair]
        for next_outbound_index, next_inbound_index in (
            (outbound_index + 1, inbound_index),
            (outbound_index, inbound_index + 1),
        ):
            candidate = (next_outbound_index, next_inbound_index)
            if (
                candidate in seen
                or next_outbound_index >= len(outbound_options)
                or next_inbound_index >= len(inbound_options)
            ):
                continue
            seen.add(candidate)
            heapq.heappush(
                heap,
                (
                    _total_price(outbound_options[next_outbound_index], inbound_options[next_inbound_index]),
                    outbound_group_index,
                    inbound_group_index,
                    next_outbound_index,
                    next_inbound_index,
                ),
            )
    return results


def combination_candidate_count(
    outbound_by_destination: dict[str, list[OneWayOption]],
    inbound_by_destination: dict[str, list[OneWayOption]],
) -> int:
    return sum(
        sum(option.price_cny is not None for option in outbound_options)
        * sum(option.price_cny is not None for option in inbound_options)
        for outbound_options in outbound_by_destination.values()
        for inbound_options in inbound_by_destination.values()
    )


def _priced_options(options: list[OneWayOption]) -> list[OneWayOption]:
    return sorted(
        (option for option in options if option.price_cny is not None),
        key=lambda option: option.price_cny,
    )


def _total_price(outbound: OneWayOption, inbound: OneWayOption) -> int:
    assert outbound.price_cny is not None
    assert inbound.price_cny is not None
    return outbound.price_cny + inbound.price_cny
