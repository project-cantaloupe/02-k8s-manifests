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
  $response = $body | curl.exe -k -sS --fail-with-body -H "osd-xsrf: true" -H "Content-Type: application/json" -X POST $endpoint --data-binary "@-"
  if ($LASTEXITCODE -ne 0) { throw "Failed to save $Type/$Id`: $response" }
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
  Save-Object "index-pattern" $indexPatternId $attributes @($existing.references) @{ "index-pattern" = "7.6.0" }
}
function Save-Visualization([string]$Id, [string]$Title, [string]$Description, $VisState, [string]$Query = "") {
  Save-Object "visualization" $Id @{
    title = $Title; description = $Description; version = 1; uiStateJSON = "{}"
    visState = Json $VisState
    kibanaSavedObjectMeta = @{ searchSourceJSON = SearchSource $Query }
  } $indexReference @{ visualization = "7.10.0" }
}
function Save-Count([string]$Id, [string]$Title, [string]$Query, [string]$Description) {
  Save-Visualization $Id $Title $Description @{
    title = $Title; type = "metric"
    aggs = @(@{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} })
    params = @{ type = "metric"; addTooltip = $true; addLegend = $false; metric = @{ percentageMode = $false; useRanges = $false; colorSchema = "Green to Red"; metricColorMode = "None"; invertColors = $false; colorsRange = @(@{ from = 0; to = 10000 }); labels = @{ show = $true }; style = @{ bgFill = "#000"; bgColor = $false; labelColor = $false; fontSize = 48; subText = "" } } }
  } $Query
}
function Save-Terms([string]$Id, [string]$Title, [string]$Query, [string]$Field, [string]$Description, [int]$Size = 10) {
  Save-Visualization $Id $Title $Description @{
    title = $Title; type = "horizontal_bar"
    aggs = @(
      @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} },
      @{ id = "2"; enabled = $true; type = "terms"; schema = "segment"; params = @{ field = $Field; size = $Size; order = "desc"; orderBy = "1"; otherBucket = $false; missingBucket = $false } }
    )
    params = @{ type = "histogram"; addTooltip = $true; addLegend = $false; legendPosition = "right"; seriesParams = @(@{ data = @{ id = "1"; label = "Count" }; type = "histogram"; mode = "normal"; valueAxis = "ValueAxis-1"; drawLines = $true; showCircles = $true; barWidth = 0.2 }) }
  } $Query
}

Ensure-OperationalFields

# Scope: Platform -> Namespace -> Area -> Workload/App.
$controls = @{
  title = "Operations Scope Filters"; type = "input_control_vis"; aggs = @()
  params = @{ updateFiltersOnChange = $true; useTimeFilter = $true; pinFilters = $false; controls = @(
    @{ id = "platform"; label = "Platform"; type = "list"; parent = ""; indexPatternRefName = "control_0_index_pattern"; fieldName = "collector_platform"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 10; order = "desc" } },
    @{ id = "namespace"; label = "Namespace"; type = "list"; parent = "platform"; indexPatternRefName = "control_1_index_pattern"; fieldName = "namespace"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 30; order = "desc" } },
    @{ id = "area"; label = "Area"; type = "list"; parent = "namespace"; indexPatternRefName = "control_2_index_pattern"; fieldName = "area"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 30; order = "desc" } },
    @{ id = "workload"; label = "Workload/App"; type = "list"; parent = "area"; indexPatternRefName = "control_3_index_pattern"; fieldName = "app"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 50; order = "desc" } }
  ) }
}
$controlRefs = 0..3 | ForEach-Object { @{ name = "control_$($_)_index_pattern"; id = $indexPatternId; type = "index-pattern" } }
Save-Object "visualization" "platform-ops-scope-v2" @{ title = "Operations Scope Filters"; description = "Progressive platform, namespace, area, and workload filters."; version = 1; uiStateJSON = "{}"; visState = Json $controls; kibanaSavedObjectMeta = @{ searchSourceJSON = Json @{ query = @{ query = ""; language = "kuery" }; filter = @() } } } $controlRefs @{ visualization = "7.10.0" }

