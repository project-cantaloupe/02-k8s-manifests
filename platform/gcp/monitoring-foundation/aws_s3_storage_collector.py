#!/usr/bin/env python3
"""Export current S3 object count and bytes to Prometheus Pushgateway.

ListObjectsV2 returns current object versions only. These metrics intentionally
exclude noncurrent versions, delete markers, and incomplete multipart uploads;
CloudWatch daily storage metrics used to include those billable storage items.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


INPUT_DIR = Path(os.environ.get("AWS_S3_COLLECTOR_INPUT_DIR", "/work"))
PUSHGATEWAY = os.environ.get(
    "PUSHGATEWAY_URL", "http://cantaloupe-finops-pushgateway.monitoring.svc:9091"
).rstrip("/")
SOURCE = "s3-list-objects-v2"

TARGETS = (
    {
        "bucket": os.environ.get("QUARANTINE_BUCKET", "cntlp-aws-quarantine"),
        "prefix": os.environ.get("QUARANTINE_PREFIX", "incoming/"),
        "file": "quarantine.json",
    },
    {
        "bucket": os.environ.get("TRANSCODE_BUCKET", "cntlp-aws-transcode"),
        "prefix": os.environ.get("TRANSCODE_PREFIX", "audios/"),
        "file": "transcode.json",
    },
)

# Keep CloudWatch-compatible storage_type values so the two sources can be
# compared during the transition without re-labeling either dataset.
STORAGE_TYPES = {
    "STANDARD": "StandardStorage",
    "STANDARD_IA": "StandardIAStorage",
    "GLACIER_IR": "GlacierInstantRetrievalStorage",
    "ONEZONE_IA": "OneZoneIAStorage",
    "INTELLIGENT_TIERING": "IntelligentTieringStorage",
    "GLACIER": "GlacierStorage",
    "DEEP_ARCHIVE": "DeepArchiveStorage",
    "REDUCED_REDUNDANCY": "ReducedRedundancyStorage",
}
EXPECTED_STORAGE_TYPES = (
    "StandardStorage",
    "StandardIAStorage",
    "GlacierInstantRetrievalStorage",
)


def escape_label(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def labels(values):
    return "{" + ",".join(
        f'{key}="{escape_label(value)}"' for key, value in sorted(values.items())
    ) + "}"


def sample(name, value, label_values=None):
    return f"{name}{labels(label_values or {})} {value}"


def load_json(name, input_dir=INPUT_DIR):
    with (input_dir / name).open(encoding="utf-8") as source_file:
        return json.load(source_file)


def cloudwatch_storage_type(storage_class):
    if storage_class in STORAGE_TYPES:
        return STORAGE_TYPES[storage_class]
    normalized = "".join(part.title() for part in storage_class.split("_"))
    return f"{normalized}Storage"


def summarize(payload):
    contents = payload.get("Contents", [])
    if not isinstance(contents, list):
        raise ValueError("S3 Contents must be a list")

    bytes_by_storage_type = {storage_type: 0 for storage_type in EXPECTED_STORAGE_TYPES}
    for item in contents:
        storage_type = cloudwatch_storage_type(item.get("StorageClass", "STANDARD"))
        bytes_by_storage_type.setdefault(storage_type, 0)
        bytes_by_storage_type[storage_type] += int(item.get("Size", 0))
    return len(contents), bytes_by_storage_type


def storage_metrics(targets=TARGETS, input_dir=INPUT_DIR, timestamp=None):
    collected_at = timestamp or int(datetime.now(timezone.utc).timestamp())
    lines = [
        "# HELP cantaloupe:aws_s3_current_object_bytes Current S3 object bytes from ListObjectsV2.",
        "# TYPE cantaloupe:aws_s3_current_object_bytes gauge",
        "# HELP cantaloupe:aws_s3_current_objects Current S3 object count from ListObjectsV2.",
        "# TYPE cantaloupe:aws_s3_current_objects gauge",
        "# HELP cantaloupe:aws_s3_collection_timestamp_seconds Last successful S3 API collection time.",
        "# TYPE cantaloupe:aws_s3_collection_timestamp_seconds gauge",
    ]
    for target in targets:
        object_count, bytes_by_storage_type = summarize(load_json(target["file"], input_dir))
        base = {
            "bucket_name": target["bucket"],
            "platform": "aws",
            "prefix": target["prefix"],
            "scope": "current-objects",
            "source": SOURCE,
        }
        for storage_type, size_bytes in sorted(bytes_by_storage_type.items()):
            lines.append(
                sample(
                    "cantaloupe:aws_s3_current_object_bytes",
                    size_bytes,
                    {**base, "storage_type": storage_type},
                )
            )
        lines.append(
            sample(
                "cantaloupe:aws_s3_current_objects",
                object_count,
                {**base, "storage_type": "AllStorageTypes"},
            )
        )
        lines.append(sample("cantaloupe:aws_s3_collection_timestamp_seconds", collected_at, base))
    return "\n".join(lines) + "\n"


def status_metrics(success, message="", timestamp=None):
    attempted_at = timestamp or int(datetime.now(timezone.utc).timestamp())
    base = {"platform": "aws", "source": SOURCE}
    lines = [
        sample("cantaloupe:aws_s3_collection_success", 1 if success else 0, base),
        sample("cantaloupe:aws_s3_collection_attempt_timestamp_seconds", attempted_at, base),
    ]
    if message:
        lines.append(
            sample(
                "cantaloupe:aws_s3_collection_error",
                1,
                {**base, "reason": message[:120]},
            )
        )
    return "\n".join(lines) + "\n"


def push(group, body):
    url = f"{PUSHGATEWAY}/metrics/job/cantaloupe_aws_s3_storage/group/{group}"
    request = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers={"Content-Type": "text/plain; version=0.0.4"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status >= 300:
            raise RuntimeError(f"Pushgateway returned HTTP {response.status}")


def main():
    try:
        push("storage", storage_metrics())
        push("collector", status_metrics(True))
        print(f"Exported current object totals for {len(TARGETS)} S3 bucket prefix(es)")
    except Exception as exc:
        try:
            push("collector", status_metrics(False, type(exc).__name__))
        except Exception as push_exc:
            print(f"Failed to publish collector error: {push_exc}", file=sys.stderr)
        print(f"S3 storage collection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
