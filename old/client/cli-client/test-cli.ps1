# test-cli.ps1 — Quick smoke test for pivot-cli commands
# Usage: powershell -File bin\test-cli.ps1

$ErrorActionPreference = "Continue"
$pass = 0
$fail = 0

function Test-Cmd($desc, $args) {
    Write-Host "`n--- $desc ---" -ForegroundColor Cyan
    Write-Host "CMD: pivot-cli $args" -ForegroundColor DarkGray
    try {
        $output = & powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\pivot-cli.ps1" $args.Split(" ") 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0 -and $output -match '"ok"\s*:\s*false') {
            Write-Host "[FAIL] exit=$exitCode" -ForegroundColor Red
            Write-Host $output
            $script:fail++
        } else {
            Write-Host "[PASS]" -ForegroundColor Green
            Write-Host $output
            $script:pass++
        }
    } catch {
        Write-Host "[FAIL] $_" -ForegroundColor Red
        $script:fail++
    }
}

Write-Host "=== pivot-cli smoke test ===" -ForegroundColor Yellow

Test-Cmd "help" "help"
Test-Cmd "list all" "discuss list"
Test-Cmd "inbox" "discuss inbox"
Test-Cmd "new (content only)" 'discuss new "smoke test from test-cli.ps1"'
Test-Cmd "new (with category+title)" 'discuss new cli-test "test title" "smoke test content"'
Test-Cmd "list cli-test" "discuss list cli-test"

Write-Host "`n=== Results: $pass passed, $fail failed ===" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })
