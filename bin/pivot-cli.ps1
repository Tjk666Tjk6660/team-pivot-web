# pivot-cli.ps1 — Team-Pivot Agent CLI for Windows PowerShell (curl wrapper)
# No runtime dependencies beyond PowerShell 5.1+.
#
# Config: ~/.pivot-cli.conf (created by 'pivot-cli login')
#   PIVOT_ENDPOINT=https://xxx.saas.enclaws.com
#   PIVOT_TOKEN=ptk_xxx

param(
    [Parameter(Position=0)]
    [string]$Command,
    [Parameter(Position=1, ValueFromRemainingArguments=$true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
$ConfigFile = Join-Path $HOME ".pivot-cli.conf"

function Write-Err($msg) { Write-Error $msg; exit 1 }

function Load-Config {
    if (-not (Test-Path $ConfigFile)) {
        Write-Err "Not logged in. Run: pivot-cli login --endpoint <url> --token <token>"
    }
    $script:Endpoint = ""
    $script:Token = ""
    Get-Content $ConfigFile | ForEach-Object {
        if ($_ -match '^PIVOT_ENDPOINT=(.+)$') { $script:Endpoint = $Matches[1] }
        if ($_ -match '^PIVOT_TOKEN=(.+)$')    { $script:Token = $Matches[1] }
    }
    if (-not $script:Endpoint) { Write-Err "PIVOT_ENDPOINT not set in $ConfigFile" }
    if (-not $script:Token)    { Write-Err "PIVOT_TOKEN not set in $ConfigFile" }
}

function Invoke-Rpc($Method, $Params) {
    $body = @{ method = $Method; params = $Params } | ConvertTo-Json -Depth 10
    $headers = @{
        "Authorization" = "Bearer $script:Token"
        "Content-Type"  = "application/json"
    }
    try {
        $resp = Invoke-RestMethod -Uri "$script:Endpoint/api/rpc" -Method POST -Headers $headers -Body $body
        $resp | ConvertTo-Json -Depth 10
    } catch {
        Write-Error "HTTP request failed: $_"
        exit 3
    }
}

function Parse-Named-Args($argList, [string[]]$names) {
    $argList = @($argList)
    $result = @{}
    $positional = @()
    $i = 0
    while ($i -lt $argList.Count) {
        $a = [string]$argList[$i]
        if ($a.StartsWith("--") -and $names -contains $a.Substring(2)) {
            $key = $a.Substring(2)
            $i++
            $result[$key] = if ($i -lt $argList.Count) { $argList[$i] } else { "" }
        } else {
            $positional += $a
        }
        $i++
    }
    # Ensure all declared names have at least empty string (avoid $null in JSON)
    foreach ($n in $names) {
        if (-not $result.ContainsKey($n)) { $result[$n] = "" }
    }
    $result["_positional"] = $positional
    return $result
}

function Cmd-Login($a) {
    $parsed = Parse-Named-Args $a @("endpoint","token")
    $ep = $parsed["endpoint"]; $tk = $parsed["token"]
    if (-not $ep -or -not $tk) { Write-Err "Usage: pivot-cli login --endpoint <url> --token <token>" }
    @("PIVOT_ENDPOINT=$ep", "PIVOT_TOKEN=$tk") | Set-Content $ConfigFile
    Write-Output "Logged in. Config saved to $ConfigFile"
}

function Cmd-Discuss($a) {
    Load-Config
    $sub = if ($a.Count -gt 0) { $a[0] } else { "" }
    $rest = if ($a.Count -gt 1) { $a[1..($a.Count-1)] } else { @() }

    # Parse all --key value pairs
    $parsed = Parse-Named-Args $rest @("category","thread","title","content","mention","comments","reason")
    $pos = @($parsed["_positional"] | Where-Object { $_ -ne $null -and $_ -ne "" })
    if ($pos.Count -gt 0) { Write-Err "All parameters must use --key <value> format. Got positional: $($pos -join ', ')" }

    switch ($sub) {
        "new" {
            if (-not $parsed["content"]) { Write-Err "Usage: pivot-cli discuss new --category <cat> --title <title> --content <text> [--mention <users>] [--comments <text>]" }
            Invoke-Rpc "app.pivot.discuss-new" @{
                category=$parsed["category"]; title=$parsed["title"]; content=$parsed["content"]
                mention_users=$parsed["mention"]; mention_comments=$parsed["comments"]
            }
        }
        "reply" {
            if (-not $parsed["category"]) { Write-Err "Usage: pivot-cli discuss reply --category <cat> --thread <thread> --content <text> [--mention <users>] [--comments <text>]" }
            if (-not $parsed["thread"]) { Write-Err "reply requires --thread" }
            if (-not $parsed["content"]) { Write-Err "reply requires --content" }
            Invoke-Rpc "app.pivot.discuss-reply" @{
                category=$parsed["category"]; thread=$parsed["thread"]; content=$parsed["content"]
                mention_users=$parsed["mention"]; mention_comments=$parsed["comments"]
            }
        }
        "list" {
            Invoke-Rpc "app.pivot.discuss-list" @{ category=$parsed["category"] }
        }
        "inbox" {
            Invoke-Rpc "app.pivot.discuss-inbox" @{}
        }
        "read" {
            if (-not $parsed["category"]) { Write-Err "Usage: pivot-cli discuss read --category <cat> --thread <thread>" }
            if (-not $parsed["thread"]) { Write-Err "read requires --thread" }
            Invoke-Rpc "app.pivot.discuss-read" @{ category=$parsed["category"]; thread=$parsed["thread"] }
        }
        {$_ -in "close","pending"} {
            if (-not $parsed["category"]) { Write-Err "Usage: pivot-cli discuss $sub --category <cat> --thread <thread>" }
            if (-not $parsed["thread"]) { Write-Err "$sub requires --thread" }
            Invoke-Rpc "app.pivot.discuss-status" @{ category=$parsed["category"]; thread=$parsed["thread"]; action=$sub; reason="" }
        }
        "reopen" {
            if (-not $parsed["category"]) { Write-Err "Usage: pivot-cli discuss reopen --category <cat> --thread <thread> --reason <text>" }
            if (-not $parsed["thread"]) { Write-Err "reopen requires --thread" }
            if (-not $parsed["reason"]) { Write-Err "reopen requires --reason" }
            Invoke-Rpc "app.pivot.discuss-status" @{ category=$parsed["category"]; thread=$parsed["thread"]; action="reopen"; reason=$parsed["reason"] }
        }
        "summarize" {
            if (-not $parsed["category"]) { Write-Err "Usage: pivot-cli discuss summarize --category <cat> --thread <thread>" }
            if (-not $parsed["thread"]) { Write-Err "summarize requires --thread" }
            Invoke-Rpc "app.pivot.discuss-summarize" @{ category=$parsed["category"]; thread=$parsed["thread"] }
        }
        "result" {
            if (-not $parsed["category"]) { Write-Err "Usage: pivot-cli discuss result --category <cat> --thread <thread>" }
            if (-not $parsed["thread"]) { Write-Err "result requires --thread" }
            Invoke-Rpc "app.pivot.discuss-result" @{ category=$parsed["category"]; thread=$parsed["thread"] }
        }
        default { Write-Err "Unknown discuss command: $sub" }
    }
}

function Cmd-File($a) {
    Load-Config
    $sub = if ($a.Count -gt 0) { $a[0] } else { "" }
    $rest = if ($a.Count -gt 1) { $a[1..($a.Count-1)] } else { @() }
    if ($sub -eq "fetch") {
        $parsed = Parse-Named-Args $rest @("paths")
        if (-not $parsed["paths"]) { Write-Err "Usage: pivot-cli file fetch --paths <path1,path2,...>" }
        Invoke-Rpc "app.pivot.file-fetch" @{ paths=$parsed["paths"] }
    } else {
        Write-Err "Unknown file command: $sub"
    }
}

function Cmd-Monitor($a) {
    Load-Config
    $sub = if ($a.Count -gt 0) { $a[0] } else { "" }
    $rest = if ($a.Count -gt 1) { $a[1..($a.Count-1)] } else { @() }
    if ($sub -eq "scan") {
        $parsed = Parse-Named-Args $rest @("window-hours","mention-window-hours")
        Invoke-Rpc "app.pivot.monitor-scan" @{
            window_hours=$parsed["window-hours"]
            mention_window_hours=$parsed["mention-window-hours"]
        }
    } else {
        Write-Err "Unknown monitor command: $sub"
    }
}

function Cmd-Help {
    Write-Output @"
pivot-cli -- Team-Pivot Agent CLI

Usage: pivot-cli <command> --key <value> ...

Commands:
  login      --endpoint <url> --token <token>
  discuss new       --category <cat> --title <title> --content <text> [--mention <users>] [--comments <text>]
  discuss reply     --category <cat> --thread <thread> --content <text> [--mention <users>] [--comments <text>]
  discuss list      [--category <cat>]
  discuss inbox
  discuss read      --category <cat> --thread <thread>
  discuss close     --category <cat> --thread <thread>
  discuss pending   --category <cat> --thread <thread>
  discuss reopen    --category <cat> --thread <thread> --reason <text>
  discuss summarize --category <cat> --thread <thread>
  discuss result    --category <cat> --thread <thread>
  monitor scan      [--window-hours <N>] [--mention-window-hours <N>]
  file fetch        --paths <path1,path2,...>

All parameters must use --key <value> format.
All commands return JSON.
"@
}

# ---- main ----
switch ($Command) {
    "login"   { Cmd-Login $Args }
    "discuss" { Cmd-Discuss $Args }
    "monitor" { Cmd-Monitor $Args }
    "file"    { Cmd-File $Args }
    {$_ -in "help","--help","-h",""} { Cmd-Help }
    default   { Write-Err "Unknown command: $Command. Run 'pivot-cli help'." }
}
