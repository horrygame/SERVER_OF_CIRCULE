import socket
import json
import threading
from threading import Thread
PORT = int(os.environ.get("PORT", 8080))
HOST, PORT = "0.0.0.0", PORT
MAX_PLAYERS = 100


class GameServer:
    def __init__(self, addr, max_conn):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(addr)
        self.max_players = max_conn
        self.players = {}
        self.bullets = []
        self.lock = threading.Lock()
        self.sock.listen(self.max_players)
        print("Сервер запущен. Ожидание подключений...")
        self.listen()

    def listen(self):
        while True:
            try:
                conn, addr = self.sock.accept()
                print(f"Новое подключение: {addr}")

                with self.lock:
                    new_player_id = str(len(self.players))
                    self.players[new_player_id] = {
                        "id": new_player_id,
                        "x": 400,
                        "y": 300,
                        "hp": 100,
                        "weapon": "knife"
                    }

                Thread(target=self.handle_client, args=(conn, new_player_id)).start()
            except Exception as e:
                print(f"Ошибка принятия подключения: {e}")

    def handle_client(self, conn, player_id):
        try:
            while True:
                data = conn.recv(1024).decode('utf-8')
                if not data:
                    break

                data = json.loads(data)

                with self.lock:
                    player = self.players.get(player_id)
                    if not player:
                        break

                    # ОБРАБОТКА ДВИЖЕНИЯ
                    if data["request"] == "move":
                        if data["move"] == "left": player["x"] = max(0, player["x"] - 5)
                        if data["move"] == "right": player["x"] = min(800, player["x"] + 5)
                        if data["move"] == "up": player["y"] = max(0, player["y"] - 5)
                        if data["move"] == "down": player["y"] = min(600, player["y"] + 5)

                    # ОБРАБОТКА СМЕНЫ ОРУЖИЯ
                    elif data["request"] == "switch_weapon":
                        player["weapon"] = data["weapon"]

                    # ОБРАБОТКА ВЫСТРЕЛА
                    elif data["request"] == "shoot":
                        if player["weapon"] == "gun":
                            self.bullets.append({
                                "id": player_id,
                                "x": player["x"],
                                "y": player["y"],
                                "dir_x": data["dir_x"],
                                "dir_y": data["dir_y"]
                            })

                    # ОБНОВЛЕНИЕ ПУЛЬ
                    self.update_bullets()

                    # ОТПРАВКА СОСТОЯНИЯ ИГРЫ
                    game_state = {
                        "your_id": player_id,
                        "players": self.players,
                        "bullets": self.bullets
                    }

                conn.sendall(bytes(json.dumps(game_state), 'utf-8'))

        except Exception as e:
            print(f"Ошибка с клиентом {player_id}: {e}")
        finally:
            with self.lock:
                if player_id in self.players:
                    del self.players[player_id]
            conn.close()
            print(f"Клиент {player_id} отключен")

    def update_bullets(self):
        # Удаляем старые пули (здесь можно добавить логику движения пуль)
        if len(self.bullets) > 50:  # Ограничиваем количество пуль
            self.bullets = self.bullets[-50:]


if __name__ == "__main__":
    server = GameServer((HOST, PORT), MAX_PLAYERS)
