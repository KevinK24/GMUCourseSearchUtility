@echo off
REM Double-clickable launcher for the gmu interactive menu.
REM Prefers the installed `gmu` console script; falls back to `python -m`
REM so this still works if the Scripts directory isn't on PATH.

REM UTF-8 console so the menu's box-drawing and arrow glyphs render.
chcp 65001 >nul 2>nul
set "PYTHONIOENCODING=utf-8"
title GMU Course Search

where gmu >nul 2>nul && goto :run_console_script

python -m gmu_courses.cli menu
goto :done

:run_console_script
gmu menu

:done
REM Keep the window open only when something went wrong, so a clean quit
REM closes immediately but a crash stays readable.
if errorlevel 1 (
    echo.
    echo ----------------------------------------------------------------
    echo Exited with an error. Review the output above.
    echo If gmu isn't installed, run from the project directory:
    echo     pip install -e .
    echo ----------------------------------------------------------------
    pause
)
