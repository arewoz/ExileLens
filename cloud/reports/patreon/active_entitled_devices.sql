-- ANONYMOUS count of linked devices (installations, not users or people) that currently hold an unexpired
-- lease AND whose link is entitled to seamless_updates. Counts only: no device, link or user identifiers
-- are selected. devices_with_valid_lease also includes linked devices that are not entitled.
SELECT
  COALESCE(SUM(
    CASE WHEN EXISTS (SELECT 1 FROM json_each(l.last_capabilities) c WHERE c.value = 'seamless_updates') THEN 1 ELSE 0 END
  ), 0) AS active_entitled_devices,
  COUNT(*) AS devices_with_valid_lease
FROM devices d
JOIN patreon_links l ON l.link_id = d.link_id
WHERE d.last_lease_expires_at > CAST(strftime('%s', 'now') AS INTEGER);
