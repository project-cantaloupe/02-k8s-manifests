param(
  [string]$DashboardsUrl = "https://cntlp-gcp-wk-02.tail270b85.ts.net"
)

$ErrorActionPreference = "Stop"
$indexPatternId = "cantaloupe-platform-logs-current"

function Json($Value, [int]$Depth = 30) { ConvertTo-Json -InputObject $Value -Depth $Depth -Compress }
function SearchSource([string]$Query) {
  Json @{ query = @{ query = $Query; language = "kuery" }; filter = @(); indexRefName = "kibanaSavedObjectMeta.searchSourceJSON.index" }
}
function Save-Object([string]$Type, [string]$Id, $Attributes, [array]$References, $MigrationVersion) {
  $body = Json @{ attributes = $Attributes; references = $References }
  $endpoint = "$($DashboardsUrl.TrimEnd('/'))/api/saved_objects/$Type/$Id`?overwrite=true"
  $bodyFile = [IO.Path]::GetTempFileName()
  try {
    [IO.File]::WriteAllText($bodyFile, $body, [Text.UTF8Encoding]::new($false))
    $response = curl.exe -k -sS --fail-with-body -H "osd-xsrf: true" -H "Content-Type: application/json" -X POST $endpoint --data-binary "@$bodyFile"
    if ($LASTEXITCODE -ne 0) { throw "Failed to save $Type/$Id`: $response" }
  } finally {
    Remove-Item -LiteralPath $bodyFile -Force -ErrorAction SilentlyContinue
  }
  Write-Host "saved $Type/$Id"
}

