# OpenSearch Dashboards saved objects

`security-logs-dashboard.ps1` creates or updates the saved objects for
`Security Logs Overview v1` through the OpenSearch Dashboards API.

`platform-logging-operations-dashboard.ps1` creates or updates
`Platform Logging Operations v2`. Its layout follows the investigation flow:
current health, incident location, cluster changes, then logging platform
health. Kubernetes API events come from the single-replica Fluent Bit event
collector. `ingest_bytes` is an approximate source-message size and must not be
reported as the physical OpenSearch index store size.

The dashboard intentionally contains log-derived security events only:

- Keycloak authentication and logout events
- OAuth2 Proxy authentication success, rejection, and callback errors
- explicit Kyverno policy violations (failed, denied, blocked, or errored decisions)
- authentication failure reasons and repeated failures by client and masked network
- raw security-event evidence for investigation

Pod health, availability, certificate state, and controller health remain in
Grafana. Fluent Bit delivery and OpenSearch ingestion remain in
`Platform Logging Operations v2`.

Run from PowerShell on a Tailscale-connected workstation:

```powershell
.\security-logs-dashboard.ps1
```

Both scripts use stable saved-object IDs and overwrite only their own IDs. They
do not change the audio application dashboard.
