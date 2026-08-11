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
  param([string]$Id, [string]$Title, [string]$Query, [string]$Description)
  $visState = @{
    title = $Title
    type = "metric"
    aggs = @(@{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} })
    params = @{
      type = "metric"; addTooltip = $true; addLegend = $false
      metric = @{
        percentageMode = $false; useRanges = $false; colorSchema = "Green to Red"
        metricColorMode = "None"; invertColors = $false
        colorsRange = @(@{ from = 0; to = 10000 })
        labels = @{ show = $true }
        style = @{ bgFill = "#000"; bgColor = $false; labelColor = $false; fontSize = 52; subText = "" }
      }
    }
  }
  Save-Object -Type visualization -Id $Id -Attributes @{
    title = $Title; description = $Description; version = 1; uiStateJSON = "{}"
    visState = ConvertTo-CompactJson $visState
    kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $Query }
  } -References $indexReference -MigrationVersion @{ visualization = "7.10.0" }
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
      @{ id = "2"; enabled = $true; type = "terms"; schema = "group"; params = @{ field = $Field; size = $Size; order = "desc"; orderBy = "1"; otherBucket = $false; missingBucket = $false } }
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

$controlsState = @{
  title = "Security Scope Filters"
  type = "input_control_vis"
  aggs = @()
  params = @{
    updateFiltersOnChange = $true; useTimeFilter = $true; pinFilters = $false
    controls = @(
      @{ id = "platform"; label = "Platform"; type = "list"; parent = ""; indexPatternRefName = "control_0_index_pattern"; fieldName = "collector_platform"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 10; order = "desc" } },
      @{ id = "component"; label = "Security Component"; type = "list"; parent = ""; indexPatternRefName = "control_1_index_pattern"; fieldName = "app"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 20; order = "desc" } },
      @{ id = "level"; label = "Level"; type = "list"; parent = ""; indexPatternRefName = "control_2_index_pattern"; fieldName = "level"; options = @{ dynamicOptions = $true; type = "terms"; multiselect = $true; size = 10; order = "desc" } }
    )
  }
}
Save-Object -Type visualization -Id "security-logs-scope-filters" -Attributes @{
  title = "Security Scope Filters"; description = "Filter by platform, security component, and normalized log level."; version = 1; uiStateJSON = "{}"
  visState = ConvertTo-CompactJson $controlsState
  kibanaSavedObjectMeta = @{ searchSourceJSON = ConvertTo-CompactJson @{ query = @{ query = $securityQuery; language = "kuery" }; filter = @() } }
} -References @(
  @{ name = "control_0_index_pattern"; id = $indexPatternId; type = "index-pattern" },
  @{ name = "control_1_index_pattern"; id = $indexPatternId; type = "index-pattern" },
  @{ name = "control_2_index_pattern"; id = $indexPatternId; type = "index-pattern" }
) -MigrationVersion @{ visualization = "7.10.0" }

Save-Metric -Id "security-logs-auth-failures" -Title "Authentication Failures" -Query 'auth_result : failure' -Description "Failed, rejected, or invalid authentication attempts parsed by Fluent Bit."
Save-Metric -Id "security-logs-auth-success" -Title "Authentication Successes" -Query 'auth_result : success' -Description "Successful Keycloak and OAuth2 Proxy authentication events."
Save-Metric -Id "security-logs-callback-errors" -Title "OAuth Callback Errors" -Query 'security_event_type : oauth_callback and auth_result : failure' -Description "OAuth authorization-code redemption and callback failures."
Save-Metric -Id "security-logs-logout-errors" -Title "Logout Errors" -Query 'security_event_type : keycloak_logout_error and auth_result : failure' -Description "Failed Keycloak logout events; use this to investigate sessions that were not terminated cleanly."
Save-Metric -Id "security-logs-kyverno-violations" -Title "Kyverno Policy Violations" -Query 'security_event_type : kyverno_policy_violation' -Description "Explicitly failed, denied, blocked, or errored Kyverno policy decisions."

$timelineState = @{
  title = "Authentication Outcomes Over Time"; type = "line"
  aggs = @(
    @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} },
    @{ id = "2"; enabled = $true; type = "date_histogram"; schema = "segment"; params = @{ field = "@timestamp"; interval = "auto"; min_doc_count = 1; extended_bounds = @{ min = ""; max = "" } } },
    @{ id = "3"; enabled = $true; type = "filters"; schema = "group"; params = @{ filters = @(
      @{ label = "Authentication failure"; input = @{ query = 'auth_result : failure'; language = "kuery" } },
      @{ label = "Authentication success"; input = @{ query = 'auth_result : success'; language = "kuery" } },
      @{ label = "OAuth callback error"; input = @{ query = 'security_event_type : oauth_callback'; language = "kuery" } }
    ) } }
  )
  params = @{ type = "line"; addTooltip = $true; addLegend = $true; legendPosition = "right"; seriesParams = @(@{ show = "true"; type = "line"; mode = "normal"; data = @{ id = "1"; label = "Authentication events" }; valueAxis = "ValueAxis-1"; drawLines = $true; showCircles = $true; lineWidth = 2; interpolation = "linear" }) }
}
Save-Object -Type visualization -Id "security-logs-events-over-time" -Attributes @{
  title = "Authentication Outcomes Over Time"; description = "Successes, failures, and callback errors over time. Compare rates within the same component before treating a rise as suspicious."; version = 1; uiStateJSON = "{}"
  visState = ConvertTo-CompactJson $timelineState
  kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $securityQuery }
} -References $indexReference -MigrationVersion @{ visualization = "7.10.0" }