$indexReference = @(@{ name = "kibanaSavedObjectMeta.searchSourceJSON.index"; id = $indexPatternId; type = "index-pattern" })
function Ensure-OperationalFields {
  $endpoint = "$($DashboardsUrl.TrimEnd('/'))/api/saved_objects/index-pattern/$indexPatternId"
  $existingJson = curl.exe -k -sS --fail-with-body -H "osd-xsrf: true" $endpoint
  if ($LASTEXITCODE -ne 0) { throw "Failed to read index pattern: $existingJson" }
  $existing = $existingJson | ConvertFrom-Json
  $parsed = ConvertFrom-Json -InputObject $existing.attributes.fields
  $fields = @()
  foreach ($item in @($parsed)) {
    if ($item.PSObject.Properties.Name -contains "value") { $fields += @($item.value) }
    elseif ($item.PSObject.Properties.Name -contains "name") { $fields += $item }
  }
  $required = @(
    @{name="ingest_bytes";type="number";esTypes=@("long")}, @{name="event_count";type="number";esTypes=@("long")},
    @{name="event_reason";type="string";esTypes=@("keyword")}, @{name="event_kind";type="string";esTypes=@("keyword")},
    @{name="event_name";type="string";esTypes=@("keyword")}, @{name="event_action";type="string";esTypes=@("keyword")},
    @{name="event_source";type="string";esTypes=@("keyword")}, @{name="level_source";type="string";esTypes=@("keyword")}
  )
  foreach ($field in $required) {
    if (-not ($fields | Where-Object { $_.name -eq $field.name })) {
      $fields += [pscustomobject]@{ name=$field.name; type=$field.type; esTypes=$field.esTypes; scripted=$false; searchable=$true; aggregatable=$true; readFromDocValues=$true }
    }
  }
  $attributes = @{}
  foreach ($property in $existing.attributes.PSObject.Properties) { $attributes[$property.Name] = $property.Value }
  $attributes.fields = Json $fields
  $formatMap = @{}
  if ($attributes.fieldFormatMap) {
    $parsedFormatMap = $attributes.fieldFormatMap | ConvertFrom-Json
    foreach ($property in $parsedFormatMap.PSObject.Properties) { $formatMap[$property.Name] = $property.Value }
  }
  # Keep the indexed value in bytes for exact aggregation, but render sums as
  # KB/MB/GB according to magnitude in metrics and data tables.
  $formatMap.ingest_bytes = @{ id = "bytes"; params = @{ pattern = "0,0.[00] b" } }
  $attributes.fieldFormatMap = Json $formatMap
  Save-Object "index-pattern" $indexPatternId $attributes @($existing.references) @{ "index-pattern" = "7.6.0" }
}
function Save-Visualization([string]$Id, [string]$Title, [string]$Description, $VisState, [string]$Query = "") {
  Save-Object "visualization" $Id @{
    title = $Title; description = $Description; version = 1; uiStateJSON = "{}"
    visState = Json $VisState
    kibanaSavedObjectMeta = @{ searchSourceJSON = SearchSource $Query }
  } $indexReference @{ visualization = "7.10.0" }
}
function Save-Count([string]$Id, [string]$Title, [string]$Query, [string]$Description, [switch]$Risk) {
  $metricColorMode = if ($Risk) { "Labels" } else { "None" }
  $useRanges = [bool]$Risk
  $ranges = @()
  if ($Risk) {
    $ranges += @{ from = 0; to = 1 }
    $ranges += @{ from = 1; to = 10000000 }
  } else {
    $ranges += @{ from = 0; to = 10000000 }
  }
  Save-Visualization $Id $Title $Description @{
    title = $Title; type = "metric"
    aggs = @(@{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} })
    params = @{ type = "metric"; addTooltip = $true; addLegend = $false; metric = @{ percentageMode = $false; useRanges = $useRanges; colorSchema = "Green to Red"; metricColorMode = $metricColorMode; invertColors = $false; colorsRange = $ranges; labels = @{ show = $true }; style = @{ bgFill = "#000"; bgColor = $false; labelColor = $false; fontSize = 48; subText = "" } } }
  } $Query
}
function Save-Terms([string]$Id, [string]$Title, [string]$Query, [string]$Field, [string]$Description, [int]$Size = 10, [string]$SeriesColor = "", [switch]$CategoryPalette, [hashtable]$Colors = @{}) {
  $bucketSchema = if ($CategoryPalette) { "group" } else { "segment" }
  $series = @{ data = @{ id = "1"; label = "Count" }; type = "histogram"; mode = "normal"; valueAxis = "ValueAxis-1"; drawLines = $true; showCircles = $true; barWidth = 0.2 }
  if ($SeriesColor) { $series.color = $SeriesColor } elseif (-not $CategoryPalette) { $series.color = "#5274C7" }
  Save-Visualization $Id $Title $Description @{
    title = $Title; type = "horizontal_bar"
    aggs = @(
      @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} },
      @{ id = "2"; enabled = $true; type = "terms"; schema = $bucketSchema; params = @{ field = $Field; size = $Size; order = "desc"; orderBy = "1"; otherBucket = $false; missingBucket = $false } }
    )
    params = @{ type = "histogram"; addTooltip = $true; addLegend = [bool]$CategoryPalette; legendPosition = "right"; seriesParams = @($series); colors = $Colors }
  } $Query
}
function Save-GroupHeader([string]$Id, [string]$Title) {
  Save-Visualization $Id $Title $Title @{
    title = $Title; type = "markdown"; aggs = @()
    params = @{ markdown = "### $Title"; openLinksInNewTab = $false }
  }
}

Ensure-OperationalFields

