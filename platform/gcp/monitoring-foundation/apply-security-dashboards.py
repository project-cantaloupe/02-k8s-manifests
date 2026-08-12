#!/usr/bin/env python3
"""Build the Grafana dashboard for security-control state.

This dashboard intentionally uses Prometheus/Kubernetes-state metrics only. It
does not duplicate OpenSearch security-event evidence and never infers policy
denials from arbitrary log text.
"""

import argparse
import json
import urllib.error
import urllib.request


DATASOURCE = {"type": "prometheus", "uid": "prometheus"}
SECURITY_COMPONENTS = (
    'namespace=~"secops|logging|kyverno|cert-manager|external-secrets",'
    'deployment=~"keycloak|oauth2-proxy|kyverno-.*|cert-manager.*|external-secrets.*"'
)


def request(base_url, user, password, method, path, body=None):
    import base64
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Grafana API {method} {path}: HTTP {error.code}: "
                           f"{error.read().decode(errors='replace')}") from error


def row(panel_id, title, y):
    return {"id": panel_id, "title": title, "type": "row", "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def stat(panel_id, title, description, expr, x, y, *, danger_on_positive=False):
    steps = ([{"color": "green", "value": None}, {"color": "red", "value": 1}]
             if danger_on_positive else [{"color": "red", "value": None}, {"color": "green", "value": 1}])
    return {
        "id": panel_id, "title": title, "description": description, "type": "stat",
        "gridPos": {"x": x, "y": y, "w": 4, "h": 5}, "datasource": DATASOURCE,
        "targets": [{"datasource": DATASOURCE, "editorMode": "code", "expr": expr,
                     "format": "time_series", "instant": True, "range": False, "refId": "A"}],
        "fieldConfig": {"defaults": {"unit": "short", "noValue": "데이터 없음",
            "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
        "options": {"colorMode": "value", "graphMode": "none", "justifyMode": "center",
                    "orientation": "auto", "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "textMode": "auto"},
    }


def series(panel_id, title, description, expr, x, y, w=12, h=8,
           legend_format="{{namespace}} / {{deployment}}"):
    return {
        "id": panel_id, "title": title, "description": description, "type": "timeseries",
        "gridPos": {"x": x, "y": y, "w": w, "h": h}, "datasource": DATASOURCE,
        "targets": [{"datasource": DATASOURCE, "editorMode": "code", "expr": expr,
                     "format": "time_series", "instant": False, "range": True,
                     "legendFormat": legend_format, "refId": "A"}],
        "fieldConfig": {"defaults": {"unit": "short", "noValue": "데이터 없음",
            "color": {"mode": "palette-classic"}, "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]}},
            "overrides": []},
        "options": {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }


def dashboard():
    unavailable = lambda selector: (
        f"sum(clamp_min(kube_deployment_spec_replicas{{{selector}}} - "
        f"kube_deployment_status_replicas_available{{{selector}}}, 0))"
    )
    security_unavailable = unavailable(SECURITY_COMPONENTS)
    scoped_namespaces = 'namespace!~"kube-system|kube-public|kube-node-lease|default"'
    psa_scoped_namespaces = scoped_namespaces
    psa_unprotected = (
        f'count(kube_namespace_created{{{psa_scoped_namespaces}}}) - '
        f'count(kube_namespace_labels{{{psa_scoped_namespaces},'
        f'label_pod_security_kubernetes_io_enforce=~"restricted|baseline"}})'
    )
    namespace_without_policy = (
        f'count(kube_namespace_created{{{scoped_namespaces}}}) - '
        f'count(count by(namespace) (kube_networkpolicy_created{{{scoped_namespaces}}}))'
    )
    default_deny_missing = (
        f'count(kube_namespace_created{{{scoped_namespaces}}}) - '
        f'count(count by(namespace) (kube_networkpolicy_created{{{scoped_namespaces},networkpolicy=~"default-deny.*"}}))'
    )

    panels = [
        row(100, "1. 보안 상태 요약", 0),
        stat(101, "전체 보안 컴포넌트 이상", "Keycloak, OAuth2 Proxy, Kyverno, cert-manager, External Secrets의 미가용 replica 수입니다.", security_unavailable, 0, 1, danger_on_positive=True),
        stat(102, "PSA 미적용 네임스페이스", "시스템 기본 네임스페이스를 제외하고 PSA enforce=restricted 또는 baseline이 아닌 네임스페이스 수입니다. privileged는 보호 적용으로 집계하지 않습니다.", psa_unprotected, 6, 1, danger_on_positive=True),
        stat(103, "NetworkPolicy 미적용 네임스페이스", "시스템 기본 네임스페이스를 제외하고 NetworkPolicy가 하나도 없는 네임스페이스 수입니다.", namespace_without_policy, 12, 1, danger_on_positive=True),
        stat(104, "Default Deny 누락 네임스페이스", "default-deny 이름의 정책이 없는 네임스페이스 수입니다. 실제 차단 건수가 아닙니다.", default_deny_missing, 18, 1, danger_on_positive=True),

        row(200, "2. 인증 / 접근 제어", 6),
        stat(201, "Keycloak 상태", "Keycloak Deployment의 desired 대비 available replica 차이입니다.", unavailable('namespace="secops",deployment="keycloak"'), 0, 7, danger_on_positive=True),
        stat(202, "OAuth2 Proxy 상태", "OAuth2 Proxy Deployment의 desired 대비 available replica 차이입니다.", unavailable('namespace="logging",deployment="oauth2-proxy"'), 6, 7, danger_on_positive=True),
        series(203, "Keycloak / OAuth2 Proxy Available Replica", "인증·접근 제어 컴포넌트의 가용 replica 추이입니다. 인증 실패율과 OAuth 오류율은 현재 Prometheus Metric이 없어 포함하지 않습니다.", 'kube_deployment_status_replicas_available{namespace=~"secops|logging",deployment=~"keycloak|oauth2-proxy"}', 0, 12, 24, 8),

        row(300, "3. Kubernetes 정책 보안", 20),
        stat(301, "Kyverno 상태", "Kyverno 컨트롤러의 미가용 replica 수입니다. 적용 정책 수·Enforce/Audit·위반 수는 Metric 수집 후 추가합니다.", unavailable('namespace="kyverno",deployment=~"kyverno-.*"'), 0, 21, danger_on_positive=True),
        stat(302, "Restricted 적용 네임스페이스", "시스템 기본 네임스페이스를 제외하고 PSA enforce=restricted 라벨이 있는 네임스페이스 수입니다.", f'count(kube_namespace_labels{{{psa_scoped_namespaces},label_pod_security_kubernetes_io_enforce="restricted"}})', 4, 21),
        stat(303, "Baseline 적용 네임스페이스", "시스템 기본 네임스페이스를 제외하고 PSA enforce=baseline 라벨이 있는 네임스페이스 수입니다.", f'count(kube_namespace_labels{{{psa_scoped_namespaces},label_pod_security_kubernetes_io_enforce="baseline"}})', 8, 21),
        stat(304, "PSA 미적용 네임스페이스", "상단 KPI와 같은 모집단입니다. privileged는 보호 적용으로 집계하지 않습니다.", psa_unprotected, 12, 21, danger_on_positive=True),
        stat(305, "NetworkPolicy 적용 네임스페이스", "시스템 기본 네임스페이스를 제외하고 하나 이상의 NetworkPolicy가 있는 네임스페이스 수입니다.", f'count(count by(namespace) (kube_networkpolicy_created{{{scoped_namespaces}}}))', 16, 21),
        stat(306, "NetworkPolicy 미적용 네임스페이스", "시스템 기본 네임스페이스를 제외하고 NetworkPolicy가 하나도 없는 네임스페이스 수입니다.", namespace_without_policy, 20, 21, danger_on_positive=True),
        stat(307, "Default Deny 적용 네임스페이스", "시스템 기본 네임스페이스를 제외하고 default-deny 이름 정책이 있는 네임스페이스 수입니다.", f'count(count by(namespace) (kube_networkpolicy_created{{{scoped_namespaces},networkpolicy=~"default-deny.*"}}))', 0, 26),
        stat(308, "Default Deny 누락 네임스페이스", "상단 KPI와 같은 모집단에서 default-deny 이름 정책이 없는 네임스페이스 수입니다.", default_deny_missing, 4, 26, danger_on_positive=True),
        series(309, "Kyverno 컨트롤러 Available Replica", "정책 엔진의 가용 replica 추이입니다. 정책 적용 현황 Metric은 수집 후 별도 패널로 추가합니다.", 'kube_deployment_status_replicas_available{namespace="kyverno",deployment=~"kyverno-.*"}', 0, 31, 12, 8),
        series(310, "NetworkPolicy 적용 네임스페이스", "시스템 기본 네임스페이스를 제외한 정책 적용 상태입니다. Calico 실제 차단 건수는 표시하지 않습니다.", f'count by(namespace) (kube_networkpolicy_created{{{scoped_namespaces}}})', 12, 31, 12, 8, legend_format="{{namespace}}"),

        row(400, "4. 자격증명 / 인증서", 39),
        stat(401, "cert-manager 상태", "cert-manager 컴포넌트의 미가용 replica 수입니다. Certificate Ready/만료/갱신 실패는 Metric 수집 후 추가합니다.", unavailable('namespace="cert-manager",deployment=~"cert-manager|cert-manager-cainjector|cert-manager-webhook"'), 0, 40, danger_on_positive=True),
        stat(402, "External Secrets 상태", "External Secrets 컴포넌트의 미가용 replica 수입니다. Secret Sync·Provider 오류는 Metric 수집 후 추가합니다.", unavailable('namespace="external-secrets",deployment=~"external-secrets|external-secrets-cert-controller|external-secrets-webhook"'), 6, 40, danger_on_positive=True),
        series(403, "인증서·Secret 컴포넌트 Available Replica", "cert-manager 및 External Secrets Deployment 가용 replica 추이입니다.", 'kube_deployment_status_replicas_available{namespace=~"cert-manager|external-secrets"}', 0, 45, 24, 8),

    ]
    return {"id": None, "uid": "cantaloupe-platform-security-overview", "title": "Platform Security Controls",
            "tags": ["cantaloupe", "security", "controls"], "timezone": "browser", "schemaVersion": 42,
            "version": 1, "refresh": "30s", "time": {"from": "now-6h", "to": "now"},
            "panels": panels, "templating": {"list": []}, "annotations": {"list": []}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url")
    parser.add_argument("--user")
    parser.add_argument("--password")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = dashboard()
    if args.dry_run:
        print(json.dumps(result, ensure_ascii=False))
        return
    if not all([args.url, args.user, args.password]):
        parser.error("--url, --user and --password are required unless --dry-run is used")
    request(args.url, args.user, args.password, "POST", "/api/dashboards/db",
            {"dashboard": result, "folderUid": "ffu8o2mu28zk0e", "overwrite": True})
    print("Platform Security Controls applied")


if __name__ == "__main__":
    main()
