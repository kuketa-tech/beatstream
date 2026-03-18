
import base64
import binascii
import hashlib
import json
import os
import socket
import threading
from datetime import datetime


class MusicStreamServer:
    def __init__(self, host='0.0.0.0', port=5555):
        self.host, self.port = host, port
        self.users_file = 'users.json'
        self.library_file = 'music_library.json'
        self.playlists_file = 'playlists.json'
        self.users = self._load(self.users_file)
        self.library = self._load(self.library_file)
        self.playlists = self._load(self.playlists_file)
        self.connections = {}
        self.music_dir = 'music_files'
        os.makedirs(self.music_dir, exist_ok=True)

    # ── Persistence ──────────────────────────────────────────────────────────
    def _load(self, path):
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save(self, data, path):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[ERR] save {path}: {e}")
            return False

    @staticmethod
    def _hash(pw):
        return hashlib.sha256(pw.encode()).hexdigest()

    # ── Client loop ──────────────────────────────────────────────────────────
    def handle_client(self, sock, addr):
        self.connections[addr] = sock
        buf = b''
        max_payload_size = 30 * 1024 * 1024  # 30 MB на весь JSON-запрос

        try:
            while True:
                data = sock.recv(512 * 1024)
                if not data:
                    break

                buf += data

                if len(buf) > max_payload_size:
                    sock.sendall(json.dumps({
                        'type': 'upload_error',
                        'message': 'Слишком большой запрос'
                    }, ensure_ascii=False).encode('utf-8'))
                    return

                try:
                    text = buf.decode('utf-8')
                    msg = json.loads(text)
                except UnicodeDecodeError:
                    # Возможно, пришла только часть UTF-8 последовательности
                    continue
                except json.JSONDecodeError:
                    # JSON ещё не пришёл целиком
                    continue

                resp = self._dispatch(msg)
                if resp:
                    sock.sendall(json.dumps(resp, ensure_ascii=False).encode('utf-8'))
                buf = b''
                break

        except Exception as e:
            print(f"[ERR] client {addr}: {e}")
        finally:
            self.connections.pop(addr, None)
            sock.close()
            print(f"[-] {addr} отключён")

    def _dispatch(self, msg):
        handlers = {
            'register': self._reg,
            'login': self._login,
            'upload_song': self._upload_song,
            'get_library': self._get_library,
            'get_playlists': self._get_playlists,
            'create_playlist': self._create_playlist,
            'add_to_playlist': self._add_to_playlist,
            'remove_from_playlist': self._remove_from_playlist,
            'delete_playlist': self._delete_playlist,
            'search_music': self._search,
            'get_song_file': self._get_song_file,
            'get_recommendations': self._get_recs,
            'get_genres': self._get_genres,
            'like_song': self._like_song,
            'get_liked_songs': self._get_liked,
            'delete_song': self._delete_song,
            'get_stats': self._get_stats,
        }
        fn = handlers.get(msg.get('type'))
        if not fn:
            return {'type': 'error', 'message': f"Неизвестный тип: {msg.get('type')}"}
        try:
            return fn(msg)
        except Exception as e:
            return {'type': 'error', 'message': str(e)}

    # ── Handlers ─────────────────────────────────────────────────────────────
    def _reg(self, m):
        u = m.get('username', '').strip()
        p = m.get('password', '').strip()
        e = m.get('email', '').strip()
        if not u or not p:
            return {'type': 'register_error', 'message': 'Заполните все поля'}
        if len(u) < 3:
            return {'type': 'register_error', 'message': 'Имя минимум 3 символа'}
        if len(p) < 4:
            return {'type': 'register_error', 'message': 'Пароль минимум 4 символа'}
        if u in self.users:
            return {'type': 'register_error', 'message': 'Пользователь уже существует'}
        self.users[u] = {
            'password': self._hash(p), 'email': e,
            'liked_songs': [], 'playlists': [],
            'created_at': datetime.now().isoformat(),
            'last_login': datetime.now().isoformat(),
        }
        self._save(self.users, self.users_file)
        return {'type': 'register_success', 'message': 'Регистрация успешна'}

    def _login(self, m):
        u = m.get('username', '').strip()
        p = m.get('password', '').strip()
        if not u or not p:
            return {'type': 'login_error', 'message': 'Заполните все поля'}
        if u not in self.users:
            return {'type': 'login_error', 'message': 'Пользователь не найден'}
        stored = self.users[u]['password']
        # Поддержка старых plain-text паролей (автомиграция)
        if stored != self._hash(p) and stored != p:
            return {'type': 'login_error', 'message': 'Неверный пароль'}
        if stored == p:
            self.users[u]['password'] = self._hash(p)
        self.users[u]['last_login'] = datetime.now().isoformat()
        self._save(self.users, self.users_file)
        return {
            'type': 'login_success', 'username': u,
            'liked_songs': self.users[u].get('liked_songs', []),
            'playlists': self.users[u].get('playlists', []),
        }

    def _upload_song(self, m):
        data_b64 = m.get('song_data')
        meta = m.get('meta', {})
        user = m.get('username', '')

        if not data_b64 or not meta:
            return {'type': 'upload_error', 'message': 'Нет данных'}

        try:
            raw_data = base64.b64decode(data_b64, validate=True)
        except (binascii.Error, ValueError):
            return {'type': 'upload_error', 'message': 'Некорректные данные файла'}

        sid = hashlib.md5(f"{meta.get('title')}{datetime.now()}".encode()).hexdigest()[:12]
        fname = f"{sid}.mp3"
        fpath = os.path.join(self.music_dir, fname)

        with open(fpath, 'wb') as f:
            f.write(raw_data)

        info = {
            'id': sid,
            'title': meta.get('title', 'Без названия'),
            'artist': meta.get('artist', 'Неизвестен'),
            'album': meta.get('album', ''),
            'genre': meta.get('genre', 'Другое'),
            'duration': meta.get('duration', 0),
            'uploaded_by': user,
            'upload_date': datetime.now().isoformat(),
            'likes': 0,
            'plays': 0,
            'filename': fname,
            'file_size': os.path.getsize(fpath),
        }
        self.library[sid] = info
        self._save(self.library, self.library_file)
        return {'type': 'upload_success', 'song_id': sid, 'song_info': info}

    def _get_library(self, m):
        g = m.get('genre', '')
        sb = m.get('sort_by', 'title')
        songs = list(self.library.values())
        if g:
            songs = [s for s in songs if s.get('genre', '').lower() == g.lower()]
        key = {
            'title': lambda x: x.get('title', '').lower(),
            'artist': lambda x: x.get('artist', '').lower(),
            'popular': lambda x: -x.get('plays', 0),
            'date': lambda x: x.get('upload_date', ''),
        }.get(sb, lambda x: x.get('title', '').lower())
        songs.sort(key=key)
        return {'type': 'library_data', 'songs': songs, 'total': len(songs)}

    def _get_playlists(self, m):
        u = m.get('username', '')
        out = []
        for pid, pl in self.playlists.items():
            if pl.get('owner') == u:
                d = pl.copy()
                d['id'] = pid
                d['songs_count'] = len(pl.get('songs', []))
                d['song_details'] = [
                    self.library[s] for s in pl.get('songs', []) if s in self.library
                ]
                out.append(d)
        return {'type': 'playlists_data', 'playlists': out}

    def _create_playlist(self, m):
        u = m.get('username', '')
        name = m.get('name', '').strip()
        if not name:
            return {'type': 'error', 'message': 'Введите название'}
        pid = hashlib.md5(f"{u}{name}{datetime.now()}".encode()).hexdigest()[:12]
        self.playlists[pid] = {
            'name': name, 'owner': u,
            'created_at': datetime.now().isoformat(),
            'songs': [], 'description': m.get('description', ''),
        }
        self._save(self.playlists, self.playlists_file)
        if u in self.users:
            self.users[u].setdefault('playlists', []).append(pid)
            self._save(self.users, self.users_file)
        return {'type': 'playlist_created', 'playlist_id': pid}

    def _add_to_playlist(self, m):
        pid, sid, u = m.get('playlist_id', ''), m.get('song_id', ''), m.get('username', '')
        if pid not in self.playlists:
            return {'type': 'error', 'message': 'Плейлист не найден'}
        if self.playlists[pid].get('owner') != u:
            return {'type': 'error', 'message': 'Нет прав'}
        if sid not in self.library:
            return {'type': 'error', 'message': 'Песня не найдена'}
        if sid not in self.playlists[pid]['songs']:
            self.playlists[pid]['songs'].append(sid)
            self._save(self.playlists, self.playlists_file)
        return {'type': 'song_added', 'success': True}

    def _remove_from_playlist(self, m):
        pid, sid, u = m.get('playlist_id', ''), m.get('song_id', ''), m.get('username', '')
        if pid not in self.playlists:
            return {'type': 'error', 'message': 'Плейлист не найден'}
        if self.playlists[pid].get('owner') != u:
            return {'type': 'error', 'message': 'Нет прав'}
        if sid in self.playlists[pid]['songs']:
            self.playlists[pid]['songs'].remove(sid)
            self._save(self.playlists, self.playlists_file)
        return {'type': 'song_removed', 'success': True}

    def _delete_playlist(self, m):
        pid, u = m.get('playlist_id', ''), m.get('username', '')
        if pid not in self.playlists:
            return {'type': 'error', 'message': 'Плейлист не найден'}
        if self.playlists[pid].get('owner') != u:
            return {'type': 'error', 'message': 'Нет прав'}
        del self.playlists[pid]
        self._save(self.playlists, self.playlists_file)
        if u in self.users and pid in self.users[u].get('playlists', []):
            self.users[u]['playlists'].remove(pid)
            self._save(self.users, self.users_file)
        return {'type': 'playlist_deleted', 'success': True}

    def _search(self, m):
        q = m.get('query', '').lower().strip()
        if not q:
            return {'type': 'search_results', 'songs': []}
        res = [
            s for s in self.library.values()
            if q in s.get('title', '').lower()
            or q in s.get('artist', '').lower()
            or q in s.get('album', '').lower()
            or q in s.get('genre', '').lower()
        ]
        return {'type': 'search_results', 'songs': res}

    def _get_song_file(self, m):
        sid = m.get('song_id', '')
        if sid not in self.library:
            return {'type': 'error', 'message': 'Песня не найдена'}
        info = self.library[sid]
        fpath = os.path.join(self.music_dir, info['filename'])
        if not os.path.exists(fpath):
            return {'type': 'error', 'message': 'Файл не найден на диске'}
        try:
            with open(fpath, 'rb') as f:
                data = f.read()
            info['plays'] = info.get('plays', 0) + 1
            self._save(self.library, self.library_file)
            return {
                'type': 'song_file',
                'song_id': sid,
                'file_data': data.hex(),
                'file_size': len(data),
                'mime_type': 'audio/mpeg',
            }
        except Exception as e:
            return {'type': 'error', 'message': f'Ошибка чтения: {e}'}

    def _get_recs(self, m):
        u = m.get('username', '')
        liked = self.users.get(u, {}).get('liked_songs', [])
        recs = sorted(
            [s for sid, s in self.library.items() if sid not in liked],
            key=lambda x: -x.get('plays', 0)
        )
        return {'type': 'recommendations', 'songs': recs[:20]}

    def _get_genres(self, m):
        g = {}
        for s in self.library.values():
            genre = s.get('genre', 'Другое')
            g[genre] = g.get(genre, 0) + 1
        return {'type': 'genres_data', 'genres': list(g.keys()), 'counts': g}

    def _like_song(self, m):
        u, sid = m.get('username', ''), m.get('song_id', '')
        if u not in self.users:
            return {'type': 'error', 'message': 'Пользователь не найден'}
        if sid not in self.library:
            return {'type': 'error', 'message': 'Песня не найдена'}
        liked = self.users[u].get('liked_songs', [])
        if sid in liked:
            liked.remove(sid)
            self.library[sid]['likes'] = max(0, self.library[sid].get('likes', 0) - 1)
            action = 'unliked'
        else:
            liked.append(sid)
            self.library[sid]['likes'] = self.library[sid].get('likes', 0) + 1
            action = 'liked'
        self.users[u]['liked_songs'] = liked
        self._save(self.users, self.users_file)
        self._save(self.library, self.library_file)
        return {'type': 'like_success', 'action': action, 'likes': self.library[sid]['likes']}

    def _get_liked(self, m):
        u = m.get('username', '')
        if u not in self.users:
            return {'type': 'liked_songs', 'songs': []}
        ids = self.users[u].get('liked_songs', [])
        songs = [self.library[i] for i in ids if i in self.library]
        return {'type': 'liked_songs', 'songs': songs}

    def _delete_song(self, m):
        sid, u = m.get('song_id', ''), m.get('username', '')
        if sid not in self.library:
            return {'type': 'error', 'message': 'Не найдена'}
        if self.library[sid].get('uploaded_by') != u:
            return {'type': 'error', 'message': 'Нет прав на удаление'}
        fpath = os.path.join(self.music_dir, self.library[sid]['filename'])
        if os.path.exists(fpath):
            os.remove(fpath)
        del self.library[sid]
        self._save(self.library, self.library_file)
        return {'type': 'delete_success'}

    def _get_stats(self, m):
        return {
            'type': 'stats_data',
            'total_songs': len(self.library),
            'total_users': len(self.users),
            'total_plays': sum(s.get('plays', 0) for s in self.library.values()),
            'total_playlists': len(self.playlists),
            'active_connections': len(self.connections),
        }

    # ── Entry point ──────────────────────────────────────────────────────────
    def start(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((self.host, self.port))
            srv.listen(10)
            print(f"🎵 BeatStream сервер слушает {self.host}:{self.port}")
            print(
                f"   👤 {len(self.users)} пользователей "
                f"| 🎶 {len(self.library)} треков "
                f"| 📁 {len(self.playlists)} плейлистов"
            )
            print("   Нажмите Ctrl+C для остановки\n")
            while True:
                conn, addr = srv.accept()
                print(f"[+] {addr}")
                threading.Thread(
                    target=self.handle_client, args=(conn, addr), daemon=True
                ).start()
        except KeyboardInterrupt:
            print("\n🛑 Сервер остановлен")
        except Exception as e:
            print(f"[FATAL] {e}")
        finally:
            srv.close()


if __name__ == '__main__':
    MusicStreamServer().start()