# Scope: Platform -> Namespace -> Area -> Workload/App.
$controls = @{
  title = "조회 범위"; type = "input_control_vis"; aggs = @()
  params = @{ updateFiltersOnChange = $true; useTimeFilter = $true; pinFilters = $false; controls = @(
    @{ id = "platform"; label = "플랫폼"; type = "list"; parent = ""; indexPatternRefName = "control_0_index_pattern"; fieldName = "collector_platform"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 10; order = "desc" } },
    @{ id = "namespace"; label = "네임스페이스"; type = "list"; parent = "platform"; indexPatternRefName = "control_1_index_pattern"; fieldName = "namespace"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 30; order = "desc" } },
    @{ id = "area"; label = "영역"; type = "list"; parent = "namespace"; indexPatternRefName = "control_2_index_pattern"; fieldName = "area"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 30; order = "desc" } },
    @{ id = "workload"; label = "워크로드/앱"; type = "list"; parent = "area"; indexPatternRefName = "control_3_index_pattern"; fieldName = "app"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 50; order = "desc" } }
  ) }
}
$controlRefs = 0..3 | ForEach-Object { @{ name = "control_$($_)_index_pattern"; id = $indexPatternId; type = "index-pattern" } }
Save-Object "visualization" "platform-ops-scope-v2" @{ title = "조회 범위"; description = "플랫폼, 네임스페이스, 영역, 워크로드 순서의 단계별 필터입니다."; version = 1; uiStateJSON = "{}"; visState = Json $controls; kibanaSavedObjectMeta = @{ searchSourceJSON = Json @{ query = @{ query = ""; language = "kuery" }; filter = @() } } } $controlRefs @{ visualization = "7.10.0" }

Save-GroupHeader "platform-ops-group-current" "1. 운영 현황"
Save-GroupHeader "platform-ops-group-incident" "2. 장애 발생 위치 분석"
Save-GroupHeader "platform-ops-group-cluster" "3. 클러스터 변경 및 이벤트"
Save-GroupHeader "platform-ops-group-health" "4. 로그 플랫폼 상태"

# 1. Current health
Save-Count "platform-ops-total" "전체 로그" "" "선택한 시간 범위의 전체 플랫폼 로그입니다."
Save-Count "platform-ops-warning" "경고 로그" 'level : warning' "정규화된 경고 로그입니다."
Save-Count "platform-ops-error" "오류 로그" 'level : error' "정규화된 오류 로그입니다."
Save-Count "platform-ops-k8s-warning" "K8s 경고" 'app : kubernetes-events and level : warning' "Kubernetes API에서 수집한 경고 이벤트입니다."
Save-Count "platform-ops-delivery-fail" "전송 실패" 'namespace : logging and app : fluent-bit and level : error and message : (flush or retry or delivery or opensearch)' "Fluent Bit의 OpenSearch 전송 실패 이벤트입니다." -Risk

$volume = @{ title = "시간대별 로그 발생량"; type = "line"; aggs = @(
  @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} },
  @{ id = "2"; enabled = $true; type = "date_histogram"; schema = "segment"; params = @{ field = "@timestamp"; interval = "auto"; min_doc_count = 1; extended_bounds = @{ min = ""; max = "" } } }
); params = @{ type = "line"; addTooltip = $true; addLegend = $false; seriesParams = @(@{ show = "true"; type = "line"; mode = "normal"; data = @{ id = "1"; label = "Logs" }; valueAxis = "ValueAxis-1"; drawLines = $true; showCircles = $false; lineWidth = 2; interpolation = "linear" }) } }
Save-Visualization "platform-ops-volume-trend" "시간대별 로그 발생량" "선택한 범위의 로그 발생 추이입니다." $volume

$levels = @{ title = "로그 레벨 분포"; type = "pie"; aggs = @(
  @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} },
  @{ id = "2"; enabled = $true; type = "terms"; schema = "segment"; params = @{ field = "level"; size = 5; order = "desc"; orderBy = "1"; missingBucket = $true; otherBucket = $false } }
); params = @{ type = "pie"; addTooltip = $true; addLegend = $true; legendPosition = "right"; isDonut = $true; labels = @{ show = $true; values = $true; last_level = $true; truncate = 100 }; colors = @{ info = "#00A69C"; warning = "#F9AB00"; error = "#D36086"; unknown = "#5274C7" } } }
Save-Visualization "platform-ops-levels" "로그 레벨 분포" "정규화된 로그 레벨 분포입니다. unknown은 빈 메시지 또는 파싱 실패를 의미합니다." $levels
Save-Terms "platform-ops-unknown-apps" "Unknown 레벨 발생 상위 앱" 'level : unknown' "app" "빈 메시지 또는 파싱 실패가 발생한 앱을 확인하는 임시 진단 패널입니다." 15

