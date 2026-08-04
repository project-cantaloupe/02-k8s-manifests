# kube-prometheus-stack

클러스터 공용 Prometheus, Grafana, kube-state-metrics, node-exporter를 설치한다.
Prometheus와 Grafana는 GCP PD CSI의 `gcp-pd-sc`를 사용하며 GCP monitoring
Worker에 배치된다. node-exporter는 모든 Linux Node의 공용 `node_*` 메트릭을
수집하므로 별도의 애플리케이션 팀이 중복 설치하지 않는다.

- Chart: `kube-prometheus-stack` `88.1.3`
- Prometheus: 20Gi, 7일 또는 15GB 중 먼저 도달하는 기준으로 보존
- Grafana: 5Gi
- Grafana Tailnet URL: `http://cntlp-gcp-wk-01:30300`
- Prometheus: ClusterIP 전용

Grafana 관리자 계정은 Git에 저장하지 않는다. 배포 전에 `monitoring`
Namespace에 `grafana-admin-credentials` Secret을 별도로 준비한다.

```bash
kubectl -n monitoring create secret generic grafana-admin-credentials \
  --from-literal=admin-user=admin \
  --from-literal=admin-password='<random-password>'
```

PVC 또는 `monitoring` Namespace를 삭제하면 `gcp-pd-sc`의 `Delete` 정책에 따라
GCP Persistent Disk도 삭제된다. 일반적인 Pod 재시작이나 Deployment 변경은
PVC를 삭제하지 않는다.
