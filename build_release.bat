@echo off
REM Builds a clean release zip for itch.io upload
REM Run this from the project root

set OUTPUT=shiny-hunter-release.zip

REM Delete old zip if exists
if exist "%OUTPUT%" del "%OUTPUT%"

REM Use PowerShell to zip only the right files
powershell -Command ^
  "$exclude = @('__pycache__', '.git', 'tools\screenshots', 'data\licenses.json', 'data\training_pairs', '*.bak', '*.pyc');" ^
  "$items = @('src', 'arduino\switch_controller', 'config', 'requirements.txt', 'setup.bat', 'start.bat', 'README.md');" ^
  "$dataItems = @('data\hunt_profile.json', 'data\ocr_config.json', 'data\sprites');" ^
  "$all = $items + $dataItems;" ^
  "Compress-Archive -Path $all -DestinationPath '%OUTPUT%' -Force;" ^
  "Write-Host 'Done! Upload %OUTPUT% to itch.io'"

echo.
echo Release zip created: %OUTPUT%
pause
