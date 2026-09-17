const express = require('express');
const app = express();
const http = require('http').createServer(app);
const io = require('socket.io')(http);

// public 폴더의 정적 HTML 파일을 제공합니다.
app.use(express.static('public'));

io.on('connection', (socket) => {
    console.log('📺 OBS 오버레이 웹소켓이 연결되었습니다.');
    
    // ---------------------------------------------------------
    // [TODO] 여기에 치지직 채팅 API 또는 크롤링 봇 코드를 연동하세요.
    // (예: npm의 'chzzk' 같은 비공식 라이브러리 활용)
    // ---------------------------------------------------------
    
    // 테스트를 위한 임시 더미 데이터 발송 (나중에 지우시면 됩니다)
    setTimeout(() => {
        socket.emit('chat_message', { nickname: '리일쯔우라3', message: '일급천제 혼천 ㅊㅊ' });
    }, 2000);
    setTimeout(() => {
        socket.emit('chat_message', { nickname: '민물고기1', message: 'ㄱㄱ' });
    }, 4000);
    setTimeout(() => {
        socket.emit('chat_message', { nickname: '잔시', message: '혼천갔다는데' });
    }, 6000);
});

const PORT = 7700;
http.listen(PORT, () => {
    console.log(`🚀 치지직 작혼 오버레이 서버 실행 중: http://localhost:${PORT}`);
});