"""Windows event log (.evtx) attachments are read as one text line per event."""
import json

import pytest

import evtx_text
from evtx_text import EvtxError, event_line
from test_app import HEADERS, setup

pytestmark = pytest.mark.skipif(not evtx_text.available(), reason="evtx package not installed")

PROVIDER = "Microsoft-Windows-DeviceManagement-Enterprise-Diagnostics-Provider"


def event(eid, level, when, data):
    """A record shaped like the evtx package's JSON for a DeviceManagement event."""
    return {"#attributes": {"xmlns": "http://schemas.microsoft.com/win/2004/08/events/event"},
            "System": {"Provider": {"#attributes": {"Name": PROVIDER, "Guid": "{00000000-0000-0000-0000-000000000000}"}},
                       "EventID": eid, "Level": level, "TimeCreated": {"#attributes": {"SystemTime": when}},
                       "Computer": "PC-0001"},
            "EventData": data}


SCEP_EVENTS = [
    event(813, 4, "2026-11-16T19:04:41.8343964Z", {"Message1": "Power/Controls/EnergyEstimationEnabled", "HexInt1": "0x1"}),
    event(306, 4, "2026-11-16T19:30:17.1000000Z", {"Message2": "S-1-5-18", "Message3": "system", "Message4": "clientinstall"}),
    event(307, 2, "2026-11-16T19:30:24.2000000Z", {"Message1": "SCEPLogDisposition:Transaction not permitted or supported"}),
    event(32, 2, "2026-11-16T19:30:24.3000000Z", {"HRESULT": "0x87d00905"}),
    event(309, 4, "2026-11-16T19:30:24.4000000Z", {"HexInt3": "0x87d00905", "Message4": "https://ndes.example.test/certsrv/mscep/mscep.dll/pkiclient.exe"}),
]


def test_an_event_becomes_one_line_with_time_level_id_provider_and_data():
    assert event_line(SCEP_EVENTS[3]) == (
        "2026-11-16 19:30:24 UTC ERROR Event 32 DeviceManagement-Enterprise-Diagnostics-Provider: HRESULT=0x87d00905")
    assert event_line(SCEP_EVENTS[2]).endswith("Message1=SCEPLogDisposition:Transaction not permitted or supported")
    # Data in <Data Name=...> lists and UserData is flattened too; namespaces are dropped.
    nested = event(4106, 3, "2026-11-16T19:31:00Z", None)
    nested.pop("EventData")
    nested["UserData"] = {"Info": {"#attributes": {"xmlns": "x"}, "Code": "5", "Items": ["a", "b"]}}
    assert event_line(nested).endswith("WARNING Event 4106 DeviceManagement-Enterprise-Diagnostics-Provider: "
                                       "Info.Code=5; Info.Items1=a; Info.Items2=b")


def test_the_text_says_messages_are_not_rendered(monkeypatch):
    monkeypatch.setattr(evtx_text, "records", lambda data: iter(SCEP_EVENTS))
    text = evtx_text.evtx_text("admin.evtx", b"")
    note, *lines = text.splitlines()
    assert "5 events from 2026-11-16 19:04:41 UTC to 2026-11-16 19:30:24 UTC" in note
    assert "not rendered" in note and "do not invent message text" in note
    assert len(lines) == 5 and lines[3].startswith("2026-11-16 19:30:24 UTC ERROR Event 32 ")


def test_a_file_that_is_not_an_event_log_is_refused():
    with pytest.raises(EvtxError, match="could not be read as a Windows event log"):
        evtx_text.evtx_text("text.evtx", b"just some text, not an event log" * 50)
    # A valid header with nothing after it reads as an empty log.
    with pytest.raises(EvtxError, match="no events|could not be read"):
        evtx_text.evtx_text("broken.evtx", b"ElfFile\x00" + b"\x00" * 4096)


def convert(client, name, body=b"x"):
    r = client.post("/v1/documents/convert?profile=local", content=body,
                    headers={**HEADERS, "X-Document-Name": name, "Content-Type": "application/octet-stream"})
    return json.loads(r.text.strip().splitlines()[-1])


def test_an_evtx_attachment_is_read_and_listed_as_a_type(tmp_path, monkeypatch):
    monkeypatch.setattr(evtx_text, "records", lambda data: iter(SCEP_EVENTS))
    client, _ = setup(tmp_path, {})
    with client:
        assert ".evtx" in client.get("/v1/documents/config", headers=HEADERS).json()["types"]
        doc = convert(client, "admin.evtx")
    assert doc["done"] and "ERROR Event 307" in doc["text"] and doc["text"].startswith("[harness: Windows event log admin.evtx")


def test_a_broken_evtx_attachment_reports_why(tmp_path):
    client, _ = setup(tmp_path, {})
    with client:
        assert convert(client, "admin.evtx", b"not an event log" * 100)["error"] == \
            "This file could not be read as a Windows event log (.evtx)"


def test_a_large_event_log_is_condensed_on_log_condense_profiles(tmp_path, monkeypatch):
    import documents
    monkeypatch.setattr(documents, "MAX_TEXT_CHARS", 20_000)
    many = [event(813, 4, f"2026-11-16T19:{n // 60 % 60:02d}:{n % 60:02d}Z", {"Message1": f"Policy/Area{n % 7}", "HexInt1": "0x1"})
            for n in range(1500)] + SCEP_EVENTS[2:4]
    monkeypatch.setattr(evtx_text, "records", lambda data: iter(many))
    client, _ = setup(tmp_path, {"log_condense": True})
    with client:
        doc = convert(client, "admin.evtx")
    assert doc["condensed"] and doc["chars"] < 20_000 and doc["original_chars"] > 20_000
    assert "Transaction not permitted or supported" in doc["text"] and "HRESULT=0x87d00905" in doc["text"]


def test_expansion_is_capped_by_text_size_and_fields_per_event(monkeypatch):
    """A small file can expand a lot through templates: the text and the fields are bounded."""
    big = event(813, 4, "2026-11-16T19:00:00Z", {f"Field{n}": "x" * 50 for n in range(500)})
    assert event_line(big).endswith("…more fields omitted") and event_line(big).count("=") == evtx_text.MAX_FIELDS
    monkeypatch.setattr(evtx_text, "records", lambda data: iter([SCEP_EVENTS[3]] * 10_000))
    with pytest.raises(EvtxError, match="expands to more than 50,000 characters"):
        evtx_text.evtx_text("admin.evtx", b"", max_chars=50_000)


def test_a_worker_slot_is_held_until_its_thread_finishes(tmp_path):
    """Cancelling a request must not free its slot while the parse is still running."""
    import asyncio
    import threading
    import documents
    from fastapi import FastAPI
    app = FastAPI()
    documents.install_documents(app, lambda: None, docling=None)
    in_worker = app.state.document_worker
    release = threading.Event()
    started = []

    async def scenario():
        # Two slots: cancel a running job, then check a third job must wait for its thread.
        first = asyncio.create_task(in_worker(release.wait, 5))
        second = asyncio.create_task(in_worker(release.wait, 5))
        await asyncio.sleep(0.05)
        first.cancel()
        third = asyncio.create_task(in_worker(lambda: started.append(True)))
        await asyncio.sleep(0.1)
        waited = not started  # both slots still busy: the cancelled job's thread is running
        release.set()
        await second
        await asyncio.wait_for(third, 2)
        return waited, bool(started)
    assert asyncio.run(scenario()) == (True, True)