# 1. Current health
Save-Count "platform-ops-total" "Total Logs" "" "All platform log documents in the selected time range."
Save-Count "platform-ops-warning" "Warning" 'level : warning' "Normalized warning-level logs."
Save-Count "platform-ops-error" "Error" 'level : error' "Normalized error-level logs."
Save-Count "platform-ops-k8s-warning" "K8s Warning Events" 'app : kubernetes-events and level : warning' "Kubernetes API warning events collected by the dedicated single-replica event collector."
Save-Count "platform-ops-delivery-fail" "Delivery Failures" 'namespace : logging and app : fluent-bit and level : error and message : (flush or retry or delivery or opensearch)' "Fluent Bit output delivery failures, not all Fluent Bit errors."

$volume = @{ title = "Log Volume Over Time"; type = "line"; aggs = @(
  @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} },
  @{ id = "2"; enabled = $true; type = "date_histogram"; schema = "segment"; params = @{ field = "@timestamp"; interval = "auto"; min_doc_count = 1; extended_bounds = @{ min = ""; max = "" } } }
); params = @{ type = "line"; addTooltip = $true; addLegend = $false; seriesParams = @(@{ show = "true"; type = "line"; mode = "normal"; data = @{ id = "1"; label = "Logs" }; valueAxis = "ValueAxis-1"; drawLines = $true; showCircles = $false; lineWidth = 2; interpolation = "linear" }) } }
Save-Visualization "platform-ops-volume-trend" "Log Volume Over Time" "Log production trend for the selected scope." $volume

$levels = @{ title = "Log Level Distribution"; type = "pie"; aggs = @(
  @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} },
  @{ id = "2"; enabled = $true; type = "terms"; schema = "segment"; params = @{ field = "level"; size = 5; order = "desc"; orderBy = "1"; missingBucket = $true; otherBucket = $false } }
); params = @{ type = "pie"; addTooltip = $true; addLegend = $true; legendPosition = "right"; isDonut = $true; labels = @{ show = $true; values = $true; last_level = $true; truncate = 100 }; colors = @{ info = "#00A69C"; warning = "#F9AB00"; error = "#D36086"; unknown = "#5274C7" } } }
Save-Visualization "platform-ops-levels" "Log Level Distribution" "Normalized levels; unknown indicates missing source severity after parser fallbacks." $levels
Save-Terms "platform-ops-unknown-apps" "Top Apps Producing Unknown Log Level" 'level : unknown' "app" "Temporary data-quality diagnostic. Unknown is now reserved for empty or unparseable records." 15

# 2. Incident location
Save-Terms "platform-ops-errors-by-namespace" "Warning / Error by Namespace" 'level : (warning or error)' "namespace" "Where warning/error logs are concentrated." 15
Save-Terms "platform-ops-top-error-workloads" "Top Error Workloads" 'level : error' "app" "Workloads producing the most error logs." 10
Save-Terms "platform-ops-by-platform" "Log Volume by Platform" "" "collector_platform" "Compare AWS, GCP, and on-prem log volume." 10
Save-Terms "platform-ops-top-producers" "Top Log Producers" "" "app" "Highest-volume workloads/apps; use the scope controls to drill into namespace and pod." 15

Save-Object "search" "platform-ops-recent-warning-error" @{
  title = "Recent Warning / Error Logs"; description = "Latest warning/error evidence in the selected scope."; hits = 0
  columns = @("collector_platform", "namespace", "app", "level", "message")
  sort = @("@timestamp", "desc")
  kibanaSavedObjectMeta = @{ searchSourceJSON = SearchSource 'level : (warning or error)' }
} $indexReference @{ search = "7.9.3" }

