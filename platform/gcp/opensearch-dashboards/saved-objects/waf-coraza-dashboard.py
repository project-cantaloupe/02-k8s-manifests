#!/usr/bin/env python3
# Builds the Coraza WAF dashboard saved objects for OpenSearch Dashboards.
#
# Emits a POSIX sh script rather than calling the API itself: Dashboards sits
# behind the oauth2-proxy SSO gate, so an unauthenticated curl from outside
# gets a 302. The generated script has to run from inside the cluster, where
# `opensearch-dashboards:5601` is reachable directly.
#
#   # 1. read the live index pattern (it carries the existing field list)
#   kubectl -n logging exec opensearch-cluster-master-0 -c opensearch -- curl -s \
#     http://opensearch-dashboards:5601/api/saved_objects/index-pattern/cantaloupe-app-logs-v1 > ip.json
#   # 2. generate and run
#   python3 waf-coraza-dashboard.py ip.json > apply.sh
#   kubectl -n logging cp apply.sh opensearch-cluster-master-0:/tmp/apply.sh
#   kubectl -n logging exec opensearch-cluster-master-0 -c opensearch -- sh /tmp/apply.sh
#
# Deliberately not applied by Argo CD - Dashboards saved objects are
# application data, not Kubernetes workloads. Same stance as the sibling
# scripts in this directory.
#
# Separate from the Keycloak/OAuth2/Kyverno "보안 로그 대시보드"
# (security-logs-*): that one reads cantaloupe-platform-logs-v2, this one
# reads cantaloupe-app-logs-v1. Deleting either leaves the other intact.
#
# The waf_* fields it queries come from parse_coraza_security() in
# platform/gcp/fluent-bit/configmap.yaml and must be mapped in
# platform/gcp/opensearch/ism/configmap.yaml - the index is `dynamic: false`,
# so an unmapped field aggregates to an empty bucket without any error.
# → tasks/todo/023_waf-blocking-and-siem.md

import json, os, sys

IP_ID = "cantaloupe-app-logs-v1"
V2 = os.getenv("WAF_DASHBOARD_VERSION") == "2"
ID_SUFFIX = "-v2" if V2 else ""
DASH_ID = "waf-coraza-overview-v2" if V2 else "waf-coraza-overview-v1"
WAF_Q = 'security_event_type : "waf_rule_match"'
INGRESS_Q = 'event_type : "ingress_request_completed"'

IDX_REF = [{"name": "kibanaSavedObjectMeta.searchSourceJSON.index", "id": IP_ID, "type": "index-pattern"}]
objs = []   # (type, id, attributes, references)

def ss(query):
    return json.dumps({"query": {"query": query, "language": "kuery"}, "filter": [],
                       "indexRefName": "kibanaSavedObjectMeta.searchSourceJSON.index"},
                      separators=(",", ":"))

def vis(vid, title, desc, state, query):
    objs.append(("visualization", vid + ID_SUFFIX, {
        "title": title, "description": desc, "version": 1, "uiStateJSON": "{}",
        "visState": json.dumps(state, separators=(",", ":"), ensure_ascii=False),
        "kibanaSavedObjectMeta": {"searchSourceJSON": ss(query)}}, IDX_REF))

def axes(cat_pos="bottom", val_pos="left", val_title="건수"):
    return {
        "categoryAxes": [{"id": "CategoryAxis-1", "type": "category", "position": cat_pos, "show": True,
                          "style": {}, "scale": {"type": "linear"},
                          "labels": {"show": True, "rotate": 0, "filter": True, "truncate": 100},
                          "title": {}}],
        "valueAxes": [{"id": "ValueAxis-1", "name": "LeftAxis-1", "type": "value", "position": val_pos,
                       "show": True, "style": {}, "scale": {"type": "linear", "mode": "normal"},
                       "labels": {"show": True, "rotate": 0, "filter": False, "truncate": 100},
                       "title": {"text": val_title}}]}

def series(label="건수", stacked="normal", bar=0.6):
    return [{"show": True, "type": "histogram", "mode": stacked, "data": {"label": label, "id": "1"},
             "valueAxis": "ValueAxis-1", "drawLinesBetweenPoints": True, "showCircles": True,
             "lineWidth": 2, "barWidth": bar}]