# 2. Incident location
$platformColors = @{ aws = "#00A69C"; gcp = "#5274C7"; onp = "#8E5EA2"; unknown = "#8A8A8A" }
Save-Terms "platform-ops-errors-by-namespace" "네임스페이스별 경고/오류" 'level : (warning or error)' "namespace" "경고와 오류가 집중된 네임스페이스를 확인합니다." 15 "#D36086"
Save-Terms "platform-ops-top-error-workloads" "오류 발생 상위 워크로드" 'level : error' "app" "오류 로그를 가장 많이 발생시킨 워크로드입니다." 10
Save-Terms "platform-ops-by-platform" "플랫폼별 로그 발생량" "" "collector_platform" "AWS, GCP, 온프레미스의 로그 발생량을 비교합니다." 10 "" -CategoryPalette -Colors $platformColors
Save-Terms "platform-ops-top-producers" "로그 발생량 상위 소스" "" "app" "로그를 가장 많이 발생시킨 워크로드/앱입니다." 15

Save-Object "search" "platform-ops-recent-warning-error" @{
  title = "최근 경고/오류 로그"; description = "선택한 범위의 최신 경고 및 오류 로그입니다."; hits = 0
  columns = @("collector_platform", "namespace", "app", "level", "message")
  sort = @("@timestamp", "desc")
  kibanaSavedObjectMeta = @{ searchSourceJSON = SearchSource 'level : (warning or error)' }
} $indexReference @{ search = "7.9.3" }

# 3. Cluster changes
Save-Terms "platform-ops-k8s-reasons" "Kubernetes 경고 이벤트 주요 발생 원인" 'app : kubernetes-events and level : warning' "event_reason" "Kubernetes 경고 이벤트를 발생 원인별로 표시합니다." 12
Save-Object "search" "platform-ops-scaling-events" @{
  title = "스케일링 이벤트 타임라인"; description = "HPA, Karpenter, Node 및 스케줄링 이벤트를 시간순으로 확인합니다."; hits = 0
  columns = @("collector_platform", "namespace", "event_kind", "event_name", "event_reason", "message")
  sort = @("@timestamp", "desc")
  kibanaSavedObjectMeta = @{ searchSourceJSON = SearchSource 'app : kubernetes-events and (event_reason : SuccessfulRescale or event_kind : NodeClaim or event_reason : (DisruptionBlocked or Disrupted or Registered or NodeReady or Scheduled))' }
} $indexReference @{ search = "7.9.3" }
Save-Count "platform-ops-argocd" "Argo CD 경고/오류" 'app : argocd* and level : (warning or error)' "Argo CD의 경고 및 오류 로그입니다."
Save-Terms "platform-ops-core-components" "핵심 컴포넌트 경고/오류" 'level : (warning or error) and app : (jenkins or keycloak or oauth2-proxy or opensearch or opensearch-dashboards or cert-manager or external-secrets)' "app" "핵심 플랫폼 컴포넌트의 경고 및 오류입니다." 12

