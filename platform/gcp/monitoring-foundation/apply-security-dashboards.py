#!/usr/bin/env python3
"""Create the security metrics dashboard and add three summaries to Platform Overview."""

import argparse
import copy
import json
import os
import urllib.request
import urllib.error
import urllib.parse


SECURITY_NAMESPACES = "secops|logging|kyverno|cert-manager|external-secrets"
SECURITY_DEPLOYMENTS = "keycloak|oauth2-proxy|kyverno-.*|cert-manager.*|external-secrets.*"
SECURITY_PODS = "keycloak-.*|oauth2-proxy-.*|kyverno-.*|cert-manager-.*|external-secrets-.*"


def request(base_url, user, password, method, path, body=None):
    token = __import__("base64").b64encode(f"{user}:{password}".encode()).decode()
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Grafana API {method} {path} failed: HTTP {error.code}: {detail}") from error


def stat_panel(template, panel_id, title, description, expr, x, y):
    panel = copy.deepcopy(template)
    panel.update({"id": panel_id, "title": title, "description": description})
    panel["gridPos"] = {"x": x, "y": y, "w": 4, "h": 5}
    panel["targets"] = [{
        "datasource": copy.deepcopy(template["targets"][0].get("datasource")),
        "editorMode": "code", "expr": expr, "format": "time_series",
        "instant": True, "legendFormat": title, "range": False, "refId": "A",
    }]
    defaults = panel.setdefault("fieldConfig", {}).setdefault("defaults", {})
    defaults["unit"] = "short"
    defaults["noValue"] = "0"
    defaults["thresholds"] = {
        "mode": "absolute",
        "steps": [{"color": "green", "value": None}, {"color": "red", "value": 1}],
    }
    defaults["links"] = [{
        "title": "Platform Security Overview 열기",
        "url": "/grafana/d/cantaloupe-platform-security-overview/platform-security-overview?orgId=1",
    }]
    return panel


def query_panel(panel_id, title, panel_type, expr, x, y, w, h, datasource, instant=False):
    panel = {
        "id": panel_id, "title": title, "type": panel_type,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": datasource,
        "targets": [{
            "datasource": datasource, "editorMode": "code", "expr": expr,
            "format": "table" if panel_type == "table" else "time_series",
            "instant": instant, "legendFormat": "{{namespace}} / {{deployment}}",
            "range": not instant, "refId": "A",
        }],
        "fieldConfig": {"defaults": {"unit": "short", "noValue": "0", "thresholds": {
            "mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "red", "value": 1}]
        }}, "overrides": []},
        "options": {},
    }
    if panel_type == "stat":
        panel["options"] = {"colorMode": "background", "graphMode": "none", "justifyMode": "center",
                            "orientation": "auto", "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                            "textMode": "auto"}
    elif panel_type == "timeseries":
        panel["options"] = {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True},
                            "tooltip": {"mode": "multi", "sort": "desc"}}
    elif panel_type == "table":
        panel["options"] = {"showHeader": True, "cellHeight": "sm", "sortBy": []}
    return panel


def row(panel_id, title, y):
    return {"id": panel_id, "title": title, "type": "row", "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-dir")
    parser.add_argument("--write-only", action="store_true", help="Write provisioning JSON without calling the save API")
    parser.add_argument("--verify-prometheus-url")
    args = parser.parse_args()

    current = request(args.url, args.user, args.password, "GET", "/api/dashboards/uid/cantaloupe-v1-platform-overview")
    dashboard = current["dashboard"]
    top_titles = ["Ready / Total Node", "Running Pod", "Pending Pod", "Failed Pod", "Restart (1h)",
                  "Targets Down", "Karpenter Node", "KEDA Ready", "Fluent Bit Critical Alerts"]
    top = {panel.get("title"): panel for panel in dashboard["panels"] if panel.get("title") in top_titles}
    if set(top_titles) != set(top):
        raise RuntimeError("Platform Overview top panels do not match the expected layout")

    for panel in dashboard["panels"]:
        if panel.get("gridPos", {}).get("y", 0) >= 6:
            panel["gridPos"]["y"] += 5
    for index, title in enumerate(top_titles):
        top[title]["gridPos"] = {"x": (index % 6) * 4, "y": 1 + (index // 6) * 5, "w": 4, "h": 5}

    template = top["Fluent Bit Critical Alerts"]
    down_expr = (
        f'sum(clamp_min(kube_deployment_spec_replicas{{namespace=~"{SECURITY_NAMESPACES}",deployment=~"{SECURITY_DEPLOYMENTS}"}} '
        f'- kube_deployment_status_replicas_available{{namespace=~"{SECURITY_NAMESPACES}",deployment=~"{SECURITY_DEPLOYMENTS}"}}, 0)) or vector(0)'
    )
    restart_expr = f'round(sum(increase(kube_pod_container_status_restarts_total{{namespace=~"{SECURITY_NAMESPACES}",pod=~"{SECURITY_PODS}"}}[1h]))) or vector(0)'
    network_expr = 'count(kube_namespace_created{namespace!~"kube-public|kube-node-lease"}) - count(count by(namespace) (kube_networkpolicy_created{namespace!~"kube-public|kube-node-lease"}))'
    summaries = [
        stat_panel(template, 110, "Security Components Down", "Unavailable replicas for security components.", down_expr, 12, 6),
        stat_panel(template, 111, "Security Pod Restarts (1h)", "Security namespace container restarts during the last hour.", restart_expr, 16, 6),
        stat_panel(template, 112, "Namespaces Without NetworkPolicy", "Namespaces without an observed NetworkPolicy.", network_expr, 20, 6),
    ]
    dashboard["panels"] = [p for p in dashboard["panels"] if p.get("id") not in {110, 111, 112}] + summaries
    dashboard["version"] = int(dashboard.get("version", 0)) + 1

    datasource = copy.deepcopy(template["targets"][0].get("datasource"))
    security_panels = [
        row(900, "1. 긴급 상태", 0),
        query_panel(901, "Security Components Down", "stat", down_expr, 0, 1, 4, 5, datasource, True),
        query_panel(902, "Security Pod Restarts (1h)", "stat", restart_expr, 4, 1, 4, 5, datasource, True),
        query_panel(903, "Namespaces Without NetworkPolicy", "stat", network_expr, 8, 1, 4, 5, datasource, True),
        query_panel(904, "Security Pods Not Ready", "stat", f'sum(kube_pod_status_ready{{namespace=~"{SECURITY_NAMESPACES}",pod=~"{SECURITY_PODS}",condition="true"}} == 0) or vector(0)', 12, 1, 4, 5, datasource, True),
        query_panel(905, "Security Pods", "stat", f'count(kube_pod_info{{namespace=~"{SECURITY_NAMESPACES}",pod=~"{SECURITY_PODS}"}}) or vector(0)', 16, 1, 4, 5, datasource, True),
        query_panel(906, "Firing Security Alerts", "stat", f'count(ALERTS{{alertstate="firing",namespace=~"{SECURITY_NAMESPACES}"}}) or vector(0)', 20, 1, 4, 5, datasource, True),
        row(910, "2. 컴포넌트 상태", 6),
        query_panel(911, "Security Deployment Available Replicas", "timeseries", f'kube_deployment_status_replicas_available{{namespace=~"{SECURITY_NAMESPACES}",deployment=~"{SECURITY_DEPLOYMENTS}"}}', 0, 7, 12, 8, datasource),
        query_panel(912, "Security Container Restarts", "timeseries", f'sum by(namespace,pod) (increase(kube_pod_container_status_restarts_total{{namespace=~"{SECURITY_NAMESPACES}",pod=~"{SECURITY_PODS}"}}[15m]))', 12, 7, 12, 8, datasource),
        row(920, "3. 상세 확인", 15),
        query_panel(921, "Unavailable Security Deployments", "table", f'clamp_min(kube_deployment_spec_replicas{{namespace=~"{SECURITY_NAMESPACES}",deployment=~"{SECURITY_DEPLOYMENTS}"}} - kube_deployment_status_replicas_available{{namespace=~"{SECURITY_NAMESPACES}",deployment=~"{SECURITY_DEPLOYMENTS}"}}, 0) > 0', 0, 16, 12, 9, datasource, True),
        query_panel(922, "Security Pod Restart Details", "table", f'sum by(namespace,pod,container) (increase(kube_pod_container_status_restarts_total{{namespace=~"{SECURITY_NAMESPACES}",pod=~"{SECURITY_PODS}"}}[1h])) > 0', 12, 16, 12, 9, datasource, True),
        query_panel(923, "Namespaces With NetworkPolicy", "table", 'count by(namespace) (kube_networkpolicy_created)', 0, 25, 12, 9, datasource, True),
        query_panel(924, "Firing Security Alerts", "table", f'ALERTS{{alertstate="firing",namespace=~"{SECURITY_NAMESPACES}"}}', 12, 25, 12, 9, datasource, True),
    ]
    security_dashboard = {
        "id": None, "uid": "cantaloupe-platform-security-overview", "title": "Platform Security Overview",
        "tags": ["cantaloupe", "security", "platform"], "timezone": "browser", "schemaVersion": 42,
        "version": 1, "refresh": "30s", "time": {"from": "now-6h", "to": "now"},
        "panels": security_panels, "templating": {"list": []}, "annotations": {"list": []},
    }

    if args.verify_prometheus_url:
        failures = []
        for panel in security_panels:
            for target in panel.get("targets", []):
                query_url = args.verify_prometheus_url.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": target["expr"]})
                try:
                    with urllib.request.urlopen(query_url, timeout=15) as response:
                        result = json.load(response)
                    if result.get("status") != "success":
                        failures.append(f'{panel["title"]}: unsuccessful response')
                except Exception as error:
                    failures.append(f'{panel["title"]}: {error}')
        if failures:
            raise RuntimeError("Prometheus query verification failed: " + "; ".join(failures))
        print(f"Verified {sum(len(panel.get('targets', [])) for panel in security_panels)} Prometheus queries")

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
        with open(os.path.join(args.output_dir, "cantaloupe-v1-platform-overview.json"), "w", encoding="utf-8") as output:
            json.dump(dashboard, output, ensure_ascii=False, indent=2)
        with open(os.path.join(args.output_dir, "cantaloupe-platform-security-overview.json"), "w", encoding="utf-8") as output:
            json.dump(security_dashboard, output, ensure_ascii=False, indent=2)

    if args.dry_run:
        print(json.dumps({"platform": dashboard, "security": security_dashboard}, ensure_ascii=False))
        return
    if args.write_only:
        print("Provisioning JSON written")
        return
    request(args.url, args.user, args.password, "POST", "/api/dashboards/db",
            {"dashboard": dashboard, "folderUid": current["meta"].get("folderUid", "ffu8o2mu28zk0e"), "overwrite": True})
    request(args.url, args.user, args.password, "POST", "/api/dashboards/db",
            {"dashboard": security_dashboard, "folderUid": "ffu8o2mu28zk0e", "overwrite": True})
    print("Platform Overview and Platform Security Overview applied")


if __name__ == "__main__":
    main()
