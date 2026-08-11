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
    [int]$AlertThreshold = 0
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
    aggs = @(@{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{} })
    params = @{
      type = "metric"; addTooltip = $true; addLegend = $false
      metric = @{
        percentageMode = $false; useRanges = $hasAlertThreshold; colorSchema = "Green to Red"
        metricColorMode = $metricColorMode; invertColors = $false
        colorsRange = $colorRanges
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

Ensure-SecurityIndexPatternFields

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

Save-Metric -Id "security-logs-failure-spike" -Title "5m Failure Spike" -Query 'auth_result : failure' -Description "Authentication failures during the panel's fixed five-minute window. The number changes color at 50 events." -AlertThreshold 50
Save-Metric -Id "security-logs-auth-failures" -Title "Authentication Failures" -Query 'auth_result : failure' -Description "Failed, rejected, or invalid authentication attempts parsed by Fluent Bit." -AlertThreshold 1
Save-Metric -Id "security-logs-auth-success" -Title "Authentication Successes" -Query 'auth_result : success' -Description "Successful Keycloak and OAuth2 Proxy authentication events."
Save-Metric -Id "security-logs-callback-errors" -Title "OAuth Callback Errors" -Query 'security_event_type : oauth_callback and auth_result : failure' -Description "OAuth authorization-code redemption and callback failures." -AlertThreshold 1
Save-Metric -Id "security-logs-logout-errors" -Title "Logout Errors" -Query 'security_event_type : keycloak_logout_error and auth_result : failure' -Description "Failed Keycloak logout events; use this to investigate sessions that were not terminated cleanly." -AlertThreshold 1
Save-Metric -Id "security-logs-kyverno-violations" -Title "Kyverno Policy Violations" -Query 'security_event_type : kyverno_policy_violation' -Description "Explicitly failed, denied, blocked, or errored Kyverno policy decisions." -AlertThreshold 1

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
  params = @{ type = "line"; addTooltip = $true; addLegend = $true; legendPosition = "right"; seriesParams = @(@{ show = "true"; type = "line"; mode = "normal"; data = @{ id = "1"; label = "Authentication events" }; valueAxis = "ValueAxis-1"; drawLines = $true; showCircles = $false; lineWidth = 3; interpolation = "linear" }) }
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
    @{ id = "2"; enabled = $true; type = "terms"; schema = "segment"; params = @{ field = "app"; size = 10; order = "desc"; orderBy = "1"; otherBucket = $false; missingBucket = $false } }
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
Save-TermsBar -Id "security-logs-failures-by-network" -Title "Repeated Failures by Masked Network" `
  -Query 'auth_result : failure and source_network : *' -Field "source_network" `
  -Description "Repeated failures grouped by the masked source network; raw source IP addresses are not indexed."

$evidenceVegaSpec = @{
  '$schema' = "https://vega.github.io/schema/vega/v5.json"
  autosize = @{ type = "fit"; contains = "padding" }
  padding = 4
  config = @{ text = @{ fontSize = 14 } }
  data = @(@{
    name = "events"
    url = @{
      index = "cantaloupe-platform-logs-v2*"
      body = @{
        size = 20
        _source = @("@timestamp", "collector_platform", "namespace", "app", "message", "security_event_type", "error_code")
        sort = @(@{ "@timestamp" = @{ order = "desc" } })
        query = @{ bool = @{
          must = @("%dashboard_context-must_clause%", @{ exists = @{ field = "security_event_type" } })
          filter = @("%dashboard_context-filter_clause%", @{ range = @{ "@timestamp" = @{ "%timefilter%" = $true } } })
          must_not = @("%dashboard_context-must_not_clause%")
        } }
      }
    }
    format = @{ property = "hits.hits" }
    transform = @(@{ type = "window"; ops = @("row_number"); as = @("row_number") })
  })
  scales = @(@{ name = "rowY"; type = "band"; domain = @{ data = "events"; field = "row_number" }; range = @(@{ signal = "28" }, @{ signal = "height" }); padding = 0.12 })
  marks = @(
    @{ type = "rule"; encode = @{ enter = @{ x = @{ value = 0 }; x2 = @{ signal = "width" }; y = @{ value = 25 }; stroke = @{ value = "#d3dae6" } } } },
    @{ type = "text"; encode = @{ enter = @{ x = @{ signal = "width*0.00" }; y = @{ value = 16 }; text = @{ value = "Time" }; fontWeight = @{ value = "bold" }; fill = @{ value = "#343741" } } } },
    @{ type = "text"; encode = @{ enter = @{ x = @{ signal = "width*0.13" }; y = @{ value = 16 }; text = @{ value = "Platform" }; fontWeight = @{ value = "bold" }; fill = @{ value = "#343741" } } } },
    @{ type = "text"; encode = @{ enter = @{ x = @{ signal = "width*0.18" }; y = @{ value = 16 }; text = @{ value = "Namespace" }; fontWeight = @{ value = "bold" }; fill = @{ value = "#343741" } } } },
    @{ type = "text"; encode = @{ enter = @{ x = @{ signal = "width*0.24" }; y = @{ value = 16 }; text = @{ value = "App" }; fontWeight = @{ value = "bold" }; fill = @{ value = "#343741" } } } },
    @{ type = "text"; encode = @{ enter = @{ x = @{ signal = "width*0.30" }; y = @{ value = 16 }; text = @{ value = "Message" }; fontWeight = @{ value = "bold" }; fill = @{ value = "#343741" } } } },
    @{ type = "text"; encode = @{ enter = @{ x = @{ signal = "width*0.85" }; y = @{ value = 16 }; text = @{ value = "Event" }; fontWeight = @{ value = "bold" }; fill = @{ value = "#343741" } } } },
    @{ type = "text"; encode = @{ enter = @{ x = @{ signal = "width*0.94" }; y = @{ value = 16 }; text = @{ value = "Error" }; fontWeight = @{ value = "bold" }; fill = @{ value = "#343741" } } } },
    @{ type = "text"; from = @{ data = "events" }; encode = @{ enter = @{ x = @{ signal = "width*0.00" }; y = @{ scale = "rowY"; field = "row_number"; band = 0.65 }; text = @{ signal = "timeFormat(toDate(datum._source['@timestamp']), '%m-%d %H:%M:%S')" }; fill = @{ value = "#343741" }; limit = @{ signal = "width*0.12" }; ellipsis = @{ value = "..." }; tooltip = @{ signal = "datum._source['@timestamp']" } } } },
    @{ type = "text"; from = @{ data = "events" }; encode = @{ enter = @{ x = @{ signal = "width*0.13" }; y = @{ scale = "rowY"; field = "row_number"; band = 0.65 }; text = @{ signal = "datum._source.collector_platform || '-'" }; fill = @{ value = "#343741" }; limit = @{ signal = "width*0.04" }; ellipsis = @{ value = "..." } } } },
    @{ type = "text"; from = @{ data = "events" }; encode = @{ enter = @{ x = @{ signal = "width*0.18" }; y = @{ scale = "rowY"; field = "row_number"; band = 0.65 }; text = @{ signal = "datum._source.namespace || '-'" }; fill = @{ value = "#343741" }; limit = @{ signal = "width*0.05" }; ellipsis = @{ value = "..." } } } },
    @{ type = "text"; from = @{ data = "events" }; encode = @{ enter = @{ x = @{ signal = "width*0.24" }; y = @{ scale = "rowY"; field = "row_number"; band = 0.65 }; text = @{ signal = "datum._source.app || '-'" }; fill = @{ value = "#343741" }; limit = @{ signal = "width*0.05" }; ellipsis = @{ value = "..." } } } },
    @{ type = "text"; from = @{ data = "events" }; encode = @{ enter = @{ x = @{ signal = "width*0.30" }; y = @{ scale = "rowY"; field = "row_number"; band = 0.65 }; text = @{ signal = "datum._source.message || '-'" }; fill = @{ value = "#343741" }; limit = @{ signal = "width*0.54" }; ellipsis = @{ value = "..." }; tooltip = @{ signal = "datum._source.message" } } } },
    @{ type = "text"; from = @{ data = "events" }; encode = @{ enter = @{ x = @{ signal = "width*0.85" }; y = @{ scale = "rowY"; field = "row_number"; band = 0.65 }; text = @{ signal = "datum._source.security_event_type || '-'" }; fill = @{ value = "#343741" }; limit = @{ signal = "width*0.08" }; ellipsis = @{ value = "..." }; tooltip = @{ signal = "datum._source.security_event_type" } } } },
    @{ type = "text"; from = @{ data = "events" }; encode = @{ enter = @{ x = @{ signal = "width*0.94" }; y = @{ scale = "rowY"; field = "row_number"; band = 0.65 }; text = @{ signal = "datum._source.error_code || '-'" }; fill = @{ value = "#343741" }; limit = @{ signal = "width*0.06" }; ellipsis = @{ value = "..." }; tooltip = @{ signal = "datum._source.error_code" } } } }
  )
}
$evidenceVegaState = @{
  title = "Recent Security Event Evidence"
  type = "vega"
  aggs = @()
  params = @{ spec = ConvertTo-CompactJson $evidenceVegaSpec; enableExternalUrls = $false }
}
Save-Object -Type visualization -Id "security-logs-recent-evidence-table" -Attributes @{
  title = "Recent Security Event Evidence"; description = "Recent structured security evidence with a message-priority column layout."; version = 1; uiStateJSON = "{}"
  visState = ConvertTo-CompactJson $evidenceVegaState
  kibanaSavedObjectMeta = @{ searchSourceJSON = ConvertTo-CompactJson @{ query = @{ query = ""; language = "kuery" }; filter = @() } }
} -MigrationVersion @{ visualization = "7.10.0" }

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
  columns = @("collector_platform", "namespace", "app", "message", "security_event_type", "error_code")
  sort = @("@timestamp", "desc"); hits = 0
  kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $securityQuery }
} -References $indexReference -MigrationVersion @{ search = "7.9.3" }

