#!/usr/bin/env python3
"""Aggregate S3 inventory and bucket controls for the FinOps dashboard."""

import argparse
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


INPUT_DIR = Path(os.environ.get("AWS_S3_FINOPS_INPUT_DIR", "/work"))
PUSHGATEWAY = os.environ.get(
    "PUSHGATEWAY_URL", "http://cantaloupe-finops-pushgateway.monitoring.svc:9091"
).rstrip("/")
BUCKETS = tuple(filter(None, (
    value.strip() for value in os.environ.get(
        "AWS_S3_BUCKETS", "cntlp-aws-quarantine,cntlp-aws-transcode"
    ).split(",")
)))
HORIZONS = (0, 30, 60, 90, 120)
QUARANTINE_BUCKET = os.environ.get("QUARANTINE_BUCKET", "cntlp-aws-quarantine")
QUARANTINE_PREFIX = os.environ.get("QUARANTINE_PREFIX", "incoming/")
STANDARD_IA_DAYS = int(os.environ.get("QUARANTINE_STANDARD_IA_DAYS", "30"))
GLACIER_IR_DAYS = int(os.environ.get("QUARANTINE_GLACIER_IR_DAYS", "60"))
PRICES = {
    "StandardStorage": float(os.environ.get("S3_STANDARD_PRICE_USD_PER_GIB_MONTH", "0.025")),
    "StandardIAStorage": float(os.environ.get("S3_STANDARD_IA_PRICE_USD_PER_GIB_MONTH", "0.0138")),
    "GlacierInstantRetrievalStorage": float(os.environ.get("S3_GLACIER_IR_PRICE_USD_PER_GIB_MONTH", "0.005")),
}
MIN_BILLABLE_BYTES = 128 * 1024
STORAGE_TYPES = {
    "STANDARD": "StandardStorage",
    "STANDARD_IA": "StandardIAStorage",
    "ONEZONE_IA": "OneZoneIAStorage",
    "INTELLIGENT_TIERING": "IntelligentTieringStorage",
    "GLACIER_IR": "GlacierInstantRetrievalStorage",
    "GLACIER": "GlacierStorage",
    "DEEP_ARCHIVE": "DeepArchiveStorage",
    "REDUCED_REDUNDANCY": "ReducedRedundancyStorage",
}
KNOWN_FILE_TYPES = {"mp3", "json", "m3u8", "ts", "aac", "wav", "flac", "mp4"}


