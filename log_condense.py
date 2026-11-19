"""Condense a troubleshooting log before it goes to the model: fixed rules, no model.

Repeats are collapsed and marked, PowerShell transcript boilerplate is dropped, and in a
long log only the lines around errors and warnings (plus its start and end) are kept. CMTrace
lines (Intune and ConfigMgr logs) are shortened to time, component, severity and message.
When a token budget applies, condensing tightens in stages until the result fits.
Message text is never rewritten, so error text stays exact for knowledge base searches.
A note at the top tells the model what was removed, so it does not assume the log is whole.
"""
import re
from pathlib import PurePath

# Logs longer than this (after removing repeats and boilerplate) keep only the lines that matter.
KEEP_ALL_LINES = 300
HEAD = TAIL = 20
CONTEXT = 2
MAX_BLOCK = 20
# Above this many lines, back-to-back block detection is skipped (single-line repeats,
# boilerplate and the keep-important pass still run), so condensing stays fast.
BLOCK_SCAN_LINES = 20000

IMPORTANT = re.compile(
    r"error|fail|exception|warn|denied|unavailable|time[d ]?out|refused|not found|cannot|can't|unable|"
    r"invalid|critical|fatal|abort|0x[0-9a-f]{8}|hresult|stack ?trace|traceback", re.I)

TIMESTAMP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}([.,]\d+)?)?(z|[+-]\d{2}:?\d{2})?\b"   # 2026-11-04 12:22:53
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}[ ,]+\d{1,2}:\d{2}(:\d{2})?( ?[ap]m)?\b"              # 11/4/2026 12:22:53 PM
    r"|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}:\d{2}([.,]\d+)?\b"                        # a date or a time alone
    r"|\b20\d{12}\b", re.I)                                                           # 20261104122253
GUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
IDS = re.compile(r"\b(pid|tid|process id|thread id|thread)\s*[:=#]?\s*\d+\b|\[\d{2,6}\]", re.I)
# Errors only, for the tightest stages: a CMTrace error or warning, or wording that says so.
SEVERE = re.compile(r"^\S+ [^:]{0,80}: (ERROR|WARNING):|error|fail|exception|denied|fatal|critical|0x8[0-9a-f]{7}", re.I)
# <![LOG[message]LOG]!><time="11:32:03.3592445" date="11-16-2026" component="AgentExecutor" context="" type="1" thread="15" file="">
# Parsed with str.find and a bounded, anchored match for the attributes, so a malformed file
# cannot make the parse quadratic.
CMTRACE_OPEN, CMTRACE_CLOSE = "<![LOG[", "]LOG]!>"
CMTRACE_TAIL = re.compile(r'\]LOG\]!><time="([^"]{0,64})" date="([^"]{0,32})" component="([^"]{0,128})" '
                          r'context="[^"]{0,256}" type="(\d)" thread="[^"]{0,32}" file="[^"]{0,512}">')
SEVERITY = {"2": "WARNING: ", "3": "ERROR: "}
SEPARATOR = re.compile(r"^\s*([*=\-_#~])\1{9,}\s*$")

# PowerShell transcript header fields that say nothing about the problem.
TRANSCRIPT_NOISE = re.compile(
    r"^(Windows PowerShell transcript (start|end)|Configuration Name|Process ID|PSVersion|PSEdition|"
    r"PSCompatibleVersions|BuildVersion|CLRVersion|WSManStackVersion|PSRemotingProtocolVersion|"
    r"SerializationVersion)\b", re.I)


def normalize(line):
    """The line as compared for repeats: times, GUIDs, process and thread IDs masked, spacing collapsed."""
    line = TIMESTAMP.sub("<time>", line)
    line = GUID.sub("<guid>", line)
    line = IDS.sub("<id>", line)
    return " ".join(line.split()).lower()


def is_log(name, text):
    """A .log file, a PowerShell transcript, or text where many lines start with a time."""
    if PurePath(name or "").suffix.lower() in (".log", ".evtx"):
        return True
    if "Windows PowerShell transcript start" in text[:2000] or "<![LOG[" in text[:5000]:
        return True
    lines = [l for l in text.splitlines()[:200] if l.strip()]
    stamped = sum(1 for l in lines if TIMESTAMP.match(l.strip()) or re.match(r"^\[?\d{4}-\d{2}-\d{2}|^\[?\d{1,2}:\d{2}", l.strip()))
    return len(lines) >= 10 and stamped >= len(lines) * 0.3


