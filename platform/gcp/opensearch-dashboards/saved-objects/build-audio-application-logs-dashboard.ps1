param(
  [string]$OutputPath = (Join-Path $PSScriptRoot "..\audio-processing-finops-improved-v6.ndjson")
)

$ErrorActionPreference = "Stop"
$indexId = "cantaloupe-app-logs-v1"
$objects = [Collections.Generic.List[string]]::new()

function Json($Value, [int]$Depth = 40) { ConvertTo-Json -InputObject $Value -Depth $Depth -Compress }
function SearchSource([string]$Query = "") { Json @{ query = @{ query = $Query; language = "kuery" }; filter = @(); indexRefName = "kibanaSavedObjectMeta.searchSourceJSON.index" } }
function IndexRef { @(@{ name = "kibanaSavedObjectMeta.searchSourceJSON.index"; type = "index-pattern"; id = $indexId }) }
function Add-Object([string]$Type, [string]$Id, $Attributes, [array]$References = @()) {
  $objects.Add((Json @{ type = $Type; id = $Id; attributes = $Attributes; references = $References }))
}
function Add-Visualization([string]$Id, [string]$Title, [string]$Description, $VisState, [string]$Query = "") {
  Add-Object "visualization" $Id @{ title = $Title; description = $Description; visState = Json $VisState; uiStateJSON = "{}"; kibanaSavedObjectMeta = @{ searchSourceJSON = SearchSource $Query } } (IndexRef)
}
function Add-Header([string]$Id, [string]$Title) {
  Add-Visualization $Id $Title $Title @{ title = $Title; type = "markdown"; params = @{ markdown = "#### $Title"; openLinksInNewTab = $false }; aggs = @() }
}
function Add-Metric([string]$Id, [string]$Title, [string]$Field, [string]$Query, [string]$Description) {
  Add-Visualization $Id $Title $Description @{ title = $Title; type = "metric"; params = @{ addLegend = $false; addTooltip = $true; fontSize = 26 }; aggs = @(@{ id = "1"; enabled = $true; type = "sum"; schema = "metric"; params = @{ field = $Field; customLabel = "용량" } }) } $Query
}
function Add-TermsTable([string]$Id, [string]$Title, [string]$Field, [string]$Query, [string]$Description, [int]$Size = 10) {
  Add-Visualization $Id $Title $Description @{ title = $Title; type = "table"; params = @{ perPage = $Size; showPartialRows = $false; showMetricsAtAllLevels = $false; sort = @{ columnIndex = 1; direction = "desc" }; showTotal = $false; totalFunc = "sum"; percentageCol = "" }; aggs = @(@{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{ customLabel = "건수" } }, @{ id = "2"; enabled = $true; type = "terms"; schema = "bucket"; params = @{ field = $Field; size = $Size; order = "desc"; orderBy = "1"; customLabel = $Title } }) } $Query
}
function Add-Search([string]$Id, [string]$Title, [string]$Description, [string]$Query, [array]$Columns, [string]$SortField = "@timestamp") {
  Add-Object "search" $Id @{ title = $Title; description = $Description; columns = $Columns; sort = @(, @($SortField, "desc")); kibanaSavedObjectMeta = @{ searchSourceJSON = SearchSource $Query } } (IndexRef)
}

Add-Object "index-pattern" $indexId @{ title = $indexId; timeFieldName = "@timestamp"; fieldFormatMap = Json @{ input_bytes = @{ id = "bytes"; params = @{ pattern = "0.0b" } }; output_bytes = @{ id = "bytes"; params = @{ pattern = "0.0b" } }; processing_duration_ms = @{ id = "number"; params = @{ pattern = "0,0.[00]" } } } }

