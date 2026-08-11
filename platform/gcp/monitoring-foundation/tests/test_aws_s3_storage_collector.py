import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "aws_s3_storage_collector.py"
SPEC = importlib.util.spec_from_file_location("aws_s3_storage_collector", MODULE_PATH)
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)


class AwsS3StorageCollectorTest(unittest.TestCase):
    def test_summarize_counts_current_objects_and_bytes_by_storage_class(self):
        payload = {
            "Contents": [
                {"Key": "incoming/one.wav", "Size": 10, "StorageClass": "STANDARD"},
                {"Key": "incoming/two.wav", "Size": 20, "StorageClass": "STANDARD_IA"},
                {"Key": "incoming/three.wav", "Size": 30, "StorageClass": "GLACIER_IR"},
            ]
        }

        count, sizes = COLLECTOR.summarize(payload)

        self.assertEqual(count, 3)
        self.assertEqual(sizes["StandardStorage"], 10)
        self.assertEqual(sizes["StandardIAStorage"], 20)
        self.assertEqual(sizes["GlacierInstantRetrievalStorage"], 30)

    def test_empty_bucket_still_exports_zero_for_expected_storage_types(self):
        count, sizes = COLLECTOR.summarize({})

        self.assertEqual(count, 0)
        self.assertEqual(
            sizes,
            {
                "StandardStorage": 0,
                "StandardIAStorage": 0,
                "GlacierInstantRetrievalStorage": 0,
            },
        )

    def test_metrics_use_distinct_names_during_cloudwatch_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory)
            (input_dir / "bucket.json").write_text(
                json.dumps({"Contents": [{"Size": 42, "StorageClass": "STANDARD"}]}),
                encoding="utf-8",
            )
            metrics = COLLECTOR.storage_metrics(
                targets=(
                    {
                        "bucket": "cntlp-aws-quarantine",
                        "prefix": "incoming/",
                        "file": "bucket.json",
                    },
                ),
                input_dir=input_dir,
                timestamp=1234567890,
            )

        self.assertIn("cantaloupe:aws_s3_current_object_bytes", metrics)
        self.assertIn("cantaloupe:aws_s3_current_objects", metrics)
        self.assertNotIn("cantaloupe:aws_s3_bucket_size_bytes", metrics)
        self.assertIn('bucket_name="cntlp-aws-quarantine"', metrics)
        self.assertIn('storage_type="StandardStorage"', metrics)
        self.assertIn(" 42", metrics)
        self.assertIn(" 1234567890", metrics)


if __name__ == "__main__":
    unittest.main()