$componentState = @{
  title = "Security Events by Component"; type = "horizontal_bar"
  aggs = @(
    @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} },
    @{ id = "2"; enabled = $true; type = "terms"; schema = "group"; params = @{ field = "app"; size = 10; order = "desc"; orderBy = "1"; otherBucket = $false; missingBucket = $false } }
  )
  params = @{ type = "histogram"; addTooltip = $true; addLegend = $false; legendPosition = "right"; seriesParams = @(@{ data = @{ id = "1"; label = "Count" }; type = "histogram"; mode = "normal"; valueAxis = "ValueAxis-1"; drawLines = $true; showCircles = $true; barWidth = 0.18 }) }
}
Save-Object -Type visualization -Id "security-logs-events-by-component" -Attributes @{
  title = "Security Events by Component"; description = "Security events grouped by the emitting component."; version = 1; uiStateJSON = "{}"
  visState = ConvertTo-CompactJson $componentState
  kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $securityQuery }
} -References $indexReference -MigrationVersion @{ visualization = "7.10.0" }

Save-TermsBar -Id "security-logs-failure-reasons" -Title "Authentication Failure Reasons" `
  -Query 'auth_result : failure and error_code : *' -Field "error_code" `
  -Description "Authentication failures grouped by normalized reason. Investigate sudden changes rather than blocking from this count alone."
Save-TermsBar -Id "security-logs-failures-by-client" -Title "Repeated Failures by Client" `
  -Query 'auth_result : failure and client_id : *' -Field "client_id" `
  -Description "Clients producing repeated authentication failures. Compare with failure reason and time trend before taking action."
Save-TermsBar -Id "security-logs-failures-by-network" -Title "Repeated Failures by Masked Network" `
  -Query 'auth_result : failure and source_network : *' -Field "source_network" `
  -Description "Repeated failures grouped by the masked source network; raw source IP addresses are not indexed."

$classificationState = @{
  title = "Security Event Classification"; type = "pie"
  aggs = @(
    @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} },
    @{ id = "2"; enabled = $true; type = "filters"; schema = "segment"; params = @{ filters = @(
      @{ label = "Keycloak failure"; input = @{ query = 'app : keycloak and auth_result : failure'; language = "kuery" } },
      @{ label = "OAuth rejection"; input = @{ query = 'app : oauth2-proxy and auth_result : failure'; language = "kuery" } },
      @{ label = "Authentication success"; input = @{ query = 'auth_result : success'; language = "kuery" } },
      @{ label = "Logout / callback error"; input = @{ query = 'security_event_type : (keycloak_logout_error or oauth_callback)'; language = "kuery" } },
      @{ label = "Kyverno policy violation"; input = @{ query = 'security_event_type : kyverno_policy_violation'; language = "kuery" } }
    ) } }
  )
  params = @{ type = "pie"; addTooltip = $true; addLegend = $true; legendPosition = "right"; isDonut = $true; labels = @{ show = $true; values = $true; last_level = $true; truncate = 100 } }
}
Save-Object -Type visualization -Id "security-logs-event-classification" -Attributes @{
  title = "Security Event Classification"; description = "Authentication and policy activity classified by observable log signature."; version = 1; uiStateJSON = "{}"
  visState = ConvertTo-CompactJson $classificationState
  kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $securityQuery }
} -References $indexReference -MigrationVersion @{ visualization = "7.10.0" }

Save-Object -Type search -Id "security-logs-recent-evidence" -Attributes @{
  title = "Recent Security Event Evidence"
  description = "Structured security evidence. Principal and source IP values are masked by Fluent Bit before indexing."
  columns = @("collector_platform", "namespace", "app", "security_event_type", "auth_result", "client_id", "principal_masked", "source_network", "error_code", "policy_name", "message")
  sort = @("@timestamp", "desc"); hits = 0
  kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $securityQuery }
} -References $indexReference -MigrationVersion @{ search = "7.9.3" }

