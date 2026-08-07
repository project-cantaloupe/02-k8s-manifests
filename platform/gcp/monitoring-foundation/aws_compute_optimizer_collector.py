#!/usr/bin/env python3
"""Export AWS Compute Optimizer EC2 recommendations to Pushgateway."""

import json
import os
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


K8S_API = os.environ.get("KUBERNETES_SERVICE_HOST")
K8S_PORT = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
K8S_TOKEN_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/token"
K8S_CA_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
PUSHGATEWAY = os.environ.get(
    "PUSHGATEWAY_URL", "http://cantaloupe-finops-pushgateway.monitoring.svc:9091"
).rstrip("/")
INPUT_DIR = Path(os.environ.get("AWS_COLLECTOR_INPUT_DIR", "/work"))
SOURCE = "aws-compute-optimizer"


def request_json(url, headers=None, context=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        return json.load(response)


def escape_label(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def labels(values):
    return "{" + ",".join(
        f'{key}="{escape_label(value)}"' for key, value in sorted(values.items())
    ) + "}"


def sample(name, value, label_values=None):
    return f"{name}{labels(label_values or {})} {value}"


def timestamp_seconds(value):
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def load_json(name):
    with (INPUT_DIR / name).open(encoding="utf-8") as source_file:
        return json.load(source_file)


def kubernetes_nodes():
    if not K8S_API:
        raise RuntimeError("Kubernetes API environment is missing")
    with open(K8S_TOKEN_FILE, encoding="utf-8") as token_file:
        token = token_file.read().strip()
    context = ssl.create_default_context(cafile=K8S_CA_FILE)
    payload = request_json(
        f"https://{K8S_API}:{K8S_PORT}/api/v1/nodes",
        headers={"Authorization": f"Bearer {token}"},
        context=context,
    )
    discovered = {}
    for node in payload.get("items", []):
        metadata = node.get("metadata", {})
        provider_id = node.get("spec", {}).get("providerID", "")
        if not provider_id.startswith("aws://"):
            continue
        instance_id = provider_id.rsplit("/", 1)[-1]
        discovered[instance_id] = metadata.get("name", instance_id)
    if not discovered:
        raise RuntimeError("No Kubernetes Node with an aws:// providerID was found")
    return discovered


def type_specs(payload):
    specs = {}
    for instance_type in payload.get("InstanceTypes", []):
        specs[instance_type.get("InstanceType", "")] = {
            "vcpu": instance_type.get("VCpuInfo", {}).get("DefaultVCpus", 0),
            "memory_bytes": instance_type.get("MemoryInfo", {}).get("SizeInMiB", 0) * 1024 * 1024,
        }
    return specs


def parse_recommendations(payload, nodes, specs):
    parsed = []
    for recommendation in payload.get("instanceRecommendations", []):
        instance_id = recommendation.get("instanceArn", "").rsplit("/", 1)[-1]
        node = nodes.get(instance_id)
        if not node:
            continue
        options = recommendation.get("recommendationOptions", [])
        top = next((option for option in options if option.get("rank") == 1), None)
        if not top:
            continue
        current_type = recommendation.get("currentInstanceType", "unknown")
        recommended_type = top.get("instanceType", "unknown")
        current_specs = specs.get(current_type, {})
        recommended_specs = specs.get(recommended_type, {})
        savings = top.get("savingsOpportunity", {}).get("estimatedMonthlySavings", {})
        parsed.append({
            "node": node,
            "current_profile": current_type,
            "recommended_profile": recommended_type,
            "current_vcpu": current_specs.get("vcpu", 0),
            "recommended_vcpu": recommended_specs.get("vcpu", 0),
            "current_memory_bytes": current_specs.get("memory_bytes", 0),
            "recommended_memory_bytes": recommended_specs.get("memory_bytes", 0),
            "monthly_savings_usd": savings.get("value", 0) if savings.get("currency", "USD") == "USD" else 0,
            "state": recommendation.get("finding", "UNKNOWN"),
            "priority": f'rank-{top.get("rank", 1)}',
            "last_refresh": timestamp_seconds(recommendation.get("lastRefreshTimestamp")),
        })
    return parsed


def recommendation_metrics(recommendations):
    lines = [
        "# HELP cantaloupe:provider_vm_recommendation_info AWS official VM recommendation metadata.",
        "# TYPE cantaloupe:provider_vm_recommendation_info gauge",
    ]
    for item in recommendations:
        base = {"platform": "aws", "node": item["node"], "source": SOURCE}
        info = {
            **base,
            "current_profile": item["current_profile"],
            "recommended_profile": item["recommended_profile"],
            "state": item["state"],
            "priority": item["priority"],
        }
        lines.append(sample("cantaloupe:provider_vm_recommendation_info", 1, info))
        values = {
            "cantaloupe:provider_vm_estimated_monthly_savings": item["monthly_savings_usd"],
            "cantaloupe:provider_vm_current_vcpu": item["current_vcpu"],
            "cantaloupe:provider_vm_recommended_vcpu": item["recommended_vcpu"],
            "cantaloupe:provider_vm_current_memory_bytes": item["current_memory_bytes"],
            "cantaloupe:provider_vm_recommended_memory_bytes": item["recommended_memory_bytes"],
            "cantaloupe:provider_vm_recommendation_last_refresh_timestamp_seconds": item["last_refresh"],
        }
        for name, value in values.items():
            lines.append(sample(name, value, base))
    return "\n".join(lines) + "\n"


def status_metrics(enrollment, success, count, message=""):
    now = int(datetime.now(timezone.utc).timestamp())
    if not success:
        status = "collection_error"
    elif enrollment == "Active":
        status = "ready" if count else "no_active_recommendation"
    elif enrollment == "Pending":
        status = "analyzing"
    else:
        status = "inactive"
    base = {"platform": "aws", "source": SOURCE, "status": status}
    lines = [
        sample("cantaloupe:provider_recommender_status", 1, base),
        sample("cantaloupe:provider_recommendation_collection_success", 1 if success else 0, {"platform": "aws"}),
        sample("cantaloupe:provider_recommendation_count", count, {"platform": "aws"}),
        sample("cantaloupe:provider_recommendation_collection_timestamp_seconds", now, {"platform": "aws"}),
    ]
    if message:
        lines.append(sample("cantaloupe:provider_recommendation_collection_error", 1, {"platform": "aws", "reason": message[:120]}))
    return "\n".join(lines) + "\n"


def push(group, body):
    url = f"{PUSHGATEWAY}/metrics/job/cantaloupe_aws_compute_optimizer/group/{group}"
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
    enrollment = "Unknown"
    try:
        nodes = kubernetes_nodes()
        enrollment = load_json("enrollment.json").get("status", "Unknown")
        recommendations = parse_recommendations(
            load_json("recommendations.json"), nodes, type_specs(load_json("instance-types.json"))
        )
        push("recommendations", recommendation_metrics(recommendations))
        push("collector", status_metrics(enrollment, True, len(recommendations)))
        print(
            f"Enrollment={enrollment}; exported {len(recommendations)} recommendation(s) "
            f"for {len(nodes)} AWS node(s)"
        )
    except Exception as exc:
        try:
            push("collector", status_metrics(enrollment, False, 0, type(exc).__name__))
        except Exception as push_exc:
            print(f"Failed to publish collector error: {push_exc}", file=sys.stderr)
        print(f"AWS recommendation collection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
