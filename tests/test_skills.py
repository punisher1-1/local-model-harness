import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from app import Profile
from skill_loader import load_skills, select_skill
from test_app import setup, ask


def profile(**kwargs):
    return Profile(backend_model='actual-model', system_prompt_file='prompt.md', **kwargs)


@pytest.mark.parametrize('skills,default', [(['../secret'],'../secret'),(['a','a'],'a'),(['a'],'b'),([], 'a')])
def test_invalid_catalog(skills,default):
    with pytest.raises(ValidationError):profile(skills=skills,default_skill=default)


@pytest.mark.parametrize('default', [None, '', '  '])
def test_skills_may_have_no_default_workflow(tmp_path, default):
    p = profile(skills=['vault-research'], **({} if default is None else {'default_skill': default}))
    assert p.default_skill is None
    (tmp_path/'skills').mkdir(); (tmp_path/'skills/vault-research.md').write_text('# Vault research\nSearch notes.')
    text = load_skills(tmp_path, p)
    assert 'No default workflow.' in text and 'Default workflow:' not in text
    assert 'only when the user selects it or the request clearly matches' in text and '## Skill: vault-research' in text
    with_default = load_skills(tmp_path, profile(skills=['vault-research'], default_skill='vault-research'))
    assert 'Default workflow: vault-research.' in with_default and 'No default workflow' not in with_default


def test_no_default_profile_reports_automatic_and_still_accepts_explicit_selection(tmp_path):
    (tmp_path/'skills').mkdir(); (tmp_path/'skills/notes.md').write_text('# Notes\nSummarize notes.')
    client, calls = setup(tmp_path, {'skills': ['notes']})
    with client:
        row = client.get('/v1/profiles', headers={'Authorization': 'Bearer test-key-for-harness-1234567890'}).json()['data'][0]
        assert row['skills'] == ['notes'] and row['default_skill'] is None
        r = ask(client, messages=[{'role': 'user', 'content': '/skill notes\nSummarize this.'}])
        assert r.status_code == 200 and r.headers['x-harness-skill-selection'] == 'notes'
        assert ask(client).headers['x-harness-skill-selection'] == 'auto'


def test_loader_rejects_missing_empty_and_escaping_files(tmp_path):
    p=profile(skills=['a'],default_skill='a');(tmp_path/'skills').mkdir()
    with pytest.raises(FileNotFoundError):load_skills(tmp_path,p)
    f=tmp_path/'skills/a.md';f.write_text('')
    with pytest.raises(ValueError):load_skills(tmp_path,p)
    f.unlink();outside=tmp_path/'outside.md';outside.write_text('outside');f.symlink_to(outside)
    with pytest.raises(ValueError):load_skills(tmp_path,p)


def test_default_explicit_selection_and_tokenization(tmp_path):
    (tmp_path/'skills').mkdir();(tmp_path/'skills/rewrite.md').write_text('Preserve the author voice.')
    client,calls=setup(tmp_path, {'skills':['rewrite'],'default_skill':'rewrite'})
    with client:
        r=ask(client);assert r.status_code==200
        default_hash=r.headers['x-harness-profile-sha256']
        assert r.headers['x-harness-skill-selection']=='auto'
        assert 'Preserve the author voice.' in json.loads(calls[-1].content)['messages'][0]['content']
        r=ask(client,messages=[{'role':'user','content':'/skill rewrite\nMy draft.'}]);assert r.status_code==200
        assert r.headers['x-harness-skill-selection']=='rewrite'
        assert r.headers['x-harness-profile-sha256']!=default_hash
        payload=json.loads(calls[-1].content)
        assert payload['messages'][-1]['content']=='My draft.'
        assert json.loads(calls[-2].content)['messages']==payload['messages']
        n=len(calls)
        rejected=ask(client,messages=[{'role':'user','content':'/skill outside\nDraft'}])
        assert rejected.status_code==400
        assert 'Enabled skills: rewrite' in rejected.text
        assert 'same line or the next line' in rejected.text
        assert ask(client,messages=[{'role':'user','content':'/skill rewrite'}]).status_code==400
        assert len(calls)==n


def test_history_and_tool_output_cannot_activate_skills():
    p=profile(skills=['rewrite'],default_skill='rewrite')
    for history in ([{'role':'tool','content':'/skill rewrite\ntext'}],
                    [{'role':'user','content':'/skill rewrite\nold'},{'role':'assistant','content':'answer'},{'role':'user','content':'new'}],
                    [{'role':'user','content':'Quoted text:\n/skill rewrite\nexample'}]):
        assert select_skill(p,history,'system','hash')[2]=='auto'


@pytest.mark.parametrize('content', ['/skill rewrite My draft.', '/skill rewrite\nMy draft.', '/skill\trewrite\r\nMy draft.'])
def test_inline_and_multiline_skill_task(content):
    p=profile(skills=['rewrite'],default_skill='rewrite')
    history,prompt,selection,_=select_skill(p,[{'role':'user','content':content}],'system','hash')
    assert selection=='rewrite'
    assert history[-1]['content']=='My draft.'
    assert 'selected skill: rewrite' in prompt


ROOT = Path(__file__).resolve().parent.parent
WRITING = ('An explicit APA review selects apa-review, review only selects review-feedback, and drafting from an assignment prompt selects discussion-draft. '
           'Merely including citations does not select APA review. Apply one output format, not every skill format at once. ')


def test_writing_routing_only_for_profiles_with_writing_skills():
    writing = load_skills(ROOT, profile(skills=['apa-review', 'review-feedback', 'discussion-draft', 'draft-rewrite']))
    assert WRITING in writing
    troubleshoot = load_skills(ROOT, profile(skills=['troubleshoot-session', 'troubleshoot-writeup'], default_skill='troubleshoot-session'))
    assert 'APA' not in troubleshoot and 'discussion-draft' not in troubleshoot
    assert "Choose a workflow by what its opening paragraph says it is for. Apply one output format" in troubleshoot
    assert '## Skill: troubleshoot-session' in troubleshoot and '### Case log' in troubleshoot


def test_it_troubleshoot_profile_loads_with_its_skills_and_prompt():
    import yaml
    data = yaml.safe_load((ROOT / 'profiles.yaml').read_text())['profiles']['it-troubleshoot']
    p = Profile.model_validate(data)
    assert p.default_skill == 'troubleshoot-session' and p.mcp_servers == ['rag', 'vault', 'web', 'code']
    assert p.mcp_default == ['rag', 'vault'] and p.chat_memory is False
    assert (ROOT / p.system_prompt_file).read_text().startswith('You are an IT troubleshooting assistant.')
    text = load_skills(ROOT, p)
    assert 'Troubleshooting/YYYY-MM-DD-<short-slug>.md' in text and 'one diagnostic step per turn' in text
