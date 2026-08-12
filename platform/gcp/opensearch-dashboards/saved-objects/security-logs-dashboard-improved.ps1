param(
  [string]$DashboardsUrl = "https://cntlp-gcp-wk-02.tail270b85.ts.net"
)

$ErrorActionPreference = "Stop"
$indexPatternId = "cantaloupe-platform-logs-current"
$securityQuery = 'security_event_type : *'

function ConvertTo-CompactJson {
  param([Parameter(Mandatory = $true)]$Value, [int]$Depth = 20)
  return ConvertTo-Json -InputObject $Value -Depth $Depth -Compress
}

function New-SearchSource {
  param([string]$Query)
  return ConvertTo-CompactJson @{
    query = @{ query = $Query; language = "kuery" }
    filter = @()
    indexRefName = "kibanaSavedObjectMeta.searchSourceJSON.index"
  }
}

function Save-Object {
  param(
    [Parameter(Mandatory = $true)][string]$Type,
    [Parameter(Mandatory = $true)][string]$Id,
    [Parameter(Mandatory = $true)]$Attributes,
    [array]$References = @(),
    [Parameter(Mandatory = $true)]$MigrationVersion
  )

  $body = ConvertTo-CompactJson @{
    attributes = $Attributes
    references = $References
  }
  $endpoint = "$($DashboardsUrl.TrimEnd('/'))/api/saved_objects/$Type/$Id`?overwrite=true"
  $result = $body | curl.exe -k -sS --fail-with-body `
    -H "osd-xsrf: true" -H "Content-Type: application/json" `
    -X POST $endpoint --data-binary "@-"
  if ($LASTEXITCODE -ne 0) { throw "Failed to save $Type/$Id`: $result" }
  $saved = $result | ConvertFrom-Json
  Write-Host "saved $($saved.type)/$($saved.id)"
}

$indexReference = @(@{
  name = "kibanaSavedObjectMeta.searchSourceJSON.index"
  id = $indexPatternId
  type = "index-pattern"
})

function Save-Metric {
  param(
    [string]$Id,
    [string]$Title,
    [string]$Query,
    [string]$Description,
    [int]$AlertThreshold = 0,
    [string]$MetricLabel = "건"
  )
  $hasAlertThreshold = $AlertThreshold -gt 0
  $metricColorMode = if ($hasAlertThreshold) { "Labels" } else { "None" }
  $colorRanges = if ($hasAlertThreshold) {
    @(@{ from = 0; to = $AlertThreshold }, @{ from = $AlertThreshold; to = 10000 })
  } else {
    @(@{ from = 0; to = 10000 })
  }
  $visState = @{
    title = $Title
    type = "metric"
    aggs = @(@{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{ customLabel = $MetricLabel } })
    params = @{
      type = "metric"; addTooltip = $true; addLegend = $false
      metric = @{
        percentageMode = $false; useRanges = $hasAlertThreshold; colorSchema = "Green to Red"
        metricColorMode = $metricColorMode; invertColors = $false
        colorsRange = $colorRanges
        labels = @{ show = $true }
        style = @{ bgFill = "#000"; bgColor = $false; labelColor = $false; fontSize = 40; subText = "" }
      }
    }
  }
  Save-Object -Type visualization -Id $Id -Attributes @{
    title = $Title; description = $Description; version = 1; uiStateJSON = "{}"
    visState = ConvertTo-CompactJson $visState
    kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $Query }
  } -References $indexReference -MigrationVersion @{ visualization = "7.10.0" }
}

