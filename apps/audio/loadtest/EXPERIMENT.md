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
