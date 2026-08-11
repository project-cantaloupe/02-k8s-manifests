# OpenSearch Dashboards saved objects

`security-logs-dashboard.ps1` creates or updates the saved objects for
`Security Logs Overview v1` through the OpenSearch Dashboards API.

The dashboard intentionally contains log-derived security events only:

- Keycloak authentication and logout events
- OAuth2 Proxy authentication success, rejection, and callback errors
- Kyverno policy processing activity (not presented as a violation count)
- raw security-event evidence for investigation

Pod health, availability, certificate state, and controller health remain in
Grafana. Fluent Bit delivery and OpenSearch ingestion remain in
`Platform Logging Operations v2`.

Run from PowerShell on a Tailscale-connected workstation:

```powershell
.\security-logs-dashboard.ps1
```

The script uses stable saved-object IDs and overwrites only those IDs. It does
not change `Platform Logging Operations v2` or the audio application dashboard.
