#!/usr/bin/env bash
# ==============================================================================
# Stoke Mahjong - Cloudflare Tunnel Runner for Linux / WSL
# 무료 공식 Cloudflare Tunnel을 실행하여 로컬 서버(localhost:7700)를
# 외부에서 접속 가능한 무료 고유 HTTPS 링크로 즉시 오픈합니다.
# ==============================================================================

set -e

PORT=${1:-7700}
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_PATH="$PROJECT_DIR/cloudflared"

if [ ! -f "$BIN_PATH" ] && ! command -v cloudflared &> /dev/null; then
    echo "⬇️ cloudflared 바이너리가 없습니다. 최신 버전을 다운로드합니다..."
    curl -sL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" -o "$BIN_PATH"
    chmod +x "$BIN_PATH"
    echo "✅ cloudflared 다운로드 완료: $BIN_PATH"
fi

RUN_CMD="$BIN_PATH"
if command -v cloudflared &> /dev/null; then
    RUN_CMD="cloudflared"
fi

echo "===================================================================="
echo "🌐 Stoke Mahjong - Cloudflare Tunnel 시작 중 (Port: $PORT)"
echo "💡 터널이 연결되면 출력되는 'https://xxxx.trycloudflare.com' 주소로"
echo "   시청자 누구나 웹 브라우저에서 실시간 자산/스펙을 조회할 수 있습니다!"
echo "   (공식 웹페이지 링크: https://xxxx.trycloudflare.com/guide)"
echo "===================================================================="

exec "$RUN_CMD" tunnel --url "http://localhost:$PORT"