# 4. Logging platform health and approximate source ingest
Save-Count "platform-ops-logging-error" "로깅 스택 오류" 'namespace : logging and level : error' "로깅 스택에서 발생한 오류 로그입니다." -Risk
$dailyIngest = @{ title = "최근 24시간 원본 로그 용량(근사치)"; type = "metric"; aggs = @(@{ id = "1"; enabled = $true; type = "sum"; schema = "metric"; params = @{ field = "ingest_bytes"; customLabel = "용량" } }); params = @{ type = "metric"; addTooltip = $true; addLegend = $false; metric = @{ percentageMode = $false; useRanges = $false; colorSchema = "Green to Red"; metricColorMode = "None"; invertColors = $false; colorsRange = @(@{ from = 0; to = 1000000000000 }); labels = @{ show = $true }; style = @{ bgFill = "#000"; bgColor = $false; labelColor = $false; fontSize = 42; subText = "원본 메시지 기준" } } } }
Save-Visualization "platform-ops-daily-ingest" "최근 24시간 원본 로그 용량(근사치)" "최근 24시간 SUM(ingest_bytes)이며 크기에 따라 B/KB/MB/GB로 표시합니다." $dailyIngest
$ingestTrend = @{ title = "시간대별 원본 로그 용량(근사치)"; type = "line"; aggs = @(
  @{ id = "1"; enabled = $true; type = "sum"; schema = "metric"; params = @{ field = "ingest_bytes"; customLabel = "용량" } },
  @{ id = "2"; enabled = $true; type = "date_histogram"; schema = "segment"; params = @{ field = "@timestamp"; interval = "auto"; min_doc_count = 1; extended_bounds = @{ min = ""; max = "" } } }
); params = @{ type = "line"; addTooltip = $true; addLegend = $false; seriesParams = @(@{ show = "true"; type = "line"; mode = "normal"; data = @{ id = "1"; label = "용량" }; valueAxis = "ValueAxis-1"; drawLines = $true; showCircles = $false; lineWidth = 2; interpolation = "linear" }) } }
Save-Visualization "platform-ops-ingest-trend" "시간대별 원본 로그 용량(근사치)" "시간대별 SUM(ingest_bytes)이며 크기에 따라 B/KB/MB/GB로 표시합니다." $ingestTrend
$usage = @{ title = "네임스페이스별 원본 로그 용량"; type = "table"; aggs = @(
  @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{ customLabel = "로그 수" } },
  @{ id = "2"; enabled = $true; type = "sum"; schema = "metric"; params = @{ field = "ingest_bytes"; customLabel = "원본 로그 용량(근사치)" } },
  @{ id = "3"; enabled = $true; type = "terms"; schema = "bucket"; params = @{ field = "namespace"; size = 30; order = "desc"; orderBy = "2"; otherBucket = $false; missingBucket = $false } }
); params = @{ type = "table"; perPage = 15; showPartialRows = $false; showMetricsAtAllLevels = $false; sort = @{ columnIndex = 2; direction = "desc" }; showTotal = $false; totalFunc = "sum" } }
Save-Visualization "platform-ops-usage-by-namespace" "네임스페이스별 원본 로그 용량" "네임스페이스별 로그 수와 원본 로그 용량의 근사치입니다." $usage

$panels = @()
function Panel([string]$Index, [string]$Ref, [int]$X, [int]$Y, [int]$W, [int]$H, $Config = @{}) { @{ gridData = @{ x=$X; y=$Y; w=$W; h=$H; i=$Index }; panelIndex=$Index; version="7.10.0"; panelRefName=$Ref; embeddableConfig=$Config } }
$panels += Panel "scope" "p_scope" 0 0 48 5
$panels += Panel "group-current" "p_group_current" 0 5 48 2 @{ hidePanelTitles=$true }
$panels += Panel "total" "p_total" 0 7 10 7; $panels += Panel "warning" "p_warning" 10 7 9 7; $panels += Panel "error" "p_error" 19 7 9 7; $panels += Panel "k8s" "p_k8s" 28 7 10 7; $panels += Panel "delivery" "p_delivery" 38 7 10 7
$panels += Panel "volume" "p_volume" 0 14 32 10; $panels += Panel "levels" "p_levels" 32 14 16 10
$panels += Panel "group-incident" "p_group_incident" 0 24 48 2 @{ hidePanelTitles=$true }
$panels += Panel "ns" "p_ns" 0 26 24 10; $panels += Panel "errapp" "p_errapp" 24 26 24 10
$panels += Panel "recent" "p_recent" 0 36 48 12 @{ columns=@("collector_platform","namespace","app","level","message"); sort=@("@timestamp","desc") }
$panels += Panel "platform" "p_platform" 0 48 24 10; $panels += Panel "producer" "p_producer" 24 48 24 10
$panels += Panel "group-cluster" "p_group_cluster" 0 58 48 2 @{ hidePanelTitles=$true }
$panels += Panel "reasons" "p_reasons" 0 60 24 10; $panels += Panel "scaling" "p_scaling" 24 60 24 10
$panels += Panel "argocd" "p_argocd" 0 70 24 8; $panels += Panel "core" "p_core" 24 70 24 8
$panels += Panel "group-health" "p_group_health" 0 78 48 2 @{ hidePanelTitles=$true }
$panels += Panel "delivery2" "p_delivery" 0 80 24 7; $panels += Panel "logerr" "p_logerr" 24 80 24 7
$panels += Panel "daily" "p_daily" 0 87 24 11 @{ timeRange=@{from="now-24h";to="now"} }; $panels += Panel "ingest" "p_ingest" 24 87 24 11
$panels += Panel "usage" "p_usage" 0 98 48 12
$panels += Panel "unknown" "p_unknown" 0 110 48 10

