@echo off
setlocal

set REDIS_URL=redis://:mes-redis-2026@127.0.0.1:6379/0
set MES_VIDEO_DIR=D:\analyze ai\data\videos
set MES_CONFIG_PATH=config.yaml
set MEDIAPIPE_DISABLE_GPU=1
set PYTHONUNBUFFERED=1

if "%1"=="--listener" goto listener
if "%1"=="--video" goto video
goto usage

:listener
echo [Windows] Starting command listener...
echo [Windows] Redis: %REDIS_URL%
python command_listener.py
goto end

:video
if "%2"=="" goto usage
echo [Windows] Processing video: %2
python main.py --video "%2" --station-id WS-01 --config config.yaml
goto end

:usage
echo Usage: run_perception.bat [options]
echo   --listener              Start Redis command listener
echo   --video ^<file^>         Process a video file directly
echo.
echo Examples:
echo   run_perception.bat --listener
echo   run_perception.bat --video D:\analyze ai\data\videos\test.mp4
goto end

:end
endlocal
