#!/usr/bin/env python3
"""Export recommendation-only VPA status to the existing FinOps Pushgateway."""

import json
import os
import re
import ssl
import time
import urllib.request

API = os.getenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
PORT = os.getenv("KUBERNETES_SERVICE_PORT_HTTPS", "443")
PUSHGATEWAY = os.getenv(
    "PUSHGATEWAY_URL", "http://cantaloupe-finops-pushgateway.monitoring.svc:9091"
).rstrip("/")
TOKEN_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/token"
CA_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

BINARY = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
}
DECIMAL = {"m": 0.001, "k": 1000, "M": 1000**2, "G": 1000**3}


def quantity(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z]+)?", str(value))
    if not match:
        return 0.0
    number, suffix = match.groups()
    if not suffix:
        return float(number)
    return float(number) * (BINARY.get(suffix) or DECIMAL.get(suffix) or 1)


def esc(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def sample(name, value, labels):
    encoded = ",".join(f'{key}="{esc(val)}"' for key, val in sorted(labels.items()))
    return f"{name}{{{encoded}}} {value}"


def get_vpas():
    with open(TOKEN_FILE, encoding="utf-8") as handle:
        token = handle.read().strip()
    url = f"https://{API}:{PORT}/apis/autoscaling.k8s.io/v1/verticalpodautoscalers?limit=500"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    context = ssl.create_default_context(cafile=CA_FILE)
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        return json.load(response).get("items", [])


def render(items):
    lines = [
        "# HELP cantaloupe_vpa_recommendation_info VPA recommendation availability and review classification.",
        "# TYPE cantaloupe_vpa_recommendation_info gauge",
        "# HELP cantaloupe_vpa_container_recommendation_cpu_cores VPA CPU recommendation by bound.",
        "# TYPE cantaloupe_vpa_container_recommendation_cpu_cores gauge",
        "# HELP cantaloupe_vpa_container_recommendation_memory_bytes VPA memory recommendation by bound.",
        "# TYPE cantaloupe_vpa_container_recommendation_memory_bytes gauge",
        "# HELP cantaloupe_vpa_collection_timestamp_seconds Last successful VPA status collection.",
        "# TYPE cantaloupe_vpa_collection_timestamp_seconds gauge",
    ]
    for item in items:
        metadata = item.get("metadata", {})
        spec = item.get("spec", {})
        labels = metadata.get("labels", {})
        target = spec.get("targetRef", {})
        base = {
            "namespace": metadata.get("namespace", ""),
            "vpa": metadata.get("name", ""),
            "workload": target.get("name", ""),
            "workload_type": target.get("kind", "").lower(),
            "rightsizing_class": labels.get("cantaloupe.io/rightsizing-class", "unclassified"),
            "review_policy": labels.get("cantaloupe.io/review-policy", "standard"),
        }
        recommendations = (
            item.get("status", {}).get("recommendation", {}).get("containerRecommendations", [])
        )
        lines.append(sample("cantaloupe_vpa_recommendation_info", 1 if recommendations else 0, base))
        for rec in recommendations:
            current = dict(base, container=rec.get("containerName", ""))
            for json_key, bound in (
                ("lowerBound", "lower"),
                ("target", "target"),
                ("upperBound", "upper"),
                ("uncappedTarget", "uncapped_target"),
            ):
                resources = rec.get(json_key, {})
                if "cpu" in resources:
                    lines.append(
                        sample(
                            "cantaloupe_vpa_container_recommendation_cpu_cores",
                            quantity(resources["cpu"]),
                            dict(current, bound=bound),
                        )
                    )
                if "memory" in resources:
                    lines.append(
                        sample(
                            "cantaloupe_vpa_container_recommendation_memory_bytes",
                            quantity(resources["memory"]),
                            dict(current, bound=bound),
                        )
                    )
    lines.append(sample("cantaloupe_vpa_collection_timestamp_seconds", int(time.time()), {}))
    return "\n".join(lines) + "\n"


def push(payload):
    request = urllib.request.Request(
        f"{PUSHGATEWAY}/metrics/job/cantaloupe_vpa_recommendations",
        data=payload.encode(),
        method="PUT",
        headers={"Content-Type": "text/plain; version=0.0.4"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status // 100 != 2:
            raise RuntimeError(f"Pushgateway returned HTTP {response.status}")


if __name__ == "__main__":
    vpas = get_vpas()
    push(render(vpas))
    print(f"Exported {len(vpas)} VPA object(s)")
