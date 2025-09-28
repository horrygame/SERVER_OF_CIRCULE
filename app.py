# server.py
import socket
import threading
import json
import os

class GameServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Важно: Render предоставляет порт через переменную окружения
        self.HOST = '0.0.0.0'  # Слушаем все интерфейсы
        self.PORT = int(os.environ.get('PORT', 8080))
        
        self.players = {}
        self.bullets = []
        self.lock = threading.Lock()
        self.running = True

    def start(self):
        try:
            self.sock.bind((self.HOST, self.PORT))
            self.sock.listen(5)
            print(f"Сервер запущен на {self.HOST}:{self.PORT}")
            
            while self.running:
                conn, addr = self.sock.accept()
                print(f"Новое подключение: {addr}")
                client_thread = threading.Thread(
                    target=self.handle_client, 
                    args=(conn,)
                )
                client_thread.daemon = True
                client_thread.start()
        except Exception as e:
            print(f"Ошибка сервера: {e}")
        finally:
            self.sock.close()

    def handle_client(self, conn):
        player_id = None
        try:
            # Получаем начальные данные от клиента
            initial_data = conn.recv(1024).decode('utf-8')
            if not initial_data:
                return
                
            data = json.loads(initial_data)
            
            if data.get("request") == "join":
                with self.lock:
                    player_id = str(len(self.players) + 1)
                    self.players[player_id] = {
                        "id": player_id,
                        "x": 400,
                        "y": 300,
                        "hp": 100,
                        "weapon": "knife"
                    }
                
                # Отправляем ID игрока обратно
                conn.sendall(json.dumps({
                    "your_id": player_id,
                    "players": self.players,
                    "bullets": self.bullets
                }).encode('utf-8'))
            
            # Основной цикл обработки клиента
            while True:
                data = conn.recv(1024).decode('utf-8')
                if not data:
                    break
                    
                data = json.loads(data)
                with self.lock:
                    if not player_id or player_id not in self.players:
                        break

                    # Обработка движения
                    if data["request"] == "move":
                        player = self.players[player_id]
                        if data["move"] == "left": 
                            player["x"] = max(0, player["x"] - 5)
                        if data["move"] == "right": 
                            player["x"] = min(800, player["x"] + 5)
                        if data["move"] == "up": 
                            player["y"] = max(0, player["y"] - 5)
                        if data["move"] == "down": 
                            player["y"] = min(600, player["y"] + 5)
                    
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

                    # Отправляем обновленное состояние игры
                    game_state = {
                        "your_id": player_id,
                        "players": self.players,
                        "bullets": self.bullets
                    }
                    
                    conn.sendall(json.dumps(game_state).encode('utf-8'))
                    
        except Exception as e:
            print(f"Ошибка с клиентом: {e}")
        finally:
            if player_id:
                with self.lock:
                    if player_id in self.players:
                        del self.players[player_id]
                print(f"Игрок {player_id} отключен")
            conn.close()

if __name__ == "__main__":
    server = GameServer()
    server.start()