def escape_label(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def sample(name, value, label_values=None):
    labels = label_values or {}
    rendered = ",".join(
        f'{key}="{escape_label(value)}"' for key, value in sorted(labels.items())
    )
    suffix = "{" + rendered + "}" if rendered else ""
    return f"{name}{suffix} {value}"


def load_json(name):
    path = INPUT_DIR / name
    if not path.is_file():
        raise RuntimeError(f"Missing collector input: {name}")
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def storage_type(item):
    raw = item.get("StorageClass") or "STANDARD"
    return STORAGE_TYPES.get(raw, raw)


def age_band(last_modified, now):
    days = max((now - parse_time(last_modified)).total_seconds() / 86400, 0)
    if days < 30:
        return "0-29d"
    if days < 60:
        return "30-59d"
    if days < 90:
        return "60-89d"
    return "90d+"


def file_type(key):
    leaf = key.rsplit("/", 1)[-1]
    if "." not in leaf:
        return "none"
    suffix = leaf.rsplit(".", 1)[-1].lower()
    return suffix if suffix in KNOWN_FILE_TYPES else "other"


def billable_bytes(size, target_class):
    if target_class in {"StandardIAStorage", "GlacierInstantRetrievalStorage"}:
        return max(int(size), MIN_BILLABLE_BYTES)
    return int(size)


def target_class(age_days, policy):
    if policy == "disabled":
        return "StandardStorage"
    if age_days >= GLACIER_IR_DAYS:
        return "GlacierInstantRetrievalStorage"
    if age_days >= STANDARD_IA_DAYS:
        return "StandardIAStorage"
    return "StandardStorage"


def inventory_metrics(now):
    totals = defaultdict(lambda: {"bytes": 0, "objects": 0})
    ages = defaultdict(lambda: {"bytes": 0, "objects": 0})
    types = defaultdict(lambda: {"bytes": 0, "objects": 0})
    delete_markers = defaultdict(int)
    current_by_bucket = {}
    page_count = 0

    for bucket in BUCKETS:
        current_payload = load_json(f"current-{bucket}.json")
        versions_payload = load_json(f"versions-{bucket}.json")
        current = current_payload.get("Contents") or []
        versions = versions_payload.get("Versions") or []
        markers = versions_payload.get("DeleteMarkers") or []
        current_by_bucket[bucket] = current

        page_count += max(1, math.ceil(len(current) / 1000))
        page_count += max(1, math.ceil((len(versions) + len(markers)) / 1000))
        delete_markers[bucket] = len(markers)

        for item in current:
            labels = (bucket, "current", storage_type(item))
            totals[labels]["bytes"] += int(item.get("Size", 0))
            totals[labels]["objects"] += 1
            band = (bucket, "current", age_band(item["LastModified"], now))
            ages[band]["bytes"] += int(item.get("Size", 0))
            ages[band]["objects"] += 1
            kind = (bucket, file_type(item.get("Key", "")))
            types[kind]["bytes"] += int(item.get("Size", 0))
            types[kind]["objects"] += 1

        for item in versions:
            if item.get("IsLatest"):
                continue
            labels = (bucket, "noncurrent", storage_type(item))
            totals[labels]["bytes"] += int(item.get("Size", 0))
            totals[labels]["objects"] += 1
            band = (bucket, "noncurrent", age_band(item["LastModified"], now))
            ages[band]["bytes"] += int(item.get("Size", 0))
            ages[band]["objects"] += 1

    lines = [
        "# HELP cantaloupe_s3_actual_size_bytes Current and noncurrent S3 bytes from list APIs.",
        "# TYPE cantaloupe_s3_actual_size_bytes gauge",
    ]
    for (bucket, state, storage), values in sorted(totals.items()):
        labels = {"bucket_name": bucket, "version_state": state, "storage_type": storage}
        lines.append(sample("cantaloupe_s3_actual_size_bytes", values["bytes"], labels))
        lines.append(sample("cantaloupe_s3_actual_object_count", values["objects"], labels))
    for (bucket, state, band), values in sorted(ages.items()):
        labels = {"bucket_name": bucket, "version_state": state, "age_band": band}
        lines.append(sample("cantaloupe_s3_actual_age_size_bytes", values["bytes"], labels))
        lines.append(sample("cantaloupe_s3_actual_age_object_count", values["objects"], labels))
    for (bucket, kind), values in sorted(types.items()):
        labels = {"bucket_name": bucket, "file_type": kind}
        lines.append(sample("cantaloupe_s3_actual_file_type_size_bytes", values["bytes"], labels))
        lines.append(sample("cantaloupe_s3_actual_file_type_object_count", values["objects"], labels))
    for bucket, count in sorted(delete_markers.items()):
        lines.append(sample("cantaloupe_s3_actual_delete_marker_count", count, {"bucket_name": bucket}))

    cohort = [
        item for item in current_by_bucket.get(QUARANTINE_BUCKET, [])
        if item.get("Key", "").startswith(QUARANTINE_PREFIX)
    ]
    for horizon in HORIZONS:
        scenario_costs = {}
        for policy in ("disabled", "enabled"):
            by_class = defaultdict(lambda: {"bytes": 0, "billable": 0, "objects": 0})
            for item in cohort:
                age = max((now - parse_time(item["LastModified"])).total_seconds() / 86400, 0) + horizon
                target = target_class(age, policy)
                size = int(item.get("Size", 0))
                by_class[target]["bytes"] += size
                by_class[target]["billable"] += billable_bytes(size, target)
                by_class[target]["objects"] += 1
            cost = 0.0
            for target, values in sorted(by_class.items()):
                labels = {
                    "bucket_name": QUARANTINE_BUCKET,
                    "policy": policy,
                    "horizon_days": str(horizon),
                    "target_storage_type": target,
                }
                lines.append(sample("cantaloupe_s3_whatif_size_bytes", values["bytes"], labels))
                lines.append(sample("cantaloupe_s3_whatif_billable_size_bytes", values["billable"], labels))
                lines.append(sample("cantaloupe_s3_whatif_object_count", values["objects"], labels))
                cost += values["billable"] / (1024 ** 3) * PRICES[target]
            scenario_costs[policy] = cost
            labels = {"bucket_name": QUARANTINE_BUCKET, "policy": policy, "horizon_days": str(horizon)}
            lines.append(sample("cantaloupe_s3_whatif_monthly_cost_usd", cost, labels))
        disabled = scenario_costs["disabled"]
        enabled = scenario_costs["enabled"]
        savings = max(disabled - enabled, 0)
        labels = {"bucket_name": QUARANTINE_BUCKET, "horizon_days": str(horizon)}
        lines.append(sample("cantaloupe_s3_whatif_monthly_savings_usd", savings, labels))
        lines.append(sample("cantaloupe_s3_whatif_savings_ratio", savings / disabled if disabled else 0, labels))

    timestamp = int(now.timestamp())
    expected_monthly = page_count * 4 * 30
    lines.extend([
        sample("cantaloupe_s3_inventory_collection_timestamp_seconds", timestamp),
        sample("cantaloupe_s3_inventory_collection_success", 1),
        sample("cantaloupe_s3_inventory_api_list_requests", page_count),
        sample("cantaloupe_s3_inventory_expected_monthly_list_requests", expected_monthly),
        sample("cantaloupe_s3_inventory_legacy_free_tier_usage_ratio", expected_monthly / 2000),
        sample("cantaloupe_s3_inventory_complete", 1),
        sample("cantaloupe_s3_whatif_standard_ia_transition_days", STANDARD_IA_DAYS),
        sample("cantaloupe_s3_whatif_glacier_ir_transition_days", GLACIER_IR_DAYS),
    ])
    for storage, price in PRICES.items():
        lines.append(sample("cantaloupe_s3_whatif_price_usd_per_gib_month", price, {"storage_type": storage}))
    return "\n".join(lines) + "\n"


def policy_metrics(now):
    lines = []
    request_count = 0
    for bucket in BUCKETS:
        versioning = load_json(f"versioning-{bucket}.json")
        lifecycle = load_json(f"lifecycle-{bucket}.json")
        encryption = load_json(f"encryption-{bucket}.json")
        public_access = load_json(f"public-access-{bucket}.json")
        policy_status = load_json(f"policy-status-{bucket}.json")
        ownership = load_json(f"ownership-{bucket}.json")
        request_count += 6

        lines.append(sample("cantaloupe_s3_bucket_versioning_enabled", 1 if versioning.get("Status") == "Enabled" else 0, {"bucket_name": bucket}))
        rules = lifecycle.get("Rules") or []
        lines.append(sample("cantaloupe_s3_bucket_lifecycle_enabled", 1 if any(rule.get("Status") == "Enabled" for rule in rules) else 0, {"bucket_name": bucket}))
        encryption_rules = encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules") or []
        lines.append(sample("cantaloupe_s3_bucket_encryption_enabled", 1 if encryption_rules else 0, {"bucket_name": bucket}))
        pab = public_access.get("PublicAccessBlockConfiguration", {})
        lines.append(sample("cantaloupe_s3_bucket_public_access_blocked", 1 if pab and all(pab.get(key) for key in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")) else 0, {"bucket_name": bucket}))
        lines.append(sample("cantaloupe_s3_bucket_policy_public", 1 if policy_status.get("PolicyStatus", {}).get("IsPublic") else 0, {"bucket_name": bucket}))
        controls = ownership.get("OwnershipControls", {}).get("Rules") or []
        lines.append(sample("cantaloupe_s3_bucket_owner_enforced", 1 if any(rule.get("ObjectOwnership") == "BucketOwnerEnforced" for rule in controls) else 0, {"bucket_name": bucket}))

        for rule in rules:
            if rule.get("Status") != "Enabled":
                continue
            base = {"bucket_name": bucket, "rule_id": rule.get("ID", "unnamed")}
            for transition in rule.get("Transitions") or []:
                labels = {**base, "storage_type": STORAGE_TYPES.get(transition.get("StorageClass", ""), transition.get("StorageClass", "unknown"))}
                lines.append(sample("cantaloupe_s3_bucket_lifecycle_transition_days", transition.get("Days", 0), labels))
            expiration = rule.get("NoncurrentVersionExpiration", {})
            if "NoncurrentDays" in expiration:
                lines.append(sample("cantaloupe_s3_bucket_noncurrent_expiration_days", expiration["NoncurrentDays"], base))

    lines.extend([
        sample("cantaloupe_s3_policy_collection_timestamp_seconds", int(now.timestamp())),
        sample("cantaloupe_s3_policy_collection_success", 1),
        sample("cantaloupe_s3_policy_api_get_requests", request_count),
        sample("cantaloupe_s3_policy_expected_monthly_get_requests", request_count * 52 / 12),
    ])
    return "\n".join(lines) + "\n"


def push(group, body):
    request = urllib.request.Request(
        f"{PUSHGATEWAY}/metrics/job/cantaloupe_s3_finops/group/{group}",
        data=body.encode("utf-8"),
        headers={"Content-Type": "text/plain; version=0.0.4"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status >= 300:
            raise RuntimeError(f"Pushgateway returned HTTP {response.status}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("inventory", "policy"))
    parser.add_argument("--print", action="store_true", dest="print_only")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    body = inventory_metrics(now) if args.mode == "inventory" else policy_metrics(now)
    if args.print_only:
        print(body, end="")
        return 0
    try:
        push(args.mode, body)
    except Exception as exc:
        print(f"S3 {args.mode} collection failed: {exc}", file=sys.stderr)
        return 1
    print(f"Published S3 {args.mode} metrics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
