"""Attached logs are condensed with fixed rules before they reach the model."""
import time

from log_condense import condense, is_log
from test_app import HEADERS, setup

TRANSCRIPT = r"""**********************
Windows PowerShell transcript start
Start time: 20261104122253
Username: EXAMPLE\SYSTEM
RunAs User: EXAMPLE\SYSTEM
Configuration Name: 
Machine: PC-OLD01 (Microsoft Windows NT 10.0.26100.0)
Process ID: 5996
PSVersion: 5.1.26100.9711
PSEdition: Desktop
PSCompatibleVersions: 1.0, 2.0, 3.0, 4.0, 5.0, 5.1.26100.9711
BuildVersion: 10.0.26100.9711
CLRVersion: 4.0.30319.42000
WSManStackVersion: 3.0
PSRemotingProtocolVersion: 2.3
SerializationVersion: 1.1.0.1
**********************
Transcript started, output file is C:\ProgramData\Microsoft\RenameComputer\RenameComputer.log
Renaming computer to PC-NEW01
Rename-Computer : Fail to rename computer 'PC-OLD01' to 'PC-NEW01' due to the following exception: The RPC 
server is unavailable.
At C:\Windows\IMECache\00000000-1111-2222-3333-444444444444_2\RenameComputer.ps1:101 char:5
+     Rename-Computer -NewName $newName
+     ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : OperationStopped: (PC-OLD01:String) [Rename-Computer], InvalidOperationException
    + FullyQualifiedErrorId : FailToRenameComputer,Microsoft.PowerShell.Commands.RenameComputerCommand
Rename-Computer : Fail to rename computer 'PC-OLD01' to 'PC-NEW01' due to the following exception: The
RPC server is unavailable.
At C:\Windows\IMECache\00000000-1111-2222-3333-444444444444_2\RenameComputer.ps1:101 char:5
+     Rename-Computer -NewName $newName
+     ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : OperationStopped: (PC-OLD01:String) [Rename-Computer], InvalidOperationException
    + FullyQualifiedErrorId : FailToRenameComputer,Microsoft.PowerShell.Commands.RenameComputerCommand

Scheduled task unregistered.
Initiating a restart in 10 minutes

**********************
Windows PowerShell transcript end
End time: 20261104122343
**********************
"""


def test_a_powershell_transcript_keeps_the_error_once_and_drops_the_header():
    text, stats = condense("RenameComputer.log", TRANSCRIPT)
    # The same error, wrapped differently by PowerShell, is one block marked as repeated.
    assert text.count("FullyQualifiedErrorId") == 1
    assert "[harness: the 7 lines above repeated 2 times in a row]" in text
    # Error lines are kept word for word; useful header lines stay, version noise goes.
    assert "+ FullyQualifiedErrorId : FailToRenameComputer,Microsoft.PowerShell.Commands.RenameComputerCommand" in text
    assert r"Username: EXAMPLE\SYSTEM" in text and "Start time: 20261104122253" in text and "End time: 20261104122343" in text
    assert "PSVersion" not in text and "CLRVersion" not in text and "*****" not in text
    assert text.startswith("[harness: condensed from ") and "do not guess" in text.splitlines()[0]
    assert stats["lines_out"] < stats["lines_in"] and stats["repeats"] >= 6


def test_prose_and_short_clean_logs_are_left_alone():
    assert condense("notes.txt", "Called the user.\nThey rebooted.\nIt works now.\n" * 2) is None
    assert not is_log("notes.txt", "Just a note about a printer.")
    short = "\n".join(f"2026-11-04 12:00:{n:02d} step {n} ok" for n in range(12))
    assert is_log("steps.txt", short) and condense("steps.txt", short) is None


