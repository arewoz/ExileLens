-- ANONYMOUS entitlement-lease refresh outcomes per UTC day, last 30 days (PATREON_DB; counts of
-- refresh requests, not users or people). Source: entitlement_refresh_daily (day / outcome / count only).
-- ok and not_eligible both issued a lease (not_eligible = a lease without capabilities).
SELECT
  day,
  SUM(CASE WHEN outcome = 'ok' THEN count ELSE 0 END) AS ok,
  SUM(CASE WHEN outcome = 'not_eligible' THEN count ELSE 0 END) AS not_eligible,
  SUM(CASE WHEN outcome = 'patreon_unavailable' THEN count ELSE 0 END) AS patreon_unavailable,
  SUM(CASE WHEN outcome = 'reauthorize_required' THEN count ELSE 0 END) AS reauthorize_required,
  SUM(CASE WHEN outcome = 'device_unknown' THEN count ELSE 0 END) AS device_unknown,
  SUM(CASE WHEN outcome = 'rate_limited' THEN count ELSE 0 END) AS rate_limited,
  SUM(CASE WHEN outcome = 'issuance_disabled' THEN count ELSE 0 END) AS issuance_disabled
FROM entitlement_refresh_daily
WHERE day >= date('now', '-30 day')
GROUP BY day
ORDER BY day DESC;