# --- 1. 요약 타일 -----------------------------------------------------------
def metric(vid, title, desc, query, label, agg=None, threshold=0):
    a = agg or {"id": "1", "enabled": True, "type": "count", "schema": "metric",
                "params": {"customLabel": label}}
    ranges = ([{"from": 0, "to": threshold}, {"from": threshold, "to": 1000000}]
              if threshold else [{"from": 0, "to": 1000000}])
    vis(vid, title, desc, {
        "title": title, "type": "metric", "aggs": [a],
        "params": {"addTooltip": True, "addLegend": False, "type": "metric",
                   "metric": {"percentageMode": False, "useRanges": bool(threshold),
                              "colorSchema": "Green to Red",
                              "metricColorMode": "Labels" if threshold else "None",
                              "invertColors": False, "colorsRange": ranges,
                              "labels": {"show": True},
                              "style": {"bgFill": "#000", "bgColor": False, "labelColor": False,
                                        "fontSize": 36, "subText": ""}}}}, query)

metric("waf-total-detections", "WAF 룰 탐지 횟수" if V2 else "WAF 탐지 총 건수",
       "요청 수가 아니라 Coraza 룰이 발화한 횟수다. 요청 하나가 여러 룰에 걸리면 여러 번 집계된다." if V2 else
       "Coraza 룰이 발화한 전체 건수. 탐지 모드에서도 계속 증가한다.", WAF_Q, "룰 탐지" if V2 else "탐지")
metric("waf-blocked-count", "실제 차단 건수",
       "SecRuleEngine On 에서만 증가한다. DetectionOnly 동안은 0 이 정상이며, 이 값이 오르는 순간이 차단 전환 시점이다.",
       WAF_Q + ' and waf_action : "blocked"', "차단", threshold=1)
# ⚠️ 949110(phase 2) 과 949111(phase 1) 을 함께 센다.
# DetectionOnly 는 끝까지 평가해 둘 다 찍지만, SecRuleEngine On 은 임계값에
# 닿는 phase 1 에서 즉시 거절하므로 949110 이 아예 실행되지 않는다.
# 949110 만 세면 차단 전환 순간 이 타일이 멈춘 것처럼 보인다.
metric("waf-threshold-exceeded", "이상점수 임계 초과 판정 횟수" if V2 else "이상점수 임계 초과",
       "CRS 차단 평가 룰(949110·949111)의 판정 횟수다. 룰 탐지 횟수와 실제 공격 요청 수를 구분하기 위한 보조 지표이며, DetectionOnly에서는 한 요청이 두 평가 룰에 기록될 수 있다." if V2 else
       "CRS 차단 평가 룰(949110·949111) 발화 건수. 탐지 모드에서는 「차단 모드였다면 403 이 되었을 요청」, 차단 모드에서는 실제로 거절된 요청을 뜻한다.",
       'waf_rule_id : ("949110" or "949111")', "판정" if V2 else "요청")
metric("waf-unique-attackers", "공격 출발 IP 수",
       "고유 클라이언트 IP 수. externalTrafficPolicy: Local 이 아니면 항상 노드 수만큼만 나온다.",
       WAF_Q, "IP", agg={"id": "1", "enabled": True, "type": "cardinality", "schema": "metric",
                          "params": {"field": "waf_client_ip", "customLabel": "IP"}})