def test_a_long_log_keeps_errors_with_context_and_marks_what_was_omitted():
    lines = [f"2026-11-04 12:{n // 60:02d}:{n % 60:02d} INFO heartbeat {n}" for n in range(1000)]
    lines[500] = "2026-11-04 12:08:20 ERROR Access is denied (0x80070005)"
    lines[700] = "2026-11-04 12:11:40 ERROR Unspecified error (0x80004005)"
    for n in (100, 300, 900):
        lines[n] = f"2026-11-04 12:{n // 60:02d}:{n % 60:02d} WARN Cannot reach update server"
    text, stats = condense("agent.log", "\n".join(lines))
    # Different error codes are different errors and both stay.
    assert "Access is denied (0x80070005)" in text and "Unspecified error (0x80004005)" in text
    # A line repeated across the log is kept once, with its count and last time.
    assert text.count("Cannot reach update server") == 1 and "seen 3 times, last at 2026-11-04 12:15:00" in text
    assert "INFO heartbeat 499" in text and "INFO heartbeat 501" in text  # context
    assert "INFO heartbeat 0" in text and "INFO heartbeat 999" in text  # start and end
    assert "lines omitted]" in text and stats["omitted"] > 800
    assert stats["lines_out"] < 120


def test_the_route_condenses_only_where_the_profile_turns_it_on(tmp_path):
    client, _ = setup(tmp_path, {"log_condense": True})
    with client:
        r = client.post("/v1/documents/condense", headers=HEADERS,
                        json={"profile": "local", "name": "RenameComputer.log", "text": TRANSCRIPT})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["condensed"]["lines_out"] < body["condensed"]["lines_in"] and body["tokens"] > 0
        assert body["text"].count("FullyQualifiedErrorId") == 1
        r = client.post("/v1/documents/condense", headers=HEADERS,
                        json={"profile": "local", "name": "notes.txt", "text": "A short note."})
        assert r.json() == {"condensed": None}
        assert client.get("/v1/profiles", headers=HEADERS).json()["data"][0]["log_condense"] is True
        assert ".log" in client.get("/v1/documents/config", headers=HEADERS).json()["types"]

    (tmp_path / "off").mkdir()
    off, _ = setup(tmp_path / "off", {})
    with off:
        r = off.post("/v1/documents/condense", headers=HEADERS,
                     json={"profile": "local", "name": "RenameComputer.log", "text": TRANSCRIPT})
        assert r.status_code == 403


def test_a_log_at_the_size_limit_with_no_repeats_condenses_quickly():
    """The worst case for repeat detection: every line distinct, near the 1,000,000-character
    attachment limit. It must not tie up a harness worker."""
    lines = [f"2026-11-04 12:00:00 line {n} pid 42 value" for n in range(24000)]
    started = time.monotonic()
    text, stats = condense("big.log", "\n".join(lines))
    assert time.monotonic() - started < 5
    assert stats["omitted"] > 20000


def cmtrace(message, time, kind=1, component="IntuneManagementExtension"):
    return (f'<![LOG[{message}]LOG]!><time="{time}.1234567" date="11-16-2026" component="{component}" '
            f'context="" type="{kind}" thread="7" file="">')


def ime_log(cycles=120):
    """An IntuneManagementExtension-style log: a repeating poll cycle, a long JSON payload per
    cycle full of error-looking words, and two real errors (type 3 and 2) buried in it."""
    out = []
    for c in range(cycles):
        t = f"11:{c // 60 % 60:02d}:{c % 60:02d}"
        for msg in ("[Win32App] Requesting required apps in session 1", "[Win32App] ESP checking app status",
                    "[Policy] Sync polices: request success, total 3 policies, failed 0",
                    "DNS detection: WinHttpGetProxyForUrl call failed because of error 12180"):
            out.append(cmtrace(msg, t))
        payload = ",".join(f'{{"Id":"{c}-{k}","ErrorCode":0,"FailureCount":0,"Detail":"{"x" * 200}"}}' for k in range(15))
        out.append(cmtrace(f"[Win32App] Get policies = [{payload}]", t))
        out.append(cmtrace(f"[Win32App] Checking applicability for policy {c}, result ok", t))
        if c == 70:
            out.append(cmtrace("[SCEP] Certificate enrollment failed (0x80094800)", t, 3))
            out.append(cmtrace("[SCEP] NDES server returned HTTP 500 for GetCACaps", t, 2))
    return "\n".join(out)


def test_cmtrace_lines_are_shortened_and_keep_their_message_and_severity():
    text, stats = condense("IntuneManagementExtension.log", ime_log(10))
    assert stats["cmtrace"] and "<![LOG[" not in text and "[harness: date 11-16-2026]" in text
    assert "IntuneManagementExtension: [Win32App] Requesting required apps in session 1" in text
    assert "CMTrace lines shortened" in text.splitlines()[0]


