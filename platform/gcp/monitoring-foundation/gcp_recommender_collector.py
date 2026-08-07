#!/usr/bin/env python3
"""Export GCP VM machine-type recommendations to Prometheus Pushgateway."""

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


K8S_API = os.environ.get("KUBERNETES_SERVICE_HOST")
K8S_PORT = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
K8S_TOKEN_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/token"
K8S_CA_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
METADATA_TOKEN_URL = (
    # Use the documented link-local endpoint directly. Self-managed kubeadm
    # Pods do not necessarily inherit Compute Engine's internal DNS record.
    "http://169.254.169.254/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)
RECOMMENDER_ID = "google.compute.instance.MachineTypeRecommender"
PUSHGATEWAY = os.environ.get(
    "PUSHGATEWAY_URL", "http://cantaloupe-finops-pushgateway.monitoring.svc:9091"
).rstrip("/")
SOURCE = "gcp-recommender"


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
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def money_value(money):
    if not money:
        return 0.0
    return float(money.get("units", 0)) + float(money.get("nanos", 0)) / 1_000_000_000


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
        spec = node.get("spec", {})
        node_labels = metadata.get("labels", {})
        provider_id = spec.get("providerID", "")
        if not provider_id.startswith("gce://"):
            continue
        parts = provider_id.removeprefix("gce://").split("/")
        if len(parts) != 3:
            continue
        project, zone, instance = parts
        discovered[instance] = {
            "node": metadata.get("name", instance),
            "project": project,
            "zone": zone,
            "instance": instance,
            "current_profile": node_labels.get("node.kubernetes.io/instance-type", "unknown"),
        }
    if not discovered:
        raise RuntimeError("No Kubernetes Node with a gce:// providerID was found")
    return discovered


def access_token():
    payload = request_json(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
    return payload["access_token"]


def list_recommendations(project, zone, token):
    parent = (
        f"projects/{project}/locations/{zone}/recommenders/{RECOMMENDER_ID}"
    )
    base = "https://recommender.googleapis.com/v1/" + urllib.parse.quote(parent, safe="/")
    recommendations = []
    page_token = ""
    while True:
        query = {"pageSize": "100"}
        if page_token:
            query["pageToken"] = page_token
        payload = request_json(
            f"{base}/recommendations?{urllib.parse.urlencode(query)}",
            headers={"Authorization": f"Bearer {token}"},
        )
        recommendations.extend(payload.get("recommendations", []))
        page_token = payload.get("nextPageToken", "")
        if not page_token:
            return recommendations


def parse_recommendation(recommendation, nodes):
    overview = recommendation.get("content", {}).get("overview", {})
    instance = overview.get("resourceName", "")
    if not instance:
        target = next(iter(recommendation.get("targetResources", [])), "")
        instance = target.rsplit("/", 1)[-1]
    node = nodes.get(instance)
    if not node:
        return None

    current = overview.get("currentMachineType", {})
    recommended = overview.get("recommendedMachineType", {})
    cost = recommendation.get("primaryImpact", {}).get("costProjection", {})
    # A saving is represented by a negative projected cost delta.
    savings = max(0.0, -money_value(cost.get("cost", {})))
    return {
        **node,
        "current_profile": current.get("name", node["current_profile"]),
        "recommended_profile": recommended.get("name", "unknown"),
        "current_vcpu": current.get("guestCpus", 0),
        "recommended_vcpu": recommended.get("guestCpus", 0),
        "current_memory_bytes": current.get("memoryBytes", 0),
        "recommended_memory_bytes": recommended.get("memoryBytes", 0),
        "monthly_savings_usd": savings,
        "state": recommendation.get("stateInfo", {}).get("state", "UNKNOWN"),
        "priority": recommendation.get("priority", "UNSPECIFIED"),
        "last_refresh": timestamp_seconds(recommendation.get("lastRefreshTime")),
    }


def recommendation_metrics(recommendations):
    lines = [
        "# HELP cantaloupe:provider_vm_recommendation_info GCP official VM recommendation metadata.",
        "# TYPE cantaloupe:provider_vm_recommendation_info gauge",
    ]
    for item in recommendations:
        base = {
            "platform": "gcp",
            "node": item["node"],
            "project": item["project"],
            "location": item["zone"],
            "source": SOURCE,
        }
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


def status_metrics(success, count, message=""):
    now = int(datetime.now(timezone.utc).timestamp())
    status = "ready" if success and count else "no_active_recommendation" if success else "collection_error"
    base = {"platform": "gcp", "source": SOURCE, "status": status}
    lines = [
        sample("cantaloupe:provider_recommender_status", 1, base),
        sample("cantaloupe:provider_recommendation_collection_success", 1 if success else 0, {"platform": "gcp"}),
        sample("cantaloupe:provider_recommendation_count", count, {"platform": "gcp"}),
        sample("cantaloupe:provider_recommendation_collection_timestamp_seconds", now, {"platform": "gcp"}),
    ]
    if message:
        lines.append(sample("cantaloupe:provider_recommendation_collection_error", 1, {"platform": "gcp", "reason": message[:120]}))
    return "\n".join(lines) + "\n"


def push(group, body):
    url = f"{PUSHGATEWAY}/metrics/job/cantaloupe_gcp_recommender/group/{group}"
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
        nodes = kubernetes_nodes()
        token = access_token()
        raw = []
        for project, zone in sorted({(n["project"], n["zone"]) for n in nodes.values()}):
            raw.extend(list_recommendations(project, zone, token))
        parsed = [item for item in (parse_recommendation(rec, nodes) for rec in raw) if item]
        # PUT replaces this grouping key, so recommendations no longer returned by
        # GCP are removed instead of remaining as stale series.
        push("recommendations", recommendation_metrics(parsed))
        push("collector", status_metrics(True, len(parsed)))
        print(f"Exported {len(parsed)} recommendation(s) for {len(nodes)} GCP node(s)")
    except Exception as exc:
        try:
            # Keep the last valid recommendation group intact on transient API
            # failures; only the independently grouped collector health changes.
            push("collector", status_metrics(False, 0, type(exc).__name__))
        except Exception as push_exc:
            print(f"Failed to publish collector error: {push_exc}", file=sys.stderr)
        print(f"GCP recommendation collection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
