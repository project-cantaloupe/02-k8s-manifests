# Audio FinOps controlled right-sizing experiment

## Purpose

This experiment starts with a documented conservative capacity assumption for a
new FFmpeg workload, observes it under repeatable traffic, and validates a
right-sized candidate against the same workload. It does not represent the
baseline as a historical production setting.

## Baseline

- Target Deployments: `audio-transcode`, `audio-transcode-burst`
- CPU request: `250m`
- Memory request: `256Mi`
- Memory limit: `512Mi`
- Rationale: stable initial sizing before representative load history exists
- Baseline collection dates: 2026-08-11 through 2026-08-12 (KST)

The pre-experiment `100m/192Mi` setting was used while the automation and smoke
path were being prepared. It is not used as the controlled experiment baseline.

## Controlled workload

The `steady`, `unexpected-burst`, and `scheduled-peak` profiles use the same
deterministic WAV fixture set for baseline and candidate runs. The result
collector persists each run with its `run_id`, `profile`, and `phase`.

All profiles use the same production path as Audio uploads: the Runner obtains
a short-lived `audio-finops` Client-Credentials token, calls the internal Audio
API, uploads the returned presigned URL to S3, and then follows the shared
SQS/Worker/artifact/READY path. Public Web accounts remain disabled; no test-only
API, Queue, or development Subject header is used.

The KEDA cron prewarm is disabled while every load CronJob is suspended. Burst
capacity is activated only by real transcode Queue backlog until scheduled-peak
is deliberately resumed.

KEDA may create up to six `audio-transcode-burst` Pods and the two
`aws-audio-burst-*` Karpenter NodePools may create one `t3.small` Node each.
These values are capacity ceilings, not permanently running capacity. With six simultaneous
Burst Pods, the `250m/256Mi` baseline is expected to require two Nodes after
DaemonSet overhead, while a validated candidate that fits all six Pods on one
Node is expected to require one. Both runs must start with zero Burst replicas
and zero Karpenter Nodes and must use the same queue workload.

The `steady`, `scheduled-peak`, and `unexpected-burst` profiles create private
audio records. They are intentionally absent from the public `/discover` page.
Only the one-item `web-validation` profile uses `AUDIO_VISIBILITY=public` and is
expected to appear in the Web UI.

## Result validity

The Collector waits five minutes after each Run so delayed CloudWatch SQS
samples can arrive, then retries collection every ten minutes during the
experiment window. A manually cloned Job must retain the top-level
`experiment=audio-finops` label; the rendered CronJob templates include it.

- `run_functional_success=1` means every requested audio was submitted and READY.
- `run_metrics_complete=1` means Worker counters, processing P95, Queue and drain
  evidence were all present and internally consistent.
- `run_info=1` requires both conditions, no real API/Base Worker rollout, and no
  terminal Job failure.

KEDA replica changes are expected experiment behavior and do not invalidate a
Run. If KEDA scales the Burst Worker but CloudWatch misses a sub-minute Queue
spike, functional success remains visible while Queue measurement completeness
is zero. Such a Run is useful as a smoke test but not as a formal FinOps sample.

## Candidate decision

The candidate is not predetermined. After valid baseline runs, choose it from:

- CPU and memory P95 and maximum usage;
- VPA target and upper-bound recommendations;
- completion and failure rates;
- processing P95;
- queue drain time, Pod restarts, and OOM events.

VPA remains recommendation-only (`updateMode: Off`). Keep the memory limit as a
safety boundary and do not introduce a CPU limit that would prevent FFmpeg from
bursting.

The prepared candidate Overlay is
`overlays/audio/right-sized-candidate`. Keep the Argo CD source path at
`apps/audio` for the baseline run, then change it to that Overlay in a reviewed
Git commit for the candidate run. Do not mutate resources directly in the live
cluster.

## Acceptance gates

- completion rate remains at least 99 percent;
- failure rate does not materially increase;
- processing P95 does not regress by more than 10 percent;
- no OOM or abnormal restart occurs;
- the queue drains after the run;
- allocated worker cost per READY track decreases.

Request reduction is allocation efficiency, not automatically an equal AWS bill
reduction. Any infrastructure bill claim must also use observed Karpenter node
runtime.

The expected two-to-one Node result is a scheduling hypothesis, not proof. Use
the observed Node count, Node-minutes, queue drain, processing P95, restarts,
OOM events, and READY tracks from each controlled run as the acceptance evidence.
