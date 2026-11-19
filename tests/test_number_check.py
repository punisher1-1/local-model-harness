import json
import re

import pytest

from code_mcp import CodeStore
from number_check import (MAX_LISTED, annotation, code_annotation, inputs_annotation, split_inputs,
                          unrun_blocks, unverified_numbers)
from research import describe_result
from test_app import setup, ask, HEADERS
from test_research import completion, tool
from test_code_mcp import env  # noqa: F401  (fixture)

PROMPT = ("Corpus: 10,000,000 documents. Average chunks per document: 23. Chunk size: 512 tokens, "
          "overlap 64. Retrieval latency budget: 200ms p95. Total end-to-end budget: 2500ms p95.")
STDOUT = ("unique_len = 10368\ntotal_vectors = 230,000,000\nraw_bytes = 942,080,000,000 (877.38037109375 GiB)\n"
          "n = 21.6129 -> year 22\noverlap_ratio = 0.125\n")
ANSWER = """## §2 — Chunking
Volume is 230,000,000 × 512 = **117,760,000,000 tokens**, of which ≈ 11.3 % is redundant.
Overlap is 64 tokens (12.5 %). Raw payload 877.38 GiB; year 22 at n = 21.61; 10,368 tokens.
The index must sustain 625 searches/second at p95 with float32 vectors; 625 again.
```python
print(117760000000)
```
| 1 | Corpus size | 10,000,000 documents |
"""


def test_flags_only_numbers_no_output_printed():
    checked, flagged = unverified_numbers(ANSWER, [STDOUT], PROMPT)
    assert flagged == ["117,760,000,000", "11.3 %", "625"]
    assert checked == 10


def test_rounding_percent_and_exemptions():
    assert unverified_numbers("Payload 877.4 GiB, ratio 12.50%, 1e3 calls.", ["877.38037\n0.125\n1000.0"], "")[1] == []
    # Rounding must agree with the printed value, not just be near it.
    assert unverified_numbers("Payload 877.39 GiB.", ["877.38037"], "")[1] == ["877.39"]
    # Given values, small integers, identifiers and section references are not claims.
    assert unverified_numbers("§12: p95 of 2500 ms, step 3, float32, 64 overlap.", [""], PROMPT) == (0, [])


def test_numbers_typed_into_a_run_are_inputs_not_unverified():
    script = ('retr = {"embed": 20, "bm25": 60, "ann": 80, "fusion": 40}\n'
              "share = 0.125\nbig = 1_600\nprint(sum(retr.values()))  # 3072 in a comment is not a literal\n")
    answer = "Embed 20 ms, BM25 60 ms, ANN 80 ms, fusion 40 ms (200 total); gen 1,600 ms; 12.5% share; 3072 dims; 300 ms."
    checked, flagged = unverified_numbers(answer, ["200\n"], "")
    assert flagged == ["20", "60", "80", "40", "1,600", "12.5%", "3072", "300"]
    assert split_inputs(flagged, [script]) == (["3072", "300"], ["20", "60", "80", "40", "1,600", "12.5%"])
    # A script that does not parse still contributes its literals.
    assert split_inputs(["42"], ["x = (42"]) == ([], ["42"])
    assert inputs_annotation(["20", "60"]) == "\n*Inputs set in code (typed into a run, not derived by it): 20 · 60.*"


def test_space_grouped_thousands_are_one_number_when_printed():
    printed = ["942080000000\n10368\n"]
    assert unverified_numbers("Raw 942 080 000 000 B; up to 10\u202f368 tokens.", printed, "") == (2, [])
    # Not printed as a whole: the parts are separate numbers, as before.
    assert unverified_numbers("Try 512 640 768 dims.", printed, "")[1] == ["512", "640", "768"]
    assert unverified_numbers("Corpus of 10 000 000 docs.", [""], "Corpus: 10,000,000 documents") == (0, [])
    # Punctuation after the number ends it; a digit after a comma or point continues it.
    assert unverified_numbers("T in (9 921, 10 368]. Each is 4 096. Total 230 000 000; done.",
                              ["9921\n10368\n4096\n230000000\n"], "") == (4, [])
    assert unverified_numbers("Size 4 096,5 units.", ["4096\n"], "")[1] == ["096,5"]


def test_annotation_caps_the_list():
    flagged = [str(n) for n in range(100, 100 + MAX_LISTED + 3)]
    text = annotation(flagged)
    assert text.startswith("\n*Unverified numbers") and "+3 more" in text and str(100 + MAX_LISTED) not in text