def cmtrace_entries(text):
    """(message, time, date, component, type) for each CMTrace entry, in one pass over the text."""
    entries, pos, close = [], 0, -1
    while True:
        start = text.find(CMTRACE_OPEN, pos)
        if start < 0:
            break
        if close < start + len(CMTRACE_OPEN):
            close = text.find(CMTRACE_CLOSE, start + len(CMTRACE_OPEN))
            if close < 0:
                break
        following = text.find(CMTRACE_OPEN, start + len(CMTRACE_OPEN), close)
        if following >= 0:
            # An opener with no closer of its own: skip to the next opener.
            pos = following
            continue
        tail = CMTRACE_TAIL.match(text, close)
        if tail:
            entries.append((text[start + len(CMTRACE_OPEN):close], *tail.groups()))
            pos = tail.end()
        else:
            pos = close + len(CMTRACE_CLOSE)
    return entries


def shorten_cmtrace(text):
    """CMTrace lines become "11:32:03.359 AgentExecutor: ERROR: message", with a date line when
    the date changes. The message is kept as written. Returns None when this is not CMTrace."""
    head = text[:5000]
    if CMTRACE_OPEN not in head or CMTRACE_CLOSE not in head:
        return None
    entries = cmtrace_entries(text)
    if len(entries) < 5 or sum(len(e[0]) + 120 for e in entries) < len(text) * 0.5:
        return None
    out, date = [], None
    for message, time, day, component, kind in entries:
        if day != date:
            out.append(f"[harness: date {day}]")
            date = day
        first, *rest = message.replace("\r\n", "\n").split("\n")
        out.append(f"{time[:12]} {component}: {SEVERITY.get(kind, '')}{first}".rstrip())
        out.extend("    " + l.rstrip() for l in rest if l.strip())
    return out


def drop_boilerplate(lines):
    kept, dropped = [], 0
    for line in lines:
        if SEPARATOR.match(line) or TRANSCRIPT_NOISE.match(line.strip()):
            dropped += 1
        else:
            kept.append(line)
    return kept, dropped


def covering(first_line, size):
    """How a marker names the lines it describes: by the first line's time when it has one, so
    the marker stays right when later passes omit some of those lines; otherwise by count."""
    stamp = TIMESTAMP.search(first_line or "")
    if stamp:
        return f"the lines from {stamp.group(0)} to here"
    return "the line above" if size == 1 else f"the {size} lines above"


