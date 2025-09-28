# server.py
import socket
import threading
import json
import os
from threading import Thread

class GameServer:
    def __init__(self):
        self.HOST = '0.0.0.0'  # Важно для Render
        self.PORT = int(os.environ.get('PORT', 8080))  # Render предоставляет порт
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.players = {}
        self.bullets = []
        self.lock = threading.Lock()
        self.player_counter = 0

    def start(self):
        try:
            self.sock.bind((self.HOST, self.PORT))
            self.sock.listen(5)
            print(f"✅ Сервер запущен на {self.HOST}:{self.PORT}. Ожидание подключений...")
            
            while True:
                conn, addr = self.sock.accept()
                print(f"🔗 Новое подключение от {addr}")
                # Для каждого клиента создаем отдельный поток
                client_thread = Thread(target=self.handle_client, args=(conn,), daemon=True)
                client_thread.start()
        except Exception as e:
            print(f"❌ Критическая ошибка сервера: {e}")
        finally:
            self.sock.close()

    def handle_client(self, conn):
        player_id = None
        try:
            # Получаем начальный запрос на подключение
            initial_data = conn.recv(1024).decode('utf-8')
            if not initial_data:
                return

            data = json.loads(initial_data)
            if data.get("request") == "join":
                with self.lock:
                    self.player_counter += 1
                    player_id = str(self.player_counter)
                    self.players[player_id] = {
                        "id": player_id,
                        "x": 400,
                        "y": 300,
                        "hp": 100,
                        "weapon": "knife"
                    }
                print(f"🎮 Игрок {player_id} присоединился. Всего игроков: {len(self.players)}")

                # Отправляем игроку его ID и начальное состояние игры
                initial_state = {
                    "your_id": player_id,
                    "players": self.players,
                    "bullets": self.bullets
                }
                conn.sendall(json.dumps(initial_state).encode('utf-8'))

            # Основной цикл обработки данных от клиента
            while True:
                data = conn.recv(1024).decode('utf-8')
                if not data:
                    break  # Клиент отключился

                data = json.loads(data)
                with self.lock:
                    if player_id not in self.players:
                        break

                    # Обработка движения
                    if data["request"] == "move":
                        player = self.players[player_id]
                        new_x, new_y = player["x"], player["y"]
                        move = data["move"]
                        if move == "left": new_x = max(0, player["x"] - 5)
                        if move == "right": new_x = min(800, player["x"] + 5)
                        if move == "up": new_y = max(0, player["y"] - 5)
                        if move == "down": new_y = min(600, player["y"] + 5)
                        player["x"], player["y"] = new_x, new_y

                    # Обработка смены оружия
                    elif data["request"] == "switch_weapon":
                        self.players[player_id]["weapon"] = data["weapon"]

                    # Обработка выстрела
                    elif data["request"] == "shoot":
                        if self.players[player_id]["weapon"] == "gun":
                            self.bullets.append({
                                "id": player_id,
                                "x": self.players[player_id]["x"],
                                "y": self.players[player_id]["y"],
                                "dir_x": data["dir_x"],
                                "dir_y": data["dir_y"]
                            })

                    # Подготавливаем и отправляем обновленное состояние игры
                    game_state = {
                        "your_id": player_id,
                        "players": self.players,
                        "bullets": self.bullets
                    }
                    conn.sendall(json.dumps(game_state).encode('utf-8'))

        except json.JSONDecodeError:
            print(f"⚠️ Ошибка декодирования JSON от игрока {player_id}")
        except Exception as e:
            print(f"⚠️ Ошибка с клиентом {player_id}: {e}")
        finally:
            # Корректно удаляем игрока при отключении
            if player_id:
                with self.lock:
                    if player_id in self.players:
                        del self.players[player_id]
                print(f"🎮 Игрок {player_id} отключен. Осталось игроков: {len(self.players)}")
            conn.close()

if __name__ == "__main__":
    server = GameServer()
    server.start()