def test_truncated_or_failed_runs_are_visible_in_the_trace():
    assert describe_result({"exit_code": 0, "truncated": True}) == "  ✓ exit 0 (output truncated)"
    assert describe_result({"exit_code": 0, "output_limit": True, "timed_out": True}) == "  ✗ exit 0 (timed out) (output truncated)"
    assert describe_result({"exit_code": 0, "truncated": False}) == "  ✓ exit 0"
    assert describe_result({"exit_code": 1}) == "  ✗ exit 1"
    assert describe_result({"exit_code": None, "timed_out": True}) == "  ✗ exit None (timed out)"


RAN = """import math
W, O = 512, 64
def chunks(T): return max(1, math.ceil((T - O) / (W - O)))
print(chunks(10144))
"""


def test_flags_python_blocks_no_run_contained():
    answer = ("```python\n# chunk geometry\nW, O = 512, 64   # window, overlap\n"
              "def chunks(T): return max(1, math.ceil((T - O) / (W - O)))\n```\n"
              "```python\nk = 23\nprint((k-1)*(W-O)+O)\n```\n"
              "```\nPRINTED 23\n```\n```py\n    print(chunks(10144))\n```")
    assert unrun_blocks(answer, [RAN]) == (3, [2])
    assert unrun_blocks(answer, [RAN, "k = 23\nprint((k-1)*(W-O)+O)"]) == (3, [])
    # A block is checked against one run at a time, not pieced together from several.
    assert unrun_blocks("```python\nW, O = 512, 64\nk = 23\n```", [RAN, "k = 23"]) == (1, [1])
    assert code_annotation(6, [2, 3, 6]) == "\n*Code not run as shown: Python blocks 2, 3, 6 of 6.*"
    assert code_annotation(6, [4]) == "\n*Code not run as shown: Python block 4 of 6.*"


def test_verify_numbers_requires_the_code_server(tmp_path):
    with pytest.raises(Exception, match="verify_numbers requires the code MCP server"):
        setup(tmp_path, {"client_tools": True, "mcp_servers": ["vault"], "verify_numbers": "annotate"})[0].__enter__()


@pytest.mark.parametrize("mode", ["annotate", "off"])
def test_tool_loop_annotates_unverified_numbers(tmp_path, env, monkeypatch, caplog, mode):  # noqa: F811
    async def fake(self, name, args):
        return {"stdout": STDOUT + "x" * 20000, "stderr": "", "exit_code": 0, "timed_out": False}
    monkeypatch.setattr(CodeStore, "call", fake)
    rounds = []

    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        rounds.append(1)
        if len(rounds) == 1:
            return completion({"role": "assistant", "tool_calls": [tool("python_run", {"code": "print(1)"})]}, "tool_calls")
        return completion({"role": "assistant", "content": ANSWER})
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["code"], "verify_numbers": mode}, handler=backend)
    with client, caplog.at_level("INFO", logger="uvicorn.error"):
        r = ask(client, messages=[{"role": "user", "content": PROMPT}])
    assert r.status_code == 200
    text = r.json()["choices"][0]["message"]["content"]
    events = [json.loads(m) for m in caplog.messages if m.startswith("{")]
    tool_event = next(e for e in events if e.get("event") == "research_tool")
    assert tool_event["truncated"] is True
    if mode == "annotate":
        text = re.sub(r"\n\*Run: [^\n]*\.\*", "", text)
        assert text.endswith("python_run (output truncated).*\n*Unverified numbers (not printed by python_run): "
                             "117,760,000,000 · 11.3 % · 625.*\n*Code not run as shown: Python block 1 of 1.*")
        assert next(e for e in events if e.get("event") == "number_check")["unverified"] == 3
    else:
        assert "Unverified numbers" not in text and not any(e.get("event") == "number_check" for e in events)


