# Synthetic market fixtures

Everything here is **invented**: league names, listing ids, seller names, prices and rate-limit numbers. No file is a capture of a real
response, real player or real listing, and none may be replaced by one. They exist so the market estimator, trust model, transport
seam and rate policy are tested completely offline. See `docs/R5-MARKET-INTELLIGENCE-PLAN.md`; live trade2 is production-disabled.

- `listing_sets.json`: compact listing scenarios for the confidence cases (strong, moderate, sparse, volatile, unusable, concentrated,
  outliers, partial FX, stale, cheap-seller skew, deep result set).
- `leagues.json`, `search_ok.json`, `fetch_ok.json`, `exchange_ok.json`: minimal well-formed responses.
- `errors.json`: failure outcomes (400, 401, 403, 429 + Retry-After, 5xx, malformed JSON, missing fields, empty search).
- `rate_headers.json`: synthetic `X-Rate-Limit-*` header sets.
