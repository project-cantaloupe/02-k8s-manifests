# Monitoring data persistence

Grafana와 Prometheus의 데이터는 `monitoring` Namespace의 GCP Persistent Disk에
저장한다. Git 브랜치나 Argo CD Application 이름은 데이터의 식별자가 아니다.
다음 항목이 유지되면 feature 브랜치에서 `main`으로 전환해도 기존 PVC를 그대로
사용한다.

- Namespace: `monitoring`
- Helm release/fullname: `monitoring`, `grafana`
- Grafana PVC: `grafana`
- Prometheus StatefulSet/PVC template 이름
- StorageClass와 기존 PVC

Grafana PVC에는 `Prune=false,Delete=false`를 설정해 Argo CD sync prune 및
Application cascade 삭제로부터 보호한다. Prometheus Operator가 만드는
StatefulSet은 PVC retention policy를 `Retain`으로 유지한다.

## 금지 작업

- `monitoring` Namespace 삭제
- 위 PVC 직접 삭제
- preview Application을 foreground/background cascade 방식으로 삭제
- PVC 또는 Helm release 이름을 바꾸면서 데이터 이전 절차를 생략
- persistence를 끄거나 PVC 템플릿을 제거한 상태로 prune sync

Pod 재시작, Deployment/StatefulSet rollout, 대시보드 ConfigMap 수정, Prometheus
rule 수정은 PVC를 삭제하지 않는다.

## Preview에서 main으로 인계

1. Namespace UID, PVC UID, PV 이름과 disk handle을 기록한다.
2. `main`에 동일한 Namespace/release/PVC 이름의 Application을 병합한다.
3. preview Application의 자동 sync를 중지한다.
4. preview Application만 non-cascading 방식으로 제거해 리소스를 orphan한다.
5. `main` Application을 sync하여 동일 리소스를 인수한다.
6. 1번의 UID와 disk handle이 그대로인지 확인한다.

preview Application을 일반 삭제하면 resources finalizer 때문에 관리 리소스가
함께 삭제될 수 있으므로 사용하지 않는다. 실제 전환은 별도 검증 작업으로
수행한다.

현재 사용 중인 PV는 클러스터에서도 reclaim policy를 `Retain`으로 설정한다.
따라서 PVC가 실수로 삭제되어도 GCP PD는 자동 삭제되지 않지만, 복구 시 기존
disk handle을 지정해 PV/PVC를 다시 연결해야 한다. Retain PV는 고아 디스크
비용이 발생할 수 있으므로 의도적으로 폐기할 때만 수동 삭제한다.
