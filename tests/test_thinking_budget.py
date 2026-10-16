import json

import pytest
from pydantic import ValidationError

from app import Profile
from test_app import setup, ask
from test_compaction import PROFILE, history, fake_backend


@pytest.mark.parametrize('budget', [-1, True, 1.5, '100', 2048, 4096])
def test_invalid_thinking_budgets(budget):
    for config in ({'backend_options': {'thinking_token_budget': budget}},
                   {'backend_presets': {'actual-model': {'backend_options': {'thinking_token_budget': budget}}}}):
        with pytest.raises(ValidationError):
            Profile(backend_model='actual-model', system_prompt_file='prompt.md', **config)


def test_server_owned_budget_and_client_output_cap(tmp_path):
    client, calls = setup(tmp_path, {'backend_options': {'thinking_token_budget': 256}, 'allow_client_params': ['max_tokens']})
    with client:
        assert ask(client).status_code == 200
        assert json.loads(calls[-1].content)['thinking_token_budget'] == 256
        assert ask(client, max_tokens=100).status_code == 200
        assert json.loads(calls[-1].content)['thinking_token_budget'] == 99
        assert ask(client, thinking_token_budget=999).status_code == 400
    assert all('thinking_token_budget' not in json.loads(r.content) for r in calls if r.url.path == '/tokenize')


def test_compaction_does_not_inherit_thinking_budget(tmp_path):
    profile = {**PROFILE, 'backend_options': {**PROFILE['backend_options'], 'thinking_token_budget': 100}}
    client, calls = setup(tmp_path, profile, handler=fake_backend([]))
    with client:
        assert ask(client, messages=history()).status_code == 200
    generations = [json.loads(r.content) for r in calls if r.url.path.endswith('/chat/completions')]
    assert len(generations) > 1
    assert all('thinking_token_budget' not in p for p in generations[:-1])
    assert generations[-1]['thinking_token_budget'] == 100


@pytest.mark.parametrize('ratio', [0, 1, 1.5, -0.2])
def test_ratio_must_be_a_fraction(ratio):
    with pytest.raises(ValidationError):
        Profile(backend_model='actual-model', system_prompt_file='prompt.md', thinking_budget_ratio=ratio)


def test_ratio_and_fixed_budget_cannot_both_be_set():
    for config in ({'thinking_budget_ratio': 0.5, 'backend_options': {'thinking_token_budget': 100}},
                   {'backend_presets': {'m': {'thinking_budget_ratio': 0.5, 'backend_options': {'thinking_token_budget': 100}}}}):
        with pytest.raises(ValidationError):
            Profile(backend_model='actual-model', system_prompt_file='prompt.md', **config)


def test_ratio_scales_with_the_actual_output_allowance(tmp_path):
    client, calls = setup(tmp_path, {'max_output_tokens': 8192, 'thinking_budget_ratio': 0.5, 'allow_client_params': ['max_tokens']})
    with client:
        assert ask(client).status_code == 200
        assert json.loads(calls[-1].content)['thinking_token_budget'] == 4096
        assert ask(client, max_tokens=1000).status_code == 200
        assert json.loads(calls[-1].content)['thinking_token_budget'] == 500
        assert ask(client, max_tokens=1).status_code == 200
        assert json.loads(calls[-1].content)['thinking_token_budget'] == 0


def test_exact_model_preset_applies_the_ratio_only_to_that_model(tmp_path):
    preset = {'max_output_tokens': 8192,
              'backend_presets': {'actual-model': {'thinking_budget_ratio': 0.25}}}
    client, calls = setup(tmp_path, preset)
    with client:
        assert ask(client).status_code == 200
        assert json.loads(calls[-1].content)['thinking_token_budget'] == 2048
    other = {**preset, 'backend_presets': {'different-model': {'thinking_budget_ratio': 0.25}}}
    client, calls = setup(tmp_path, other)
    with client:
        assert ask(client).status_code == 200
        assert 'thinking_token_budget' not in json.loads(calls[-1].content)