$panels = @(
  @{ gridData = @{ x = 0; y = 0; w = 48; h = 5; i = "scope" }; panelIndex = "scope"; version = "7.10.0"; panelRefName = "panel_scope"; embeddableConfig = @{} },
  @{ gridData = @{ x = 0; y = 5; w = 10; h = 7; i = "failures" }; panelIndex = "failures"; version = "7.10.0"; panelRefName = "panel_failures"; embeddableConfig = @{} },
  @{ gridData = @{ x = 10; y = 5; w = 10; h = 7; i = "success" }; panelIndex = "success"; version = "7.10.0"; panelRefName = "panel_success"; embeddableConfig = @{} },
  @{ gridData = @{ x = 20; y = 5; w = 10; h = 7; i = "callback" }; panelIndex = "callback"; version = "7.10.0"; panelRefName = "panel_callback"; embeddableConfig = @{} },
  @{ gridData = @{ x = 30; y = 5; w = 9; h = 7; i = "logout" }; panelIndex = "logout"; version = "7.10.0"; panelRefName = "panel_logout"; embeddableConfig = @{} },
  @{ gridData = @{ x = 39; y = 5; w = 9; h = 7; i = "kyverno" }; panelIndex = "kyverno"; version = "7.10.0"; panelRefName = "panel_kyverno"; embeddableConfig = @{} },
  @{ gridData = @{ x = 0; y = 12; w = 34; h = 11; i = "timeline" }; panelIndex = "timeline"; version = "7.10.0"; panelRefName = "panel_timeline"; embeddableConfig = @{} },
  @{ gridData = @{ x = 34; y = 12; w = 14; h = 11; i = "component" }; panelIndex = "component"; version = "7.10.0"; panelRefName = "panel_component"; embeddableConfig = @{} },
  @{ gridData = @{ x = 0; y = 23; w = 16; h = 11; i = "reasons" }; panelIndex = "reasons"; version = "7.10.0"; panelRefName = "panel_reasons"; embeddableConfig = @{} },
  @{ gridData = @{ x = 16; y = 23; w = 16; h = 11; i = "clients" }; panelIndex = "clients"; version = "7.10.0"; panelRefName = "panel_clients"; embeddableConfig = @{} },
  @{ gridData = @{ x = 32; y = 23; w = 16; h = 11; i = "networks" }; panelIndex = "networks"; version = "7.10.0"; panelRefName = "panel_networks"; embeddableConfig = @{} },
  @{ gridData = @{ x = 0; y = 34; w = 48; h = 13; i = "evidence" }; panelIndex = "evidence"; version = "7.10.0"; panelRefName = "panel_evidence"; embeddableConfig = @{ columns = @("collector_platform", "namespace", "app", "security_event_type", "auth_result", "client_id", "principal_masked", "source_network", "error_code", "policy_name", "message"); sort = @("@timestamp", "desc") } }
)
$dashboardReferences = @(
  @{ name = "panel_scope"; id = "security-logs-scope-filters"; type = "visualization" },
  @{ name = "panel_failures"; id = "security-logs-auth-failures"; type = "visualization" },
  @{ name = "panel_success"; id = "security-logs-auth-success"; type = "visualization" },
  @{ name = "panel_callback"; id = "security-logs-callback-errors"; type = "visualization" },
  @{ name = "panel_logout"; id = "security-logs-logout-errors"; type = "visualization" },
  @{ name = "panel_kyverno"; id = "security-logs-kyverno-violations"; type = "visualization" },
  @{ name = "panel_timeline"; id = "security-logs-events-over-time"; type = "visualization" },
  @{ name = "panel_component"; id = "security-logs-events-by-component"; type = "visualization" },
  @{ name = "panel_reasons"; id = "security-logs-failure-reasons"; type = "visualization" },
  @{ name = "panel_clients"; id = "security-logs-failures-by-client"; type = "visualization" },
  @{ name = "panel_networks"; id = "security-logs-failures-by-network"; type = "visualization" },
  @{ name = "panel_evidence"; id = "security-logs-recent-evidence"; type = "search" }
)
Save-Object -Type dashboard -Id "security-logs-overview-v1" -Attributes @{
  title = "Security Logs Overview v1"
  description = "Structured authentication and policy events with pre-index PII masking. Component health remains in Grafana; logging pipeline operations remain in Platform Logging Operations v2."
  version = 1; hits = 0; timeRestore = $true; timeFrom = "now-24h"; timeTo = "now"
  refreshInterval = @{ pause = $false; value = 30000 }
  optionsJSON = ConvertTo-CompactJson @{ useMargins = $true; hidePanelTitles = $false }
  panelsJSON = ConvertTo-CompactJson $panels
  kibanaSavedObjectMeta = @{ searchSourceJSON = ConvertTo-CompactJson @{ query = @{ query = ""; language = "kuery" }; filter = @() } }
} -References $dashboardReferences -MigrationVersion @{ dashboard = "7.9.3" }

Write-Host "Security dashboard: $($DashboardsUrl.TrimEnd('/'))/app/dashboards#/view/security-logs-overview-v1"
