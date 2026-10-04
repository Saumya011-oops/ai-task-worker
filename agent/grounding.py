"""Grounding: a value the worker types into a system must appear in something it actually observed
(task text, tool results, remembered facts). Blocks invented numbers/dates BEFORE they are saved."""
from __future__ import annotations

import re
from datetime import datetime

_DATE_FMTS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d/%m/%Y")


def variants(v: str) -> set[str]:
    """Textual forms a value may take elsewhere: 48250 / 48250.00 / 48,250.00, 2026-10-29 / 29 Oct 2026."""
    v = v.strip().lower()
    out = {v, v.replace(",", "")}
    num = re.sub(r"[^\d.]", "", v)
    if re.fullmatch(r"\d+(\.\d+)?", num) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) and not re.search(r"[a-z]{3}", re.sub(r"inr", "", v)):
        x = float(num)
        out |= {f"{x:g}", f"{x:.1f}", f"{x:.2f}", f"{x:,.2f}", f"{x:,.0f}"}
    for fmt in _DATE_FMTS:
        try:
            d = datetime.strptime(v.title() if "%b" in fmt or "%B" in fmt else v, fmt)
        except ValueError:
            continue
        for f in _DATE_FMTS[:4]:
            out |= {d.strftime(f).lower(), d.strftime(f).lower().lstrip("0")}
    return out


def is_grounded(value: str, corpus: str) -> bool:
    low = corpus.lower()
    return any(c in low for c in variants(value))


def needs_grounding(value: str) -> bool:
    """Only data-like values (containing a digit) are checked; plain words (search terms, names) are not."""
    return bool(re.search(r"\d", value)) and len(value.strip()) >= 3
