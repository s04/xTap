import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { auditArchive } from '../scripts/audit-archive.mjs';

test('checks older daily archives and requires the complete article body', () => {
  const dir = mkdtempSync(join(tmpdir(), 'xtap-audit-'));
  try {
    const full = { id: 'article', is_article: true, article: { blocks: [{text:'full body'}] } };
    writeFileSync(join(dir, 'tweets-2000-01-01.jsonl'), JSON.stringify({id:'old'})+'\n'+JSON.stringify(full)+'\n');
    writeFileSync(join(dir, 'tweets-2000-01-02.jsonl'), JSON.stringify({id:'article',is_article_preview:true})+'\n');
    assert.deepEqual(auditArchive([{id:'old'},full],dir), {expected:2,archivedIds:2,missing:[],incompleteArticles:[]});
    assert.deepEqual(auditArchive([{id:'absent'}, {...full,article:{blocks:[{text:'different body'}]}}],dir),
      {expected:2,archivedIds:2,missing:['absent'],incompleteArticles:['article']});
  } finally { rmSync(dir, {recursive:true,force:true}); }
});
