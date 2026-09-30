from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import api_error
from .models import Location, Mold


SHELF_CAPACITY = 10


def shelf_counts(db: Session, location_ids: Iterable[int]) -> dict[int, int]:
    ids = set(location_ids)
    if not ids:
        return {}
    rows = db.execute(
        select(Mold.current_location_id, func.count(Mold.id))
        .where(Mold.current_location_id.in_(ids), Mold.is_current.is_(True))
        .group_by(Mold.current_location_id)
    ).all()
    return {location_id: count for location_id, count in rows}


def ensure_shelf_capacity(db: Session, locations: Mapping[int, Location], movements: Iterable[tuple[int | None, int | None]]) -> None:
    """Check the net change in each shelf before writing a batch of movements.

    A shelf already above capacity may still have molds moved out of it.
    Callers lock the affected location rows before calling this function.
    """
    changes: Counter[int] = Counter()
    for source_id, target_id in movements:
        if source_id == target_id:
            continue
        if source_id is not None:
            changes[source_id] -= 1
        if target_id is not None:
            changes[target_id] += 1
    increased = {location_id: delta for location_id, delta in changes.items() if delta > 0 and locations[location_id].type == "SHELF"}
    counts = shelf_counts(db, increased)
    for location_id, increase in increased.items():
        current = counts.get(location_id, 0)
        if current + increase > SHELF_CAPACITY:
            raise api_error(409, "LOCATION_FULL", f"库位 {locations[location_id].code} 已存 {current} 个，本次增加 {increase} 个；普通库位最多存放 {SHELF_CAPACITY} 个模具")
