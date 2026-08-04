# OpenCost

OpenCost는 별도 Prometheus를 설치하지 않고 `monitoring-prometheus`를 조회한다.
초기 구성은 Kubernetes CPU·Memory 요청량과 사용량 기반 allocation 검증에
집중하며, GCP Billing BigQuery 또는 AWS CUR 연동은 자격 증명과 비용 데이터
위치가 확정된 뒤 별도 변경으로 추가한다.

- Chart: `opencost` `2.5.28`
- Tailnet URL: `http://cntlp-gcp-wk-01:30990`
- 자체 영속 볼륨 없음: 비용 이력은 Prometheus 보존 기간을 따른다.
- OpenCost UI에는 자체 인증이 없으므로 NodePort를 인터넷에 공개하지 않는다.

기본 배포만으로 allocation API와 CPU·Memory·PV 비용 계산은 동작하지만,
클라우드 청구서와 일치하는 실비 분석까지 자동으로 완성되지는 않는다. GCP
Cloud Billing API/BigQuery 연동과 Node의 instance type·region·zone 라벨은
인프라 담당 범위에서 별도로 준비한다. 이 연동 전에는 OpenCost가 누락된 가격을
기본 가격으로 계산하므로 결과를 추정값으로 취급한다.
