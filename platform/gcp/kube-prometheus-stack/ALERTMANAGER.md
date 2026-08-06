# Cantaloupe Alertmanager 운영 안내

## Slack Webhook Secret

Slack Incoming Webhook URL은 Git에 저장하지 않는다. AlertmanagerConfig와
동일한 `monitoring` 네임스페이스에 다음 Secret이 있어야 한다.

```bash
kubectl -n monitoring create secret generic alertmanager-slack-webhook \
  --from-literal=api-url='실제_SLACK_WEBHOOK_URL' \
  --dry-run=client -o yaml \
  | kubectl apply -f -
```

값을 노출하지 않고 Secret 구조만 확인한다.

```bash
kubectl -n monitoring get secret alertmanager-slack-webhook \
  -o go-template='type={{.type}} keys={{range $k,$v := .data}}{{$k}} {{end}}{{"\n"}}'
```

정상 결과는 `type=Opaque keys=api-url`이다.

## 알림 정책

- `warning`, `critical`만 `#cantaloupe-platform-alerts`로 전송한다.
- 동일한 namespace/alertname/severity 알림은 한 메시지로 묶는다.
- 최초 대기 30초, 신규 그룹 갱신 5분, 미복구 반복 알림 4시간이다.
- 복구 시 resolved 메시지를 보낸다.
- 항상 firing 상태인 Watchdog은 별도 heartbeat 서비스가 없으므로 비활성화한다.
- Alertmanager UI는 외부에 공개하지 않고 Grafana 데이터소스로 조회한다.

## 배포 후 검증

```bash
kubectl -n monitoring get alertmanager,alertmanagerconfig,pod,svc
kubectl -n monitoring get secret alertmanager-slack-webhook
kubectl -n monitoring logs alertmanager-monitoring-alertmanager-0 -c alertmanager --tail=100
```

Prometheus Target에서 Alertmanager와의 연결 상태도 확인한다.

```promql
prometheus_notifications_alertmanagers_discovered
```

값이 1 이상이어야 한다. 실제 Slack 통합 검증은 만료 시간이 짧은
`severity=warning` 시험 알림을 Alertmanager API v2에 전송하고 다음 지표와
Slack 채널 수신 여부를 함께 확인한다.

```promql
sum(increase(alertmanager_notifications_total{integration="slack"}[10m]))
sum(increase(alertmanager_notifications_failed_total{integration="slack"}[10m]))
```

첫 번째 값은 1 이상, 실패 값은 0이어야 한다.
