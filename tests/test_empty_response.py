import json

import httpx
import pytest

from app import AnswerState, EmptyAnswerError
from test_app import setup, ask


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('reason', ['length', 'stop'])
def test_reasoning_only_is_explicit_error(tmp_path, stream, reason):
    def backend(request):
        if request.url.path != '/v1/chat/completions':
            return
        message = {'content': None, 'reasoning_content': 'private reasoning'}
        event = {'choices': [{'index': 0, 'delta' if stream else 'message': message, 'finish_reason': reason}]}
        if stream:
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text='data: '+json.dumps(event)+'\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json=event)
    client, _ = setup(tmp_path, handler=backend)
    with client:
        response = ask(client, stream=stream)
        assert response.status_code == (200 if stream else 502)
        assert 'no final text or tool calls' in response.text
        assert ('output token limit' in response.text) == (reason == 'length')
        assert not client.app.state.slots.locked()


@pytest.mark.parametrize('message', [{'content': 'Final answer'}, {'tool_calls': [{'index': 0, 'function': {'name': 'search'}}]}])
def test_terminal_chunk_answer_and_tool_calls_are_valid(message):
    state = AnswerState()
    state.observe({'choices': [{'delta': message, 'finish_reason': 'stop'}]}, streaming=True)
    state.require_answer()


def test_reasoning_and_whitespace_do_not_count_as_answer():
    state = AnswerState()
    state.observe({'choices': [{'delta': {'content': '  ', 'reasoning': 'hidden'}}]}, streaming=True)
    state.observe({'choices': [], 'usage': {'completion_tokens': 4096}}, streaming=True)
    with pytest.raises(EmptyAnswerError):
        state.require_answer()


@pytest.mark.parametrize("stream", [False, True])
def test_compaction_notice_cannot_mask_empty_answer(tmp_path, stream):
    from test_compaction import PROFILE, history, fake_backend
    original = fake_backend([])
    def backend(request):
        if request.url.path.endswith("chat/completions"):
            payload = json.loads(request.content)
            if not payload["messages"][0]["content"].startswith("Summarize the supplied visible conversation"):
                event = {"choices": [{"delta" if stream else "message": {"content": ""}, "finish_reason": "length"}]}
                if stream:
                    return httpx.Response(200, headers={"content-type": "text/event-stream"}, text="data: "+json.dumps(event)+"\n\ndata: [DONE]\n\n")
                return httpx.Response(200, json=event)
        return original(request)
    client, _ = setup(tmp_path, PROFILE, handler=backend)
    with client:
        response = ask(client, messages=history(), stream=stream)
        assert "no final text or tool calls" in response.text
        assert "Context compacted" not in response.text