$refs = @(
  @{name="p_scope";id="platform-ops-scope-v2";type="visualization"}, @{name="p_group_current";id="platform-ops-group-current";type="visualization"}, @{name="p_group_incident";id="platform-ops-group-incident";type="visualization"}, @{name="p_group_cluster";id="platform-ops-group-cluster";type="visualization"}, @{name="p_group_health";id="platform-ops-group-health";type="visualization"},
  @{name="p_total";id="platform-ops-total";type="visualization"}, @{name="p_warning";id="platform-ops-warning";type="visualization"}, @{name="p_error";id="platform-ops-error";type="visualization"}, @{name="p_k8s";id="platform-ops-k8s-warning";type="visualization"}, @{name="p_delivery";id="platform-ops-delivery-fail";type="visualization"},
  @{name="p_volume";id="platform-ops-volume-trend";type="visualization"}, @{name="p_levels";id="platform-ops-levels";type="visualization"}, @{name="p_ns";id="platform-ops-errors-by-namespace";type="visualization"}, @{name="p_errapp";id="platform-ops-top-error-workloads";type="visualization"}, @{name="p_recent";id="platform-ops-recent-warning-error";type="search"}, @{name="p_platform";id="platform-ops-by-platform";type="visualization"}, @{name="p_producer";id="platform-ops-top-producers";type="visualization"},
  @{name="p_reasons";id="platform-ops-k8s-reasons";type="visualization"}, @{name="p_scaling";id="platform-ops-scaling-events";type="search"}, @{name="p_argocd";id="platform-ops-argocd";type="visualization"}, @{name="p_core";id="platform-ops-core-components";type="visualization"},
  @{name="p_logerr";id="platform-ops-logging-error";type="visualization"}, @{name="p_daily";id="platform-ops-daily-ingest";type="visualization"}, @{name="p_ingest";id="platform-ops-ingest-trend";type="visualization"}, @{name="p_usage";id="platform-ops-usage-by-namespace";type="visualization"}, @{name="p_unknown";id="platform-ops-unknown-apps";type="visualization"}
)
Save-Object "dashboard" "platform-logging-operations-v2" @{
  title="플랫폼 로그 운영 v2"; description="운영 현황, 장애 위치, 클러스터 변경, 로그 플랫폼 상태 순서의 운영 로그 대시보드입니다."; version=1; hits=0
  panelsJSON=Json $panels; optionsJSON='{ "useMargins": true, "hidePanelTitles": false }'; timeRestore=$true; timeFrom="now-24h"; timeTo="now"; refreshInterval=@{pause=$false;value=30000}
  kibanaSavedObjectMeta=@{searchSourceJSON=Json @{query=@{query="";language="kuery"};filter=@()}}
} $refs @{dashboard="7.9.3"}

Write-Host "Dashboard: $($DashboardsUrl.TrimEnd('/'))/app/dashboards#/view/platform-logging-operations-v2"
