# GCP Persistent Disk CSI

Self-managed Cantaloupe Kubernetes 클러스터의 GCP Worker에서 Persistent Disk를
동적으로 생성하고 연결하기 위한 CSI 구성이다.

공식 `gcp-compute-persistent-disk-csi-driver`의 `noauth` overlay를 immutable
commit SHA로 고정한다. Controller는 GCE Metadata Server를 통해 인증하므로
두 GCP Worker VM에 Service Account가 연결되어 있고 그 계정에 필요한 Compute
Disk 권한이 있어야 한다. Metadata Server가 HTTP 200을 반환하더라도 아래
응답 본문이 비어 있으면 Service Account가 연결되지 않은 상태다.

```bash
curl -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/
```

최소한 `default/` 또는 사용할 Service Account 이름이 출력되는 것을 확인한 뒤
배포한다. 인증 키 JSON을 Git이나 Kubernetes 평문 매니페스트에 저장하지 않는다.

## Argo CD 배포

이 디렉터리는 `gcp-storage` Argo CD Application이 독립적으로 관리한다.
Prometheus나 OpenSearch Application에 CSI 리소스를 포함하지 않는다. CSI와
StorageClass를 먼저 Sync하고 다음 조건을 검증한 뒤 소비 워크로드를 배포한다.

1. 두 GCP Worker VM의 Metadata Server에서 Service Account가 조회됨
2. 해당 Service Account의 Persistent Disk 생성·연결·삭제 권한
3. `kubectl kustomize platform/gcp/csi-driver` 렌더링 성공
4. Controller가 `platform=gcp,role=logging` 노드에 배치됨
5. Linux Node Agent가 `platform=gcp`인 두 Worker에만 배치됨
6. 테스트 PVC의 provision, attach, mount, expansion, delete 성공

공식 배포 스크립트 대신 Argo CD가 설치하므로 프로젝트 공통 시스템 Add-on
Namespace인 `storage-system`도 이 디렉터리에서 함께 선언한다.

현재 클러스터의 `monitoring-local-retain` local PV는 이 StorageClass로 자동
전환되지 않는다. Prometheus와 Grafana를 CSI로 옮기는 작업은 별도 PR에서 PVC
및 데이터 이전 계획과 함께 진행한다.