# --- 2. 무엇을 잡았나 -------------------------------------------------------
attack_family_agg = ({"id": "2", "enabled": True, "type": "filters", "schema": "segment",
                      "params": {"filters": [
                          {"label": "SQL Injection", "input": {"query": 'waf_rule_group : "REQUEST-942-APPLICATION-ATTACK-SQLI"', "language": "kuery"}},
                          {"label": "Cross-Site Scripting", "input": {"query": 'waf_rule_group : "REQUEST-941-APPLICATION-ATTACK-XSS"', "language": "kuery"}},
                          {"label": "로컬 파일 접근", "input": {"query": 'waf_rule_group : "REQUEST-930-APPLICATION-ATTACK-LFI"', "language": "kuery"}},
                          {"label": "원격 파일 접근", "input": {"query": 'waf_rule_group : "REQUEST-931-APPLICATION-ATTACK-RFI"', "language": "kuery"}},
                          {"label": "원격 명령 실행", "input": {"query": 'waf_rule_group : "REQUEST-932-APPLICATION-ATTACK-RCE"', "language": "kuery"}},
                          {"label": "PHP Injection", "input": {"query": 'waf_rule_group : "REQUEST-933-APPLICATION-ATTACK-PHP"', "language": "kuery"}},
                          {"label": "일반 애플리케이션 공격", "input": {"query": 'waf_rule_group : "REQUEST-934-APPLICATION-ATTACK-GENERIC"', "language": "kuery"}},
                          {"label": "비정상 HTTP 요청", "input": {"query": 'waf_rule_group : "REQUEST-920-PROTOCOL-ENFORCEMENT"', "language": "kuery"}},
                          {"label": "HTTP 프로토콜 공격", "input": {"query": 'waf_rule_group : "REQUEST-921-PROTOCOL-ATTACK"', "language": "kuery"}},
                          {"label": "보안 스캐너 탐지", "input": {"query": 'waf_rule_group : "REQUEST-913-SCANNER-DETECTION"', "language": "kuery"}}
                      ]}} if V2 else
                     {"id": "2", "enabled": True, "type": "terms", "schema": "segment",
                      "params": {"field": "waf_rule_group", "size": 12, "order": "desc", "orderBy": "1",
                                 "otherBucket": False, "missingBucket": False, "customLabel": "공격군"}})
