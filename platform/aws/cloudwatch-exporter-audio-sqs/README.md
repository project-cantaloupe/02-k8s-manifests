# Audio SQS CloudWatch Exporter

Audio 파이프라인의 SQS 적체·대기시간·유입·처리량을 1분 주기로 중앙
Prometheus에 제공한다. S3 저장량은 AWS에서 하루 한 번 게시되므로 기존
`cloudwatch-exporter`가 24시간 주기로 별도 수집한다. 두 수집기를 합치면 SQS를
보기 위해 S3 CloudWatch API까지 매분 호출하게 되므로 분리한다.

이 메트릭은 정적 `audio-transcode` 1개를 유지해도 필요하다. 향후 KEDA가 SQS를
기준으로 replica를 조절하면 같은 Queue 메트릭을 확장 입력과 결과 검증에 재사용하며,
Karpenter 채택 여부와도 무관하다.

대시보드는 가능하면 statistic suffix가 붙은 exporter 원본보다 다음 recording
rule을 사용한다.

```text
cantaloupe:audio_transcode_queue_backlog
cantaloupe:audio_transcode_queue_inflight
cantaloupe:audio_transcode_queue_oldest_age_seconds
cantaloupe:audio_transcode_dlq_messages
cantaloupe:audio_sqs_collector_up
```

SQS는 비활성 Queue의 CloudWatch sample을 잠시 게시하지 않을 수 있다. 위 네 개의
Audio 전용 rule은 이 경우 `0`을 반환하므로 정상적인 빈 Queue가 Grafana에서
`No data`로 오해되지 않는다. Collector 자체의 장애와 빈 Queue를 구분하려면 반드시
`cantaloupe:audio_sqs_collector_up`을 함께 표시한다.

`NumberOfMessages*`는 CloudWatch의 60초 period 합계다. 누적 counter가 아니므로
Grafana에서 다시 `rate()`나 `increase()`를 적용하지 않는다.
