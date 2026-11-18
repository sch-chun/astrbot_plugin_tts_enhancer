# Known Limitations and Upstream Responsibility

This file records behaviors that, after review, have been classified as "design trade-offs / upstream guarantees / unreachable" and are no longer actively fixed by this plugin (or require only minimal hardening).

The corresponding tests were originally pinned with `@pytest.mark.xfail(strict=True)`; after a second review they were handled by category as follows:

- **Design trade-offs**: converted to ordinary green tests asserting the "accepted actual behavior" (with the `should_not` bug implication removed from the name),
  locking the current contract, avoiding xfail's continuously misleading "this is a bug" signal, and avoiding `strict=True` breaking CI spuriously during normal refactoring.
- **Upstream guarantees / unreachable paths**: still **kept as green-test guards**, locking the current behavior and retaining the regression sentinel.
  "Not fixing the code" does not mean "deleting the tests" — all three cases successfully construct real inputs and test this repository's code
  (`src/config.py` / `src/tts_service.py`); deleting them would lose awareness of future behavior changes.
  Only #14 received one extra line of code hardening because the "unreachable" argument might become invalid after a `sub_agent` refactor (see below).

## Kept as Green-Test Guards (Upstream Guarantees / Unreachable, No Code Fix)

### Bug #6 — Missing Validation When providers Is Misconfigured as a dict (Upstream Guarantee)

- Symptom: when `providers` is a non-empty dict, it triggers
  `AttributeError: 'str' object has no attribute 'get'` (lack of structural validation when the config structure is misconfigured).
- Verdict: `_conf_schema.json` already requires `providers` to be an array, and saving via the WebUI is rejected by AstrBot's
  `validate_config()`; it can only be triggered by manually editing `data/config/<plugin>_config.json` to bypass the guardrail,
  which is the user's responsibility and not a mandatory fix for this repository.
- Guard: `tests/test_config.py::TestAcceptedBehavior::test_providers_as_dict_raises_attribute_error`
  locks in the current behavior "misconfiguration as a dict triggers `AttributeError`"; if structural validation is added later, it will fail to signal the behavior change.

### Bug #15 — bool Passes the context_window Type Check (Upstream Guarantee)

- Symptom: `isinstance(x, int)` silently passes for `True` (`bool` is a subclass of `int`).
- Verdict: this input comes from config and the schema declares `int`, so it falls within AstrBot's validation scope;
  the `validate_params` on the LLM output path is not covered upstream and should exclude `bool` itself (cf. P3-3a). The config side is upstream's responsibility; no code fix.
- Guard: `tests/test_tts_service.py::TestAcceptedBehavior::test_bool_context_window_silently_accepted`
  locks in the current behavior where "`context_window: True` is treated as a valid window and returns history rather than empty".

## Design Trade-offs Converted to Green Tests (Accepted Behavior)

- **Bug #1** (empty / whitespace-only `<tts>` tags return an empty list): an empty tag has no content to speak, so silently removing the whole segment is acceptable.
- **Bug #3** (nested `<tts>` tags are not recursively expanded, inner tags remain): nesting is undefined input,
  so a non-recursive parser producing undefined output is acceptable.
- **Bug #5** (fixed): `_load_providers` once wrote `__resolved_name` in-place into the caller's `raw_config`;
  P2⑥ (1.0.0) changed it to deep-copy the original config and write internal private fields only to the copied entries, so the caller's config is no longer polluted.
