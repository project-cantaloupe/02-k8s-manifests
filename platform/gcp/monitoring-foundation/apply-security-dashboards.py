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


def stat(panel_id, title, description, expr, x, y, *, w=6, h=5, danger_on_positive=False):
    steps = ([{"color": "green", "value": None}, {"color": "red", "value": 1}]
             if danger_on_positive else [{"color": "red", "value": None}, {"color": "green", "value": 1}])
    return {
        "id": panel_id, "title": title, "description": description, "type": "stat",
        "gridPos": {"x": x, "y": y, "w": w, "h": h}, "datasource": DATASOURCE,
        "targets": [{"datasource": DATASOURCE, "editorMode": "code", "expr": expr,
                     "format": "time_series", "instant": True, "range": False, "refId": "A"}],
        "fieldConfig": {"defaults": {"unit": "short", "noValue": "데이터 없음",
            "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
        "options": {"colorMode": "value", "graphMode": "none", "justifyMode": "center",
                    "orientation": "auto", "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "textMode": "auto"},
    }


def bar_gauge(panel_id, title, description, targets, x, y, w, h=5, colors=None):
    """Show related existing instant queries together without changing them."""
    return {
        "id": panel_id, "title": title, "description": description, "type": "bargauge",
        "gridPos": {"x": x, "y": y, "w": w, "h": h}, "datasource": DATASOURCE,
        "targets": [{"datasource": DATASOURCE, "editorMode": "code", "expr": expr,
                     "format": "time_series", "instant": True, "range": False,
                     "legendFormat": label, "refId": chr(ord("A") + index)}
                    for index, (label, expr) in enumerate(targets)],
        "fieldConfig": {"defaults": {"unit": "short", "noValue": "0",
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]}},
            "overrides": [
                {"matcher": {"id": "byName", "options": label},
                 "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]}
                for label, color in [("미적용", "red"), ("누락", "red"), ("Not Ready", "red"), ("실패", "red")]
            ] + [
                {"matcher": {"id": "byName", "options": label},
                 "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]}
                for label, color in (colors or [])
            ]},
        "options": {"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
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
    # These namespaces are deliberately excluded by
    # governance/secops/generate-default-network-policies.yaml because a
    # default deny would break gateways, admission webhooks, CNI, or mesh
    # traffic. Keep dashboard coverage aligned with the policy's real scope.
    network_policy_scoped_namespaces = (
        'namespace!~"kube-system|kube-public|kube-node-lease|default|kyverno|'
        'tigera-operator|calico-system|calico-apiserver|cert-manager|'
        'istio-system|audio-ingress|istio-cni|ztunnel"'
    )
    psa_scoped_namespaces = scoped_namespaces
    psa_unprotected = (
        f'count(kube_namespace_created{{{psa_scoped_namespaces}}}) - '
        f'count(kube_namespace_labels{{{psa_scoped_namespaces},'
        f'label_pod_security_kubernetes_io_enforce=~"restricted|baseline|privileged"}})'
    )
    namespace_without_policy = (
        f'count(kube_namespace_created{{{network_policy_scoped_namespaces}}}) - '
        f'count(count by(namespace) (kube_networkpolicy_created{{{network_policy_scoped_namespaces}}}))'
    )
    default_deny_missing = (
        f'count(kube_namespace_created{{{network_policy_scoped_namespaces}}}) - '
        f'count(count by(namespace) (kube_networkpolicy_created{{{network_policy_scoped_namespaces},networkpolicy=~"default-deny.*"}}))'
    )

    panels = [
        row(100, "1. 보안 상태 요약", 0),
        stat(101, "전체 보안 컴포넌트 이상", "Keycloak, OAuth2 Proxy, Kyverno, cert-manager, External Secrets의 미가용 replica 수입니다.", security_unavailable, 0, 1, danger_on_positive=True),
        stat(102, "PSA 미적용 네임스페이스", "시스템 기본 네임스페이스를 제외하고 PSA enforce 라벨이 없는 네임스페이스 수입니다. privileged는 적용된 예외 등급으로 별도 표시합니다.", psa_unprotected, 6, 1, danger_on_positive=True),
        stat(103, "NetworkPolicy 미적용 네임스페이스", "정책 생성 범위에서 NetworkPolicy가 하나도 없는 네임스페이스 수입니다. Gateway·Webhook·CNI·Mesh 예외는 제외합니다.", namespace_without_policy, 12, 1, danger_on_positive=True),
        stat(104, "Default Deny 누락 네임스페이스", "정책 생성 범위에서 default-deny 정책이 없는 네임스페이스 수입니다. 의도적 예외는 제외하며 실제 차단 건수는 아닙니다.", default_deny_missing, 18, 1, danger_on_positive=True),

        row(200, "2. 인증 / 접근 제어", 6),
        stat(201, "Keycloak 상태", "Keycloak Deployment의 desired 대비 available replica 차이입니다.", unavailable('namespace="secops",deployment="keycloak"'), 0, 7, danger_on_positive=True),
        stat(202, "OAuth2 Proxy 상태", "OAuth2 Proxy Deployment의 desired 대비 available replica 차이입니다.", unavailable('namespace="logging",deployment="oauth2-proxy"'), 6, 7, danger_on_positive=True),
        stat(204, "AuthorizationPolicy 적용 수", "kube-state-metrics가 실제 수집한 Istio AuthorizationPolicy 객체 수입니다. Denied 요청 수는 아닙니다.", 'sum(kube_customresource_authorizationpolicy)', 12, 7),
        stat(205, "AuthorizationPolicy 적용 네임스페이스", "AuthorizationPolicy 객체가 하나 이상 있는 네임스페이스 수입니다.", 'count(count by(namespace) (kube_customresource_authorizationpolicy))', 18, 7),
        series(203, "Keycloak / OAuth2 Proxy Available Replica", "인증·접근 제어 컴포넌트의 가용 replica 추이입니다. 인증 실패율과 OAuth 오류율은 현재 Prometheus Metric이 없어 포함하지 않습니다.", 'kube_deployment_status_replicas_available{namespace=~"secops|logging",deployment=~"keycloak|oauth2-proxy"}', 0, 12, 24, 8),

        row(300, "3. Kubernetes 정책 보안", 20),
        stat(301, "Kyverno 상태", "Kyverno 컨트롤러의 미가용 replica 수입니다.", unavailable('namespace="kyverno",deployment=~"kyverno-.*"'), 0, 21, danger_on_positive=True),
        bar_gauge(311, "PSA 적용 현황", "Restricted·Baseline·Privileged 예외·미적용을 같은 모집단에서 비교합니다.", [("Restricted", f'count(kube_namespace_labels{{{psa_scoped_namespaces},label_pod_security_kubernetes_io_enforce="restricted"}})'), ("Baseline", f'count(kube_namespace_labels{{{psa_scoped_namespaces},label_pod_security_kubernetes_io_enforce="baseline"}})'), ("Privileged 예외", f'count(kube_namespace_labels{{{psa_scoped_namespaces},label_pod_security_kubernetes_io_enforce="privileged"}})'), ("미적용", psa_unprotected)], 6, 21, 6),
        bar_gauge(312, "NetworkPolicy 적용 현황", "정책 생성 대상 Namespace의 적용·미적용 수입니다. 의도적 예외는 제외합니다.", [("적용", f'count(count by(namespace) (kube_networkpolicy_created{{{network_policy_scoped_namespaces}}}))'), ("미적용", namespace_without_policy)], 12, 21, 6),
        bar_gauge(313, "Default Deny 적용 현황", "정책 생성 대상 Namespace의 default-deny 적용·누락 수입니다. 의도적 예외는 제외합니다.", [("적용", f'count(count by(namespace) (kube_networkpolicy_created{{{network_policy_scoped_namespaces},networkpolicy=~"default-deny.*"}}))'), ("누락", default_deny_missing)], 18, 21, 6),
        series(309, "Kyverno 컨트롤러 Available Replica", "정책 엔진의 가용 replica 추이입니다.", 'kube_deployment_status_replicas_available{namespace="kyverno",deployment=~"kyverno-.*"}', 0, 26, 12, 8),
        series(310, "NetworkPolicy 적용 네임스페이스", "정책 생성 대상 Namespace의 정책 적용 상태입니다. 의도적 예외와 Calico 실제 차단 건수는 표시하지 않습니다.", f'count by(namespace) (kube_networkpolicy_created{{{network_policy_scoped_namespaces}}})', 12, 26, 12, 8, legend_format="{{namespace}}"),

        row(320, "4. Kyverno 정책 결과", 34),
        stat(321, "최근 1시간 Kyverno 정책 위반", "최근 1시간 rule_result=fail로 기록된 Kyverno 정책 결과 수입니다. 상세 리소스와 원인은 OpenSearch 보안 로그에서 확인합니다.", 'sum(increase(kyverno_policy_results_total{rule_result=~"(?i:fail)"}[1h])) or vector(0)', 0, 35, w=8, danger_on_positive=True),
        stat(322, "Kyverno 메트릭 수집 이상", "Kyverno Prometheus Target이 Down이거나 Target 자체가 없으면 1 이상입니다.", '(sum(up{namespace="kyverno"} == 0) or vector(0)) + (absent(up{namespace="kyverno"}) or vector(0))', 8, 35, w=8, danger_on_positive=True),
        stat(323, "최근 1시간 Admission 거부", "Admission 요청 처리 중 fail로 기록된 Kyverno 정책 결과 수입니다.", 'sum(increase(kyverno_policy_results_total{rule_result=~"(?i:fail)",rule_execution_cause="admission_request"}[1h])) or vector(0)', 16, 35, w=8, danger_on_positive=True),
        series(324, "정책별 Kyverno 위반 추이", "위반 증가량을 policy_name별로 표시합니다. 상세 리소스와 메시지는 OpenSearch에서 확인합니다.", 'sum by(policy_name) (increase(kyverno_policy_results_total{rule_result=~"(?i:fail)"}[$__rate_interval]))', 0, 40, 24, 8, legend_format="{{policy_name}}"),

        row(400, "5. 자격증명 / 인증서", 48),
        stat(401, "cert-manager 상태", "cert-manager 컴포넌트의 미가용 replica 수입니다.", unavailable('namespace="cert-manager",deployment=~"cert-manager|cert-manager-cainjector|cert-manager-webhook"'), 0, 49, danger_on_positive=True),
        stat(402, "External Secrets 상태", "External Secrets 컴포넌트의 미가용 replica 수입니다.", unavailable('namespace="external-secrets",deployment=~"external-secrets|external-secrets-cert-controller|external-secrets-webhook"'), 6, 49, danger_on_positive=True),
        bar_gauge(411, "Certificate 상태", "Ready·Not Ready·만료 예정은 cert-manager의 기존 Certificate Metric을 함께 표시합니다.", [("Ready", 'sum(certmanager_certificate_ready_status{condition="True"})'), ("Not Ready", 'sum(certmanager_certificate_ready_status{condition="False"})'), ("30일 이내 만료", 'count((certmanager_certificate_expiration_timestamp_seconds - time() > 0) and (certmanager_certificate_expiration_timestamp_seconds - time() <= 30 * 24 * 60 * 60)) or vector(0)'), ("7일 이내 만료", 'count((certmanager_certificate_expiration_timestamp_seconds - time() > 0) and (certmanager_certificate_expiration_timestamp_seconds - time() <= 7 * 24 * 60 * 60)) or vector(0)')], 12, 49, 12, colors=[("Ready", "green"), ("Not Ready", "red"), ("30일 이내 만료", "orange"), ("7일 이내 만료", "red")]),
        bar_gauge(412, "ExternalSecret Sync 상태", "ExternalSecret Ready 조건의 정상·실패 수입니다.", [("정상", 'sum(externalsecret_status_condition{condition="Ready",status="True"})'), ("실패", 'sum(externalsecret_status_condition{condition="Ready",status="False"})')], 0, 54, 12),
        stat(410, "Provider 접근 오류 (1시간)", "최근 1시간 External Secrets Provider API 호출 중 success 이외 상태의 증가량입니다.", 'sum(increase(externalsecret_provider_api_calls_count{status!="success"}[1h])) or vector(0)', 12, 54, w=12, danger_on_positive=True),
        series(403, "인증서·Secret 컴포넌트 Available Replica", "cert-manager 및 External Secrets Deployment 가용 replica 추이입니다.", 'kube_deployment_status_replicas_available{namespace=~"cert-manager|external-secrets"}', 0, 59, 24, 8),

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
