# Argo CD Root Application

`root-application.yaml`은 Argo CD 설치 파일이 아니라, 이미 설치된 Argo CD와
이 저장소의 `applications/` 목록을 연결하는 최초 진입점이다.

## 동작 원리

- Root Application은 `main` 브랜치의 `applications/`만 감시한다.
- `applications/kustomization.yaml`에 등록된 Application만 생성한다.
- 저장소의 다른 YAML을 자동으로 검색하거나 적용하지 않는다.
- `resources: []`인 상태에서는 아무 Application도 생성하지 않는다.

## 최초 등록

이 구조가 `main`에 병합되고 Argo CD의 repository credential이 준비된 뒤
Root Application을 한 번만 적용한다.

```bash
kubectl diff -f bootstrap/root-application.yaml
kubectl apply -f bootstrap/root-application.yaml
```

Control Plane에 저장소를 clone하지 않는 경우 로컬 파일을 SSH 표준입력으로
전달할 수 있다.

```powershell
Get-Content -Raw ".\bootstrap\root-application.yaml" |
  tailscale ssh ubuntu@100.82.100.58 "kubectl apply -f -"
```

최초 등록 이후에는 Root Application을 다시 수동 적용할 필요가 없다. 팀원은
`applications/`에 Application YAML을 추가하고 `main`에 병합하는 방식으로
새 파트를 배포한다.
