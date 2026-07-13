# Task 6 Review-Fix Report: SellerSprite Reverse-Keyword UI

## Scope

Resolved only the Task 6 review findings for bounded-result status accuracy,
empty successful exports, and static-contract coverage.

## RED evidence

After adding the missing review assertions, the focused static test run failed
as expected because the UI had neither a bounded-row helper nor the bilingual
`showing` status:

```text
2 failed, 3 passed
```

## Changes

- Successful responses now derive the displayed rows exclusively from
  `data.keyword_rows`, bounded to 20.
- A successful response with no displayable bounded rows uses the dedicated
  no-rows outcome, including zero and absent rows.
- When the server's total count exceeds the bounded display count, the status
  clearly says `Showing {shown} of {total}` (with a Chinese equivalent).
- The normal success message reports the actual displayed count.
- Static tests now assert the `keyword_rows` contract, zero and bounded-result
  outcome branches, loading/button restore/request-failure handling, and
  escaping at every rendered row field (keyword, all metrics, and trend).

## GREEN evidence

Source-mounted isolated Docker validation:

```text
tests/test_webui_sellersprite_static.py
tests/test_webui_keyword_chat_static.py
tests/test_agent_server.py
32 passed in 7.28s
```

`git diff --check` is clean.