function Ensure-SecurityIndexPatternFields {
  $endpoint = "$($DashboardsUrl.TrimEnd('/'))/api/saved_objects/index-pattern/$indexPatternId"
  $existingJson = curl.exe -k -sS --fail-with-body -H "osd-xsrf: true" $endpoint
  if ($LASTEXITCODE -ne 0) { throw "Failed to read index pattern $indexPatternId`: $existingJson" }

  $existing = $existingJson | ConvertFrom-Json
  $parsedFields = ConvertFrom-Json -InputObject $existing.attributes.fields
  # Windows PowerShell 5.1 can preserve a previously wrapped array as a
  # single object with a `value` property. Unwrap it so Dashboards receives
  # the flat field-definition array it expects.
  $fields = @()
  foreach ($item in @($parsedFields)) {
    if ($item.PSObject.Properties.Name -contains "value") {
      $fields += @($item.value)
    } elseif ($item.PSObject.Properties.Name -contains "name") {
      $fields += $item
    }
  }
  $securityFields = @(
    @{ name = "security_event_type"; type = "string"; esTypes = @("keyword") },
    @{ name = "auth_result"; type = "string"; esTypes = @("keyword") },
    @{ name = "realm"; type = "string"; esTypes = @("keyword") },
    @{ name = "client_id"; type = "string"; esTypes = @("keyword") },
    @{ name = "error_code"; type = "string"; esTypes = @("keyword") },
    @{ name = "principal_masked"; type = "string"; esTypes = @("keyword") },
    @{ name = "source_network"; type = "string"; esTypes = @("keyword") },
    @{ name = "policy_name"; type = "string"; esTypes = @("keyword") },
    @{ name = "policy_result"; type = "string"; esTypes = @("keyword") },
    @{ name = "rule_name"; type = "string"; esTypes = @("keyword") }
  )

  foreach ($field in $securityFields) {
    if (-not ($fields | Where-Object { $_.name -eq $field.name })) {
      $fields += [pscustomobject]@{
        name = $field.name; type = $field.type; esTypes = $field.esTypes
        scripted = $false; searchable = $true; aggregatable = $true
        readFromDocValues = $true
      }
    }
  }

  $attributes = @{}
  foreach ($property in $existing.attributes.PSObject.Properties) {
    $attributes[$property.Name] = $property.Value
  }
  $attributes["fields"] = ConvertTo-Json -InputObject $fields -Depth 20 -Compress
  Save-Object -Type "index-pattern" -Id $indexPatternId -Attributes $attributes `
    -References @($existing.references) -MigrationVersion @{ "index-pattern" = "7.6.0" }
}

function Save-TermsBar {
  param(
    [string]$Id,
    [string]$Title,
    [string]$Query,
    [string]$Field,
    [string]$Description,
    [int]$Size = 10
  )
  $visState = @{
    title = $Title; type = "horizontal_bar"
    aggs = @(
      @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} },
      @{ id = "2"; enabled = $true; type = "terms"; schema = "segment"; params = @{ field = $Field; size = $Size; order = "desc"; orderBy = "1"; otherBucket = $false; missingBucket = $false } }
    )
    params = @{
      type = "histogram"; addTooltip = $true; addLegend = $false; legendPosition = "right"
      seriesParams = @(@{ data = @{ id = "1"; label = "Count" }; type = "histogram"; mode = "normal"; valueAxis = "ValueAxis-1"; drawLines = $true; showCircles = $true; barWidth = 0.18 })
    }
  }
  Save-Object -Type visualization -Id $Id -Attributes @{
    title = $Title; description = $Description; version = 1; uiStateJSON = "{}"
    visState = ConvertTo-CompactJson $visState
    kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $Query }
  } -References $indexReference -MigrationVersion @{ visualization = "7.10.0" }
}

function Save-TermsTable {
  param(
    [string]$Id,
    [string]$Title,
    [string]$Query,
    [string]$Field,
    [string]$BucketLabel,
    [string]$Description,
    [int]$Size = 5
  )

  $visState = @{
    title = $Title
    type = "table"
    aggs = @(
      @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{ customLabel = "건수" } },
      @{ id = "2"; enabled = $true; type = "terms"; schema = "bucket"; params = @{
          field = $Field; size = $Size; order = "desc"; orderBy = "1"
          otherBucket = $false; missingBucket = $false; customLabel = $BucketLabel
      } }
    )
    params = @{
      perPage = $Size
      showPartialRows = $false
      showMetricsAtAllLevels = $false
      sort = @{ columnIndex = 1; direction = "desc" }
      showTotal = $false
      totalFunc = "sum"
      percentageCol = ""
    }
  }

  Save-Object -Type visualization -Id $Id -Attributes @{
    title = $Title; description = $Description; version = 1; uiStateJSON = "{}"
    visState = ConvertTo-CompactJson $visState
    kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $Query }
  } -References $indexReference -MigrationVersion @{ visualization = "7.10.0" }
}

function Save-GroupHeader {
  param([string]$Id, [string]$Title)

  $visState = @{
    title = $Title
    type = "markdown"
    aggs = @()
    params = @{
      markdown = "#### $Title"
      openLinksInNewTab = $false
    }
  }

  Save-Object -Type visualization -Id $Id -Attributes @{
    title = $Title; description = ""; version = 1; uiStateJSON = "{}"
    visState = ConvertTo-CompactJson $visState
    kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource "" }
  } -References $indexReference -MigrationVersion @{ visualization = "7.10.0" }
}

Ensure-SecurityIndexPatternFields

# ---------------------------------------------------------------------------
# Scope filters
# 보안 로그 대시보드는 "사건 조사" 중심이다.
# 현재 Fluent Bit이 구조화하는 보안 이벤트는 Keycloak / OAuth2 Proxy / Kyverno이다.
# PSA / Calico / Istio 등은 security_event_type으로 구조화되기 전까지 빈 패널을 만들지 않는다.
# ---------------------------------------------------------------------------
$controlsState = @{
  title = "보안 로그 필터"
  type = "input_control_vis"
  aggs = @()
  params = @{
    updateFiltersOnChange = $true; useTimeFilter = $true; pinFilters = $false
    controls = @(
      @{ id = "platform"; label = "플랫폼"; type = "list"; parent = ""; indexPatternRefName = "control_0_index_pattern"; fieldName = "collector_platform"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 10; order = "desc" } },
      @{ id = "component"; label = "보안 컴포넌트"; type = "list"; parent = ""; indexPatternRefName = "control_1_index_pattern"; fieldName = "app"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 20; order = "desc" } },
      @{ id = "namespace"; label = "네임스페이스"; type = "list"; parent = ""; indexPatternRefName = "control_2_index_pattern"; fieldName = "namespace"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 20; order = "desc" } },
      @{ id = "level"; label = "심각도"; type = "list"; parent = ""; indexPatternRefName = "control_3_index_pattern"; fieldName = "level"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 10; order = "desc" } },
      @{ id = "result"; label = "인증 결과"; type = "list"; parent = ""; indexPatternRefName = "control_4_index_pattern"; fieldName = "auth_result"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 10; order = "desc" } }
    )
  }
}
Save-Object -Type visualization -Id "security-logs-scope-filters" -Attributes @{
  title = "보안 로그 필터"
  description = "플랫폼, 보안 컴포넌트, 네임스페이스, 심각도, 인증 결과 기준 필터입니다."
  version = 1; uiStateJSON = "{}"
  visState = ConvertTo-CompactJson $controlsState
  kibanaSavedObjectMeta = @{ searchSourceJSON = ConvertTo-CompactJson @{ query = @{ query = $securityQuery; language = "kuery" }; filter = @() } }
} -References @(
  @{ name = "control_0_index_pattern"; id = $indexPatternId; type = "index-pattern" },
  @{ name = "control_1_index_pattern"; id = $indexPatternId; type = "index-pattern" },
  @{ name = "control_2_index_pattern"; id = $indexPatternId; type = "index-pattern" },
  @{ name = "control_3_index_pattern"; id = $indexPatternId; type = "index-pattern" },
  @{ name = "control_4_index_pattern"; id = $indexPatternId; type = "index-pattern" }
) -MigrationVersion @{ visualization = "7.10.0" }

# ---------------------------------------------------------------------------
# Group headers
# ---------------------------------------------------------------------------
Save-GroupHeader "security-logs-group-overview" "1. 보안 현황"
Save-GroupHeader "security-logs-group-auth" "2. 인증 및 접근 분석"
Save-GroupHeader "security-logs-group-policy" "3. 정책 위반 및 보안 이벤트"
Save-GroupHeader "security-logs-group-evidence" "4. 최근 보안 이벤트"

# ---------------------------------------------------------------------------
# 1. 보안 현황
# ---------------------------------------------------------------------------
Save-Metric -Id "security-logs-failure-spike" -Title "최근 5분 인증 실패" `
  -Query 'auth_result : failure' `
  -Description "최근 5분 동안의 인증 실패 건수입니다. 50건 이상이면 강조합니다." `
  -AlertThreshold 50

Save-Metric -Id "security-logs-auth-failures" -Title "인증 실패" `
  -Query 'auth_result : failure' `
  -Description "조회 기간 내 Keycloak/OAuth2 Proxy 인증 실패 건수입니다." `
  -AlertThreshold 1

Save-Metric -Id "security-logs-callback-errors" -Title "OAuth 콜백 오류" `
  -Query 'security_event_type : oauth_callback and auth_result : failure' `
  -Description "OAuth authorization-code redemption 및 callback 실패 건수입니다." `
  -AlertThreshold 1

Save-Metric -Id "security-logs-logout-errors" -Title "로그아웃 오류" `
  -Query 'security_event_type : keycloak_logout_error and auth_result : failure' `
  -Description "Keycloak 로그아웃 실패 이벤트입니다." `
  -AlertThreshold 1

Save-Metric -Id "security-logs-kyverno-violations" -Title "Kyverno 정책 위반" `
  -Query 'security_event_type : kyverno_policy_violation' `
  -Description "Kyverno가 fail/deny/block/error로 판정한 정책 위반 건수입니다." `
  -AlertThreshold 1

# ---------------------------------------------------------------------------
# 2. 인증 및 접근 분석
# ---------------------------------------------------------------------------
$timelineState = @{
  title = "시간대별 인증 결과"
  type = "line"
  aggs = @(
    @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{ customLabel = "건수" } },
    @{ id = "2"; enabled = $true; type = "date_histogram"; schema = "segment"; params = @{ field = "@timestamp"; interval = "auto"; min_doc_count = 1; extended_bounds = @{ min = ""; max = "" } } },
    @{ id = "3"; enabled = $true; type = "filters"; schema = "group"; params = @{ filters = @(
      @{ label = "인증 실패"; input = @{ query = 'auth_result : failure'; language = "kuery" } },
      @{ label = "인증 성공"; input = @{ query = 'auth_result : success'; language = "kuery" } },
      @{ label = "OAuth 콜백 오류"; input = @{ query = 'security_event_type : oauth_callback and auth_result : failure'; language = "kuery" } }
    ) } }
  )
  params = @{
    type = "line"; addTooltip = $true; addLegend = $true; legendPosition = "right"
    seriesParams = @(@{
      show = "true"; type = "line"; mode = "normal"
      data = @{ id = "1"; label = "인증 이벤트" }
      valueAxis = "ValueAxis-1"; drawLines = $true; showCircles = $false
      lineWidth = 3; interpolation = "linear"
    })
    valueAxes = @(@{
      id = "ValueAxis-1"; name = "ValueAxis-1"; type = "value"; position = "left"; show = $true
      scale = @{ type = "linear"; mode = "normal" }
      labels = @{ show = $true; rotate = 0; filter = $false; truncate = 100 }
      title = @{ text = "건수" }
    })
  }
}
Save-Object -Type visualization -Id "security-logs-events-over-time" -Attributes @{
  title = "시간대별 인증 결과"
  description = "인증 성공/실패와 OAuth 콜백 오류의 시간대별 추이입니다."
  version = 1; uiStateJSON = "{}"
  visState = ConvertTo-CompactJson $timelineState
  kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $securityQuery }
} -References $indexReference -MigrationVersion @{ visualization = "7.10.0" }