Add-Visualization "audio-id-filters" "작업 추적 필터" "request_id, job_id, audio_id로 관련 로그를 좁힙니다." @{ title = "작업 추적 필터"; type = "input_control_vis"; params = @{ controls = @(@{ id = "request-id"; fieldName = "request_id"; parent = ""; label = "Request ID"; type = "list"; options = @{ type = "terms"; multiselect = $true; dynamicOptions = $true; size = 10 } }, @{ id = "job-id"; fieldName = "job_id"; parent = ""; label = "Job ID"; type = "list"; options = @{ type = "terms"; multiselect = $true; dynamicOptions = $true; size = 10 } }, @{ id = "audio-id"; fieldName = "audio_id"; parent = ""; label = "Audio ID"; type = "list"; options = @{ type = "terms"; multiselect = $true; dynamicOptions = $true; size = 10 } }); updateFiltersOnChange = $true; useTimeFilter = $true; pinFilters = $false }; aggs = @() }

Add-Header "audio-group-health" "1. 완료 데이터"
Add-Metric "audio-input-volume" "완료 작업 입력 용량" "input_bytes" 'event_type : "transcode_completed" and status : "success"' "완료된 Transcode 작업 1건당 한 번 기록된 input_bytes 합계입니다."
Add-Metric "audio-output-volume-completed" "완료 작업 출력 용량" "output_bytes" 'event_type : "transcode_completed" and status : "success"' "완료된 Transcode 작업의 output_bytes 합계입니다."
Add-Visualization "audio-input-size-distribution" "완료 오디오 입력 크기 분포" "완료 작업의 input_bytes를 운영상 의미 있는 크기 구간으로 나눕니다." @{ title = "완료 오디오 입력 크기 분포"; type = "histogram"; params = @{ addLegend = $false; addTooltip = $true; scale = "linear"; categoryAxes = @(@{ id = "CategoryAxis-1"; type = "category"; position = "bottom"; show = $true }); valueAxes = @(@{ id = "ValueAxis-1"; name = "ValueAxis-1"; type = "value"; position = "left"; show = $true }) }; aggs = @(@{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{ customLabel = "완료 작업 수" } }, @{ id = "2"; enabled = $true; type = "range"; schema = "segment"; params = @{ field = "input_bytes"; ranges = @(@{ from = 0; to = 10485760; label = "0-10 MB" }, @{ from = 10485760; to = 52428800; label = "10-50 MB" }, @{ from = 52428800; to = 104857600; label = "50-100 MB" }, @{ from = 104857600; to = 524288000; label = "100-500 MB" }, @{ from = 524288000; label = "500 MB 이상" }) } }) } 'event_type : "transcode_completed" and status : "success" and input_bytes : *'

Add-Header "audio-group-errors" "2. 오류 원인 분석"
Add-TermsTable "audio-errors-by-code" "오류 코드 Top 5" "error_code" "error_code : *" "error_code별 실패 빈도를 보여줍니다." 5
Add-TermsTable "audio-errors-by-app" "컴포넌트별 오류" "app" 'level : "error" or error_code : * or status : ("failure" or "failed" or "rejected")' "오류 신호가 기록된 로그를 app별로 집계합니다." 10
Add-TermsTable "audio-retryable-errors" "재시도 가능 여부" "retryable" "retryable : *" "실패 로그의 retryable=true/false 분포입니다." 2
Add-Search "audio-top-retried-jobs" "재시도 상위 작업" "retry_count가 기록된 작업을 재시도 횟수 내림차순으로 확인합니다." "retry_count : *" @("@timestamp", "app", "job_id", "audio_id", "attempt", "retry_count", "error_code", "retryable") "retry_count"
Add-Search "audio-recent-failed-requests" "최근 실패 작업" "Transcode 실패, 실패 상태 또는 error_code가 기록된 최신 작업입니다." 'event_type : "transcode_failed" or status : ("failure" or "failed" or "rejected") or error_code : *' @("@timestamp", "app", "event_type", "status", "job_id", "audio_id", "attempt", "retry_count", "error_code", "message")

Add-Header "audio-group-demand" "3. HTTP 오류 분석"
Add-TermsTable "audio-http-error-routes" "HTTP 오류 경로 Top 5" "http_route" "http_status >= 400" "HTTP 4xx/5xx가 발생한 경로를 빈도순으로 보여줍니다." 5
Add-TermsTable "audio-http-errors-over-time" "HTTP 오류 상태 코드" "http_status" "http_status >= 400" "HTTP 오류를 실제 상태 코드별로 집계합니다." 10
Add-Search "audio-recent-http-errors" "최근 HTTP 오류" "최근 HTTP 4xx/5xx 요청의 추적 근거입니다." "http_status >= 400" @("@timestamp", "app", "request_id", "http_method", "http_route", "http_status", "upstream_service", "response_code_details", "message")

