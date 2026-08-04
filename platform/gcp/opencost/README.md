# OpenCost

OpenCost는 별도 Prometheus를 설치하지 않고 `monitoring-prometheus`를 조회한다.
초기 구성은 Kubernetes CPU·Memory 요청량과 사용량 기반 allocation 검증에
집중하며, GCP Billing BigQuery 또는 AWS CUR 연동은 자격 증명과 비용 데이터
위치가 확정된 뒤 별도 변경으로 추가한다.

- Chart: `opencost` `2.5.28`
- Tailnet URL: `https://cntlp-gcp-wk-01.tail270b85.ts.net/`
- 자체 영속 볼륨 없음: 비용 이력은 Prometheus 보존 기간을 따른다.
- OpenCost UI에는 자체 인증이 없으므로 NodePort를 인터넷에 공개하지 않는다.

하나의 Kubernetes 클러스터에 AWS, GCP, 온프레미스 Node가 섞여 있으므로
OpenCost 한 인스턴스의 CSV Provider로 Node별 가격을 적용한다. 가격표 ConfigMap과
마운트, Provider 환경변수는 `values.yaml`에 함께 선언되어 Argo CD가 원자적으로
관리한다.

- AWS: 서울 리전 Linux/Shared/On-Demand 공개 인스턴스 가격
- GCP: 서울 리전 E2 vCPU와 RAM On-Demand 공개 SKU 합계
- 온프레미스: 공개 가격이 없으므로 프로젝트 기준 CPU `$0.03/core-hour`, RAM
  `$0.004/GiB-hour`로 산정한 가상 원가
- `gcp-pd-sc`: 서울 리전 zonal `pd-standard` 공개 가격

Grafana는 OpenCost가 계산해 Prometheus에 노출한 결과를 시각화할 뿐 가격 계산의
원본이 아니다. 실제 청구 할인, 세금, 네트워크, AWS CPU credit, CUD/SUD 및 기타
청구 조정은 포함하지 않으므로 결과는 공개 On-Demand 기준 추정 비용이다.

가격 근거와 재검증 절차는 [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)에 기록한다.
