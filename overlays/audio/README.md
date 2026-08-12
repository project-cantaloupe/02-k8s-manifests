# Audio FinOps Right-sizing Overlay

기본 `apps/audio` 경로는 1차 Baseline `250m/256Mi`를 유지한다. 동일 부하의
Baseline Run이 유효하게 수집된 뒤에만 Argo CD `app-audio`의 source path를
`overlays/audio/right-sized-candidate`로 변경한다.

Candidate는 Base와 Burst Transcode의 Request를 함께 `50m/224Mi`로 바꾸고 Memory
Limit `512Mi`는 유지한다. Load Runner의 `EXPERIMENT_PHASE`도 `candidate`로 고정한다.
VPA 추천을 자동 반영하는 설정이 아니며 동일 부하에서
READY, 처리 P95, 실패, OOM·Restart·MemoryPressure와 Karpenter Node-minute를 확인한
뒤 채택한다.

Candidate가 안전 조건을 통과하지 못하면 Argo CD source path를 `apps/audio`로
되돌리는 Git Revert로 Baseline을 복원한다. Runtime에서 `kubectl edit` 또는
`kubectl set resources`로 값을 바꾸지 않는다.
