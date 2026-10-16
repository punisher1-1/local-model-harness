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
