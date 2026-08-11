import datetime as dt
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[4]


def load_collector():
    lines = (ROOT / "apps/audio/loadtest/collector-configmap.yaml").read_text(
        encoding="utf-8"
    ).splitlines()
    start = lines.index("  collector.py: |") + 1
    source = []
    for line in lines[start:]:
        if line.startswith("    "):
            source.append(line[4:])
        elif not line:
            source.append("")
        else:
            break
    namespace = {"__name__": "collector_test"}
    exec(compile("\n".join(source), "collector.py", "exec"), namespace)
    return namespace


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.collector = load_collector()
        self.result = {
            "run_id": "pilot-10",
            "profile": "pilot-10",
            "phase": "pilot",
            "started_at": "2026-08-11T14:00:00+00:00",
            "finished_at": "2026-08-11T14:02:00+00:00",
            "requested": 10,
            "submitted": 10,
            "upload_errors": 0,
            "status_counts": {"READY": 10},
        }

    def test_valid_run_separates_functional_success_and_metric_completeness(self):
        metrics = {
            "processing_p95_seconds": 3.5,
            "transcode_completed": 10,
            "transcode_failed": 0,
            "transcode_retried": 0,
            "queue_visible_max": 4,
            "queue_inflight_max": 2,
            "queue_drained": 1,
            "queue_activity_missing": 0,
            "counter_mismatch": 0,
            "deployment_changed": 0,
            "job_failed": 0,
        }

        samples = self.collector["result_samples"](self.result, metrics)

        self.assertEqual(samples["cantaloupe_audio_finops_run_functional_success"], 1)
        self.assertEqual(samples["cantaloupe_audio_finops_run_metrics_complete"], 1)
        self.assertEqual(samples["cantaloupe_audio_finops_run_info"], 1)

    def test_missing_short_queue_spike_is_incomplete_only_when_burst_scaled(self):
        metrics = {
            "processing_p95_seconds": 3.5,
            "transcode_completed": 10,
            "transcode_failed": 0,
            "transcode_retried": 0,
            "queue_visible_max": 0,
            "queue_inflight_max": 0,
            "queue_drained": 1,
            "queue_activity_missing": 1,
            "counter_mismatch": 0,
            "deployment_changed": 0,
            "job_failed": 0,
            "burst_replicas_max": 1,
        }

        samples = self.collector["result_samples"](self.result, metrics)
        self.assertEqual(samples["cantaloupe_audio_finops_run_functional_success"], 1)
        self.assertEqual(samples["cantaloupe_audio_finops_run_queue_measurement_complete"], 0)
        self.assertEqual(samples["cantaloupe_audio_finops_run_metrics_complete"], 0)
        self.assertEqual(samples["cantaloupe_audio_finops_run_info"], 0)

        metrics["burst_replicas_max"] = 0
        samples = self.collector["result_samples"](self.result, metrics)
        self.assertEqual(samples["cantaloupe_audio_finops_run_queue_measurement_complete"], 1)
        self.assertEqual(samples["cantaloupe_audio_finops_run_info"], 1)

    def test_collect_ignores_burst_replica_generation_and_rounds_counters(self):
        queries = []

        start_timestamp = dt.datetime.fromisoformat(self.result["started_at"]).timestamp()

        def prom(query, when):
            queries.append(query)
            if "kube_deployment_status_observed_generation" in query:
                return 7
            if "audio_transcode_completed_total" in query:
                return 1 if when == start_timestamp else 11
            if "audio_transcode_failed_total" in query:
                return 0
            if "audio_transcode_retried_total" in query:
                return 0
            return 1

        def prom_range(query, *_):
            if "messages_visible" in query:
                return [(100.0, 0.0), (160.0, 5.0), (220.0, 0.0)]
            return [(100.0, 0.0), (160.0, 2.0), (220.0, 0.0)]

        self.collector["prom"] = prom
        self.collector["prom_range"] = prom_range

        metrics = self.collector["collect"](self.result)

        generation_queries = [
            query for query in queries if "kube_deployment_status_observed_generation" in query
        ]
        self.assertTrue(generation_queries)
        self.assertTrue(all("audio-transcode-burst" not in query for query in generation_queries))
        self.assertIn('sum(audio_transcode_completed_total{namespace="apps"})', queries)
        self.assertEqual(metrics["deployment_changed"], 0)
        self.assertEqual(metrics["transcode_completed"], 10)
        self.assertEqual(metrics["counter_mismatch"], 0)
        self.assertEqual(metrics["queue_visible_max"], 5)
        self.assertEqual(metrics["queue_inflight_max"], 2)
        self.assertEqual(metrics["queue_backlog_max"], 7)
        self.assertEqual(metrics["queue_drained"], 1)

    def test_failed_job_without_result_log_gets_synthetic_result(self):
        job = {
            "metadata": {"name": "failed-run"},
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "env": [
                                    {"name": "LOAD_COUNT", "value": "10"},
                                    {"name": "LOAD_PROFILE", "value": "pilot-10"},
                                    {"name": "EXPERIMENT_PHASE", "value": "pilot"},
                                ]
                            }
                        ]
                    }
                }
            },
            "status": {
                "startTime": "2026-08-11T14:00:00Z",
                "conditions": [
                    {"type": "Failed", "lastTransitionTime": "2026-08-11T14:01:00Z"}
                ],
            },
        }

        result = self.collector["failed_job_result"](
            job, dt.datetime(2026, 8, 11, 14, 2, tzinfo=dt.timezone.utc)
        )

        self.assertEqual(result["run_id"], "failed-run")
        self.assertEqual(result["requested"], 10)
        self.assertEqual(result["submitted"], 0)
        self.assertEqual(result["status_counts"], {"JOB_FAILED": 10})

    def test_collection_waits_for_cloudwatch_delay(self):
        early = dt.datetime(2026, 8, 11, 14, 6, 59, tzinfo=dt.timezone.utc)
        due = dt.datetime(2026, 8, 11, 14, 7, tzinfo=dt.timezone.utc)

        self.assertFalse(self.collector["is_due"](self.result, early))
        self.assertTrue(self.collector["is_due"](self.result, due))


if __name__ == "__main__":
    unittest.main()
