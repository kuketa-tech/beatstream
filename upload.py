import base64
import json
import socket
from pathlib import Path

HOST, PORT = 'localhost', 5555


def upload(filepath, title, artist, album='', genre='Поп', username='admin'):
    filepath = Path(filepath)

    if not filepath.is_absolute():
        filepath = Path(__file__).parent / filepath

    if not filepath.exists():
        raise FileNotFoundError(f'Файл не найден: {filepath}')

    with open(filepath, 'rb') as f:
        song_data_b64 = base64.b64encode(f.read()).decode('ascii')

    msg = {
        'type': 'upload_song',
        'username': username,
        'song_data': song_data_b64,
        'meta': {
            'title': title,
            'artist': artist,
            'album': album,
            'genre': genre,
            'duration': 0,
        }
    }

    payload = json.dumps(msg, ensure_ascii=False).encode('utf-8')

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((HOST, PORT))
    s.sendall(payload)
    s.shutdown(socket.SHUT_WR)

    buf = b''
    try:
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                resp = json.loads(buf.decode('utf-8'))
                if resp.get('type') == 'upload_success':
                    song_info = resp.get('song_info', {})
                    print(f"✓ Загружено: {song_info.get('title')} ({song_info.get('artist')})")
                else:
                    print('Ошибка сервера:', resp.get('message', resp))
                return resp
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

        if buf:
            try:
                resp = json.loads(buf.decode('utf-8'))
                print(resp)
                return resp
            except Exception:
                pass

        raise ConnectionError('Сервер закрыл соединение без ответа')
    finally:
        s.close()


if __name__ == '__main__':
    upload('song3.mp3', 'Лето', 'Вивальди', genre='Классика')
