#!/usr/bin/env python3
"""Normalize GCP Recommender and AWS Compute Optimizer JSON snapshots.

Authentication and API calls intentionally remain outside this program. A human
using gcloud/aws CLI or a keyless CI job writes JSON snapshots, then this script
normalizes only non-secret recommendation fields. This keeps long-lived cloud
credentials out of Kubernetes and Git.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "provider-recommendations.yaml"


def money_value(value: dict | None) -> float:
    if not value:
        return 0.0
    return float(value.get("units", 0)) + float(value.get("nanos", 0)) / 1_000_000_000


def gcp_recommendations(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    normalized = []
    for item in data:
        overview = item.get("content", {}).get("overview", {})
        current = overview.get("currentMachineType", {})
        recommended = overview.get("recommendedMachineType", {})
        impact = item.get("primaryImpact", {}).get("costProjection", {})
        cost = impact.get("cost", {})
        local = impact.get("costInLocalCurrency", {})
        resource = overview.get("resourceName") or overview.get("resource", "").rsplit("/", 1)[-1]
        if not resource or not current.get("name") or not recommended.get("name"):
            continue
        normalized.append(
            {
                "platform": "gcp",
                "resource": resource,
                "location": overview.get("location", "unknown"),
                "currentProfile": current["name"],
                "recommendedProfile": recommended["name"],
                "currentVCPU": float(current.get("guestCpus", 0)),
                "recommendedVCPU": float(recommended.get("guestCpus", 0)),
                "currentMemoryGiB": float(current.get("memoryBytes", 0)) / 1024**3,
                "recommendedMemoryGiB": float(recommended.get("memoryBytes", 0)) / 1024**3,
                "estimatedMonthlySavingsUSD": abs(money_value(cost)),
                "estimatedMonthlySavingsLocal": abs(money_value(local)),
                "localCurrency": local.get("currencyCode", ""),
                "source": "gcp-recommender",
                "state": item.get("stateInfo", {}).get("state", "UNKNOWN"),
                "priority": item.get("priority", "UNKNOWN"),
                "lastRefreshTime": item.get("lastRefreshTime"),
                "sourceRef": "google.compute.instance.MachineTypeRecommender",
            }
        )
    return normalized


def aws_resource_name(instance_arn: str) -> str:
    if not instance_arn:
        return "unknown"
    return instance_arn.rsplit("/", 1)[-1]


def aws_recommendations(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    normalized = []
    for item in data.get("instanceRecommendations", []):
        options = item.get("recommendationOptions") or []
        if not options:
            continue
        option = sorted(options, key=lambda value: float(value.get("rank", 999)))[0]
        savings = option.get("savingsOpportunity", {}).get("estimatedMonthlySavings", {})
        normalized.append(
            {
                "platform": "aws",
                "resource": aws_resource_name(item.get("instanceArn", "")),
                "location": "unknown",
                "currentProfile": item.get("currentInstanceType", "unknown"),
                "recommendedProfile": option.get("instanceType", "unknown"),
                "currentVCPU": 0,
                "recommendedVCPU": 0,
                "currentMemoryGiB": 0,
                "recommendedMemoryGiB": 0,
                "estimatedMonthlySavingsUSD": float(savings.get("value", 0)),
                "estimatedMonthlySavingsLocal": 0,
                "localCurrency": savings.get("currency", "USD"),
                "source": "aws-compute-optimizer",
                "state": item.get("finding", "UNKNOWN"),
                "priority": f'risk-{option.get("performanceRisk", "unknown")}',
                "lastRefreshTime": item.get("lastRefreshTimestamp"),
                "sourceRef": "compute-optimizer:GetEC2InstanceRecommendations",
            }
        )
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gcp-json", type=Path)
    parser.add_argument("--aws-json", type=Path)
    parser.add_argument(
        "--aws-status",
        choices=["no-active-recommendation", "inactive", "analyzing"],
        default="analyzing",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    recommendations: list[dict] = []
    providers = {}
    if args.gcp_json:
        gcp = gcp_recommendations(args.gcp_json)
        recommendations.extend(gcp)
        providers["gcp"] = {
            "status": "ready" if gcp else "no-active-recommendation",
            "source": "gcp-recommender",
            "note": "Normalized from a keyless gcloud/API snapshot.",
        }
    if args.aws_json:
        aws = aws_recommendations(args.aws_json)
        recommendations.extend(aws)
        providers["aws"] = {
            "status": "ready" if aws else args.aws_status,
            "source": "aws-compute-optimizer",
            "note": "Normalized from a keyless aws CLI/API snapshot.",
        }

    document = {
        "schemaVersion": "v1",
        "version": f'cantaloupe-provider-recommendations-{datetime.now(timezone.utc).date().isoformat()}',
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "providers": providers,
        "recommendations": recommendations,
    }
    rendered = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    if args.check:
        current = yaml.safe_load(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else None
        proposed = yaml.safe_load(rendered)
        comparable_current = {
            "providers": (current or {}).get("providers", {}),
            "recommendations": (current or {}).get("recommendations", []),
        }
        comparable_proposed = {
            "providers": proposed.get("providers", {}),
            "recommendations": proposed.get("recommendations", []),
        }
        if comparable_current != comparable_proposed:
            print("provider recommendation cache differs from snapshots")
            return 1
        print("provider recommendation cache matches snapshots")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"updated {OUTPUT} with {len(recommendations)} recommendations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
