# Backtest Analysis Script
$logPath = "logs\backtest\2025-10-21\main.log"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "BACKTEST ANALYSIS - 2025-10-21" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Read log file
$content = Get-Content $logPath

# Signal Analysis
Write-Host "SIGNAL GENERATION SUMMARY:" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$allSignals = $content | Select-String -Pattern '\*\*\* .* SIGNAL GENERATED'
$trueBreakoutSignals = $allSignals | Select-String -Pattern 'TRUE .* SIGNAL GENERATED'
$fakeoutSignals = $allSignals | Select-String -Pattern 'FALSE .* SIGNAL GENERATED'
$buySignals = $allSignals | Select-String -Pattern 'BUY SIGNAL GENERATED'
$sellSignals = $allSignals | Select-String -Pattern 'SELL SIGNAL GENERATED'

Write-Host "Total Signals Generated: $($allSignals.Count)" -ForegroundColor Green
Write-Host "  - True Breakout Signals: $($trueBreakoutSignals.Count)"
Write-Host "  - Fakeout Signals: $($fakeoutSignals.Count)"
Write-Host "  - Buy Signals: $($buySignals.Count)"
Write-Host "  - Sell Signals: $($sellSignals.Count)"

# Execution Analysis
Write-Host "`nEXECUTION SUMMARY:" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$executionFailed = $content | Select-String -Pattern 'Signal execution failed'
$positionLimitFailed = $content | Select-String -Pattern 'Position limit check failed'

Write-Host "Signals Failed to Execute: $($executionFailed.Count)" -ForegroundColor Red
Write-Host "  - Position Limit Failures: $($positionLimitFailed.Count)"

# Calculate success rate
$successRate = if ($allSignals.Count -gt 0) { 
    [math]::Round((($allSignals.Count - $executionFailed.Count) / $allSignals.Count) * 100, 2) 
} else { 0 }
Write-Host "Execution Success Rate: $successRate%" -ForegroundColor $(if ($successRate -gt 0) { "Green" } else { "Red" })

# Strategy Breakdown
Write-Host "`nSTRATEGY BREAKDOWN:" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$strategy15M = $allSignals | Select-String -Pattern '\[15M_1M\]'
$strategy4H = $allSignals | Select-String -Pattern '\[4H_5M\]'

Write-Host "15M_1M Strategy: $($strategy15M.Count) signals"
Write-Host "4H_5M Strategy: $($strategy4H.Count) signals"

# Breakout Detection
Write-Host "`nBREAKOUT DETECTION:" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$breakoutAbove = $content | Select-String -Pattern 'BREAKOUT ABOVE HIGH DETECTED'
$breakoutBelow = $content | Select-String -Pattern 'BREAKOUT BELOW LOW DETECTED'
$breakoutQualified = $content | Select-String -Pattern 'QUALIFIED.*\(High Vol'

Write-Host "Breakouts Above High: $($breakoutAbove.Count)"
Write-Host "Breakouts Below Low: $($breakoutBelow.Count)"
Write-Host "High Volume Breakouts: $($breakoutQualified.Count)"

# Volume Analysis
Write-Host "`nVOLUME VALIDATION:" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$highVolPass = $content | Select-String -Pattern '\(High Vol ✓\)'
$highVolFail = $content | Select-String -Pattern '\(High Vol ✗\)'
$lowVolPass = $content | Select-String -Pattern '\(Low Vol ✓\)'
$lowVolFail = $content | Select-String -Pattern '\(Low Vol ✗\)'

Write-Host "High Volume Passed: $($highVolPass.Count)"
Write-Host "High Volume Failed: $($highVolFail.Count)"
Write-Host "Low Volume Passed: $($lowVolPass.Count)"
Write-Host "Low Volume Failed: $($lowVolFail.Count)"

# Timeframe Analysis
Write-Host "`nTIMEFRAME COVERAGE:" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$startTime = ($content | Select-String -Pattern '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}' | Select-Object -First 1).Line -replace ' \| .*', ''
$endTime = ($content | Select-String -Pattern '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}' | Select-Object -Last 2 | Select-Object -First 1).Line -replace ' \| .*', ''

Write-Host "Start Time: $startTime"
Write-Host "End Time: $endTime"

# Symbol Analysis
Write-Host "`nTOP 10 MOST ACTIVE SYMBOLS:" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$symbolSignals = $allSignals | ForEach-Object {
    if ($_.Line -match '\[([A-Z0-9_]+)\]') {
        $matches[1]
    }
} | Group-Object | Sort-Object Count -Descending | Select-Object -First 10

foreach ($symbol in $symbolSignals) {
    Write-Host "$($symbol.Name): $($symbol.Count) signals"
}

Write-Host "`n========================================`n" -ForegroundColor Cyan

