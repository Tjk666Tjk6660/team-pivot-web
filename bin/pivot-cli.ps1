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
    $result = @{}
    $positional = @()
    $i = 0
    while ($i -lt $argList.Count) {
        $a = $argList[$i]
        if ($a.StartsWith("--") -and $names -contains $a.Substring(2)) {
            $key = $a.Substring(2)
            $i++
            $result[$key] = if ($i -lt $argList.Count) { $argList[$i] } else { "" }
        } else {
            $positional += $a
        }
        $i++
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

    switch ($sub) {
        "new" {
            $parsed = Parse-Named-Args $rest @("draft","mention","comments")
            $pos = $parsed["_positional"]
            $cat = if ($pos.Count -gt 0) { $pos[0] } else { "" }
            $title = if ($pos.Count -gt 1) { $pos[1] } else { "" }
            if (-not $cat) { Write-Err "Usage: pivot-cli discuss new <category> <title> [--draft <path>] [--mention <users>]" }
            Invoke-Rpc "app.pivot.discuss-new" @{
                category=$cat; title=$title
                draft_path=$parsed["draft"]; mention_users=$parsed["mention"]; mention_comments=$parsed["comments"]
            }
        }
        "reply" {
            $parsed = Parse-Named-Args $rest @("draft","mention","comments")
            $pos = $parsed["_positional"]
            $target = if ($pos.Count -gt 0) { $pos[0] } else { "" }
            if (-not $target) { Write-Err "Usage: pivot-cli discuss reply <category>/<thread> [--draft <path>]" }
            $parts = $target -split "/", 2
            Invoke-Rpc "app.pivot.discuss-reply" @{
                category=$parts[0]; thread=$parts[1]
                draft_path=$parsed["draft"]; mention_users=$parsed["mention"]; mention_comments=$parsed["comments"]
            }
        }
        "list" {
            $cat = if ($rest.Count -gt 0) { $rest[0] } else { "" }
            Invoke-Rpc "app.pivot.discuss-list" @{ category=$cat }
        }
        "inbox" {
            Invoke-Rpc "app.pivot.discuss-inbox" @{}
        }
        "read" {
            $target = if ($rest.Count -gt 0) { $rest[0] } else { "" }
            if (-not $target) { Write-Err "Usage: pivot-cli discuss read <category>/<thread>" }
            $parts = $target -split "/", 2
            Invoke-Rpc "app.pivot.discuss-read" @{ category=$parts[0]; thread=$parts[1] }
        }
        {$_ -in "close","pending"} {
            $target = if ($rest.Count -gt 0) { $rest[0] } else { "" }
            if (-not $target) { Write-Err "Usage: pivot-cli discuss $sub <category>/<thread>" }
            $parts = $target -split "/", 2
            Invoke-Rpc "app.pivot.discuss-status" @{ category=$parts[0]; thread=$parts[1]; action=$sub; reason="" }
        }
        "reopen" {
            $parsed = Parse-Named-Args $rest @("reason")
            $pos = $parsed["_positional"]
            $target = if ($pos.Count -gt 0) { $pos[0] } else { "" }
            if (-not $target -or -not $parsed["reason"]) { Write-Err "Usage: pivot-cli discuss reopen <cat>/<thread> --reason <text>" }
            $parts = $target -split "/", 2
            Invoke-Rpc "app.pivot.discuss-status" @{ category=$parts[0]; thread=$parts[1]; action="reopen"; reason=$parsed["reason"] }
        }
        default { Write-Err "Unknown discuss command: $sub" }
    }
}

function Cmd-File($a) {
    Load-Config
    $sub = if ($a.Count -gt 0) { $a[0] } else { "" }
    if ($sub -eq "fetch") {
        $paths = ($a[1..($a.Count-1)]) -join ","
        if (-not $paths) { Write-Err "Usage: pivot-cli file fetch <path> [<path2> ...]" }
        Invoke-Rpc "app.pivot.file-fetch" @{ paths=$paths }
    } else {
        Write-Err "Unknown file command: $sub"
    }
}

function Cmd-Help {
    Write-Output @"
pivot-cli — Team-Pivot Agent CLI

Usage: pivot-cli <command> [options]

Commands:
  login --endpoint <url> --token <token>    Save credentials
  discuss new <category> <title> [options]  Start a new discussion
  discuss reply <category>/<thread> [opts]  Reply to a discussion
  discuss list [category]                   List discussions
  discuss inbox                             Show unread
  discuss read <category>/<thread>          Read a discussion
  discuss close <category>/<thread>         Close a discussion
  discuss pending <category>/<thread>       Shelve a discussion
  discuss reopen <cat>/<thread> --reason X  Reopen a discussion
  file fetch <path> [<path2> ...]           Fetch files

All commands return JSON.
"@
}

# ---- main ----
switch ($Command) {
    "login"   { Cmd-Login $Args }
    "discuss" { Cmd-Discuss $Args }
    "file"    { Cmd-File $Args }
    {$_ -in "help","--help","-h",""} { Cmd-Help }
    default   { Write-Err "Unknown command: $Command. Run 'pivot-cli help'." }
}
