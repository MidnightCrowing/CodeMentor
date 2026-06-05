# CodeMentor Batch Analysis Script
# Usage:
#   .\batch_analysis.ps1 -Date "2026-05-27" -Mode concurrent -Concurrency 5
#   .\batch_analysis.ps1 -Date "2026-05-27" -Mode batch
#   .\batch_analysis.ps1 -JobId "xxx-xxx-xxx" -QueryOnly

param(
    [string]$Date = "",
    [string]$Mode = "concurrent",
    [int]$Concurrency = 10,
    [string]$JobId = "",
    [switch]$QueryOnly,
    [string]$AdminUserId = "admin-51c17fe5-5ft",
    [string]$ApiBase = "http://47.93.3.71/api/v1"
)

# Set output encoding to UTF-8
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Query job status only
if ($QueryOnly) {
    if (-not $JobId) {
        Write-Host "Error: -JobId required for query mode" -ForegroundColor Red
        exit 1
    }

    Write-Host "Querying job status: $JobId" -ForegroundColor Cyan

    $headers = @{
        "Authorization" = "Bearer $AdminUserId"
    }

    try {
        $result = Invoke-RestMethod -Uri "$ApiBase/analysis/daily/batch/jobs/$JobId" `
            -Method GET `
            -Headers $headers

        Write-Host "`nJob Details:" -ForegroundColor Green
        $result | ConvertTo-Json -Depth 10
    }
    catch {
        Write-Host "Query failed: $_" -ForegroundColor Red
        exit 1
    }

    exit 0
}

# Trigger batch analysis
if (-not $Date) {
    # Default to yesterday
    $Date = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
}

Write-Host "Triggering batch analysis" -ForegroundColor Cyan
Write-Host "  Date: $Date" -ForegroundColor Yellow
Write-Host "  Mode: $Mode" -ForegroundColor Yellow
Write-Host "  Concurrency: $Concurrency" -ForegroundColor Yellow
Write-Host ""

# Build request
$headers = @{
    "Authorization" = "Bearer $AdminUserId"
    "Content-Type" = "application/json"
}

$bodyObj = @{
    date = $Date
    mode = $Mode
}

if ($Mode -eq "concurrent") {
    $bodyObj.concurrency = $Concurrency
}

$body = $bodyObj | ConvertTo-Json

Write-Host "Executing (this may take a while)..." -ForegroundColor Green
Write-Host ""

# Start the job and get initial response
try {
    # Use Invoke-WebRequest to get raw response
    $response = Invoke-WebRequest -Uri "$ApiBase/analysis/daily/batch" `
        -Method POST `
        -Headers $headers `
        -Body $body `
        -TimeoutSec 300

    # Parse response
    $content = $response.Content
    $lines = $content -split "`n"

    $extractedJobId = ""

    foreach ($line in $lines) {
        $line = $line.Trim()
        if ($line) {
            try {
                $json = $line | ConvertFrom-Json

                # Extract job_id
                if ($json.job_id) {
                    $extractedJobId = $json.job_id
                }

                # Display progress
                if ($json.type -eq "job_created") {
                    Write-Host "Job created" -ForegroundColor Green
                    Write-Host "  Job ID: $($json.job_id)" -ForegroundColor Cyan
                    Write-Host "  Total users: $($json.total_users)" -ForegroundColor Cyan
                    Write-Host ""
                }
                elseif ($json.type -eq "progress") {
                    $percent = [math]::Round(($json.completed / $json.total) * 100, 1)
                    Write-Host "  Progress: $($json.completed)/$($json.total) ($percent%) | Failed: $($json.failed)" -ForegroundColor Yellow
                }
                elseif ($json.type -eq "completed") {
                    Write-Host "`nJob completed" -ForegroundColor Green
                    Write-Host "  Total: $($json.total)" -ForegroundColor Cyan
                    Write-Host "  Success: $($json.completed)" -ForegroundColor Green
                    Write-Host "  Failed: $($json.failed)" -ForegroundColor Red

                    if ($json.failed_users -and $json.failed_users.Count -gt 0) {
                        Write-Host "  Failed users: $($json.failed_users -join ', ')" -ForegroundColor Red
                    }
                }
                elseif ($json.type -eq "error") {
                    Write-Host "`nError: $($json.message)" -ForegroundColor Red
                }
                elseif ($json.message) {
                    Write-Host "  $($json.message)" -ForegroundColor Gray
                }
                elseif ($json.code) {
                    Write-Host "API Error (code $($json.code)): $($json.message)" -ForegroundColor Red
                }
            }
            catch {
                # Ignore unparseable lines
            }
        }
    }

    # Show query command
    if ($extractedJobId) {
        Write-Host "`nQuery job status:" -ForegroundColor Cyan
        Write-Host "  .\scripts\batch_analysis.ps1 -JobId '$extractedJobId' -QueryOnly" -ForegroundColor White
    }
    else {
        Write-Host "`nNo job ID extracted." -ForegroundColor Yellow
    }
}
catch {
    Write-Host "Request failed: $($_.Exception.Message)" -ForegroundColor Red

    if ($_.Exception.Response) {
        try {
            $errorStream = $_.Exception.Response.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($errorStream)
            $errorBody = $reader.ReadToEnd()
            Write-Host "Error details: $errorBody" -ForegroundColor Red
        }
        catch {
            # Ignore
        }
    }

    exit 1
}