Save-TermsTable -Id "security-logs-failure-reasons" -Title "인증 실패 원인 상위 5개" `
  -Query 'auth_result : failure and error_code : *' -Field "error_code" `
  -BucketLabel "실패 원인" `
  -Description "인증 실패를 error_code 기준으로 집계합니다." -Size 5

Save-TermsTable -Id "security-logs-failures-by-network" -Title "반복 인증 실패 네트워크 상위 5개" `
  -Query 'auth_result : failure and source_network : *' -Field "source_network" `
  -BucketLabel "마스킹 네트워크" `
  -Description "원본 IP가 아닌 마스킹된 source_network 기준 반복 인증 실패입니다." -Size 5

Save-TermsTable -Id "security-logs-failures-by-client" -Title "인증 실패 Client 상위 5개" `
  -Query 'auth_result : failure and client_id : *' -Field "client_id" `
  -BucketLabel "Client" `
  -Description "인증 실패를 client_id 기준으로 집계합니다." -Size 5

# ---------------------------------------------------------------------------
# 3. 정책 위반 및 보안 이벤트
# 현재 수집 파이프라인에서 구조화되는 정책 이벤트는 Kyverno 위반이다.
# ---------------------------------------------------------------------------
Save-TermsTable -Id "security-logs-kyverno-policy-top" -Title "Kyverno 위반 정책 상위 5개" `
  -Query 'security_event_type : kyverno_policy_violation and policy_name : *' -Field "policy_name" `
  -BucketLabel "정책" `
  -Description "Kyverno 위반 이벤트를 policy_name 기준으로 집계합니다." -Size 5