# 3. Cluster changes
Save-Terms "platform-ops-k8s-reasons" "Kubernetes Warning Event Reasons" 'app : kubernetes-events and level : warning' "event_reason" "Warning events grouped by Kubernetes reason." 12
Save-Object "search" "platform-ops-scaling-events" @{
  title = "Scaling Events Timeline"; description = "HPA, Karpenter, Node, and scheduling events that explain scaling changes."; hits = 0
  columns = @("collector_platform", "namespace", "event_kind", "event_name", "event_reason", "message")
  sort = @("@timestamp", "desc")
  kibanaSavedObjectMeta = @{ searchSourceJSON = SearchSource 'app : kubernetes-events and (event_reason : SuccessfulRescale or event_kind : NodeClaim or event_reason : (DisruptionBlocked or Disrupted or Registered or NodeReady or Scheduled))' }
} $indexReference @{ search = "7.9.3" }
Save-Count "platform-ops-argocd" "Argo CD Warning / Error" 'app : argocd* and level : (warning or error)' "Explicit Argo CD warning/error logs."
Save-Terms "platform-ops-harbor" "Harbor Registry HTTP Errors" 'app : harbor* and http_status_class : (4xx or 5xx)' "http_status_class" "Harbor 4xx and 5xx responses only." 4
Save-Terms "platform-ops-core-components" "Other Core Component Errors" 'level : (warning or error) and app : (jenkins or keycloak or oauth2-proxy or opensearch or opensearch-dashboards or cert-manager or external-secrets)' "app" "Warning/error logs from other core platform components." 12

# 4. Logging platform health and approximate source ingest
Save-Count "platform-ops-logging-error" "Logging Stack Errors" 'namespace : logging and level : error' "Error-level events emitted by the logging stack."
$dailyIngest = @{ title = "Daily Source Ingest Bytes"; type = "metric"; aggs = @(@{ id = "1"; enabled = $true; type = "sum"; schema = "metric"; params = @{ field = "ingest_bytes"; customLabel = "Bytes" } }); params = @{ type = "metric"; addTooltip = $true; addLegend = $false; metric = @{ percentageMode = $false; useRanges = $false; metricColorMode = "None"; labels = @{ show = $true }; style = @{ bgFill = "#000"; bgColor = $false; labelColor = $false; fontSize = 42; subText = "source payload bytes" } } } }
Save-Visualization "platform-ops-daily-ingest" "Daily Source Ingest Bytes" "Approximate source message bytes indexed during the panel's fixed 24-hour window; this is not Lucene store size." $dailyIngest
$ingestTrend = @{ title = "Ingest Volume Over Time"; type = "line"; aggs = @(
  @{ id = "1"; enabled = $true; type = "sum"; schema = "metric"; params = @{ field = "ingest_bytes"; customLabel = "Bytes" } },
  @{ id = "2"; enabled = $true; type = "date_histogram"; schema = "segment"; params = @{ field = "@timestamp"; interval = "auto"; min_doc_count = 1; extended_bounds = @{ min = ""; max = "" } } }
); params = @{ type = "line"; addTooltip = $true; addLegend = $false; seriesParams = @(@{ show = "true"; type = "line"; mode = "normal"; data = @{ id = "1"; label = "Bytes" }; valueAxis = "ValueAxis-1"; drawLines = $true; showCircles = $false; lineWidth = 2; interpolation = "linear" }) } }
Save-Visualization "platform-ops-ingest-trend" "Ingest Volume Over Time" "Approximate source message bytes over time." $ingestTrend
$usage = @{ title = "Log Usage by Namespace"; type = "table"; aggs = @(
  @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{ customLabel = "Documents" } },
  @{ id = "2"; enabled = $true; type = "sum"; schema = "metric"; params = @{ field = "ingest_bytes"; customLabel = "Ingest Bytes" } },
  @{ id = "3"; enabled = $true; type = "terms"; schema = "bucket"; params = @{ field = "namespace"; size = 30; order = "desc"; orderBy = "2"; otherBucket = $false; missingBucket = $false } }
); params = @{ type = "table"; perPage = 15; showPartialRows = $false; showMetricsAtAllLevels = $false; sort = @{ columnIndex = 2; direction = "desc" }; showTotal = $false; totalFunc = "sum" } }
Save-Visualization "platform-ops-usage-by-namespace" "Log Usage by Namespace" "Documents and approximate source payload bytes by namespace." $usage

