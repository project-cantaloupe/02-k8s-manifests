# Audio Processing / FinOps Preview

This directory holds an importable OpenSearch Dashboards saved-object export for
the structured Audio application log test. It is deliberately not applied by
Argo CD: Dashboards saved objects are application data, not Kubernetes
workloads.

After the test branch has produced \`cantaloupe-app-logs-v1\` records, import
\`audio-processing-finops-preview.ndjson\` in **Stack Management → Saved
Objects → Import**. The dashboard is intentionally separate from **Platform
Logging Operations v2** and can be deleted without affecting that dashboard.

The dashboard expects these fields:

- \`event_type\`, \`status\`, \`job_id\`, \`audio_id\`, \`attempt\`, \`retry_count\`
- \`audio_duration_ms\`, \`processing_duration_ms\`, \`input_bytes\`, \`output_bytes\`
- \`error_code\`, \`retryable\`, \`http_status\`, \`http_route\`

No S3 object keys, presigned URLs, request bodies, or user subjects are
included in the indexed document.
