# Create .venv-pix2tex inside YouTubeProcess
$ErrorActionPreference = "Stop"
$SkillRoot = Split-Path -Parent $PSScriptRoot
$WorkspaceRoot = (Resolve-Path (Join-Path $SkillRoot "..\..\..")).Path
$ProcessRoot = Join-Path $WorkspaceRoot "YouTubeProcess"
$Venv = Join-Path $ProcessRoot ".venv-pix2tex"
$Py = "C:\ProgramData\anaconda3\python.exe"

if (-not (Test-Path $Py)) {
    throw "Anaconda Python not found: $Py"
}

New-Item -ItemType Directory -Force -Path $ProcessRoot | Out-Null
Write-Host "YouTubeProcess: $ProcessRoot"
Write-Host "Creating venv at $Venv ..."
if (Test-Path $Venv) {
    Write-Host "  (venv already exists, reusing)"
} else {
    & $Py -m venv $Venv
}

$VenvPy = Join-Path $Venv "Scripts\python.exe"
& $VenvPy -m pip install --upgrade pip wheel
& $VenvPy -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
& $VenvPy -m pip install "numpy<2" pillow opencv-python pix2tex matplotlib

& $VenvPy -c "from pix2tex.cli import LatexOCR; print('pix2tex OK:', LatexOCR)"
Write-Host ""
Write-Host "Done. Example:"
Write-Host "  C:\ProgramData\anaconda3\python.exe $SkillRoot\scripts\board_to_latex.py --video-id nocZR2m180M"
