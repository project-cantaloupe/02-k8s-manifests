#!/usr/bin/env python3
"""Generate Prometheus recording/alert rules for On-prem VM right-sizing.

The generator deliberately separates a capacity recommendation based on
observed P95 from the "applicable now" decision based on current Kubernetes
Requests and safety signals. It never changes a VM or a Workload.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
POLICY = ROOT / "onprem-rightsizing-policy.yaml"
OUTPUT = ROOT.parent / "monitoring-foundation" / "onprem-rightsizing-rules.yaml"


def load_policy() -> dict:
    data = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    required = {"schemaVersion", "version", "lookback", "resolution", "safety", "tcoModel", "profiles", "recommendation"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"policy missing required keys: {sorted(missing)}")
    if data["schemaVersion"] != "v1":
        raise ValueError(f"unsupported schemaVersion: {data['schemaVersion']}")
    if len(data["profiles"]) < 2:
        raise ValueError("at least two On-prem profiles are required")

    names: set[str] = set()
    instance_types: set[str] = set()
    for profile in data["profiles"]:
        for key in ("name", "instanceType", "vcpu", "memoryGiB"):
            if key not in profile:
                raise ValueError(f"profile missing {key}: {profile}")
        if profile["name"] in names:
            raise ValueError(f"duplicate profile name: {profile['name']}")
        if profile["instanceType"] in instance_types:
            raise ValueError(f"duplicate profile instanceType: {profile['instanceType']}")
        if float(profile["vcpu"]) <= 0 or float(profile["memoryGiB"]) <= 0:
            raise ValueError(f"profile capacity must be positive: {profile['name']}")
        names.add(profile["name"])
        instance_types.add(profile["instanceType"])

    return data


def profile_hourly_cost(policy: dict, profile: dict) -> float:
    host = policy["tcoModel"]["physicalHostCapacity"]
    ratio = max(float(profile["vcpu"]) / float(host["vcpu"]), float(profile["memoryGiB"]) / float(host["memoryGiB"]))
    return round(float(policy["tcoModel"]["physicalHostHourlyTCOUSD"]) * ratio, 9)


def static_metric(metric: str, label: str, profiles: list[dict], value_key: str) -> str:
    expressions = []
    for profile in profiles:
        value = profile[value_key]
        expressions.append(f'label_replace(vector({value}), "{label}", "{profile["name"]}", "", "")')
    return "\n  or\n".join(expressions)


def feasible_expr(profile: dict) -> str:
    memory_bytes = int(float(profile["memoryGiB"]) * 1024**3)
    return (
        f'(cantaloupe:onprem_node_required_cpu_cores <= {float(profile["vcpu"]):.9f})'
        f' and on (node) '
        f'(cantaloupe:onprem_node_required_memory_bytes <= {memory_bytes})'
    )


def recommendation_expr(profiles: list[dict]) -> str:
    ordered = sorted(profiles, key=lambda p: (float(p["hourlyCostUSD"]), float(p["vcpu"]), float(p["memoryGiB"])))
    candidates = []
    cheaper = []
    for profile in ordered:
        feasible = feasible_expr(profile)
        selected = feasible
        if cheaper:
            selected = f'({feasible}) unless on (node) ({" or ".join(cheaper)})'
        candidates.append(
            f'label_replace((0 * ({selected}) + 1), "recommended_profile", "{profile["name"]}", "", "")'
        )
        cheaper.append(feasible)
    return "\n  or\n".join(candidates)


def rules(policy: dict) -> dict:
    safety = policy["safety"]
    profiles = []
    for raw in policy["profiles"]:
        profile = dict(raw)
        profile["hourlyCostUSD"] = profile_hourly_cost(policy, profile)
        profiles.append(profile)

    lookback = policy["lookback"]
    resolution = policy["resolution"]
    onprem_filter = 'max by (node) (kube_node_labels{label_platform="onp"})'
    cpu_p95 = (
        f'quantile_over_time(0.95, (sum by (node) (rate(container_cpu_usage_seconds_total{{job="kubelet",container!="",container!="POD"}}[5m])))[{lookback}:{resolution}])'
        f' and on (node) {onprem_filter}'
    )
    observation_hours = (
        f'count_over_time((sum by (node) (rate(container_cpu_usage_seconds_total{{job="kubelet",container!="",container!="POD"}}[5m])))[{lookback}:{resolution}]) / 12'
        f' and on (node) {onprem_filter}'
    )
    memory_p95 = (
        f'quantile_over_time(0.95, (sum by (node) (container_memory_working_set_bytes{{job="kubelet",container!="",container!="POD"}}))[{lookback}:{resolution}])'
        f' and on (node) {onprem_filter}'
    )
    cpu_requests = (
        'sum by (node) (kube_pod_container_resource_requests{job="kube-state-metrics",resource="cpu",unit="core"})'
        f' and on (node) {onprem_filter}'
    )
    memory_requests = (
        'sum by (node) (kube_pod_container_resource_requests{job="kube-state-metrics",resource="memory",unit="byte"})'
        f' and on (node) {onprem_filter}'
    )

    profile_cost_metric = static_metric("cantaloupe:onprem_profile_hourly_cost", "recommended_profile", profiles, "hourlyCostUSD")
    profile_cpu_metric = static_metric("cantaloupe:onprem_profile_vcpu", "recommended_profile", profiles, "vcpu")
    memory_profiles = [{**p, "memoryBytes": int(float(p["memoryGiB"]) * 1024**3)} for p in profiles]
    profile_memory_metric = static_metric("cantaloupe:onprem_profile_memory_bytes", "recommended_profile", memory_profiles, "memoryBytes")

    current_profile_cost_parts = []
    current_profile_cpu_parts = []
    current_profile_memory_parts = []
    for profile in profiles:
        current_profile_cost_parts.append(
            f'{profile["hourlyCostUSD"]:.9f} * max by (node) '
            f'(kube_node_labels{{label_platform="onp",label_node_kubernetes_io_instance_type="{profile["instanceType"]}"}})'
        )
        current_profile_cpu_parts.append(
            f'{float(profile["vcpu"]):.9f} * max by (node) '
            f'(kube_node_labels{{label_platform="onp",label_node_kubernetes_io_instance_type="{profile["instanceType"]}"}})'
        )
        current_profile_memory_parts.append(
            f'{int(float(profile["memoryGiB"]) * 1024**3)} * max by (node) '
            f'(kube_node_labels{{label_platform="onp",label_node_kubernetes_io_instance_type="{profile["instanceType"]}"}})'
        )
    current_profile_cost = "\n  or\n".join(current_profile_cost_parts)
    current_profile_cpu = "\n  or\n".join(current_profile_cpu_parts)
    current_profile_memory = "\n  or\n".join(current_profile_memory_parts)

    rec_info = recommendation_expr(profiles)
    max_sched = float(safety["maxSchedulableRatio"])
    oom_expr = (
        f'max by (node) (max_over_time(kube_pod_container_status_last_terminated_reason{{reason="OOMKilled"}}[{lookback}]) '
        ' * on (namespace, pod) group_left(node) max by (namespace, pod, node) (kube_pod_info)) > 0'
    )
    memory_pressure_expr = (
        'max by (node) (kube_node_status_condition{condition="MemoryPressure",status="true"} == 1)'
        f' and on (node) {onprem_filter}'
    )

    group_rules = [
        {"record": "cantaloupe:onprem_node_cpu_p95_7d_cores", "expr": cpu_p95},
        {"record": "cantaloupe:onprem_node_memory_p95_7d_bytes", "expr": memory_p95},
        {"record": "cantaloupe:onprem_node_observation_hours", "expr": observation_hours},
        {
            "record": "cantaloupe:onprem_node_observation_confidence",
            "expr": (
                '(cantaloupe:onprem_node_observation_hours >= bool 6)'
                ' + (cantaloupe:onprem_node_observation_hours >= bool 24)'
                ' + (cantaloupe:onprem_node_observation_hours >= bool 168)'
            ),
        },
        {"record": "cantaloupe:onprem_node_cpu_requests_cores", "expr": cpu_requests},
        {"record": "cantaloupe:onprem_node_memory_requests_bytes", "expr": memory_requests},
        {
            "record": "cantaloupe:onprem_node_required_cpu_cores",
            "expr": f'cantaloupe:onprem_node_cpu_p95_7d_cores * {float(safety["cpuHeadroomRatio"]):.9f} + {float(safety["systemReservedCPU"]):.9f}',
        },
        {
            "record": "cantaloupe:onprem_node_required_memory_bytes",
            "expr": f'cantaloupe:onprem_node_memory_p95_7d_bytes * {float(safety["memoryHeadroomRatio"]):.9f} + {int(float(safety["systemReservedMemoryGiB"]) * 1024**3)}',
        },
        {"record": "cantaloupe:onprem_profile_hourly_cost", "expr": profile_cost_metric},
        {"record": "cantaloupe:onprem_profile_vcpu", "expr": profile_cpu_metric},
        {"record": "cantaloupe:onprem_profile_memory_bytes", "expr": profile_memory_metric},
        {"record": "cantaloupe:onprem_node_current_profile_hourly_cost", "expr": current_profile_cost},
        {"record": "cantaloupe:onprem_node_current_profile_vcpu", "expr": current_profile_cpu},
        {"record": "cantaloupe:onprem_node_current_profile_memory_bytes", "expr": current_profile_memory},
        {"record": "cantaloupe:onprem_node_recommendation_info", "expr": rec_info},
        {
            "record": "cantaloupe:onprem_node_recommended_vcpu",
            "expr": 'cantaloupe:onprem_node_recommendation_info * on (recommended_profile) group_left() cantaloupe:onprem_profile_vcpu',
        },
        {
            "record": "cantaloupe:onprem_node_recommended_memory_bytes",
            "expr": 'cantaloupe:onprem_node_recommendation_info * on (recommended_profile) group_left() cantaloupe:onprem_profile_memory_bytes',
        },
        {
            "record": "cantaloupe:onprem_node_recommended_hourly_cost",
            "expr": 'cantaloupe:onprem_node_recommendation_info * on (recommended_profile) group_left() cantaloupe:onprem_profile_hourly_cost',
        },
        {
            "record": "cantaloupe:onprem_node_potential_savings_per_hour",
            "expr": 'clamp_min(cantaloupe:onprem_node_current_profile_hourly_cost - on (node) cantaloupe:onprem_node_recommended_hourly_cost, 0)',
        },
        {
            "record": "cantaloupe:onprem_node_potential_savings_per_month",
            "expr": '730 * cantaloupe:onprem_node_potential_savings_per_hour',
        },
        {
            "record": "cantaloupe:onprem_node_estimated_cost_change_per_month",
            "expr": (
                '730 * (cantaloupe:onprem_node_recommended_hourly_cost '
                '- on (node) cantaloupe:onprem_node_current_profile_hourly_cost)'
            ),
        },
        {
            "record": "cantaloupe:onprem_node_under_provisioned_signal",
            "expr": (
                '((cantaloupe:onprem_node_required_cpu_cores '
                '> bool on (node) cantaloupe:onprem_node_current_profile_vcpu) '
                '+ on (node) '
                '(cantaloupe:onprem_node_required_memory_bytes '
                '> bool on (node) cantaloupe:onprem_node_current_profile_memory_bytes)) > bool 0'
            ),
        },
        {
            "record": "cantaloupe:onprem_node_catalog_exceeded_signal",
            "expr": (
                '(cantaloupe:onprem_node_under_provisioned_signal == 1) '
                'unless on (node) cantaloupe:onprem_node_recommendation_info'
            ),
        },
        {
            "record": "cantaloupe:onprem_node_over_provisioned_signal",
            "expr": (
                '(cantaloupe:onprem_node_recommended_hourly_cost '
                '< bool on (node) cantaloupe:onprem_node_current_profile_hourly_cost) '
                '* on (node) (cantaloupe:onprem_node_under_provisioned_signal == bool 0)'
            ),
        },
        {
            "record": "cantaloupe:onprem_node_optimized_signal",
            "expr": (
                '(cantaloupe:onprem_node_recommended_hourly_cost '
                '== bool on (node) cantaloupe:onprem_node_current_profile_hourly_cost) '
                '* on (node) (cantaloupe:onprem_node_under_provisioned_signal == bool 0)'
            ),
        },
        {
            "record": "cantaloupe:onprem_node_decision_info",
            "expr": (
                'label_replace((cantaloupe:onprem_node_catalog_exceeded_signal == 1), '
                '"decision", "CATALOG_EXCEEDED", "", "") '
                'or label_replace(((cantaloupe:onprem_node_under_provisioned_signal == 1) '
                'and on (node) cantaloupe:onprem_node_recommendation_info), '
                '"decision", "UNDER_PROVISIONED", "", "") '
                'or label_replace((cantaloupe:onprem_node_over_provisioned_signal == 1), '
                '"decision", "OVER_PROVISIONED", "", "") '
                'or label_replace((cantaloupe:onprem_node_optimized_signal == 1), '
                '"decision", "OPTIMIZED", "", "")'
            ),
        },
        {
            "record": "cantaloupe:onprem_node_requests_fit_recommendation",
            "expr": (
                f'(cantaloupe:onprem_node_cpu_requests_cores <= on (node) cantaloupe:onprem_node_recommended_vcpu * {max_sched:.9f})'
                f' and on (node) '
                f'(cantaloupe:onprem_node_memory_requests_bytes <= on (node) cantaloupe:onprem_node_recommended_memory_bytes * {max_sched:.9f})'
            ),
        },
        {"record": "cantaloupe:onprem_node_recent_oom_signal", "expr": oom_expr},
        {"record": "cantaloupe:onprem_node_memory_pressure", "expr": memory_pressure_expr},
        {
            "record": "cantaloupe:onprem_node_recommendation_safe_to_review",
            "expr": (
                'cantaloupe:onprem_node_requests_fit_recommendation '
                'and on (node) (cantaloupe:onprem_node_observation_hours >= 24) '
                'unless on (node) cantaloupe:onprem_node_recent_oom_signal '
                'unless on (node) cantaloupe:onprem_node_memory_pressure'
            ),
        },
        {
            "alert": "OnPremRightSizingBlockedByRequests",
            "expr": (
                '(cantaloupe:onprem_node_potential_savings_per_month > 0 '
                'and on (node) (cantaloupe:onprem_node_observation_hours >= 24)) '
                'unless on (node) cantaloupe:onprem_node_requests_fit_recommendation'
            ),
            "for": "30m",
            "labels": {"severity": "warning", "category": "finops"},
            "annotations": {
                "summary": "On-prem VM 축소 전에 Workload Request 조정이 필요합니다",
                "description": "{{ $labels.node }} 노드의 P95 기준 권장 Profile에는 현재 Pod Request 합계가 안전하게 들어가지 않습니다.",
                "action": "VM을 먼저 축소하지 말고 Workload Right-sizing과 재스케줄링 가능 여부를 검증하세요.",
            },
        },
    ]

    return {
        "apiVersion": "monitoring.coreos.com/v1",
        "kind": "PrometheusRule",
        "metadata": {
            "name": "cantaloupe-onprem-rightsizing",
            "namespace": "monitoring",
            "labels": {"release": "monitoring", "app": "opencost", "area": "monitoring", "category": "finops"},
            "annotations": {"cantaloupe.io/policy-version": policy["version"]},
        },
        "spec": {"groups": [{"name": "cantaloupe.finops.onprem-rightsizing", "interval": "5m", "rules": group_rules}]},
    }


def render(policy: dict) -> str:
    header = "# GENERATED by generate_onprem_rightsizing.py. Do not edit manually.\n"
    return header + yaml.safe_dump(rules(policy), sort_keys=False, allow_unicode=True, width=140)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when generated rules are stale")
    args = parser.parse_args()
    output = render(load_policy())
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != output:
            print("onprem-rightsizing-rules.yaml is stale; run generate_onprem_rightsizing.py")
            return 1
        print("onprem-rightsizing-rules.yaml is current")
        return 0
    OUTPUT.write_text(output, encoding="utf-8")
    print(f"generated {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