def collapse_blocks(lines):
    """Collapse a block of lines repeated back to back (allowing re-wrapping of one line)."""
    if len(lines) > BLOCK_SCAN_LINES:
        return lines, 0
    # Each line is normalized once; a block compares as its normalized lines joined, so the
    # same block wrapped differently still matches.
    norm = [normalize(l) for l in lines]

    def joined(a, b):
        return " ".join(x for x in norm[a:b] if x)

    out, collapsed, i = [], 0, 0
    while i < len(lines):
        best = None
        for size in range(min(MAX_BLOCK, (len(lines) - i) // 2), 0, -1):
            key = joined(i, i + size)
            if not key:
                continue
            count, j = 1, i + size
            while True:
                match = next((n for n in (size, size - 1, size + 1)
                              if n > 0 and j + n <= len(lines) and joined(j, j + n) == key), None)
                if match is None:
                    break
                count, j = count + 1, j + match
            if count > 1 and size > 1 or count > 1 and not best:
                best = (size, count, j)
                if size > 1:
                    break
        if best:
            size, count, end = best
            out.extend(lines[i:i + size])
            out.append(f"[harness: {covering(lines[i], size)} repeated {count} times in a row]")
            collapsed += end - i - size
            i = end
        else:
            out.append(lines[i])
            i += 1
    return out, collapsed


def collapse_repeats(lines):
    """Lines seen again later (not back to back): keep the first, note the count and last time.
    A run of three or more such lines (a repeated cycle) gets one marker instead of one each."""
    seen, order, keys = {}, [], []
    for n, line in enumerate(lines):
        key = normalize(line)
        keys.append(key)
        if not key or line.startswith("[harness:"):
            order.append(n)
            continue
        if key in seen:
            seen[key]["count"] += 1
            stamp = TIMESTAMP.search(line)
            if stamp:
                seen[key]["last"] = stamp.group(0)
        else:
            seen[key] = {"first": n, "count": 1, "last": None}
            order.append(n)

    def repeated(n):
        info = seen.get(keys[n])
        return info if info and info["first"] == n and info["count"] > 1 else None

    out, collapsed, i = [], 0, 0
    while i < len(order):
        info = repeated(order[i])
        if not info:
            out.append(lines[order[i]])
            i += 1
            continue
        j = i
        while j + 1 < len(order) and repeated(order[j + 1]):
            j += 1
        run = order[i:j + 1]
        counts = [seen[keys[n]]["count"] for n in run]
        collapsed += sum(counts) - len(run)
        if len(run) >= 3:
            out.extend(lines[n] for n in run)
            # A back-to-back block marker right after the run belongs to its lines: keep it
            # directly under them, before this run's marker.
            if j + 1 < len(order) and lines[order[j + 1]].startswith("[harness: the") and "in a row]" in lines[order[j + 1]]:
                j += 1
                out.append(lines[order[j]])
            low, high = min(counts) - 1, max(counts) - 1
            more = f"{low} more time{'s' if low != 1 else ''}" if low == high else f"{low} to {high} more times"
            last = f", the last at {info['last']}" if info["last"] else ""
            which = covering(lines[run[0]], len(run))
            which = which.replace("the lines from", "each line from", 1) if which.startswith("the lines from") else f"each of {which}"
            out.append(f"[harness: {which} recurs {more} later in the log{last}; those copies removed]")
        else:
            for n in run:
                r = seen[keys[n]]
                out.append(lines[n] + f"  [harness: seen {r['count']} times" + (f", last at {r['last']}" if r["last"] else "") + "]")
        i = j + 1
    return out, collapsed


# Selection stages, loosest first: (keep everything when this short, lines of context around
# important lines, head/tail lines, errors only, longest line kept whole).
STAGES = [
    (KEEP_ALL_LINES, CONTEXT, HEAD, False, None),
    (0, 1, 10, False, 2000),
    (0, 0, 5, False, 600),
    (0, 0, 5, False, 250),
    (0, 3, 5, True, 600),
    (0, 0, 5, True, 400),
]
# In a CMTrace log the severity field decides what an error is; words like "ErrorCode = 0" do not.
CMTRACE_SEVERE = re.compile(r"^\S+ [^:]{0,80}: (ERROR|WARNING):")


def clip(line, limit):
    """Cut a very long line (a JSON payload, say) in the middle, keeping its start and end."""
    if limit is None or len(line) <= limit or line.startswith("[harness:"):
        return line
    head, tail = int(limit * 0.7), int(limit * 0.2)
    return f"{line[:head]} …[harness: {len(line) - head - tail:,} characters cut]… {line[-tail:]}"


def select(lines, stage, cmtrace=False):
    """Keep the start, the end, and the lines around errors and warnings, marking gaps."""
    keep_all, context, head, severe_only, longest = STAGES[stage]
    if len(lines) <= keep_all:
        return lines, 0
    lines = [clip(l, longest) for l in lines]
    pattern = (CMTRACE_SEVERE if cmtrace else SEVERE) if severe_only else IMPORTANT
    keep = set(range(min(head, len(lines)))) | set(range(max(0, len(lines) - head), len(lines)))
    for n, line in enumerate(lines):
        if line.startswith("[harness:"):
            # Markers stay with the line they describe.
            if n - 1 in keep or stage == 0:
                keep.add(n)
        elif pattern.search(line):
            keep.update(range(max(0, n - context), min(len(lines), n + context + 1)))
            if n + 1 < len(lines) and lines[n + 1].startswith(("[harness: the", "[harness: each")):
                keep.add(n + 1)
    return gaps(lines, keep)


def gaps(lines, keep):
    out, omitted, gap = [], 0, 0
    for n, line in enumerate(lines):
        if n in keep:
            if gap:
                out.append(f"[harness: {gap:,} lines omitted]")
                omitted += gap
                gap = 0
            out.append(line)
        else:
            gap += 1
    if gap:
        out.append(f"[harness: {gap:,} lines omitted]")
        omitted += gap
    return out, omitted


def newest_that_fit(lines, max_chars, pattern):
    """Last resort: the most recent error lines that fit; everything else is marked omitted."""
    keep, size = set(), 0
    for n in range(len(lines) - 1, -1, -1):
        if not pattern.search(lines[n]):
            continue
        size += len(lines[n]) + 1
        if size > max_chars:
            break
        keep.add(n)
    return gaps(lines, keep)


class Prepared:
    """A log after the expensive passes (CMTrace parsing, boilerplate, repeats), ready for
    selection. Selection can then run several times against different budgets cheaply."""
    def __init__(self, original_lines, lines, short, boilerplate, repeats):
        self.original_lines, self.lines, self.cmtrace = original_lines, lines, short
        self.boilerplate, self.repeats = boilerplate, repeats


def prepare(name, text):
    """Returns a Prepared log, or None when this is not a log."""
    if not is_log(name, text):
        return None
    original = text.count("\n") + 1 - (1 if text.endswith("\n") else 0)
    short = shorten_cmtrace(text)
    lines = short if short is not None else [l.rstrip() for l in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    lines, boilerplate = drop_boilerplate(lines)
    lines, in_a_row = collapse_blocks(lines)
    lines, scattered = collapse_repeats(lines)
    return Prepared(original, lines, short is not None, boilerplate, in_a_row + scattered)


def finish(prep, max_chars=None):
    """Select from a Prepared log, tightening in stages until it fits max_chars.
    Returns (condensed text, stats), or None when condensing saves little."""
    lines = prep.lines
    for stage in range(len(STAGES)):
        chosen, omitted = select(lines, stage, prep.cmtrace)
        body = tidy(chosen)
        if max_chars is None or sum(len(l) + 1 for l in body) <= max_chars:
            break
    else:
        stage = len(STAGES)
        chosen, omitted = newest_that_fit(tidy(chosen), max_chars - 400, CMTRACE_SEVERE if prep.cmtrace else SEVERE)
        body = tidy(chosen)
        omitted = len(lines) - sum(1 for l in body if not l.startswith("[harness:"))
    original = prep.original_lines
    removed = original - len(body)
    if not body or (max_chars is None and not prep.cmtrace and removed < max(3, original * 0.1) and not prep.repeats):
        return None
    stats = {"lines_in": original, "lines_out": len(body), "repeats": prep.repeats,
             "boilerplate": prep.boilerplate, "omitted": omitted, "stage": stage, "cmtrace": prep.cmtrace}
    parts = []
    if prep.cmtrace:
        parts.append("CMTrace lines shortened to time, component, severity and message")
    if stage >= 1 and any("characters cut]…" in l for l in body):
        parts.append("very long lines cut in the middle (marked)")
    if prep.repeats:
        parts.append(f"{prep.repeats:,} repeated lines collapsed (marked)")
    if prep.boilerplate:
        parts.append(f"{prep.boilerplate} header and separator lines dropped")
    if omitted:
        parts.append(f"{omitted:,} lines omitted (marked)" + {
            0: "", 1: ", keeping one line of context around errors and warnings",
            2: ", keeping only the lines that mention errors and warnings",
            3: ", keeping only the lines that mention errors and warnings",
            4: ", keeping errors and warnings with three lines of context", 5: ", keeping only errors and warnings",
            6: ", keeping only the newest errors that fit"}[stage])
    note = (f"[harness: condensed from {original:,} lines to {len(body):,}: " + "; ".join(parts) +
            ". Message text is otherwise unchanged, so quote it as it is; omitted lines and cut text are not shown, so do not guess at them.]")
    return note + "\n" + "\n".join(body), stats


def condense(name, text, max_chars=None):
    """Returns (condensed text, stats), or None when this is not a log or condensing saves little."""
    prep = prepare(name, text)
    return None if prep is None else finish(prep, max_chars)


def tidy(lines):
    """Drop blank lines left behind by removed blocks."""
    out = []
    for line in lines:
        if line.strip() or (out and out[-1].strip()):
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return out