$panels = @(
  @{ gridData = @{ x = 0; y = 0; w = 48; h = 5; i = "scope" }; panelIndex = "scope"; version = "7.10.0"; panelRefName = "panel_scope"; embeddableConfig = @{} },
  @{ gridData = @{ x = 0; y = 5; w = 8; h = 7; i = "spike" }; panelIndex = "spike"; version = "7.10.0"; panelRefName = "panel_spike"; embeddableConfig = @{ timeRange = @{ from = "now-5m"; to = "now" } } },
  @{ gridData = @{ x = 8; y = 5; w = 8; h = 7; i = "failures" }; panelIndex = "failures"; version = "7.10.0"; panelRefName = "panel_failures"; embeddableConfig = @{} },
  @{ gridData = @{ x = 16; y = 5; w = 8; h = 7; i = "success" }; panelIndex = "success"; version = "7.10.0"; panelRefName = "panel_success"; embeddableConfig = @{} },
  @{ gridData = @{ x = 24; y = 5; w = 8; h = 7; i = "callback" }; panelIndex = "callback"; version = "7.10.0"; panelRefName = "panel_callback"; embeddableConfig = @{} },
  @{ gridData = @{ x = 32; y = 5; w = 8; h = 7; i = "logout" }; panelIndex = "logout"; version = "7.10.0"; panelRefName = "panel_logout"; embeddableConfig = @{} },
  @{ gridData = @{ x = 40; y = 5; w = 8; h = 7; i = "kyverno" }; panelIndex = "kyverno"; version = "7.10.0"; panelRefName = "panel_kyverno"; embeddableConfig = @{} },
  @{ gridData = @{ x = 0; y = 12; w = 34; h = 11; i = "timeline" }; panelIndex = "timeline"; version = "7.10.0"; panelRefName = "panel_timeline"; embeddableConfig = @{} },
  @{ gridData = @{ x = 34; y = 12; w = 14; h = 11; i = "component" }; panelIndex = "component"; version = "7.10.0"; panelRefName = "panel_component"; embeddableConfig = @{} },
  @{ gridData = @{ x = 0; y = 23; w = 24; h = 11; i = "reasons" }; panelIndex = "reasons"; version = "7.10.0"; panelRefName = "panel_reasons"; embeddableConfig = @{} },
  @{ gridData = @{ x = 24; y = 23; w = 24; h = 11; i = "networks" }; panelIndex = "networks"; version = "7.10.0"; panelRefName = "panel_networks"; embeddableConfig = @{} },
  @{ gridData = @{ x = 0; y = 34; w = 48; h = 13; i = "evidence" }; panelIndex = "evidence"; version = "7.10.0"; panelRefName = "panel_evidence"; embeddableConfig = @{} }
)
$dashboardReferences = @(
  @{ name = "panel_scope"; id = "security-logs-scope-filters"; type = "visualization" },
  @{ name = "panel_spike"; id = "security-logs-failure-spike"; type = "visualization" },
  @{ name = "panel_failures"; id = "security-logs-auth-failures"; type = "visualization" },
  @{ name = "panel_success"; id = "security-logs-auth-success"; type = "visualization" },
  @{ name = "panel_callback"; id = "security-logs-callback-errors"; type = "visualization" },
  @{ name = "panel_logout"; id = "security-logs-logout-errors"; type = "visualization" },
  @{ name = "panel_kyverno"; id = "security-logs-kyverno-violations"; type = "visualization" },
  @{ name = "panel_timeline"; id = "security-logs-events-over-time"; type = "visualization" },
  @{ name = "panel_component"; id = "security-logs-events-by-component"; type = "visualization" },
  @{ name = "panel_reasons"; id = "security-logs-failure-reasons"; type = "visualization" },
  @{ name = "panel_networks"; id = "security-logs-failures-by-network"; type = "visualization" },
  @{ name = "panel_evidence"; id = "security-logs-recent-evidence-table"; type = "visualization" }
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
