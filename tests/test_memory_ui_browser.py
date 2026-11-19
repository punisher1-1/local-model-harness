import json
import os
import pytest
from pathlib import Path
pytestmark = pytest.mark.skipif(os.getenv("HARNESS_BROWSER_TESTS") != "1", reason="Opt-in Chromium UI test")
sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
root=Path(__file__).resolve().parents[1] / 'memory_ui'
def test_browser_save_retry_search_delete():
 rows=[]; saves=[]; fail_save=True
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=os.getenv('HARNESS_CHROMIUM_PATH') or None,headless=True)
  page=browser.new_page(); errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
  def route(r):
   nonlocal fail_save
   path=r.request.url.split('http://harness.test')[1]
   if path.startswith('/memory'):
    name={'/memory':'index.html','/memory/app.js':'app.js','/memory/style.css':'style.css'}[path]
    r.fulfill(body=(root/name).read_text(),content_type={'html':'text/html','js':'text/javascript','css':'text/css'}[name.split('.')[-1]]); return
   assert r.request.headers['authorization']=='Bearer test-credential'
   result={}; status=200
   if path=='/v1/identity':result={'actor_id':'lab-service','kind':'service_key','memory_permissions':['memory.read','memory.write','memory.delete'],'memory_scopes':['home','legacy','work']}
   elif path.endswith('/health'):result={'namespace':'demo','scope':'shared_service','recall_profiles':['local-assistant'],'memory_scope':r.request.headers.get('x-harness-memory-scope')}
   elif path=='/v1/memories' and r.request.method=='POST':
    body=r.request.post_data_json;saves.append(body)
    if not rows:rows.append({**body,'memory_id':'00000000-0000-4000-8000-000000000001','created_at':'2026-09-16T12:00:00Z'})
    if fail_save:fail_save=False;r.abort();return
    result=rows[0]
   elif r.request.method=='DELETE':rows.clear();status=204
   else:result={'data':rows if r.request.headers.get('x-harness-memory-scope')=='legacy' else [],'next_cursor':None}
   r.fulfill(status=status,body='' if status==204 else json.dumps(result),content_type='application/json')
  page.route('**/*',route);page.goto('http://harness.test/memory')
  page.locator('#credential').fill('test-credential');page.locator('#connect button').click();page.locator('#workspace').wait_for(state='visible')
  page.locator('#content').fill('<img src=x onerror=alert(1)> Synthetic memory')
  page.locator('#save-button').click();page.wait_for_function("document.getElementById('status').className === 'error'")
  page.locator('#save-button').click();page.locator('article').wait_for()
  assert len(saves)==2 and saves[0]['idempotency_key']==saves[1]['idempotency_key']
  assert page.locator('article img').count()==0
  assert '<img' in page.locator('.memory-text').inner_text()
  page.locator('#memory-scope').select_option('home');page.wait_for_function("document.querySelectorAll('article').length===0")
  page.wait_for_function("document.getElementById('status').textContent.includes('Active memory scope: home')")
  page.locator('#memory-scope').select_option('legacy');page.locator('article').wait_for()
  page.locator('#query').fill('Synthetic');page.locator('#search button').click()
  page.on('dialog',lambda d:d.accept());page.locator('.delete').click();page.wait_for_function("document.querySelectorAll('article').length===0")
  page.locator('#disconnect').click();assert page.locator('#workspace').is_hidden()
  assert page.evaluate('localStorage.length')==0 and not errors, errors
  browser.close()
