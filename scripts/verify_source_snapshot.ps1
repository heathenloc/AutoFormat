$ErrorActionPreference = 'Stop'
$snapshotPath = Join-Path $PSScriptRoot '..\modules\brief_parsing\SOURCE_SNAPSHOT.json'
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\modules\brief_parsing')).Path
$snapshot = Get-Content -LiteralPath $snapshotPath -Raw | ConvertFrom-Json
$mismatches = @()
foreach ($file in $snapshot.files) {
    $path = Join-Path $sourceRoot $file.path
    if (-not (Test-Path -LiteralPath $path)) {
        $mismatches += "MISSING $($file.path)"
        continue
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $file.sha256.ToLowerInvariant()) {
        $mismatches += "CHANGED $($file.path)"
    }
}
Write-Output "Snapshot files: $($snapshot.files.Count); mismatches: $($mismatches.Count)"
$mismatches | Write-Output
if ($mismatches.Count -gt 0) { exit 1 }
