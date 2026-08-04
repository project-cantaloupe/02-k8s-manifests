# GCP Persistent Disk CSI

Self-managed Cantaloupe Kubernetes 클러스터의 GCP Worker에서 Persistent Disk를
동적으로 생성하고 연결하기 위한 CSI 구성이다.

공식 `gcp-compute-persistent-disk-csi-driver`의 `noauth` overlay를 immutable
commit SHA로 고정한다. Controller는 GCE Metadata Server를 통해 인증하므로
GCP VM Service Account에 필요한 Compute Disk 권한이 있어야 한다.

## 배포 경계

이 디렉터리는 아직 `applications/`의 Argo CD Application으로 등록하지 않는다.
PR merge만으로 라이브 클러스터에 자동 적용되지 않는다. 다음 조건을 확인한 뒤
별도 `gcp-storage` Application으로 등록하고 최초에는 수동 Sync한다.

1. GCP Worker VM Service Account의 Persistent Disk 생성·연결·삭제 권한
2. `kubectl kustomize platform/gcp/csi-driver` 렌더링 성공
3. Controller가 `platform=gcp,role=logging` 노드에 배치됨
4. Linux Node Agent가 `platform=gcp`인 두 Worker에만 배치됨
5. 테스트 PVC의 provision, attach, mount, expansion, delete 성공

공식 배포 스크립트 대신 Argo CD가 설치하므로 `gce-pd-csi-driver` Namespace도
이 디렉터리에서 함께 선언한다.

현재 클러스터의 `monitoring-local-retain` local PV는 이 StorageClass로 자동
전환되지 않는다. Prometheus와 Grafana를 CSI로 옮기는 작업은 별도 PR에서 PVC
및 데이터 이전 계획과 함께 진행한다.
