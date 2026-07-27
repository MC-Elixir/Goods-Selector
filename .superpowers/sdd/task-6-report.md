# Task 6 Report: SellerSprite reverse-keyword WebUI

## Status

Implemented a dedicated, bounded SellerSprite reverse-keyword export card in
the Settings view. The existing generic Browser Assistant remains unchanged,
including its separate raw diagnostic output for the 1688 workflow.

## RED evidence

Before the UI implementation, the new static test failed as expected:

```text
3 failed in 0.03s
```

The failures showed the missing dedicated form, result renderer, bounded row
rendering, and translated human-action status keys.

## Implementation

- Added `#sellerSpriteReverseKeywordForm`, `#sellerSpriteReverseKeywordStatus`,
  and `#sellerSpriteReverseKeywordResults` for one Amazon US ASIN.
- The form POSTs only `{ asin }` to the Task 5 API endpoint, disables its
  submit button while running, and uses a generic translated request failure
  message instead of exposing exception content.
- Results render at most 20 escaped rows with keyword, search volume (or
  lower bound), purchase rate (or lower bound), competing products (or lower
  bound), and trend. Missing values are shown as `-`; raw payloads, source
  paths, cookies, manifests, and JSON diagnostics are never rendered.
- Added explicit translated outcome messages for human action, login,
  captcha, permission, disabled/unavailable browser automation, cancellation,
  and other failures. Existing rows are re-rendered after a language toggle.
- Added card/table styling with horizontal overflow for narrow screens.

## GREEN evidence

Focused source-mounted Docker run:

```bash
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -e LOG_DIR=/app/data/logs \
  -v "$PWD:/app:ro" -v "$TEST_DATA:/app/data" -w /app \
  --entrypoint pytest amazon-selector:dev \
  tests/test_webui_sellersprite_static.py \
  tests/test_webui_keyword_chat_static.py tests/test_agent_server.py \
  -q -s -p no:cacheprovider
```

Result: `30 passed in 7.32s`.

`git diff --check` is clean.

## Files changed

- `webui/index.html`
- `webui/app.js`
- `webui/styles.css`
- `tests/test_webui_sellersprite_static.py`

## Self-review

- Confirmed the card is Amazon-US-only and has no mock data or mock control.
- Confirmed all user-visible card text has English and Chinese translations.
- Confirmed result values are escaped at rendering time and numeric values are
  accepted only when finite numbers.
- Confirmed no SellerSprite-specific raw JSON rendering or untrusted exception
  text was added; the generic Browser Assistant diagnostic is preserved.
- Confirmed the shared SDD ledger and reports for prior tasks were not staged.
