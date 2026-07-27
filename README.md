# k8s-manifests

클러스터 위에 뜨는 것 전부. **ArgoCD가 이 리포를 보고 동기화한다.**

`kubectl apply`를 손으로 하지 않는다. 여기 커밋한 것만 클러스터에 반영된다.

## 구조

```
governance/     전 클러스터 공통 보안·비용 규칙
platform/       영역별 도구
  aws/          area=aws 노드
  gcp/          area=gcp 노드
  onprem/       area=onprem 노드
apps/           고객 서비스
```

## 규칙 — 디렉터리 이름 = 영역 = 노드 라벨

`platform/gcp/` 아래 있는 건 전부 `area=gcp` 노드에 뜬다.

**`nodeSelector`를 매니페스트에 직접 쓰지 않는다.** 영역 디렉터리의
`kustomization.yaml`이 한 번에 주입한다. 새 도구를 추가하는 사람은 이 존재를
몰라도 된다.

### 새 도구 추가하기

```bash
# 1. 영역 디렉터리 안에 폴더를 만든다
mkdir platform/gcp/loki

# 2. 매니페스트를 넣는다 (nodeSelector 는 적지 않는다)
vi platform/gcp/loki/deployment.yaml

# 3. 영역 kustomization 의 resources 에 한 줄 추가
vi platform/gcp/kustomization.yaml
```

## 거버넌스

`governance/`는 SecOps·FinOps가 소유한다. CODEOWNERS로 승인이 강제된다.

| 디렉터리 | 용도 |
|---|---|
| `governance/secops/` | 전 클러스터 보안 규칙 |
| `governance/finops/` | 전 클러스터 비용 규칙 |
| `governance/exceptions/` | 규칙에서 빼는 것 |
| `platform/*/policies/` | 그 영역에만 **더** 거는 규칙 |
| `apps/*/policies/` | 그 앱에만 **더** 거는 규칙 |

**빼기와 더하기를 다른 곳에 둔다.** `ls governance/exceptions/` 하나로
"기준에서 벗어난 게 뭐가 있나"에 답할 수 있어야 하기 때문이다.

정책 엔진은 Kyverno다. 정책을 YAML로 쓰고, 예외는 `PolicyException` 리소스로
남는다 — 문서에 적어둔 예외와 실제가 어긋나지 않는다.

## 클라우드 자원 쪽 거버넌스는 여기 없다

EC2 태그나 IAM 정책 같은 건 클러스터가 아니라 클라우드에 거는 것이라
[`infra-provisioning/terraform/modules/`](../infra-provisioning/) 에 있다.

같은 정책 의도가 두 리포에 나뉘어 구현된다. 한쪽만 고치면 반쪽만 적용된다.
