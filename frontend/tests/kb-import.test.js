import test from 'node:test';
import assert from 'node:assert/strict';
import {kbImport} from '../src/client.js';

test('a leading H1 becomes the title and leaves the body', () => {
  const a = kbImport('# Intune rename fails\r\n\r\n## Symptoms\r\nRPC error\r\n', 'x.md');
  assert.equal(a.title, 'Intune rename fails');
  assert.equal(a.body, '## Symptoms\nRPC error');
  assert.deepEqual(a.tags, []);
});

test('front matter title and tags are used and removed', () => {
  const inline = kbImport('---\ntitle: "Dock monitor blank"\ntags: [macOS, DisplayLink, "#dock"]\n---\n# Other heading\nBody', 'f.md');
  assert.equal(inline.title, 'Dock monitor blank');
  assert.deepEqual(inline.tags, ['macos', 'displaylink', 'dock']);
  assert.equal(inline.body, 'Body');
  const listed = kbImport('---\ntags:\n  - intune\n  - rename\n---\nText only', 'rename-rpc_error.md');
  assert.deepEqual(listed.tags, ['intune', 'rename']);
  assert.equal(listed.title, 'rename rpc error');
});

test('a heading after other text stays in the body', () => {
  const a = kbImport('Intro line\n\n# Not a title\nMore', 'notes.md');
  assert.equal(a.title, 'notes');
  assert.ok(a.body.startsWith('Intro line'));
});
