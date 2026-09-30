$ErrorActionPreference = 'Stop'
$snapshotPath = Join-Path $PSScriptRoot '..\modules\brief_parsing\SOURCE_SNAPSHOT.json'
$localChangesPath = Join-Path $PSScriptRoot '..\modules\brief_parsing\LOCAL_CHANGES.json'
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\modules\brief_parsing')).Path
$snapshot = Get-Content -LiteralPath $snapshotPath -Raw | ConvertFrom-Json
$localChanges = Get-Content -LiteralPath $localChangesPath -Raw | ConvertFrom-Json
$allowedChanges = @{}
foreach ($change in $localChanges.changes) {
    if ($allowedChanges.ContainsKey($change.path) -or $change.sha256 -notmatch '^[a-f0-9]{64}$') {
        throw "Invalid local change entry: $($change.path)"
    }
    $allowedChanges[$change.path] = $change.sha256
}
$mismatches = @()
$verifiedLocalChanges = @()
foreach ($file in $snapshot.files) {
    $path = Join-Path $sourceRoot $file.path
    if (-not (Test-Path -LiteralPath $path)) {
        $mismatches += "MISSING $($file.path)"
        continue
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $file.sha256.ToLowerInvariant()) {
        if ($allowedChanges.ContainsKey($file.path) -and
            $actual -eq $allowedChanges[$file.path]) {
            $verifiedLocalChanges += $file.path
        } else {
            $mismatches += "UNRECORDED CHANGE $($file.path)"
        }
    } elseif ($allowedChanges.ContainsKey($file.path)) {
        $mismatches += "STALE LOCAL CHANGE $($file.path)"
    }
}
foreach ($change in $localChanges.changes) {
    if ($change.path -notin $verifiedLocalChanges -and
        $change.path -notin ($snapshot.files | ForEach-Object { $_.path })) {
        $mismatches += "UNKNOWN LOCAL CHANGE $($change.path)"
    }
}
Write-Output "Snapshot files: $($snapshot.files.Count); recorded local changes: $($verifiedLocalChanges.Count); mismatches: $($mismatches.Count)"
$mismatches | Write-Output
if ($mismatches.Count -gt 0) { exit 1 }
