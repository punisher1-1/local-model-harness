"""Read a Windows event log (.evtx) attachment as text, one line per event.

Parsing uses the `evtx` package (a Rust parser with Python bindings). Windows builds an
event's readable message from message files on the machine that wrote it; those are not
available here, so each line carries what the file itself holds: time, level, event ID,
provider and the event's data fields (for example HRESULTs, URLs and status text). The lines
start with a timestamp, so log condensing (log_condense.py) treats the result as a log.
"""
import io
import json

MAX_RECORDS = 500_000
VALUE_CHARS = 2000
# Event logs store repeated text as templates, so a small file can expand a lot. These bound the
# work per event and the total text, whatever the file size.
MAX_FIELDS = 200
MAX_RECORD_JSON = 1_000_000
DEFAULT_MAX_CHARS = 20_000_000
LEVELS = {0: "INFO", 1: "CRITICAL", 2: "ERROR", 3: "WARNING", 4: "INFO", 5: "VERBOSE"}


class EvtxError(Exception):
    """A user-facing reason the event log could not be read."""


def available():
    try:
        import evtx  # noqa: F401
    except ImportError:
        return False
    return True


def fields(value, prefix=""):
    """Flatten an event's data into (name, value) pairs, skipping XML namespace noise."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "#attributes":
                yield from ((k, v) for k, v in fields(item, prefix) if k.split(".")[-1] != "xmlns")
                continue
            name = prefix if key == "#text" else (f"{prefix}.{key}" if prefix else key)
            yield from fields(item, name)
    elif isinstance(value, list):
        for n, item in enumerate(value, 1):
            yield from fields(item, f"{prefix}{n}" if prefix else str(n))
    elif value not in (None, ""):
        text = " ".join(str(value).split())
        yield prefix or "value", text if len(text) <= VALUE_CHARS else text[:VALUE_CHARS] + "…"


def event_line(event):
    system = event.get("System") or {}
    eid = system.get("EventID")
    if isinstance(eid, dict):
        eid = eid.get("#text", "")
    stamp = ((system.get("TimeCreated") or {}).get("#attributes") or {}).get("SystemTime", "")
    when = stamp[:19].replace("T", " ") + (" UTC" if stamp else "")
    provider = ((system.get("Provider") or {}).get("#attributes") or {}).get("Name", "")
    provider = provider.removeprefix("Microsoft-Windows-")
    level = LEVELS.get(system.get("Level"), str(system.get("Level", "")))
    data = event.get("EventData") or event.get("UserData") or {}
    pairs = []
    for n, (k, v) in enumerate(fields(data)):
        if n >= MAX_FIELDS:
            pairs.append("…more fields omitted")
            break
        pairs.append(f"{k}={v}")
    pairs = "; ".join(pairs)
    return f"{when} {level} Event {eid} {provider}: {pairs}".rstrip(": ")


def records(data):
    from evtx import PyEvtxParser
    try:
        parser = PyEvtxParser(io.BytesIO(data))
        for n, record in enumerate(parser.records_json()):
            if n >= MAX_RECORDS:
                raise EvtxError(f"This event log has more than {MAX_RECORDS:,} events; export a filtered copy first")
            raw = record["data"]
            if len(raw) > MAX_RECORD_JSON:
                raise EvtxError("An event in this log is too large to read; export a filtered copy first")
            yield json.loads(raw).get("Event") or {}
    except EvtxError:
        raise
    except Exception:
        raise EvtxError("This file could not be read as a Windows event log (.evtx)") from None


def evtx_text(name, data, max_chars=DEFAULT_MAX_CHARS):
    """The event log as text: a note for the model, then one line per event in file order.
    Stops with an error once the text passes max_chars."""
    lines, size = [], 0
    for e in records(data):
        line = event_line(e)
        size += len(line) + 1
        if size > max_chars:
            raise EvtxError(f"This event log expands to more than {max_chars:,} characters of text; export a filtered copy first")
        lines.append(line)
    if not lines:
        raise EvtxError("This event log has no events")
    first, last = lines[0][:23], lines[-1][:23]
    note = (f"[harness: Windows event log {name}, {len(lines):,} events from {first} to {last}. Event messages "
            "are not rendered here (Windows builds them from message files on the original machine), so each "
            "line shows the time, level, event ID, provider and the event's data fields. Interpret event IDs "
            "from the knowledge base or documentation, and do not invent message text.]")
    return note + "\n" + "\n".join(lines)
