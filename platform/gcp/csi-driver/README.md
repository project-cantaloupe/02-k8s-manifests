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

특히 attach·detach 경로에는 다음 Compute Engine 권한이 필요하다. 디스크 생성만
성공해도 이 권한이 없으면 PVC는 `Bound`되지만 Pod는
`ContainerCreating`에서 멈춘다.

```text
compute.instances.get
compute.instances.attachDisk
compute.instances.detachDisk
compute.disks.get
```

GCP Worker에 Service Account가 연결된 경우 attach 작업의 호출 주체가 해당
Service Account를 사용할 수 있도록 `iam.serviceAccounts.actAs`도 필요하다.
일반적으로 대상 Service Account에 `roles/iam.serviceAccountUser`를 부여해
충족한다. 이 권한이 없으면 디스크와 PV 생성은 성공하지만 attach operation이
`SERVICE_ACCOUNT_ACCESS_DENIED`로 실패한다.

공식 배포 스크립트 대신 Argo CD가 설치하므로 프로젝트 공통 시스템 Add-on
Namespace인 `storage-system`도 이 디렉터리에서 함께 선언한다.

기존의 미사용 `monitoring-local-retain` local PV와 StorageClass는 제거했다.
Prometheus, Grafana 등 GCP 영속 워크로드는 각 Application에서 별도 PVC를
선언하고 `storageClassName: gcp-pd-sc`를 명시한다. 하나의 `ReadWriteOnce` PVC를
여러 StatefulSet 또는 여러 노드가 동시에 공유하지 않는다.
