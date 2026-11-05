"""Privacy-preserving record linkage (PPRL) tokens -- a simplified, generic illustration.

Each data source standardizes demographics, then computes keyed hashes (HMAC-SHA256) of several
field combinations. The public health agency receives only the tokens (no names, street
addresses, phone numbers, or MRNs) and links records that share enough tokens.

DEMO ONLY: the key below is public and fixed so outputs are reproducible. A real deployment would
use a secret managed by a trusted linkage party, rotate it, and undergo privacy/legal review
(hashed identifiers can still be personal information).

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from synth.names import NICKNAMES

DEMO_LINKAGE_KEY = b"chronic-disease-exchange-lab::demo-only-public-key"
_CANON = {nick.upper(): full.upper() for full, nick in NICKNAMES.items()}


def _norm(s: str | None) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def standardize_given(s: str | None) -> str:
    g = _norm(s)
    return _CANON.get(g, g)


def standardize_family(s: str | None) -> str:
    """Uppercase letters only; for hyphenated names keep the first component."""
    return _norm((s or "").split("-")[0])


def soundex(name: str) -> str:
    name = _norm(name)
    if not name:
        return ""
    table = {
        **dict.fromkeys("BFPV", "1"),
        **dict.fromkeys("CGJKQSXZ", "2"),
        **dict.fromkeys("DT", "3"),
        "L": "4",
        **dict.fromkeys("MN", "5"),
        "R": "6",
    }
    out, last = name[0], table.get(name[0], "")
    for ch in name[1:]:
        code = table.get(ch, "")
        if code and code != last:
            out += code
        if ch not in "HW":
            last = code
    return (out + "000")[:4]


def _h(*parts: str) -> str:
    msg = "|".join(parts).encode()
    return hmac.new(DEMO_LINKAGE_KEY, msg, hashlib.sha256).hexdigest()[:24]


def tokens(
    given: str | None, family: str | None, birth_date: str | None, sex: str | None, postal: str | None
) -> dict[str, str]:
    g, f = standardize_given(given), standardize_family(family)
    dob = birth_date or ""
    sx = (sex or "")[:1].upper()
    z = (postal or "")[:5]
    return {
        "T1": _h("T1", f, g, dob, sx),  # exact standardized name + DOB + sex
        "T2": _h("T2", soundex(f), g[:1], dob, sx),  # typo-tolerant family name
        "T3": _h("T3", f, dob, sx, z),  # tolerant of first-name variants
        "T4": _h("T4", f, g, dob[:4], z),  # tolerant of DOB day/month errors
        "T5": _h("T5", g, dob, z),  # tolerant of family-name changes/typos
    }


# A pair of records from different organizations is linked if ANY rule's tokens all match.
LINK_RULES = [("T1",), ("T2", "T3"), ("T2", "T4"), ("T3", "T4"), ("T2", "T5"), ("T4", "T5")]


def patient_tokens(patient: dict) -> dict[str, str]:
    name = (patient.get("name") or [{}])[0]
    addr = (patient.get("address") or [{}])[0]
    return tokens(
        (name.get("given") or [""])[0],
        name.get("family"),
        patient.get("birthDate"),
        patient.get("gender"),
        addr.get("postalCode"),
    )
