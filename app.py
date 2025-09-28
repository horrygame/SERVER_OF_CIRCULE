import socket
import threading
import json
import os
import time
from threading import Thread

class GameServer:
    def __init__(self):
        self.HOST = '0.0.0.0'
        self.PORT = int(os.environ.get('PORT', 10000))
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.players = {}
        self.bullets = []
        self.lock = threading.Lock()
        self.player_counter = 0
        self.running = True

    def start(self):
        try:
            self.sock.bind((self.HOST, self.PORT))
            self.sock.listen(10)
            print(f"✅ Сервер запущен на {self.HOST}:{self.PORT}")
            print("✅ Ожидание подключений...")
            
            # Запускаем поток для очистки пуль
            cleanup_thread = Thread(target=self.cleanup_bullets, daemon=True)
            cleanup_thread.start()
            
            while self.running:
                try:
                    conn, addr = self.sock.accept()
                    print(f"🔗 Новое подключение от {addr}")
                    client_thread = Thread(target=self.handle_client, args=(conn,), daemon=True)
                    client_thread.start()
                except Exception as e:
                    if self.running:
                        print(f"⚠️ Ошибка принятия подключения: {e}")
                    
        except Exception as e:
            print(f"❌ Ошибка сервера: {e}")
        finally:
            self.sock.close()

    def cleanup_bullets(self):
        """Периодическая очистка старых пуль"""
        while self.running:
            time.sleep(5)
            with self.lock:
                if len(self.bullets) > 100:
                    self.bullets = self.bullets[-50:]
                    print("🧹 Очистка старых пуль")

    def handle_client(self, conn):
        player_id = None
        try:
            # Получаем начальный запрос
            data = conn.recv(1024).decode('utf-8')
            if not data:
                return
                
            data = json.loads(data)
            
            if data.get("request") == "join":
                with self.lock:
                    self.player_counter += 1
                    player_id = str(self.player_counter)
                    self.players[player_id] = {
                        "id": player_id,
                        "x": 400,
                        "y": 300,
                        "hp": 100,
                        "weapon": "knife",
                        "last_update": time.time()
                    }
                
                print(f"🎮 Игрок {player_id} присоединился. Всего игроков: {len(self.players)}")
                
                # Отправляем подтверждение
                response = {
                    "status": "connected", 
                    "your_id": player_id,
                    "players": self.players,
                    "bullets": self.bullets
                }
                conn.sendall((json.dumps(response) + "\n").encode('utf-8'))
            
            # Основной цикл
            while self.running:
                data = conn.recv(1024).decode('utf-8')
                if not data:
                    break
                    
                data = json.loads(data)
                
                with self.lock:
                    if player_id not in self.players:
                        break

                    player = self.players[player_id]
                    player["last_update"] = time.time()

                    # Обработка движения
                    if data["request"] == "move":
                        move = data["move"]
                        if move == "left": 
                            player["x"] = max(20, player["x"] - 5)
                        if move == "right": 
                            player["x"] = min(780, player["x"] + 5)
                        if move == "up": 
                            player["y"] = max(20, player["y"] - 5)
                        if move == "down": 
                            player["y"] = min(580, player["y"] + 5)
                    
                    # Смена оружия
                    elif data["request"] == "switch_weapon":
                        player["weapon"] = data["weapon"]
                    
                    # Выстрел
                    elif data["request"] == "shoot":
                        if player["weapon"] == "gun":
                            self.bullets.append({
                                "id": player_id,
                                "x": player["x"],
                                "y": player["y"],
                                "dir_x": data["dir_x"],
                                "dir_y": data["dir_y"],
                                "created": time.time()
                            })

                    # Отправляем состояние игры
                    game_state = {
                        "your_id": player_id,
                        "players": self.players,
                        "bullets": self.bullets
                    }
                    conn.sendall((json.dumps(game_state) + "\n").encode('utf-8'))
                    
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка JSON от игрока {player_id}: {e}")
        except Exception as e:
            if self.running:
                print(f"❌ Ошибка с клиентом {player_id}: {e}")
        finally:
            if player_id:
                with self.lock:
                    if player_id in self.players:
                        del self.players[player_id]
                print(f"🎮 Игрок {player_id} отключен. Осталось: {len(self.players)}")
            try:
                conn.close()
            except:
                pass

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except:
            pass

if __name__ == "__main__":
    server = GameServer()
    try:
        server.start()
    except KeyboardInterrupt:
        print("🛑 Сервер остановлен")
        server.stop()
