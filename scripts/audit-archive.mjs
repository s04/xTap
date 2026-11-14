// Read-only coverage check. Never sends requests or writes to the archive.
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

export function auditArchive(expected, directory) {
  const saved = new Map();
  for (const file of readdirSync(directory).filter(name => /^tweets-.*\.jsonl$/.test(name))) {
    for (const line of readFileSync(join(directory, file), 'utf8').split('\n').filter(Boolean)) {
      const post = JSON.parse(line);
      const prior = saved.get(post.id);
      // A preview must never replace an already archived full article.
      if (!prior?.is_article || post.is_article) saved.set(post.id, post);
    }
  }
  const missing = [], incompleteArticles = [];
  for (const post of expected) {
    const actual = saved.get(post.id);
    if (!actual) missing.push(post.id);
    else if (post.is_article && (!actual.is_article ||
      JSON.stringify(actual.article?.blocks) !== JSON.stringify(post.article?.blocks))) {
      incompleteArticles.push(post.id);
    }
  }
  return { expected: expected.length, archivedIds: saved.size,
    missing: [...new Set(missing)], incompleteArticles: [...new Set(incompleteArticles)] };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [expectedFile, directory] = process.argv.slice(2);
  if (!expectedFile || !directory) {
    console.error('Usage: node scripts/audit-archive.mjs <expected-posts.jsonl> <archive-directory>');
    process.exitCode = 2;
  } else {
    const expected = readFileSync(expectedFile, 'utf8').split('\n').filter(Boolean).map(JSON.parse);
    const result = auditArchive(expected, directory);
    console.log(JSON.stringify(result, null, 2));
    process.exitCode = result.missing.length || result.incompleteArticles.length ? 1 : 0;
  }
}