Add-Header "audio-group-performance" "4. 작업 추적 근거"
Add-Search "audio-recent-transcode-failures" "최근 Transcode 실패" "transcode_failed 이벤트의 작업 식별자와 실패 원인을 확인합니다." 'event_type : "transcode_failed"' @("@timestamp", "app", "job_id", "audio_id", "attempt", "retry_count", "error_code", "retryable", "message")
Add-Search "audio-recent-transcode-completed" "최근 Transcode 완료" "실패 작업과 대조할 수 있는 최근 transcode_completed 이벤트입니다." 'event_type : "transcode_completed" and status : "success"' @("@timestamp", "app", "job_id", "audio_id", "attempt", "retry_count", "input_bytes", "output_bytes", "processing_duration_ms")

$panelSpecs = @(
  @("visualization", "audio-id-filters", 0, 0, 48, 5),
  @("visualization", "audio-group-health", 0, 5, 48, 2),
  @("visualization", "audio-input-volume", 0, 7, 12, 8), @("visualization", "audio-output-volume-completed", 12, 7, 12, 8), @("visualization", "audio-input-size-distribution", 24, 7, 24, 8),
  @("visualization", "audio-group-errors", 0, 15, 48, 2),
  @("visualization", "audio-errors-by-code", 0, 17, 16, 10), @("visualization", "audio-errors-by-app", 16, 17, 16, 10), @("visualization", "audio-retryable-errors", 32, 17, 16, 10),
  @("search", "audio-top-retried-jobs", 0, 27, 24, 11), @("search", "audio-recent-failed-requests", 24, 27, 24, 11),
  @("visualization", "audio-group-demand", 0, 38, 48, 2),
  @("visualization", "audio-http-error-routes", 0, 40, 16, 10), @("visualization", "audio-http-errors-over-time", 16, 40, 16, 10), @("search", "audio-recent-http-errors", 32, 40, 16, 10),
  @("visualization", "audio-group-performance", 0, 50, 48, 2),
  @("search", "audio-recent-transcode-failures", 0, 52, 24, 12), @("search", "audio-recent-transcode-completed", 24, 52, 24, 12)
)
$panels = @(); $references = @(); $i = 0
foreach ($spec in $panelSpecs) {
  $i++; $ref = "panel_$($i - 1)"
  $panels += @{ version = "7.10.2"; gridData = @{ x = $spec[2]; y = $spec[3]; w = $spec[4]; h = $spec[5]; i = "$i" }; panelIndex = "$i"; embeddableConfig = @{}; panelRefName = $ref }
  $references += @{ name = $ref; type = $spec[0]; id = $spec[1] }
}
$references += @{ name = "kibanaSavedObjectMeta.searchSourceJSON.index"; type = "index-pattern"; id = $indexId }
Add-Object "dashboard" "audio-processing-finops" @{ title = "Audio Application Logs / Troubleshooting"; description = "완료 데이터, 실패 원인, HTTP 오류, 요청·작업 추적 근거를 로그로 분석합니다. 서비스 메트릭과 비용은 Grafana에서 확인합니다."; panelsJSON = Json $panels; optionsJSON = Json @{ useMargins = $true; hidePanelTitles = $false }; timeRestore = $true; timeTo = "now"; timeFrom = "now-24h"; refreshInterval = @{ pause = $false; value = 30000 }; kibanaSavedObjectMeta = @{ searchSourceJSON = Json @{ query = @{ query = ""; language = "kuery" }; filter = @() } } } $references

[IO.File]::WriteAllLines((Resolve-Path (Split-Path $OutputPath -Parent) | ForEach-Object { Join-Path $_ (Split-Path $OutputPath -Leaf) }), $objects, [Text.UTF8Encoding]::new($false))
Write-Host "Wrote $($objects.Count) saved objects to $OutputPath"