Save-TermsTable -Id "security-logs-events-by-component" -Title "보안 이벤트 발생 컴포넌트 상위 5개" `
  -Query $securityQuery -Field "app" `
  -BucketLabel "컴포넌트" `
  -Description "구조화된 보안 이벤트를 발생시킨 컴포넌트 상위 5개입니다." -Size 5

$classificationState = @{
  title = "보안 이벤트 분류"
  type = "pie"
  aggs = @(
    @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{ customLabel = "건수" } },
    @{ id = "2"; enabled = $true; type = "filters"; schema = "segment"; params = @{ filters = @(
      @{ label = "Keycloak 인증 실패"; input = @{ query = 'app : keycloak and auth_result : failure'; language = "kuery" } },
      @{ label = "OAuth 인증 실패"; input = @{ query = 'app : oauth2-proxy and auth_result : failure'; language = "kuery" } },
      @{ label = "인증 성공"; input = @{ query = 'auth_result : success'; language = "kuery" } },
      @{ label = "로그아웃/콜백 오류"; input = @{ query = 'security_event_type : (keycloak_logout_error or oauth_callback)'; language = "kuery" } },
      @{ label = "Kyverno 정책 위반"; input = @{ query = 'security_event_type : kyverno_policy_violation'; language = "kuery" } }
    ) } }
  )
  params = @{
    type = "pie"; addTooltip = $true; addLegend = $true; legendPosition = "right"
    isDonut = $true
    labels = @{ show = $true; values = $true; last_level = $true; truncate = 100 }
  }
}
Save-Object -Type visualization -Id "security-logs-event-classification" -Attributes @{
  title = "보안 이벤트 분류"
  description = "현재 구조화 가능한 Keycloak/OAuth2 Proxy/Kyverno 보안 이벤트 분류입니다."
  version = 1; uiStateJSON = "{}"
  visState = ConvertTo-CompactJson $classificationState
  kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $securityQuery }
} -References $indexReference -MigrationVersion @{ visualization = "7.10.0" }

# ---------------------------------------------------------------------------
# 4. 최근 보안 이벤트
# ---------------------------------------------------------------------------
Save-Object -Type search -Id "security-logs-recent-evidence" -Attributes @{
  title = "최근 보안 이벤트 상세"
  description = "PII는 Fluent Bit에서 마스킹된 뒤 인덱싱됩니다. 사건 조사용 구조화 필드와 원문 메시지를 함께 확인합니다."
  columns = @(
    "collector_platform", "namespace", "app", "security_event_type",
    "auth_result", "error_code", "policy_name", "source_network", "message"
  )
  sort = @("@timestamp", "desc"); hits = 0
  kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $securityQuery }
} -References $indexReference -MigrationVersion @{ search = "7.9.3" }

# ---------------------------------------------------------------------------
# Dashboard layout
# ---------------------------------------------------------------------------
$panels = @(
  @{ gridData = @{ x = 0; y = 0; w = 48; h = 5; i = "scope" }; panelIndex = "scope"; version = "7.10.0"; panelRefName = "panel_scope"; embeddableConfig = @{} },

  @{ gridData = @{ x = 0; y = 5; w = 48; h = 2; i = "group_overview" }; panelIndex = "group_overview"; version = "7.10.0"; panelRefName = "panel_group_overview"; embeddableConfig = @{ hidePanelTitles = $true } },
  @{ gridData = @{ x = 0; y = 7; w = 10; h = 8; i = "spike" }; panelIndex = "spike"; version = "7.10.0"; panelRefName = "panel_spike"; embeddableConfig = @{ timeRange = @{ from = "now-5m"; to = "now" } } },
  @{ gridData = @{ x = 10; y = 7; w = 10; h = 8; i = "failures" }; panelIndex = "failures"; version = "7.10.0"; panelRefName = "panel_failures"; embeddableConfig = @{} },
  @{ gridData = @{ x = 20; y = 7; w = 10; h = 8; i = "callback" }; panelIndex = "callback"; version = "7.10.0"; panelRefName = "panel_callback"; embeddableConfig = @{} },
  @{ gridData = @{ x = 30; y = 7; w = 9; h = 8; i = "logout" }; panelIndex = "logout"; version = "7.10.0"; panelRefName = "panel_logout"; embeddableConfig = @{} },
  @{ gridData = @{ x = 39; y = 7; w = 9; h = 8; i = "kyverno" }; panelIndex = "kyverno"; version = "7.10.0"; panelRefName = "panel_kyverno"; embeddableConfig = @{} },

  @{ gridData = @{ x = 0; y = 15; w = 48; h = 2; i = "group_auth" }; panelIndex = "group_auth"; version = "7.10.0"; panelRefName = "panel_group_auth"; embeddableConfig = @{ hidePanelTitles = $true } },
  @{ gridData = @{ x = 0; y = 17; w = 48; h = 11; i = "timeline" }; panelIndex = "timeline"; version = "7.10.0"; panelRefName = "panel_timeline"; embeddableConfig = @{} },
  @{ gridData = @{ x = 0; y = 28; w = 16; h = 10; i = "reasons" }; panelIndex = "reasons"; version = "7.10.0"; panelRefName = "panel_reasons"; embeddableConfig = @{} },
  @{ gridData = @{ x = 16; y = 28; w = 16; h = 10; i = "networks" }; panelIndex = "networks"; version = "7.10.0"; panelRefName = "panel_networks"; embeddableConfig = @{} },
  @{ gridData = @{ x = 32; y = 28; w = 16; h = 10; i = "clients" }; panelIndex = "clients"; version = "7.10.0"; panelRefName = "panel_clients"; embeddableConfig = @{} },

  @{ gridData = @{ x = 0; y = 38; w = 48; h = 2; i = "group_policy" }; panelIndex = "group_policy"; version = "7.10.0"; panelRefName = "panel_group_policy"; embeddableConfig = @{ hidePanelTitles = $true } },
  @{ gridData = @{ x = 0; y = 40; w = 16; h = 11; i = "policy_top" }; panelIndex = "policy_top"; version = "7.10.0"; panelRefName = "panel_policy_top"; embeddableConfig = @{} },
  @{ gridData = @{ x = 16; y = 40; w = 16; h = 11; i = "component" }; panelIndex = "component"; version = "7.10.0"; panelRefName = "panel_component"; embeddableConfig = @{} },
  @{ gridData = @{ x = 32; y = 40; w = 16; h = 11; i = "classification" }; panelIndex = "classification"; version = "7.10.0"; panelRefName = "panel_classification"; embeddableConfig = @{} },

  @{ gridData = @{ x = 0; y = 51; w = 48; h = 2; i = "group_evidence" }; panelIndex = "group_evidence"; version = "7.10.0"; panelRefName = "panel_group_evidence"; embeddableConfig = @{ hidePanelTitles = $true } },
  @{ gridData = @{ x = 0; y = 53; w = 48; h = 14; i = "evidence" }; panelIndex = "evidence"; version = "7.10.0"; panelRefName = "panel_evidence"; embeddableConfig = @{
      columns = @(
        "collector_platform", "namespace", "app", "security_event_type",
        "auth_result", "error_code", "policy_name", "source_network", "message"
      )
      sort = @("@timestamp", "desc")
  } }
)

$dashboardReferences = @(
  @{ name = "panel_scope"; id = "security-logs-scope-filters"; type = "visualization" },

  @{ name = "panel_group_overview"; id = "security-logs-group-overview"; type = "visualization" },
  @{ name = "panel_spike"; id = "security-logs-failure-spike"; type = "visualization" },
  @{ name = "panel_failures"; id = "security-logs-auth-failures"; type = "visualization" },
  @{ name = "panel_callback"; id = "security-logs-callback-errors"; type = "visualization" },
  @{ name = "panel_logout"; id = "security-logs-logout-errors"; type = "visualization" },
  @{ name = "panel_kyverno"; id = "security-logs-kyverno-violations"; type = "visualization" },

  @{ name = "panel_group_auth"; id = "security-logs-group-auth"; type = "visualization" },
  @{ name = "panel_timeline"; id = "security-logs-events-over-time"; type = "visualization" },
  @{ name = "panel_reasons"; id = "security-logs-failure-reasons"; type = "visualization" },
  @{ name = "panel_networks"; id = "security-logs-failures-by-network"; type = "visualization" },
  @{ name = "panel_clients"; id = "security-logs-failures-by-client"; type = "visualization" },

  @{ name = "panel_group_policy"; id = "security-logs-group-policy"; type = "visualization" },
  @{ name = "panel_policy_top"; id = "security-logs-kyverno-policy-top"; type = "visualization" },
  @{ name = "panel_component"; id = "security-logs-events-by-component"; type = "visualization" },
  @{ name = "panel_classification"; id = "security-logs-event-classification"; type = "visualization" },

  @{ name = "panel_group_evidence"; id = "security-logs-group-evidence"; type = "visualization" },
  @{ name = "panel_evidence"; id = "security-logs-recent-evidence"; type = "search" }
)

Save-Object -Type dashboard -Id "security-logs-overview-v1" -Attributes @{
  title = "보안 로그 대시보드"
  description = "Keycloak/OAuth2 Proxy/Kyverno의 구조화된 보안 이벤트를 사건 조사 관점에서 분석합니다. 보안 구성 상태/메트릭은 Grafana에서 분리해 확인합니다."
  version = 1; hits = 0
  timeRestore = $true; timeFrom = "now-24h"; timeTo = "now"
  refreshInterval = @{ pause = $false; value = 30000 }
  optionsJSON = ConvertTo-CompactJson @{ useMargins = $true; hidePanelTitles = $false }
  panelsJSON = ConvertTo-CompactJson $panels
  kibanaSavedObjectMeta = @{ searchSourceJSON = ConvertTo-CompactJson @{ query = @{ query = ""; language = "kuery" }; filter = @() } }
} -References $dashboardReferences -MigrationVersion @{ dashboard = "7.9.3" }

Write-Host "Security dashboard: $($DashboardsUrl.TrimEnd('/'))/app/dashboards#/view/security-logs-overview-v1"
