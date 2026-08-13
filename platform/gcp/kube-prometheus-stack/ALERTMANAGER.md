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

오디오 서비스 알람은 같은 Workspace의 전용 채널 Webhook을 별도 Secret으로
관리한다. `service=audio` 라벨이 있는 warning/critical 알람만 이 Receiver로
분기되며 기존 플랫폼 채널에는 중복 전송하지 않는다.

```bash
read -s SLACK_AUDIO_WEBHOOK
kubectl -n monitoring create secret generic alertmanager-slack-audio-webhook \
  --from-literal=api-url="$SLACK_AUDIO_WEBHOOK" \
  --dry-run=client -o yaml | kubectl apply -f -
unset SLACK_AUDIO_WEBHOOK
```

Kyverno Enforce 거부 알림은 AWS Secrets Manager의
`cntlp/alertmanager/slack/kyverno`에서 `api_url` 속성만 ExternalSecret으로
동기화한다. 값은 AWS UI에서 수동 등록하며 Git과 Terraform state에는 넣지 않는다.
생성되는 Kubernetes Secret 이름은 `alertmanager-slack-kyverno-webhook`이다.

Secret 확인 시 `.data` 또는 `api-url`을 출력하지 않는다. 존재 여부만 다음처럼
확인한다.

```bash
kubectl -n monitoring get secret alertmanager-slack-audio-webhook \
  -o jsonpath='{.metadata.name}{" 등록 완료\\n"}'
```

값을 노출하지 않고 Secret 구조만 확인한다.

```bash
kubectl -n monitoring get secret alertmanager-slack-webhook \
  -o go-template='type={{.type}} keys={{range $k,$v := .data}}{{$k}} {{end}}{{"\n"}}'
```

정상 결과는 `type=Opaque keys=api-url`이다.

## 알림 정책

- `warning`, `critical`만 `#cantaloupe-platform-alerts`로 전송한다.
- 그중 `service=audio` 알람은 `#cantaloupe-audio-alerts`로 분기하고 플랫폼
  채널에는 중복 전송하지 않는다.
- `service=kyverno` 알람은 Kyverno 전용 채널로 분기하고 플랫폼 채널에는
  중복 전송하지 않는다.
- `service=argocd` 지속 상태 알람은 플랫폼 채널을 유지하되, 앱과 대상
  Namespace 및 GitHub/Argo CD 확인 링크가 포함된 전용 메시지 형식을 사용한다.
- `service=audio` 앱 알람은 Audio 전용 채널과 실제 줄바꿈 기반 전용 형식을 사용한다.
- Slack 허용 목록에 포함된 kube-prometheus 기본 운영 알람은 alertname으로만
  `slack-prometheus-alerts`에 분기해 Platform Overview 링크를 제공한다.
  Fluent Bit와 OpenSearch 보안/로깅 알람은 이 분기에 포함하지 않으며 기존 담당자
  라우팅과 메시지 형식을 유지한다.
- Kyverno 알림에는 정책, Namespace/Kind, 필수 리소스 선언값과 확인 절차를
  표시한다. Kyverno admission 메트릭에는 Git commit 정보가 없으므로 커밋을
  추정해 표시하지 않는다. 원인 커밋은 PR 정책 검사 결과 또는 Argo CD revision에서
  확인한다.
- 동일한 namespace/alertname/severity 알림은 한 메시지로 묶는다.
- 최초 대기 30초, 신규 그룹 갱신 5분, 미복구 반복 알림 4시간이다.
- 복구 시 resolved 메시지를 보낸다.
- Kyverno admission 거부는 최근 5분의 이벤트를 즉시 알린다. 원인이 해소되지 않아
  자동 동기화 Argo CD Application이 15분 이상 `OutOfSync`이면
  `ArgoCDApplicationOutOfSyncPersistent` 상태 알림이 플랫폼 채널에 발생한다.
  이 상태 알림은 동기화될 때까지 30분마다 반복되고, `Synced` 복구 시 해소된다.
  Argo CD 메트릭만으로 Kyverno가 원인이라고 단정할 수 없으므로 두 알림은
  원인 이벤트와 지속 상태로 분리한다.
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
