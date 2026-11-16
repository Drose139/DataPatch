$ErrorActionPreference = 'Stop'
$caseRoot = [System.IO.Path]::GetFullPath('D:\DataPatch-work\unseen-carrier-20261026-001')
if (-not (Test-Path -LiteralPath (Join-Path $caseRoot 'native-case.json'))) { throw 'Not a prepared case' }
$deletedPaths = @()
foreach ($relativeDir in @('project\target', 'project\logs')) {
    $targetDir = [System.IO.Path]::GetFullPath((Join-Path $caseRoot $relativeDir))
    if (-not $targetDir.StartsWith($caseRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Generated artifact path escaped the selected case'
    }
    if (Test-Path -LiteralPath $targetDir) {
        $resolvedDir = (Resolve-Path -LiteralPath $targetDir).Path
        if ($resolvedDir -ne $targetDir) { throw 'Unexpected resolved artifact path' }
        Remove-Item -LiteralPath $resolvedDir -Recurse -Force
        $deletedPaths += $resolvedDir
    }
}
$deletedPaths | ConvertTo-Json
