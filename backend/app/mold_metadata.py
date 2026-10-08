from __future__ import annotations

import re
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator


METADATA_FIELDS = ("manufacturer", "mold_category", "pairs_per_mold", "sole_material", "initial_quarter", "opened_on")
STANDARD_SIZES = ("39", "40", "40.5", "41", "42", "42.5", "43", "44", "44.5", "45")
SHOE_TYPES = ("男鞋", "女鞋", "女童", "男童")
WOMEN_SIZES = ("35.5", "36", "36.5", "37.5", "38", "38.5", "39", "40", "40.5", "41")
BIG_KIDS_SIZES = ("32", "33", "33.5", "34", "35", "35.5", "36", "36.5", "37.5", "38")
LITTLE_KIDS_SIZES = ("25", "26", "27", "27.5", "28", "28.5", "29.5", "30", "31", "31.5")
# Reference templates, selected subsets of Nike's EU charts; not factory mold specifications.
SIZE_PRESETS = {"男鞋": STANDARD_SIZES, "女鞋": WOMEN_SIZES, "女童": BIG_KIDS_SIZES, "男童": BIG_KIDS_SIZES}


def numeric_size(value: str) -> str:
    text = normalize_size(value)
    if not re.fullmatch(r"[0-9]{1,3}(?:\.[05]0*)?", text):
        raise ValueError("码数须为正整数或半码，例如 35、35.5")
    number = Decimal(text)
    if not 0 < number < 1000:
        raise ValueError("码数须大于 0 且小于 1000")
    return format(number.normalize(), "f")


def size_plan(shoe_type: str, sizes: list[str] | None) -> tuple[str, ...] | None:
    if shoe_type not in SHOE_TYPES:
        raise ValueError("请选择男鞋、女鞋、女童或男童")
    if sizes is None:
        return SIZE_PRESETS[shoe_type]
    normalized = tuple(numeric_size(size) for size in sizes)
    if not normalized or len(normalized) > 100 or len(set(normalized)) != len(normalized):
        raise ValueError("整套码数须为 1～100 个不重复码数")
    return tuple(sorted(normalized, key=Decimal))


def expected_sizes(mold_set) -> tuple[str, ...] | None:
    if mold_set.size_labels is not None:
        return tuple(json.loads(mold_set.size_labels))
    if mold_set.mold_category:
        return SIZE_PRESETS.get(mold_set.model.shoe_type or "男鞋")
    return None


def expected_size_count(mold_set) -> int | None:
    sizes = expected_sizes(mold_set)
    return len(sizes) if sizes is not None else (10 if not mold_set.mold_category else None)


def set_complete(mold_set, members) -> bool:
    sizes = expected_sizes(mold_set)
    if sizes is not None:
        return {mold.size_label for mold in members} == set(sizes) and len(members) == len(sizes)
    return not mold_set.mold_category and len(members) == 10


def normalize_category(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("模具类别只能为 A模 或 B模")
    category = value.strip().upper()
    if category in {"A", "B"}:
        category += "模"
    if category not in {"A模", "B模"}:
        raise ValueError("模具类别只能为 A模 或 B模")
    return category


def standard_size(value: str) -> str:
    try:
        number = Decimal(normalize_size(value))
    except (InvalidOperation, ValueError):
        raise ValueError("码数必须属于固定十码：" + "、".join(STANDARD_SIZES)) from None
    if number.is_finite():
        for size in STANDARD_SIZES:
            if number == Decimal(size):
                return size
    raise ValueError("码数必须属于固定十码：" + "、".join(STANDARD_SIZES))


def set_identity(number: str, category: str) -> str:
    code = f"{number.strip().upper()}-{normalize_category(category)[0]}"
    if not number.strip() or any(character in number for character in ":\r\n") or len(code) + 5 > 80:
        raise ValueError("款号不能为空、含冒号或换行，且款号加套别及码数后不能超过 80 字符")
    return code


def mold_identity(number: str, category: str, size: str) -> str:
    identity = f"{set_identity(number, category)}-{numeric_size(size)}"
    if len(identity) > 80:
        raise ValueError("款号、类别和码数组合不能超过 80 字符")
    return identity


class MoldMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manufacturer: str | None = Field(default=None, max_length=100)
    mold_category: str | None = Field(default=None, max_length=30)
    pairs_per_mold: int | None = Field(default=None, strict=True, ge=1, le=99)
    sole_material: str | None = Field(default=None, max_length=30)
    initial_quarter: str | None = Field(default=None, pattern=r"^[0-9]{2}Q[1-4]$")
    opened_on: date | None = None

    @field_validator("manufacturer", "mold_category", "sole_material", "initial_quarter", mode="before")
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if "\n" in value or "\r" in value:
                raise ValueError("标签资料不能包含换行")
            return value or None
        return value

    @field_validator("initial_quarter", mode="before")
    @classmethod
    def uppercase_quarter(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("opened_on", mode="before")
    @classmethod
    def parse_date(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            if not re.fullmatch(r"[0-9]{4}[-.][0-9]{1,2}[-.][0-9]{1,2}", value):
                raise ValueError("开制日期须为 YYYY-MM-DD 或 YYYY.M.D")
            year, month, day = map(int, re.split(r"[-.]", value))
            return date(year, month, day)
        return value


def metadata_dict(mold) -> dict:
    values = {field: getattr(mold, field) for field in METADATA_FIELDS}
    values["mold_category"] = mold.set.mold_category or mold.mold_category
    if values["opened_on"] is not None:
        values["opened_on"] = values["opened_on"].isoformat()
    return values


def normalize_size(value: str) -> str:
    size = value.strip().rstrip("#＃").strip()
    if not size:
        raise ValueError("模具码数不能为空")
    return size
