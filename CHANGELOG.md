# Changelog

## Unreleased

- Honor explicit client timeouts in synchronous and asynchronous requests while
  preserving operation defaults when timeout is omitted or None.
- Preserve the idempotency key on exhausted network errors for uncertain outcomes.
- Parse JSON content before applying string-path heuristics; treat PathLike as
  an explicit file path and report malformed JSON as SpavikDataError.
- Reject ambiguous CSV headers, surplus fields and invalid quoting with line
  numbers instead of silently dropping values.
- Require Python 3.11 or later. Lock development dependencies and audit them in CI.
