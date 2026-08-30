$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $scriptDir '.venv\Scripts\pythonw.exe'
$python = Join-Path $scriptDir '.venv\Scripts\python.exe'
$app = Join-Path $scriptDir 'aggro_ui.py'

if (Test-Path $pythonw) {
    & $pythonw $app
} elseif (Test-Path $python) {
    & $python $app
} else {
    & python $app
}
