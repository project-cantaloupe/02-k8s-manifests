param(
  [string]$DashboardsUrl = "https://cntlp-gcp-wk-02.tail270b85.ts.net"
)

$ErrorActionPreference = "Stop"
$indexPatternId = "cantaloupe-security-v1"
$trivyQuery = 'scan.scan_type : "vulnerability"'

$vulnPrefix = "event_data.resources.scan_overview.application/vnd.security.vulnerability.report; version=1.1.summary.summary"

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
  $payloadFile = New-TemporaryFile
  try {
    [IO.File]::WriteAllText($payloadFile.FullName, $body, [Text.UTF8Encoding]::new($false))
    $result = curl.exe -k -sS --fail-with-body -H "osd-xsrf: true" -H "Content-Type: application/json" -X POST $endpoint --data-binary "@$($payloadFile.FullName)"
  } finally {
    Remove-Item -LiteralPath $payloadFile.FullName -Force -ErrorAction SilentlyContinue
  }
  if ($LASTEXITCODE -ne 0) { throw "Failed to save $Type/$Id`: $result" }
  $saved = $result | ConvertFrom-Json
  Write-Host "saved $($saved.type)/$($saved.id)"
}

$indexReference = @(@{
  name = "kibanaSavedObjectMeta.searchSourceJSON.index"
  id = $indexPatternId
  type = "index-pattern"
})

function Ensure-IndexPattern {
  $endpoint = "$($DashboardsUrl.TrimEnd('/'))/api/saved_objects/index-pattern/$indexPatternId"
  $existingJson = curl.exe -k -sS -H "osd-xsrf: true" $endpoint
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating index pattern $indexPatternId..."
    Save-Object -Type "index-pattern" -Id $indexPatternId -Attributes @{
      title = "cantaloupe-security-*"
      timeFieldName = "@timestamp"
    } -MigrationVersion @{ "index-pattern" = "7.6.0" }
  } else {
    Write-Host "Index pattern $indexPatternId already exists."
  }
}

function Save-Metric {
  param([string]$Id, [string]$Title, [string]$Query, [string]$Description, [string]$AggType="count", [string]$Field="")
  
  $aggParams = @{ customLabel = $Title }
  if ($AggType -eq "sum") {
    $aggParams["field"] = $Field
  }

  $visState = @{
    title = $Title
    type = "metric"
    aggs = @(@{ id = "1"; enabled = $true; type = $AggType; schema = "metric"; params = $aggParams })
    params = @{
      type = "metric"; addTooltip = $true; addLegend = $false
      metric = @{
        percentageMode = $false; useRanges = $false; colorSchema = "Green to Red"
        metricColorMode = "None"; invertColors = $false
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

function Save-TermsTable {
  param([string]$Id, [string]$Title, [string]$Query, [string]$Field, [string]$BucketLabel, [string]$Description, [int]$Size = 10)
  $visState = @{
    title = $Title; type = "table"
    aggs = @(
      @{ id = "1"; enabled = $true; type = "count"; schema = "metric"; params = @{ customLabel = "스캔 횟수" } },
      @{ id = "2"; enabled = $true; type = "terms"; schema = "bucket"; params = @{ field = $Field; size = $Size; order = "desc"; orderBy = "1"; otherBucket = $false; missingBucket = $false; customLabel = $BucketLabel } }
    )
    params = @{
      perPage = $Size; showPartialRows = $false; showMetricsAtAllLevels = $false; sort = @{ columnIndex = 1; direction = "desc" }; showTotal = $false; totalFunc = "sum"
    }
  }
  Save-Object -Type visualization -Id $Id -Attributes @{
    title = $Title; description = $Description; version = 1; uiStateJSON = "{}"
    visState = ConvertTo-CompactJson $visState
    kibanaSavedObjectMeta = @{ searchSourceJSON = New-SearchSource $Query }
  } -References $indexReference -MigrationVersion @{ visualization = "7.10.0" }
}

Ensure-IndexPattern

Save-Metric -Id "trivy-total-scans" -Title "Total Image Scans" -Query $trivyQuery -Description "Total vulnerability scans completed"
Save-Metric -Id "trivy-critical-vulns" -Title "Total Critical Vulnerabilities" -Query $trivyQuery -AggType "sum" -Field "$vulnPrefix.Critical" -Description "Sum of Critical vulnerabilities"
Save-Metric -Id "trivy-high-vulns" -Title "Total High Vulnerabilities" -Query $trivyQuery -AggType "sum" -Field "$vulnPrefix.High" -Description "Sum of High vulnerabilities"

Save-TermsTable -Id "trivy-vulns-by-repo" -Title "Scans by Repository" -Query $trivyQuery -Field "repository.repo_full_name.keyword" -BucketLabel "Repository" -Description "Vulnerability scans grouped by repository"

$panels = @(
  @{ gridData = @{ x = 0; y = 0; w = 16; h = 8; i = "1" }; panelIndex = "1"; version = "7.10.0"; panelRefName = "panel_1"; embeddableConfig = @{} },
  @{ gridData = @{ x = 16; y = 0; w = 16; h = 8; i = "2" }; panelIndex = "2"; version = "7.10.0"; panelRefName = "panel_2"; embeddableConfig = @{} },
  @{ gridData = @{ x = 32; y = 0; w = 16; h = 8; i = "3" }; panelIndex = "3"; version = "7.10.0"; panelRefName = "panel_3"; embeddableConfig = @{} },
  @{ gridData = @{ x = 0; y = 8; w = 48; h = 12; i = "4" }; panelIndex = "4"; version = "7.10.0"; panelRefName = "panel_4"; embeddableConfig = @{} }
)

$dashboardReferences = @(
  @{ name = "panel_1"; id = "trivy-total-scans"; type = "visualization" },
  @{ name = "panel_2"; id = "trivy-critical-vulns"; type = "visualization" },
  @{ name = "panel_3"; id = "trivy-high-vulns"; type = "visualization" },
  @{ name = "panel_4"; id = "trivy-vulns-by-repo"; type = "visualization" }
)

Save-Object -Type dashboard -Id "trivy-vulnerability-overview" -Attributes @{
  title = "Trivy Vulnerability Overview (Harbor)"
  description = "Dashboard for Harbor Trivy scan webhooks."
  version = 1; hits = 0
  timeRestore = $true; timeFrom = "now-24h"; timeTo = "now"
  refreshInterval = @{ pause = $false; value = 30000 }
  optionsJSON = ConvertTo-CompactJson @{ useMargins = $true; hidePanelTitles = $false }
  panelsJSON = ConvertTo-CompactJson $panels
  kibanaSavedObjectMeta = @{ searchSourceJSON = ConvertTo-CompactJson @{ query = @{ query = ""; language = "kuery" }; filter = @() } }
} -References $dashboardReferences -MigrationVersion @{ dashboard = "7.9.3" }

Write-Host "Dashboard created: $($DashboardsUrl.TrimEnd('/'))/app/dashboards#/view/trivy-vulnerability-overview"
