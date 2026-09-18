@echo off
chcp 65001 > nul
cd /d "%~dp0"
title Stoke Mahjong - Cloudflare Tunnel

echo ====================================================================
echo [Stoke Mahjong] Cloudflare Tunnel 실행 중...
echo ====================================================================

if not exist "%~dp0cloudflared.exe" (
    echo [INFO] cloudflared.exe를 다운로드합니다...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe', '%~dp0cloudflared.exe')"
    if not exist "%~dp0cloudflared.exe" (
        echo [ERROR] cloudflared.exe 다운로드에 실패했습니다.
        pause
        exit /b 1
    )
)

echo [INFO] 터널 연결을 시작합니다 (Port: 7700)...
echo [INFO] 아래에 생성되는 'https://xxxx.trycloudflare.com' 주소로
echo        시청자 누구나 웹 브라우저에서 실시간 스펙을 조회할 수 있습니다!
echo        (공식 웹페이지: https://xxxx.trycloudflare.com/guide)
echo ====================================================================
echo.

"%~dp0cloudflared.exe" tunnel --url http://127.0.0.1:7700

echo.
echo ====================================================================
echo [INFO] Cloudflare Tunnel이 종료되었습니다.
echo ====================================================================
pause
