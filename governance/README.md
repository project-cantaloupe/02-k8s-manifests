# governance

전 클러스터에 공통으로 거는 보안·비용 규칙. 정책 엔진은 **Kyverno**다.

## 규칙이 적용되는 세 경로

| 경로 | 하는 일 |
|---|---|
| `secops/`, `finops/` | 전체에 **강제** (ClusterPolicy) |
| `exceptions/` | 특정 대상만 **면제** (PolicyException) |
| `platform/*/policies/`, `apps/*/policies/` | 특정 대상에만 **추가** |

빼기(`exceptions/`)와 더하기(`*/policies/`)를 다른 곳에 둔다.
`ls exceptions/` 하나로 "기준에서 벗어난 게 뭐냐"에 답할 수 있어야 한다.

## 정책은 Enforce 로 쓴다

`validationFailureAction: Audit` 은 위반을 기록만 하고 통과시킨다.
그건 규칙이 아니라 통계다. 새 정책을 넣을 때 이유 없이 Audit 로 두지 않는다.

## 예외를 추가할 때

`exceptions/` 에 파일을 만들고 **사유와 재검토 시점**을 적는다.
만료 없는 예외는 영구 면제가 된다.