$panels = @()
function Panel([string]$Index, [string]$Ref, [int]$X, [int]$Y, [int]$W, [int]$H, $Config = @{}) { @{ gridData = @{ x=$X; y=$Y; w=$W; h=$H; i=$Index }; panelIndex=$Index; version="7.10.0"; panelRefName=$Ref; embeddableConfig=$Config } }
$panels += Panel "scope" "p_scope" 0 0 48 5
$panels += Panel "total" "p_total" 0 5 10 7; $panels += Panel "warning" "p_warning" 10 5 9 7; $panels += Panel "error" "p_error" 19 5 9 7; $panels += Panel "k8s" "p_k8s" 28 5 10 7; $panels += Panel "delivery" "p_delivery" 38 5 10 7
$panels += Panel "volume" "p_volume" 0 12 32 10; $panels += Panel "levels" "p_levels" 32 12 16 10
$panels += Panel "ns" "p_ns" 0 22 24 10; $panels += Panel "errapp" "p_errapp" 24 22 24 10
$panels += Panel "recent" "p_recent" 0 32 48 12 @{ columns=@("collector_platform","namespace","app","level","message"); sort=@("@timestamp","desc") }
$panels += Panel "platform" "p_platform" 0 44 24 10; $panels += Panel "producer" "p_producer" 24 44 24 10
$panels += Panel "reasons" "p_reasons" 0 54 24 10; $panels += Panel "scaling" "p_scaling" 24 54 24 10
$panels += Panel "argocd" "p_argocd" 0 64 14 8; $panels += Panel "harbor" "p_harbor" 14 64 16 8; $panels += Panel "core" "p_core" 30 64 18 8
$panels += Panel "delivery2" "p_delivery" 0 72 12 7; $panels += Panel "logerr" "p_logerr" 12 72 12 7; $panels += Panel "daily" "p_daily" 24 72 12 7 @{ timeRange=@{from="now-24h";to="now"} }; $panels += Panel "ingest" "p_ingest" 36 72 12 7
$panels += Panel "usage" "p_usage" 0 79 48 12
$panels += Panel "unknown" "p_unknown" 0 91 48 10

$refs = @(
  @{name="p_scope";id="platform-ops-scope-v2";type="visualization"}, @{name="p_total";id="platform-ops-total";type="visualization"}, @{name="p_warning";id="platform-ops-warning";type="visualization"}, @{name="p_error";id="platform-ops-error";type="visualization"}, @{name="p_k8s";id="platform-ops-k8s-warning";type="visualization"}, @{name="p_delivery";id="platform-ops-delivery-fail";type="visualization"},
  @{name="p_volume";id="platform-ops-volume-trend";type="visualization"}, @{name="p_levels";id="platform-ops-levels";type="visualization"}, @{name="p_ns";id="platform-ops-errors-by-namespace";type="visualization"}, @{name="p_errapp";id="platform-ops-top-error-workloads";type="visualization"}, @{name="p_recent";id="platform-ops-recent-warning-error";type="search"}, @{name="p_platform";id="platform-ops-by-platform";type="visualization"}, @{name="p_producer";id="platform-ops-top-producers";type="visualization"},
  @{name="p_reasons";id="platform-ops-k8s-reasons";type="visualization"}, @{name="p_scaling";id="platform-ops-scaling-events";type="search"}, @{name="p_argocd";id="platform-ops-argocd";type="visualization"}, @{name="p_harbor";id="platform-ops-harbor";type="visualization"}, @{name="p_core";id="platform-ops-core-components";type="visualization"},
  @{name="p_logerr";id="platform-ops-logging-error";type="visualization"}, @{name="p_daily";id="platform-ops-daily-ingest";type="visualization"}, @{name="p_ingest";id="platform-ops-ingest-trend";type="visualization"}, @{name="p_usage";id="platform-ops-usage-by-namespace";type="visualization"}, @{name="p_unknown";id="platform-ops-unknown-apps";type="visualization"}
)
Save-Object "dashboard" "platform-logging-operations-v2" @{
  title="Platform Logging Operations v2"; description="Operational flow: current health, incident location, cluster changes, and logging platform health."; version=1; hits=0
  panelsJSON=Json $panels; optionsJSON='{ "useMargins": true, "hidePanelTitles": false }'; timeRestore=$true; timeFrom="now-24h"; timeTo="now"; refreshInterval=@{pause=$false;value=30000}
  kibanaSavedObjectMeta=@{searchSourceJSON=Json @{query=@{query="";language="kuery"};filter=@()}}
} $refs @{dashboard="7.9.3"}

Write-Host "Dashboard: $($DashboardsUrl.TrimEnd('/'))/app/dashboards#/view/platform-logging-operations-v2"
