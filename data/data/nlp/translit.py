"""Name transliteration / spelling-variant generation.

This is the raw material Fellegi-Sunter entity resolution needs: real Indian name
duplication is mostly *romanisation drift* (Ramesh/Ramesha, Geetha/Geeta/Githa,
Lakshmi/Laxmi/Lakshmy), so generating the plausible variant set for a name is what
lets "arrested before under a different spelling" actually resolve.

Rule-based and dependency-free. If AI4Bharat IndicXlit weights are provisioned
(VERITAS_INDICXLIT_MODEL), `transliterate` also returns its cross-script (Kannada)
candidates; without them it returns the Latin-script variant set, which is where
the real duplication lives and is what the linkage scorer consumes.
"""
import os
import re
from functools import lru_cache

# Romanisation-drift substitutions. Each is applied to the ORIGINAL token only —
# never chained — because chaining re-expands its own output ("sh"->"s"->"sh"
# produced Rameshh/Lakshhhmi). The reverse direction is tried only when the
# forward pattern is absent, for the same reason.
_SUBS: tuple[tuple[str, str], ...] = (
    ("th", "t"),      # Geetha  -> Geeta
    ("ee", "i"),      # Geetha  -> Githa
    ("oo", "u"),      # Poojary -> Pujary
    ("ksh", "x"),     # Lakshmi -> Laxmi
    ("sh", "s"),      # Suresh  -> Sures
    ("v", "w"),       # Vinay   -> Winay
    ("ai", "ei"),
)
_VOWELS = "aeiou"


def _sub_variants(low: str) -> set[str]:
    out: set[str] = set()
    for a, b in _SUBS:
        if a in low:
            out.add(low.replace(a, b))
        elif b in low:
            out.add(low.replace(b, a))
    return out


def _suffix_variants(low: str) -> set[str]:
    """Trailing-'a' drift (Manjunath <-> Manjunatha) and trailing i/y (Lakshmi/Lakshmy)."""
    out: set[str] = set()
    if low.endswith("a") and len(low) > 4:
        out.add(low[:-1])
    elif low and low[-1] not in _VOWELS:
        out.add(low + "a")
    if low.endswith("i"):
        out.add(low[:-1] + "y")
    elif low.endswith("y"):
        out.add(low[:-1] + "i")
    return out


def _token_variants(tok: str) -> set[str]:
    low = tok.lower()
    bases = {low} | _sub_variants(low)
    out = set(bases)
    for b in bases:                       # one level of suffix drift per base
        out |= _suffix_variants(b)
    out |= {re.sub(r"(.)\1", r"\1", b) for b in bases}   # collapse doubled letters
    return {v.title() for v in out if len(v) > 2}


@lru_cache(maxsize=8192)
def transliterate(name: str) -> list[str]:
    """Candidate spelling variants for a name, original first. One token varies at
    a time — the full cross-product explodes and adds no linkage signal."""
    if not name or not name.strip():
        return []
    tokens = name.split()
    out: list[str] = [name]
    for i, tok in enumerate(tokens):
        for v in sorted(_token_variants(tok)):
            candidate = " ".join(v if j == i else tokens[j] for j in range(len(tokens)))
            if candidate not in out:
                out.append(candidate)
    out += [v for v in _indicxlit_variants(name) if v not in out]
    return out


def _indicxlit_variants(name: str) -> list[str]:
    """Cross-script (Kannada) candidates — only when IndicXlit weights are provisioned.

    MISSING EXTERNAL MODEL: AI4Bharat IndicXlit. Set VERITAS_INDICXLIT_MODEL to
    enable. Without it the Latin-script variants above carry entity resolution.
    """
    if not os.getenv("VERITAS_INDICXLIT_MODEL"):
        return []
    return list(_load_indicxlit().transliterate_word(name, lang_code="kn", topk=3))


@lru_cache(maxsize=1)
def _load_indicxlit():
    from ai4bharat.transliteration import XlitEngine   # provisioned separately
    return XlitEngine("kn", beam_width=4, src_script_type="roman")


if __name__ == "__main__":
    for n in ("Ramesh", "Geetha", "Lakshmi", "Manjunath Gowda"):
        print(f"{n:18} -> {transliterate(n)[:6]}")
