"""Policy replay: re-run the item verdict policy on stored, already-measured PoB values.

A replay fixture is DATA ONLY (see ``fixtures/*.json``). ``replay.replay`` feeds it through the
production ``ranking.enrich_slot_comparison`` (metric profile -> score -> resistance analysis ->
guardrails -> item impact -> verdict), so the policy is never re-implemented here and no PoB
runtime is needed. ``capture.capture_fixture`` builds a fixture from a real ``evaluate_item`` row.
"""
