"""Сборка масок для брутфорса по позициям.

Пользователь задаёт не маску в синтаксисе hashcat, а понятную сетку: для каждой
позиции — «любой символ», цифра, строчная, ПРОПИСНАЯ, hex или свой набор; плюс
длину (фиксированную или диапазон). Здесь это превращается в `-a 3` с
пользовательскими charset'ами `-1..-4`, а для диапазона — в инкрементальный режим.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import WilfiError

CARDINALITY = {
    "?d": 10,
    "?l": 26,
    "?u": 26,
    "?h": 16,
    "?s": 33,
    "?a": 95,
    "?b": 256,
}
PRESETS = {
    "any": "?a",
    "digit": "?d",
    "lower": "?l",
    "upper": "?u",
    "hex": "?h",
    "special": "?s",
}
KIND_TITLES = {
    "fixed": "символ",
    "digit": "цифры",
    "lower": "строчные",
    "upper": "ПРОПИСНЫЕ",
    "hex": "hex",
    "special": "знаки",
    "any": "любой",
    "custom": "свой набор",
}
MAX_CUSTOM_SETS = 4
WPA_MIN, WPA_MAX = 8, 63


@dataclass
class MaskSpec:
    mask: str
    charsets: list[tuple[int, str]] = field(default_factory=list)
    length_min: int = 0
    length_max: int = 0
    keyspace: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def incremental(self) -> bool:
        return self.length_min < self.length_max

    def argv_fragment(self) -> list[str]:
        """Куски команды hashcat для этой маски."""
        out = ["-a", "3", self.mask]
        for index, chars in self.charsets:
            out += [f"-{index}", chars]
        if self.incremental:
            out += ["-i", f"--increment-min={self.length_min}", f"--increment-max={self.length_max}"]
        return out

    def summary(self) -> dict:
        return {
            "mask": self.mask,
            "charsets": [{"slot": i, "chars": c} for i, c in self.charsets],
            "length_min": self.length_min,
            "length_max": self.length_max,
            "keyspace": self.keyspace,
            "keyspace_human": human_keyspace(self.keyspace),
            "incremental": self.incremental,
            "warnings": self.warnings,
        }


def human_keyspace(value: int) -> str:
    """Читаемая оценка перебора: 780, 1.5 тыс, 2.5 млн, 6.6 квадрлн."""
    if value < 1_000:
        return str(value)
    for scale, name in ((10 ** 3, "тыс"), (10 ** 6, "млн"), (10 ** 9, "млрд"),
                        (10 ** 12, "трлн"), (10 ** 15, "квадрлн")):
        if value < scale * 1000:
            return f"{value / scale:.1f} {name}"
    return f"{value:.0e}"


def build(positions: list[dict], length_min: int | None = None,
          length_max: int | None = None, pad: str = "auto") -> MaskSpec:
    """positions: [{"kind": "digit"|"lower"|...|"fixed"|"custom", "value": "..."}]

    pad — чем добивать недостающие позиции при диапазоне длин:
    "auto" (тип последней заданной позиции, если это пресет, иначе ?a),
    "any" (?a), "last" (тип последней позиции принудительно).
    """
    warnings: list[str] = []
    if not positions:
        raise WilfiError("не задано ни одной позиции", code="no_positions")

    given = len(positions)
    top = int(length_max or given)
    bottom = int(length_min or given)
    if top < given:
        top = given
    if bottom < given:
        warnings.append(f"длина от {bottom} меньше числа заданных позиций ({given}) — поднял до {given}")
        bottom = given
    if bottom > top:
        bottom, top = top, bottom
    if top > WPA_MAX:
        raise WilfiError(f"длина {top} больше 63 — WPA-пароль длиннее не бывает", code="too_long")
    if bottom < WPA_MIN:
        warnings.append(f"длина {bottom} < 8: такой пароль в WPA-сети невозможен, только если это не PSK")
    if top > 16:
        warnings.append("длина больше 16 — перебор почти наверняка не закончится")

    tokens: list[str] = []
    charsets: list[tuple[int, str]] = []
    custom_index: dict[str, int] = {}
    card_per_pos: list[int] = []

    for number, position in enumerate(positions, start=1):
        kind = (position.get("kind") or "any").strip()
        value = (position.get("value") or "").strip()
        if kind == "fixed":
            if len(value) != 1:
                raise WilfiError(f"позиция {number}: нужен ровно один символ", code="bad_position")
            if ord(value) > 126:
                raise WilfiError(f"позиция {number}: только ASCII — маски hashcat байтовые", code="bad_position")
            tokens.append("??" if value == "?" else value)
            card_per_pos.append(1)
        elif kind in PRESETS:
            tokens.append(PRESETS[kind])
            card_per_pos.append(CARDINALITY[PRESETS[kind]])
        elif kind == "custom":
            chars = "".join(dict.fromkeys(value))
            if not chars:
                raise WilfiError(f"позиция {number}: пустой набор символов", code="bad_position")
            if any(ord(c) > 126 for c in chars):
                raise WilfiError(f"позиция {number}: в наборе не-ASCII символы", code="bad_position")
            if chars not in custom_index:
                if len(custom_index) >= MAX_CUSTOM_SETS:
                    raise WilfiError(
                        f"больше {MAX_CUSTOM_SETS} разных наборов hashcat не примет — объедините их",
                        code="too_many_sets")
                custom_index[chars] = len(custom_index) + 1
            slot = custom_index[chars]
            tokens.append(f"?{slot}")
            card_per_pos.append(len(chars))
        else:
            raise WilfiError(f"позиция {number}: неизвестный тип {kind}", code="bad_position")

    for chars, slot in custom_index.items():
        charsets.append((slot, chars))
    charsets.sort()

    last_kind = (positions[-1].get("kind") or "any").strip()
    if pad == "any":
        pad_token = "?a"
    elif pad == "last" or (pad == "auto" and last_kind in PRESETS):
        pad_token = PRESETS.get(last_kind, "?a")
    else:
        pad_token = "?a"
    for _ in range(top - given):
        tokens.append(pad_token)
        card_per_pos.append(CARDINALITY.get(pad_token, 95))

    keyspace = 0
    for length in range(bottom, top + 1):
        product = 1
        for card in card_per_pos[:length]:
            product *= card
        keyspace += product
        if keyspace > 10**18:
            keyspace = 10**18
            break

    return MaskSpec(
        mask="".join(tokens),
        charsets=charsets,
        length_min=bottom,
        length_max=top,
        keyspace=keyspace,
        warnings=warnings,
    )