def test_activity_line_shows_failed_and_unrun_code(tmp_path, env, monkeypatch):  # noqa: F811
    results = iter([{"stdout": "", "stderr": "NameError", "exit_code": 1, "timed_out": False},
                    {"stdout": "10368\n", "stderr": "", "exit_code": 0, "timed_out": False, "truncated": True}])

    async def fake(self, name, args):
        return next(results)
    monkeypatch.setattr(CodeStore, "call", fake)
    rounds = []
    answer = "Upper bound 10,368 tokens; stride 448, guessed 999.\n```python\nprint(23 * 448 + 64)\n```\n```python\nprint(chunks(10144))\n```"

    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        rounds.append(1)
        if len(rounds) < 3:
            return completion({"role": "assistant", "tool_calls": [tool("python_run", {"code": "print(23 * 448 + 64)"}, f"call{len(rounds)}")]}, "tool_calls")
        return completion({"role": "assistant", "content": answer})
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["code"], "verify_numbers": "annotate"}, handler=backend)
    with client:
        text = ask(client, messages=[{"role": "user", "content": "How many tokens?"}]).json()["choices"][0]["message"]["content"]
    assert "python_run (exit 1) → python_run (output truncated).*" in text
    assert "\n*Unverified numbers (not printed by python_run): 999.*\n*Inputs set in code (typed into a run, not derived by it): 448.*" in text
    assert text.endswith("\n*Code not run as shown: Python block 2 of 2.*")


def runs_client(tmp_path, monkeypatch):
    results = iter([{"stdout": "", "stderr": "NameError: x", "exit_code": 1, "timed_out": False},
                    {"stdout": "4096\n", "stderr": "", "exit_code": 0, "timed_out": False},
                    {"error": "sandbox_busy"}])

    async def fake(self, name, args):
        return next(results)
    monkeypatch.setattr(CodeStore, "call", fake)
    rounds = []

    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        rounds.append(1)
        if len(rounds) <= 3:
            return completion({"role": "assistant", "tool_calls": [tool("python_run", {"code": f"print({len(rounds)})"}, f"call{len(rounds)}")]}, "tool_calls")
        return completion({"role": "assistant", "content": "Each vector is 4096 bytes."})
    return setup(tmp_path, {"client_tools": True, "mcp_servers": ["code"]}, handler=backend)[0]


EXPECTED_RUNS = [
    {"code": "print(1)", "stdout": "", "stderr": "NameError: x", "exit_code": 1, "timed_out": False, "output_limit": False, "truncated": False},
    {"code": "print(2)", "stdout": "4096\n", "stderr": "", "exit_code": 0, "timed_out": False, "output_limit": False, "truncated": False},
    {"code": "print(3)", "error": "sandbox_busy"}]


@pytest.mark.parametrize("stream", [False, True])
def test_chat_receives_the_exact_runs_only_when_it_asks(tmp_path, env, monkeypatch, stream):  # noqa: F811
    body = {"model": "local", "messages": [{"role": "user", "content": "Bytes per vector?"}], "stream": stream}
    for want in (True, False):
        (tmp_path / str(want)).mkdir()
        with runs_client(tmp_path / str(want), monkeypatch) as client:
            r = client.post("/v1/chat/completions", headers={**HEADERS, **({"X-Harness-Runs": "1"} if want else {})}, json=body)
        assert r.status_code == 200
        if stream:
            events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: {")]
            runs = next((e["harness_runs"] for e in events if "harness_runs" in e), None)
        else:
            runs = r.json().get("harness_runs")
        assert runs == (EXPECTED_RUNS if want else None)


def test_saved_answers_keep_their_runs():
    from conversation_store import Message
    m = Message.model_validate({"id": "a", "role": "assistant", "content": "x", "runs": EXPECTED_RUNS})
    assert m.model_dump()["runs"][2] == {"code": "print(3)", "stdout": None, "stderr": None, "exit_code": None,
                                         "timed_out": None, "output_limit": None, "truncated": None, "error": "sandbox_busy"}
    with pytest.raises(Exception):
        Message.model_validate({"id": "a", "role": "assistant", "content": "x", "runs": [{"code": "x", "html": "<b>"}]})
    with pytest.raises(Exception):
        Message.model_validate({"id": "a", "role": "assistant", "content": "x", "runs": [{"code": "x"}] * 17})


def test_run_line_names_model_profile_and_harness(monkeypatch):
    import research
    monkeypatch.setattr(research, "HARNESS_VERSION", "4c4e299")
    assert research.run_line("qwen3.8-27b", "local-bench") == "\n*Run: model qwen3.8-27b · profile local-bench · harness 4c4e299.*"
    # Markdown in a model ID cannot break the italic line.
    assert research.run_line("a*b_c`d", "p") == "\n*Run: model abcd · profile p · harness 4c4e299.*"


def test_harness_version_comes_from_the_image(monkeypatch):
    import importlib
    import research
    monkeypatch.setenv("HARNESS_VERSION", "ee83978; rm -rf /")
    assert importlib.reload(research).HARNESS_VERSION == "ee83978rm-rf"
    monkeypatch.delenv("HARNESS_VERSION")
    assert importlib.reload(research).HARNESS_VERSION == "unknown"
