$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$taskPython = 'python'
if (Test-Path -LiteralPath '.venv/Scripts/python.exe') {
    $taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
}
if (-not (Test-Path -LiteralPath 'data/library.sqlite3')) {
    if (Test-Path -LiteralPath '../work/on_flirtation/source/manifest.json') {
        & $taskPython -m source_finder import-workspace --root ..
        if ($LASTEXITCODE -ne 0) { throw 'Book import failed. Check the terminal output.' }
    }
}
Write-Host 'Open http://127.0.0.1:8765 in your browser. Press Ctrl+C to stop.'
& $taskPython -m source_finder serve
