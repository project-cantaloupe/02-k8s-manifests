#!/usr/bin/env python3
"""Generate immutable OpenCost values and pricing validation rules."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
from datetime import date, datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "pricing-catalog.yaml"
ALLOCATION_POLICY = ROOT / "allocation-policy.yaml"
OUTPUT = ROOT / "generated-values.yaml"


def load_catalog() -> dict:
    data = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    required = {
        "schemaVersion", "version", "currency", "effectiveDate", "lastReviewedAt",
        "reviewAfterDays", "nodeMatchField", "nodes",
    }
    missing = required - data.keys()
    if missing:
        raise ValueError(f"missing catalog fields: {sorted(missing)}")
    if not data["nodes"]:
        raise ValueError("nodes must not be empty")
    if data["schemaVersion"] != "v1":
        raise ValueError(f"unsupported schemaVersion: {data['schemaVersion']}")
    if data["nodeMatchField"] != "metadata.labels.node.kubernetes.io/instance-type":
        raise ValueError("this catalog supports only the standard instance-type label match field")
    if int(data["reviewAfterDays"]) <= 0:
        raise ValueError("reviewAfterDays must be positive")

    for field in ("effectiveDate", "lastReviewedAt"):
        value = data[field]
        if isinstance(value, date):
            value = value.isoformat()
        datetime.fromisoformat(str(value))

    keys: set[tuple[str, str]] = set()
    for item in data["nodes"]:
        for field in (
            "platform", "region", "instanceType", "purchaseOption",
            "source", "sourceDate", "sourceRef",
        ):
            if not str(item.get(field, "")).strip():
                raise ValueError(f"{field} is required for every node price")
        key = (item["region"].strip().lower(), item["instanceType"].strip().lower())
        if key in keys:
            raise ValueError(f"duplicate region and instanceType: {key}")
        keys.add(key)
        if item["platform"] not in {"aws", "gcp", "onp"}:
            raise ValueError(f"unsupported platform: {item['platform']}")
        if float(item["hourlyPriceUSD"]) <= 0:
            raise ValueError(f"price must be positive: {key}")
        if item["platform"] in {"aws", "gcp"} and item["purchaseOption"] != "on-demand":
            raise ValueError("current cloud price model supports on-demand nodes only")
        if item["platform"] in {"aws", "gcp"} and "public" not in item["source"]:
            raise ValueError("cloud node prices must identify a public pricing source")
    return data


def load_allocation_policy() -> dict:
    data = yaml.safe_load(ALLOCATION_POLICY.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != "v1":
        raise ValueError("allocation policy schemaVersion must be v1")
    if data.get("method") != "normalized-node-total":
        raise ValueError("allocation policy method must be normalized-node-total")
    for field in ("version", "note"):
        if not str(data.get(field, "")).strip():
            raise ValueError(f"allocation policy {field} is required")
    for field in ("cpuUSDPerCoreHour", "ramUSDPerGiBHour"):
        if float(data.get("weights", {}).get(field, 0)) <= 0:
            raise ValueError(f"allocation policy weights.{field} must be positive")
    for field in ("provider", "region", "family", "sourceRef"):
        if not str(data.get("basis", {}).get(field, "")).strip():
            raise ValueError(f"allocation policy basis.{field} is required")
    return data


def csv_text(catalog: dict) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(
        ["EndTimestamp", "InstanceID", "Region", "AssetClass", "InstanceIDField",
         "InstanceType", "MarketPriceHourly", "Version"]
    )
    for item in catalog["nodes"]:
        writer.writerow(
            ["", item["instanceType"], item["region"], "node", catalog["nodeMatchField"],
             item["instanceType"], f"{float(item['hourlyPriceUSD']):.9f}", catalog["version"]]
        )
    for item in catalog.get("persistentVolumes", []):
        writer.writerow(
            ["", item["storageClass"], "", "pv", "spec.storageClassName",
             item["storageClass"], f"{float(item['hourlyPricePerGiBUSD']):.9f}", catalog["version"]]
        )
    return stream.getvalue()


def expected_price_expr(catalog: dict) -> str:
    entries = []
    for item in catalog["nodes"]:
        entries.append(
            f'{float(item["hourlyPriceUSD"]):.9f} * max by (node) '
            f'(kube_node_labels{{label_platform="{item["platform"]}",'
            f'label_topology_kubernetes_io_region="{item["region"]}",'
            f'label_node_kubernetes_io_instance_type="{item["instanceType"]}"}})'
        )
    return "\n  or\n".join(entries)


def generated(catalog: dict, policy: dict) -> str:
    pricing = csv_text(catalog)
    checksum = hashlib.sha256(pricing.encode()).hexdigest()
    reviewed = catalog["lastReviewedAt"]
    if isinstance(reviewed, date):
        reviewed = reviewed.isoformat()
    review_epoch = int(datetime.fromisoformat(str(reviewed)).replace(tzinfo=timezone.utc).timestamp())
    ready_nodes = 'max by (node) (kube_node_status_condition{condition="Ready",status="true"} == 1)'
    values = {
        "podAnnotations": {"checksum/node-pricing": checksum},
        "opencost": {
            "exporter": {
                "extraEnv": {"USE_CUSTOM_PROVIDER": "true", "USE_CSV_PROVIDER": "true", "CSV_PATH": "/var/configs/node-pricing.csv"},
                "extraVolumeMounts": [{"name": "opencost-pricing", "mountPath": "/var/configs", "readOnly": True}],
            },
            "customPricing": {"costModel": {
                "description": f"Cantaloupe allocation weights ({policy['version']})",
                "CPU": float(policy["weights"]["cpuUSDPerCoreHour"]),
                "spotCPU": float(policy["weights"]["cpuUSDPerCoreHour"]),
                "RAM": float(policy["weights"]["ramUSDPerGiBHour"]),
                "spotRAM": float(policy["weights"]["ramUSDPerGiBHour"]),
            }},
        },
        "extraVolumes": [{"name": "opencost-pricing", "configMap": {"name": "opencost-node-pricing"}}],
        "extraObjects": [
            {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "opencost-node-pricing", "namespace": "monitoring",
             "labels": {"app": "opencost", "area": "monitoring", "cost-model": catalog["version"]}},
             "data": {"node-pricing.csv": pricing}},
            {"apiVersion": "monitoring.coreos.com/v1", "kind": "PrometheusRule",
             "metadata": {"name": "cantaloupe-pricing-integrity", "namespace": "monitoring",
                          "labels": {"release": "monitoring", "app": "opencost", "area": "monitoring"}},
             "spec": {"groups": [{"name": "cantaloupe.finops.pricing", "interval": "1m", "rules": [
                 {"record": "cantaloupe:node_catalog_expected_cost_per_hour", "expr": expected_price_expr(catalog)},
                 {"record": "cantaloupe:pricing_catalog_last_review_timestamp_seconds", "expr": f"vector({review_epoch})"},
                 {"alert": "OpenCostPricingCoverageIncomplete", "expr": f"{ready_nodes} unless on (node) cantaloupe:node_catalog_expected_cost_per_hour", "for": "5m",
                  "labels": {"severity": "warning", "category": "finops"},
                  "annotations": {"summary": "가격표에 등록되지 않은 Kubernetes 노드가 있습니다", "description": "Ready 노드의 platform, region, instance-type 조합이 OpenCost 가격 카탈로그와 일치하지 않습니다.", "action": "노드 라벨을 확인하고 공식 가격을 조사한 뒤 pricing-catalog.yaml에 추가하고 generate_pricing.py를 실행하세요."}},
                 {"alert": "OpenCostNodePriceMismatch", "expr": "abs(max by (node) (node_total_hourly_cost) - on (node) cantaloupe:node_catalog_expected_cost_per_hour) > 0.0005", "for": "10m",
                  "labels": {"severity": "warning", "category": "finops"},
                  "annotations": {"summary": "OpenCost 적용 가격과 가격표가 일치하지 않습니다", "description": "생성된 CSV 가격과 node_total_hourly_cost 차이가 시간당 $0.0005를 초과했습니다.", "action": "OpenCost Pod의 가격표 checksum과 ConfigMap을 확인하고 Argo CD Sync 및 Pod 재시작 상태를 점검하세요."}},
                 {"alert": "OpenCostNodePricingLabelsMissing", "expr": f'{ready_nodes} unless on (node) max by (node) (kube_node_labels{{label_platform!="",label_role!="",label_topology_kubernetes_io_region!="",label_node_kubernetes_io_instance_type!=""}})', "for": "5m",
                  "labels": {"severity": "warning", "category": "finops"},
                  "annotations": {"summary": "Ready 노드에 필수 FinOps 라벨이 없습니다", "description": "platform, role, topology.kubernetes.io/region 또는 node.kubernetes.io/instance-type이 누락됐습니다.", "action": "01 인프라의 site-node-labels/site-verify 결과를 확인하고 누락 라벨을 보정하세요."}},
                 {"alert": "OpenCostInstanceTypeMetadataMissing", "expr": f'{ready_nodes} unless on (node) max by (node) (node_total_hourly_cost{{instance_type!=""}})', "for": "10m",
                  "labels": {"severity": "warning", "category": "finops"},
                  "annotations": {"summary": "OpenCost 노드 사양 메타데이터가 없습니다", "description": "OpenCost 비용 메트릭의 instance_type 값이 비어 있습니다.", "action": "Node의 node.kubernetes.io/instance-type 라벨과 OpenCost CSV 매칭 결과를 확인하세요."}},
                 {"alert": "OpenCostCloudProviderIDMissing", "expr": f'({ready_nodes} and on (node) max by (node) (kube_node_labels{{label_platform=~"aws|gcp"}})) unless on (node) max by (node) (node_total_hourly_cost{{provider_id!=""}})', "for": "10m",
                  "labels": {"severity": "warning", "category": "finops"},
                  "annotations": {"summary": "클라우드 노드의 providerID가 없습니다", "description": "AWS 또는 GCP Ready 노드의 OpenCost provider_id가 비어 있습니다. On-prem 노드는 검사 대상에서 제외됩니다.", "action": "Node spec.providerID와 kubelet --provider-id 설정을 확인하세요."}},
                 {"alert": "OpenCostProviderPlatformMismatch", "expr": '((max by (node) (kube_node_labels{label_platform="aws"}) unless on (node) max by (node) (node_total_hourly_cost{provider_id=~"aws://.*"})) or (max by (node) (kube_node_labels{label_platform="gcp"}) unless on (node) max by (node) (node_total_hourly_cost{provider_id=~"gce://.*"})))', "for": "10m",
                  "labels": {"severity": "warning", "category": "finops"},
                  "annotations": {"summary": "Node platform과 providerID 형식이 일치하지 않습니다", "description": "AWS 노드는 aws://, GCP 노드는 gce:// providerID를 사용해야 합니다.", "action": "VM 실제 공급자와 Node platform 라벨 및 spec.providerID를 비교하세요."}},
                 {"alert": "OpenCostPricingCatalogStale", "expr": f"time() - cantaloupe:pricing_catalog_last_review_timestamp_seconds > {int(catalog['reviewAfterDays']) * 86400}", "for": "1h",
                  "labels": {"severity": "warning", "category": "finops"},
                  "annotations": {"summary": "OpenCost 가격표 정기 검토일이 지났습니다", "description": f"pricing-catalog.yaml을 {catalog['reviewAfterDays']}일 이상 검토하지 않았습니다.", "action": "AWS/GCP 공개가격과 On-prem TCO 가정을 재확인하고 lastReviewedAt을 갱신하세요."}},
                 {"alert": "OpenCostCostMetricsAbsent", "expr": "absent(node_total_hourly_cost)", "for": "10m",
                  "labels": {"severity": "critical", "category": "finops"},
                  "annotations": {"summary": "OpenCost 노드 비용 메트릭이 수집되지 않습니다", "description": "Prometheus에서 node_total_hourly_cost를 찾을 수 없습니다.", "action": "OpenCost Pod, ServiceMonitor, Prometheus Target과 최근 로그를 순서대로 확인하세요."}},
             ]}]}}
        ],
    }
    header = "# GENERATED by generate_pricing.py. Do not edit manually.\n"
    return header + yaml.safe_dump(values, sort_keys=False, allow_unicode=True, width=120)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = generated(load_catalog(), load_allocation_policy())
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            print("generated-values.yaml is stale; run generate_pricing.py")
            return 1
        print("pricing catalog and generated values are valid")
        return 0
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