def test_a_repeated_cycle_gets_one_marker_not_one_per_line():
    text, _ = condense("IntuneManagementExtension.log", ime_log(10))
    assert "[harness: each line from 11:00:00.123 to here recurs 9 more times later in the log" in text
    assert "seen 10 times" not in text


def test_a_budget_tightens_condensing_until_it_fits_and_keeps_the_real_errors():
    log = ime_log()
    loose, _ = condense("IntuneManagementExtension.log", log)
    for budget in (40_000, 8_000, 1_500):
        text, stats = condense("IntuneManagementExtension.log", log, budget)
        assert len(text) <= budget < len(loose)
        assert "ERROR: [SCEP] Certificate enrollment failed (0x80094800)" in text
        if budget > 1_500:
            assert "WARNING: [SCEP] NDES server returned HTTP 500 for GetCACaps" in text
    # At the errors-only stages the CMTrace type decides: "ErrorCode":0 payloads are not errors.
    text, stats = condense("IntuneManagementExtension.log", log, 1_500)
    assert stats["stage"] >= 5 and '"ErrorCode":0' not in text


def test_a_log_over_the_text_limit_is_condensed_by_the_harness(tmp_path, monkeypatch):
    import json as _json
    import documents
    monkeypatch.setattr(documents, "MAX_TEXT_CHARS", 200_000)
    big = ime_log(200).encode()
    assert len(big) > 200_000

    def post(client):
        r = client.post("/v1/documents/convert?profile=local", content=big,
                        headers={**HEADERS, "X-Document-Name": "IntuneManagementExtension.log", "Content-Type": "application/octet-stream"})
        return _json.loads(r.text.strip().splitlines()[-1])

    client, _ = setup(tmp_path, {"log_condense": True})
    with client:
        doc = post(client)
    assert doc["done"] and doc["condensed"]["cmtrace"] and doc["original_chars"] == len(big)
    assert "0x80094800" in doc["text"] and doc["chars"] < 200_000 and doc["fits"]

    (tmp_path / "off").mkdir()
    off, _ = setup(tmp_path / "off", {})
    with off:
        assert "more than 200,000 characters" in post(off)["error"]


def test_malformed_cmtrace_cannot_make_parsing_slow():
    """Openers with no closers, or attributes with no closing quote, parse in one pass."""
    from log_condense import shorten_cmtrace
    started = time.monotonic()
    shorten_cmtrace("<![LOG[" * 5 + "x]LOG]!>" + "<![LOG[" * 200_000)
    shorten_cmtrace(('<![LOG[m]LOG]!><time="' + "a" * 100) * 100_000)
    assert time.monotonic() - started < 2


def test_the_expensive_passes_run_once_for_several_budgets():
    from log_condense import finish, prepare
    prep = prepare("IntuneManagementExtension.log", ime_log())
    sizes = [len(finish(prep, budget)[0]) for budget in (40_000, 8_000, 1_500)]
    assert sizes == sorted(sizes, reverse=True) and sizes[-1] <= 1_500


def test_markers_name_their_lines_by_time_and_never_stack_out_of_order():
    """From the real IME log: a block repeated back to back whose lines also recur later got its
    "repeated in a row" marker pushed under the cycle marker, so it described the wrong lines."""
    def at(sec, msg, kind=1):
        return cmtrace(msg, f"11:30:{sec:02d}", kind)
    block = ["EMS Agent Started", "RecycleScripts = True", "EnableDeviceAction = True", "Found 1 MDM certificates"]
    lines = [at(1, m) for m in block] + [at(2, m) for m in block]          # back to back
    lines += [at(3, f"Startup step {n}") for n in range(30)]                # unique
    lines += [at(40, m) for m in block]                                     # the same lines later
    text, _ = condense("IntuneManagementExtension.log", "\n".join(lines))
    out = text.splitlines()
    found = next(n for n, l in enumerate(out) if l.endswith("Found 1 MDM certificates"))
    # The in-a-row marker sits directly under the block it describes, named by the block's first time.
    assert out[found + 1] == "[harness: the lines from 11:30:01.123 to here repeated 2 times in a row]"
    assert out[found + 2] == ("[harness: each line from 11:30:01.123 to here recurs 1 more time later in the log, "
                              "the last at 11:30:40.123; those copies removed]")
    assert text.count("EMS Agent Started") == 1
