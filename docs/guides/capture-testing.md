# Capture testing

Run `mise run check` from the repository root. For parser iteration, use
`node --test tests/parser-golden.test.mjs`. For pipeline or lifecycle changes,
run both browser checks:

- Chromium: `cd tests/e2e && npm ci && npx playwright install chromium && npm test`.
- Firefox: install the test dependencies pinned in `.github/workflows/e2e.yml`
  in a separate Python environment, run `python -m camoufox fetch`, then
  `python tests/e2e/firefox-jsonl-test.py` from the root with that interpreter.

The Firefox check uses a temporary profile, temporary archive, random local
ports and test credentials. It disables native-token bootstrap so a daemon
outage cannot fall back to the user's production daemon. All page requests are
intercepted locally. It checks background termination separately from closing
and reopening the whole browser. Do not point fixture replay at a live account
or the user's archive.

## Live verification

1. Let the user navigate normally. Capture only the responses already received.
   Do not automate repeated requests against X to exercise a test case.
2. Keep raw recordings, profiles, tokens and screenshots outside git. Record
   navigation, clicks and scrolling when authorized; do not record typed text.
3. Use discovery dumps to make sanitized fixtures, following
   `tests/fixtures/FIXTURES.md`. Inspect expected results against the source:
   regenerating a golden file with the parser under test does not prove coverage.
4. Compare normalized expected posts against **every** daily archive file:
   `node scripts/audit-archive.mjs /private/expected-posts.jsonl /path/to/archive`.
   The command is read-only and exits nonzero for missing posts or mismatched
   full-article blocks. A post absent from today's file may already exist in an
   older file. Counters are not proof of disk writes. The audit does not certify
   the parser's coverage, media downloads, or every field in an archived post.
5. Open an article's full body, not just its preview. Compare its raw blocks and
   media references with the saved full article. For video posts, inspect all
   supplied variants, including streaming playlists, not just the best MP4.
6. After changing the extension, reload it and verify the **running** manifest
   version and new archive rows. Copying files alone is not installation proof.
   Restarting the native daemon is separate from reloading the extension.

## Browser and installation gotchas

- Use Camoufox's own supported Python Playwright dependency. A newer Playwright
  MCP can send protocol methods that Camoufox does not implement. Keep the
  regular Firefox MCP and Camoufox driver configurations separate.
- Camoufox needs `allowAddonNewtab: true` to permit extension-created dashboard
  tabs. A driver-created blank tab is not proof that the dashboard loaded.
- Wait for fixture responses to finish before opening the status page. Use a
  separate status tab so navigating away cannot cancel the capture under test.
- Use fresh test profiles for reproducibility. Keep a user's login profile
  intact; save open URLs before any authorized restart.
- A temporary unsigned Firefox add-on lasts only until the browser closes.
  Regular Firefox needs Mozilla signing for a permanent install. A separately
  published fork needs its own add-on ID and the native host's matching allowed
  extension ID. Do not assume an upstream ID can be published by the fork owner.
- Verify the deployment checkout's branch and commit after merging. Verify the
  daemon's reported version too; an updated branch ref does not prove a running
  process or a detached checkout has changed.

## Linux file picker failures

A selection timeout can happen before Firefox reads the extension or upload.
Check `journalctl --user -u xdg-desktop-portal -u xdg-document-portal` for
`Failed to register file` errors before blaming the XPI. Check that the document
portal actually responds, not just that systemd calls it active:

```sh
timeout 5 busctl --user call org.freedesktop.portal.Documents \
  /org/freedesktop/portal/documents org.freedesktop.DBus.Peer Ping
```

A timeout indicates a portal problem. Restarting the user document and desktop
portal services can restore file selection without restarting Firefox, but
interrupts pending file dialogs. Verify the service responds and retry a file
selection before declaring it fixed. This is separate from extension signing.
