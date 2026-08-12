import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "aws_s3_finops_collector.py"
SPEC = importlib.util.spec_from_file_location("aws_s3_finops_collector", MODULE_PATH)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        collector.INPUT_DIR = Path(self.tempdir.name)
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.tempdir.cleanup()

    def write(self, name, payload):
        (collector.INPUT_DIR / name).write_text(json.dumps(payload), encoding="utf-8")

    def inventory_inputs(self):
        self.write("current-cntlp-aws-quarantine.json", {"Contents": [
            {"Key": "incoming/new.wav", "Size": 100, "LastModified": "2026-08-01T12:00:00Z", "StorageClass": "STANDARD"},
            {"Key": "incoming/old.wav", "Size": 200, "LastModified": "2026-06-01T12:00:00Z", "StorageClass": "STANDARD"},
        ]})
        self.write("versions-cntlp-aws-quarantine.json", {"Versions": [
            {"Key": "incoming/new.wav", "VersionId": "2", "IsLatest": True, "Size": 100, "LastModified": "2026-08-01T12:00:00Z", "StorageClass": "STANDARD"},
            {"Key": "incoming/new.wav", "VersionId": "1", "IsLatest": False, "Size": 90, "LastModified": "2026-07-01T12:00:00Z", "StorageClass": "STANDARD"},
        ], "DeleteMarkers": []})
        self.write("current-cntlp-aws-transcode.json", {"Contents": [
            {"Key": "track/result.mp3", "Size": 300, "LastModified": "2026-08-10T12:00:00Z", "StorageClass": "STANDARD"},
        ]})
        self.write("versions-cntlp-aws-transcode.json", {"Versions": [], "DeleteMarkers": [{"Key": "gone", "VersionId": "1", "IsLatest": True, "LastModified": "2026-08-01T12:00:00Z"}]})

    def policy_inputs(self):
        for bucket in collector.BUCKETS:
            self.write(f"versioning-{bucket}.json", {"Status": "Enabled"})
            self.write(f"lifecycle-{bucket}.json", {"Rules": [
                {
                    "ID": "rule", "Status": "Enabled",
                    "Transitions": [{"Days": 30, "StorageClass": "STANDARD_IA"}],
                    "Expiration": {"Days": 365},
                    "NoncurrentVersionExpiration": {"NoncurrentDays": 7},
                },
                {
                    "ID": "paused-rule", "Status": "Disabled",
                    "Transitions": [{"Days": 90, "StorageClass": "GLACIER_IR"}],
                },
            ]})
            self.write(f"encryption-{bucket}.json", {"ServerSideEncryptionConfiguration": {"Rules": [{}]}})
            self.write(f"public-access-{bucket}.json", {"PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            }})
            self.write(f"policy-status-{bucket}.json", {"PolicyStatus": {"IsPublic": False}})
            self.write(f"ownership-{bucket}.json", {"OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}})

    def test_inventory_and_whatif_metrics(self):
        self.inventory_inputs()
        body = collector.inventory_metrics(self.now)
        self.assertIn('cantaloupe_s3_actual_size_bytes{bucket_name="cntlp-aws-quarantine",storage_type="StandardStorage",version_state="current"} 300', body)
        self.assertIn('cantaloupe_s3_actual_size_bytes{bucket_name="cntlp-aws-quarantine",storage_type="StandardStorage",version_state="noncurrent"} 90', body)
        self.assertIn('cantaloupe_s3_actual_delete_marker_count{bucket_name="cntlp-aws-transcode"} 1', body)
        self.assertIn('cantaloupe_s3_inventory_expected_monthly_list_requests 480', body)
        self.assertIn('policy="enabled"', body)
        self.assertIn('horizon_days="120"', body)
        self.assertIn('horizon_days="180"', body)
        self.assertIn('cantaloupe_s3_whatif_cumulative_cost_usd', body)
        self.assertIn('cantaloupe_s3_whatif_cumulative_savings_usd', body)

    def test_policy_metrics(self):
        self.policy_inputs()
        body = collector.policy_metrics(self.now)
        self.assertIn('cantaloupe_s3_bucket_versioning_enabled{bucket_name="cntlp-aws-quarantine"} 1', body)
        self.assertIn('cantaloupe_s3_bucket_public_access_blocked{bucket_name="cntlp-aws-transcode"} 1', body)
        self.assertIn('cantaloupe_s3_bucket_lifecycle_rule_count{bucket_name="cntlp-aws-quarantine",status="enabled"} 1', body)
        self.assertIn('cantaloupe_s3_bucket_lifecycle_rule_count{bucket_name="cntlp-aws-quarantine",status="all"} 2', body)
        self.assertIn('cantaloupe_s3_bucket_lifecycle_rule_info{bucket_name="cntlp-aws-quarantine",rule_id="rule",scope="all-objects",status="Enabled"} 1', body)
        self.assertIn('cantaloupe_s3_bucket_lifecycle_transition_days{bucket_name="cntlp-aws-quarantine",days="30",rule_id="rule",scope="all-objects",status="Enabled",storage_type="StandardIAStorage"} 30', body)
        self.assertIn('cantaloupe_s3_bucket_current_expiration_days{bucket_name="cntlp-aws-quarantine",days="365",rule_id="rule",scope="all-objects",status="Enabled"} 365', body)
        self.assertIn('cantaloupe_s3_bucket_noncurrent_expiration_days{bucket_name="cntlp-aws-quarantine",days="7",rule_id="rule",scope="all-objects",status="Enabled"} 7', body)
        self.assertIn('cantaloupe_s3_bucket_lifecycle_transition_days{bucket_name="cntlp-aws-quarantine",days="90",rule_id="paused-rule",scope="all-objects",status="Disabled",storage_type="GlacierInstantRetrievalStorage"} 90', body)
        self.assertIn('cantaloupe_s3_policy_api_get_requests 12', body)


if __name__ == "__main__":
    unittest.main()