vis("waf-attack-families", "탐지된 공격 유형" if V2 else "공격 유형별 탐지 건수",
    "이해하기 쉬운 공격명으로 묶으며 CRS 차단 평가 룰(949xxx)은 제외한다." if V2 else
    "CRS 룰 파일 기준 공격군. 룰 ID 로 묶으면 같은 공격의 변종이 흩어져 보인다.",
    {"title": "탐지된 공격 유형" if V2 else "공격 유형별 탐지 건수", "type": "horizontal_bar",
     "aggs": [{"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}},
              attack_family_agg],
     "params": dict({"type": "histogram", "grid": {"categoryLines": False}, "addTooltip": True,
                     "addLegend": False, "legendPosition": "right", "seriesParams": series(bar=0.6),
                     "times": [], "addTimeMarker": False, "labels": {"show": False}},
                    **axes(cat_pos="left", val_pos="bottom"))}, WAF_Q)

vis("waf-top-rules", "발화 룰 Top 15",
    "룰 ID 별 히트 수. 오탐 후보를 여기서 고른다 — 정상 경로에서 뜨는 룰이 예외 대상이다.",
    {"title": "발화 룰 Top 15", "type": "table",
     "aggs": [{"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {"customLabel": "건수"}},
              {"id": "2", "enabled": True, "type": "terms", "schema": "bucket",
               "params": {"field": "waf_rule_id", "size": 15, "order": "desc", "orderBy": "1",
                          "otherBucket": False, "missingBucket": False, "customLabel": "룰 ID"}},
              {"id": "3", "enabled": True, "type": "terms", "schema": "bucket",
               "params": {"field": "waf_msg", "size": 1, "order": "desc", "orderBy": "1",
                          "otherBucket": False, "missingBucket": False, "customLabel": "설명"}}],
     "params": {"perPage": 15, "showPartialRows": False, "showMetricsAtAllLevels": False,
                "sort": {"columnIndex": 2, "direction": "desc"}, "showTotal": False,
                "totalFunc": "sum", "percentageCol": ""}}, WAF_Q)

# --- 3. 누가 / 어디를 -------------------------------------------------------
vis("waf-top-attackers", "공격 출발 IP Top 10",
    "차단 목록 후보. WAF 레코드에만 원본 IP 가 남고 액세스 로그는 /24 로 마스킹된다.",
    {"title": "공격 출발 IP Top 10", "type": "table",
     "aggs": [{"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {"customLabel": "건수"}},
              {"id": "2", "enabled": True, "type": "terms", "schema": "bucket",
               "params": {"field": "waf_client_ip", "size": 10, "order": "desc", "orderBy": "1",
                          "otherBucket": False, "missingBucket": False, "customLabel": "출발 IP"}}],
     "params": {"perPage": 10, "showPartialRows": False, "showMetricsAtAllLevels": False,
                "sort": {"columnIndex": 1, "direction": "desc"}, "showTotal": False,
                "totalFunc": "sum", "percentageCol": ""}}, WAF_Q)

vis("waf-target-paths", "표적 경로 Top 10",
    "공격이 노린 경로. 정상 앱 경로가 여기 올라오면 오탐을 의심한다.",
    {"title": "표적 경로 Top 10", "type": "table",
     "aggs": [{"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {"customLabel": "건수"}},
              {"id": "2", "enabled": True, "type": "terms", "schema": "bucket",
               "params": {"field": "waf_uri", "size": 10, "order": "desc", "orderBy": "1",
                          "otherBucket": False, "missingBucket": False, "customLabel": "경로"}}],
     "params": {"perPage": 10, "showPartialRows": False, "showMetricsAtAllLevels": False,
                "sort": {"columnIndex": 1, "direction": "desc"}, "showTotal": False,
                "totalFunc": "sum", "percentageCol": ""}}, WAF_Q)

risk_agg = ({"id": "2", "enabled": True, "type": "filters", "schema": "segment",
             "params": {"filters": [
                 {"label": "임계값 미만 (0~4)", "input": {"query": "waf_anomaly_score >= 0 and waf_anomaly_score < 5", "language": "kuery"}},
                 {"label": "차단 기준 도달 (5~9)", "input": {"query": "waf_anomaly_score >= 5 and waf_anomaly_score < 10", "language": "kuery"}},
                 {"label": "고위험 (10~14)", "input": {"query": "waf_anomaly_score >= 10 and waf_anomaly_score < 15", "language": "kuery"}},
                 {"label": "매우 높은 위험 (15 이상)", "input": {"query": "waf_anomaly_score >= 15", "language": "kuery"}}
             ]}} if V2 else
            {"id": "2", "enabled": True, "type": "histogram", "schema": "segment",
             "params": {"field": "waf_anomaly_score", "interval": 5, "extended_bounds": {},
                        "customLabel": "이상점수"}})
vis("waf-anomaly-distribution", "공격 위험도별 요청 분포" if V2 else "이상점수 분포",
    "이상점수를 임계값 미만, 차단 기준 도달, 고위험, 매우 높은 위험으로 구간화한다." if V2 else
    "CRS 는 severity 로 점수를 더한다(critical 5 / error 4 / warning 3 / notice 2). 임계값 5 이상이 차단 대상이다.",
    {"title": "공격 위험도별 요청 분포" if V2 else "이상점수 분포", "type": "histogram",
     "aggs": [{"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}},
              risk_agg],
     "params": dict({"type": "histogram", "grid": {"categoryLines": False}, "addTooltip": True,
                     "addLegend": False, "legendPosition": "right", "seriesParams": series(bar=0.8),
                     "times": [], "addTimeMarker": False, "labels": {"show": False}}, **axes())},
    'waf_anomaly_score : *')

# --- 4. 시간 추이 -----------------------------------------------------------
vis("waf-events-over-time", "시간대별 탐지·차단 추이",
    "탐지에서 차단으로 넘어간 시점이 계열 분리로 드러난다.",
    {"title": "시간대별 탐지·차단 추이", "type": "histogram",
     "aggs": [{"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}},
              {"id": "2", "enabled": True, "type": "date_histogram", "schema": "segment",
               "params": {"field": "@timestamp", "timeRange": {"from": "now-24h", "to": "now"},
                          "useNormalizedOsdInterval": True, "interval": "auto", "drop_partials": False,
                          "min_doc_count": 1, "extended_bounds": {}}},
              {"id": "3", "enabled": True, "type": "terms", "schema": "group",
               "params": {"field": "waf_action", "size": 5, "order": "desc", "orderBy": "1",
                          "otherBucket": False, "missingBucket": False, "customLabel": "조치"}}],
     "params": dict({"type": "histogram", "grid": {"categoryLines": False}, "addTooltip": True,
                     "addLegend": True, "legendPosition": "right",
                     "seriesParams": series(stacked="stacked", bar=0.9),
                     "times": [], "addTimeMarker": False, "labels": {"show": False}}, **axes())}, WAF_Q)

# --- 5. 차단 검증 (액세스 로그) ---------------------------------------------
vis("waf-403-by-reason", "403 응답의 원인별 분해",
    "WAF 차단과 Istio RBAC 거부는 둘 다 403 이다. response_code_details 로 갈라야 WAF 차단 건수를 과대계상하지 않는다.",
    {"title": "403 응답의 원인별 분해", "type": "table",
     "aggs": [{"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {"customLabel": "건수"}},
              {"id": "2", "enabled": True, "type": "terms", "schema": "bucket",
               "params": {"field": "response_code_details", "size": 10, "order": "desc", "orderBy": "1",
                          "otherBucket": False, "missingBucket": False, "customLabel": "종료 사유"}}],
     "params": {"perPage": 10, "showPartialRows": False, "showMetricsAtAllLevels": False,
                "sort": {"columnIndex": 1, "direction": "desc"}, "showTotal": False,
                "totalFunc": "sum", "percentageCol": ""}},
    INGRESS_Q + ' and http_status : 403')

vis("waf-ingress-status", "게이트웨이 응답 코드 추이",
    "정상 회귀 감시용. 차단 전환 뒤 4xx 가 정상 경로에서 튀면 오탐이다.",
    {"title": "게이트웨이 응답 코드 추이", "type": "histogram",
     "aggs": [{"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}},
              {"id": "2", "enabled": True, "type": "date_histogram", "schema": "segment",
               "params": {"field": "@timestamp", "timeRange": {"from": "now-24h", "to": "now"},
                          "useNormalizedOsdInterval": True, "interval": "auto", "drop_partials": False,
                          "min_doc_count": 1, "extended_bounds": {}}},
              {"id": "3", "enabled": True, "type": "terms", "schema": "group",
               "params": {"field": "http_status_class", "size": 5, "order": "desc", "orderBy": "1",
                          "otherBucket": False, "missingBucket": False, "customLabel": "상태"}}],
     "params": dict({"type": "histogram", "grid": {"categoryLines": False}, "addTooltip": True,
                     "addLegend": True, "legendPosition": "right",
                     "seriesParams": series(stacked="stacked", bar=0.9),
                     "times": [], "addTimeMarker": False, "labels": {"show": False}}, **axes())},
    INGRESS_Q)

# --- 6. 증거 ---------------------------------------------------------------
EV_COLS = ["waf_action", "waf_rule_id", "waf_msg", "waf_client_ip", "waf_uri",
           "waf_anomaly_score", "waf_severity", "collector_node"]
objs.append(("search", "waf-recent-events" + ID_SUFFIX, {
    "title": "최근 WAF 이벤트 상세",
    "description": "사건 조사용. waf_client_ip 는 마스킹하지 않은 공격 출발지다 — 차단 목록에 그대로 쓸 수 있다.",
    "columns": EV_COLS, "sort": ["@timestamp", "desc"], "hits": 0,
    "kibanaSavedObjectMeta": {"searchSourceJSON": ss(WAF_Q)}}, IDX_REF))

# --- 대시보드 --------------------------------------------------------------
LAYOUT = [
    ("waf-total-detections",     0,  0, 12, 8, "visualization"),
    ("waf-blocked-count",       12,  0, 12, 8, "visualization"),
    ("waf-threshold-exceeded",  24,  0, 12, 8, "visualization"),
    ("waf-unique-attackers",    36,  0, 12, 8, "visualization"),
    ("waf-attack-families",      0,  8, 24, 13, "visualization"),
    ("waf-top-rules",           24,  8, 24, 13, "visualization"),
    ("waf-top-attackers",        0, 21, 16, 12, "visualization"),
    ("waf-target-paths",        16, 21, 16, 12, "visualization"),
    ("waf-anomaly-distribution",32, 21, 16, 12, "visualization"),
    ("waf-events-over-time",     0, 33, 48, 12, "visualization"),
    ("waf-403-by-reason",        0, 45, 24, 11, "visualization"),
    ("waf-ingress-status",      24, 45, 24, 11, "visualization"),
    ("waf-recent-events",        0, 56, 48, 15, "search"),
]
panels, refs = [], []
for vid, x, y, w, h, typ in LAYOUT:
    name = "panel_" + vid.replace("-", "_")
    cfg = {"columns": EV_COLS, "sort": ["@timestamp", "desc"]} if typ == "search" else {}
    panels.append({"gridData": {"x": x, "y": y, "w": w, "h": h, "i": vid}, "panelIndex": vid,
                   "version": "7.10.0", "panelRefName": name, "embeddableConfig": cfg})
    refs.append({"name": name, "id": vid + ID_SUFFIX, "type": typ})

objs.append(("dashboard", DASH_ID, {
    "title": "WAF 보안 대시보드 2" if V2 else "WAF (Coraza) 보안 대시보드",
    "description": "audio-ingress 게이트웨이 Envoy 안에서 도는 Coraza WAF 의 탐지·차단 현황. 기존 「보안 로그 대시보드」(Keycloak/OAuth2/Kyverno)와 분리돼 있으며 서로 영향을 주지 않는다.",
    "version": 1, "hits": 0, "timeRestore": True, "timeFrom": "now-24h", "timeTo": "now",
    "refreshInterval": {"pause": False, "value": 30000},
    "optionsJSON": json.dumps({"useMargins": True, "hidePanelTitles": False}, separators=(",", ":")),
    "panelsJSON": json.dumps(panels, separators=(",", ":"), ensure_ascii=False),
    "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps(
        {"query": {"query": "", "language": "kuery"}, "filter": []}, separators=(",", ":"))}}, refs))

# --- index-pattern 필드 등록 -------------------------------------------------
NEW_FIELDS = [("waf_rule_id", "string", "keyword"), ("waf_rule_group", "string", "keyword"),
              ("waf_msg", "string", "keyword"), ("waf_severity", "string", "keyword"),
              ("waf_uri", "string", "keyword"), ("waf_client_ip", "ip", "ip"),
              ("waf_anomaly_score", "number", "integer"), ("waf_action", "string", "keyword"),
              ("waf_crs_version", "string", "keyword"), ("security_event_type", "string", "keyword"),
              ("source_network", "string", "keyword"), ("http_user_agent", "string", "keyword"),
              ("response_flags", "string", "keyword"), ("response_code_details", "string", "keyword")]
ip = json.load(open(sys.argv[1]))
fields = json.loads(ip["attributes"]["fields"])
have = {f["name"] for f in fields}
for name, ftype, es in NEW_FIELDS:
    if name not in have:
        fields.append({"name": name, "type": ftype, "esTypes": [es], "count": 0, "scripted": False,
                       "searchable": True, "aggregatable": True, "readFromDocValues": True})
attrs = dict(ip["attributes"]); attrs["fields"] = json.dumps(fields, separators=(",", ":"))
objs.insert(0, ("index-pattern", IP_ID, attrs, ip.get("references", [])))

# --- 실행 스크립트 ----------------------------------------------------------
OSD = "http://opensearch-dashboards:5601"
out = ["#!/bin/sh", "set -e", 'fail=0']
for typ, oid, attrs, references in objs:
    body = json.dumps({"attributes": attrs, "references": references},
                      separators=(",", ":"), ensure_ascii=False)
    out.append("cat > /tmp/p.json <<'JSONEOF'\n" + body + "\nJSONEOF")
    out.append(f'code=$(curl -s -o /tmp/r.json -w "%{{http_code}}" -X POST '
               f'-H "osd-xsrf: true" -H "Content-Type: application/json" '
               f'"{OSD}/api/saved_objects/{typ}/{oid}?overwrite=true" --data-binary @/tmp/p.json)')
    out.append(f'if [ "$code" -ge 300 ]; then echo "FAIL {typ}/{oid} HTTP $code"; '
               f'head -c 400 /tmp/r.json; echo; fail=1; else echo "ok {typ}/{oid}"; fi')
out.append('exit $fail')
print("\n".join(out))
