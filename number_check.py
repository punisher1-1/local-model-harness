"""Flags numbers in a final answer that no executed python_run output printed, and Python
blocks in the answer that no run executed. Unprinted numbers typed into a run as literals
are listed apart, as inputs: the code used them but did not derive them.

Provenance only: a printed number that is wrong still passes. Numbers given in the
user's messages, integers up to SMALL (ordinals, counts) and fenced code are exempt.
"""
import io
import re
import tokenize
from decimal import Decimal, InvalidOperation

SMALL = 10
MAX_LISTED = 20
FENCE = re.compile(r"```.*?```", re.S)
PYTHON_FENCE = re.compile(r"```(?:python|py)[ \t]*\n(.*?)```", re.S | re.I)
NUMBER = re.compile(r"(?<![\w.§#-])\d[\d,_]*(?:\.\d+)?(?:[eE][+-]?\d+)?(?: ?%)?")
# Thousands grouped with spaces (942 080 000 000). Tried whole first; if the whole value is
# neither printed nor given, its parts are checked as separate numbers instead.
SPACED = re.compile(r"(?<![\w.§#-])\d{1,3}(?:[ \u00a0\u2007\u2009\u202f]\d{3})+(?:\.\d+)?(?!\d|[.,]\d)(?: ?%)?")


def numbers(text):
    found = []
    for m in NUMBER.finditer(text):
        raw = m.group().rstrip(",")
        try:
            found.append((raw, Decimal(raw.rstrip("% ").replace(",", "").replace("_", ""))))
        except InvalidOperation:
            pass
    return found


def printed_match(raw, value, printed):
    places = len(raw.rstrip("% ").split(".")[1]) if "." in raw else 0
    # A percentage may be printed as a fraction (12.5% vs 0.125).
    targets = [(value, places)] + ([(value / 100, places + 2)] if raw.endswith("%") else [])
    for target, digits in targets:
        step = Decimal(1).scaleb(-digits)
        for p in printed:
            try:
                if p == target or p.quantize(step) == target:
                    return True
            except InvalidOperation:
                continue
    return False


def unverified_numbers(answer, outputs, given_text):
    """Return (numbers checked, unique unverified numbers in order of appearance)."""
    printed = {v for out in outputs for _, v in numbers(out)}
    given = {v for _, v in numbers(given_text)}
    checked, flagged = 0, []
    text = FENCE.sub(" ", answer)
    for m in reversed(list(SPACED.finditer(text))):
        raw = m.group()
        value = Decimal(re.sub(r"[\s\u00a0\u2007\u2009\u202f%]", "", raw))
        if value in given or printed_match(raw, value, printed):
            checked += value not in given
            text = text[:m.start()] + " " * len(raw) + text[m.end():]
    for raw, value in numbers(text):
        if value <= SMALL or value in given:
            continue
        checked += 1
        if raw not in flagged and not printed_match(raw, value, printed):
            flagged.append(raw)
    return checked, flagged


def code_literals(scripts):
    found = set()
    for script in scripts:
        try:
            raws = [t.string for t in tokenize.generate_tokens(io.StringIO(script).readline) if t.type == tokenize.NUMBER]
        except (tokenize.TokenError, SyntaxError):
            raws = [m.group() for m in NUMBER.finditer(script)]
        for raw in raws:
            try:
                found.add(Decimal(raw.replace("_", "").replace(",", "")))
            except InvalidOperation:
                pass
    return found


def split_inputs(flagged, scripts):
    """Split unverified numbers into (still unverified, typed into a run as a literal)."""
    literals = code_literals(scripts)
    unverified, inputs = [], []
    for raw in flagged:
        value = Decimal(raw.rstrip("% ").replace(",", "").replace("_", ""))
        typed = value in literals or (raw.endswith("%") and value / 100 in literals)
        (inputs if typed else unverified).append(raw)
    return unverified, inputs


def listed(items):
    return " · ".join(items[:MAX_LISTED]) + (f" · +{len(items) - MAX_LISTED} more" if len(items) > MAX_LISTED else "")


def annotation(flagged):
    return "\n*Unverified numbers (not printed by python_run): " + listed(flagged) + ".*"


def inputs_annotation(inputs):
    return "\n*Inputs set in code (typed into a run, not derived by it): " + listed(inputs) + ".*"


def code_lines(code):
    # Indentation, blank lines and comments may differ between the run and the answer.
    lines = (re.sub(r"\s+#.*$", "", l).strip() for l in code.splitlines())
    return {l for l in lines if l and not l.startswith("#")}


def unrun_blocks(answer, scripts):
    """Return (Python blocks in the answer, 1-based numbers of those no single run contained)."""
    ran = [code_lines(s) for s in scripts]
    blocks = [code_lines(b) for b in PYTHON_FENCE.findall(answer)]
    return len(blocks), [i for i, b in enumerate(blocks, 1) if b and not any(b <= r for r in ran)]


def code_annotation(total, unrun):
    return (f"\n*Code not run as shown: Python block{'s' if len(unrun) > 1 else ''} "
            + ", ".join(map(str, unrun)) + f" of {total}.*")
