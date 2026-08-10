# Audio Application Logs / FinOps

This directory holds an importable OpenSearch Dashboards saved-object export for
the structured Audio application logs. It is deliberately not applied by
Argo CD: Dashboards saved objects are application data, not Kubernetes
workloads.

After \`cantaloupe-app-logs-v1\` contains records, import
\`audio-processing-finops-preview.ndjson\` in **Stack Management → Saved
Objects → Import**. The dashboard is intentionally separate from **Platform
Logging Operations v2** and can be deleted without affecting that dashboard.

The dashboard expects these fields:

- \`event_type\`, \`status\`, \`request_id\`, \`job_id\`, \`audio_id\`, \`attempt\`, \`retry_count\`
- \`audio_duration_ms\`, \`processing_duration_ms\`, \`input_bytes\`, \`output_bytes\`
- \`error_code\`, \`retryable\`, \`http_status\`, \`http_method\`, \`http_route\`, \`upstream_service\`

No S3 object keys, presigned URLs, request bodies, or user subjects are
included in the indexed document.
