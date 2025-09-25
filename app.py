from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import time
import threading
import math
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*")

# Конфигурация игры
MAX_PLAYERS_PER_ROOM = 6
WAITING_TIME = 30  # секунды
GAME_DURATION = 150  # 2.5 минуты

# Хранилище данных
rooms = {}
players = {}
player_rooms = {}  # player_id -> room_id

class GameRoom:
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = []  # Только реальные игроки
        self.bots = []     # Только боты
        self.status = 'waiting'  # waiting, counting, playing, finished
        self.creation_time = time.time()
        self.start_time = None
        self.waiting_timer = None
        self.game_timer = None
        self.game_start_time = None
        
        # Начальное состояние игры
        self.game_state = {
            'players': {},
            'game_time': GAME_DURATION,
            'status': 'waiting',
            'start_time': None
        }

    def add_player(self, player_id, player_name):
        """Добавляет реального игрока в комнату"""
        if len(self.players) >= MAX_PLAYERS_PER_ROOM:
            return False
        
        # Создаем данные игрока
        player_data = {
            'id': player_id,
            'name': player_name,
            'position': [random.randint(100, 700), random.randint(100, 500)],
            'color': self.get_random_color(),
            'score': 0,
            'is_bot': False,
            'last_move': time.time(),
            'velocity': [0, 0]
        }
        
        # Добавляем в списки
        self.players.append(player_id)
        self.game_state['players'][player_id] = player_data
        players[player_id] = player_data
        player_rooms[player_id] = self.room_id
        
        print(f"Игрок {player_name} добавлен в комнату {self.room_id}. Теперь игроков: {len(self.players)}")
        
        # Если это первый игрок, запускаем таймер ожидания
        if len(self.players) == 1 and self.status == 'waiting':
            self.status = 'counting'
            self.start_time = time.time()
            self.start_waiting_timer()
        
        # Отправляем обновление состояния комнаты
        self.broadcast_room_update()
        
        # Если комната заполнена, начинаем игру сразу
        if len(self.players) >= MAX_PLAYERS_PER_ROOM and self.status == 'counting':
            print("Комната заполнена, начинаем игру сразу")
            self.start_game()
            
        return True

    def remove_player(self, player_id):
        """Удаляет игрока из комнаты"""
        if player_id in self.players:
            self.players.remove(player_id)
            
        if player_id in self.game_state['players']:
            del self.game_state['players'][player_id]
            
        if player_id in players:
            del players[player_id]
            
        if player_id in player_rooms:
            del player_rooms[player_id]
        
        print(f"Игрок {player_id} удален из комнаты {self.room_id}. Осталось игроков: {len(self.players)}")
        
        # Если комната пустая, удаляем ее
        if len(self.players) == 0 and len(self.bots) == 0:
            if self.waiting_timer and self.status == 'counting':
                self.waiting_timer.cancel()
            if self.room_id in rooms:
                del rooms[self.room_id]
                print(f"Комната {self.room_id} удалена")
        else:
            # Обновляем оставшихся игроков
            self.broadcast_room_update()

    def add_bot(self):
        """Добавляет бота в комнату"""
        if len(self.game_state['players']) >= MAX_PLAYERS_PER_ROOM:
            return False
        
        bot_id = f"bot_{self.room_id}_{len(self.bots) + 1}"
        bot_data = {
            'id': bot_id,
            'name': f"Бот_{len(self.bots) + 1}",
            'position': [random.randint(100, 700), random.randint(100, 500)],
            'color': self.get_random_color(),
            'score': 0,
            'is_bot': True,
            'last_move': time.time(),
            'move_direction': [random.uniform(-1, 1), random.uniform(-1, 1)],
            'direction_change_time': time.time()
        }
        
        # Нормализуем направление
        length = math.sqrt(bot_data['move_direction'][0]**2 + bot_data['move_direction'][1]**2)
        if length > 0:
            bot_data['move_direction'][0] /= length
            bot_data['move_direction'][1] /= length
        
        self.bots.append(bot_id)
        self.game_state['players'][bot_id] = bot_data
        
        print(f"Бот {bot_id} добавлен в комнату {self.room_id}")
        return True

    def start_waiting_timer(self):
        """Запускает таймер ожидания игроков"""
        def countdown():
            time_left = WAITING_TIME
            while time_left > 0 and self.status == 'counting':
                time.sleep(1)
                elapsed = time.time() - self.start_time
                time_left = max(0, WAITING_TIME - elapsed)
                
                # Обновляем информацию о комнате
                self.broadcast_room_update(int(time_left))
                
                # Если комната заполнилась, начинаем игру
                if len(self.players) >= MAX_PLAYERS_PER_ROOM:
                    break
                    
                if time_left <= 0:
                    break
            
            # Если все еще в режиме ожидания, начинаем игру
            if self.status == 'counting':
                self.start_game()
        
        self.waiting_timer = threading.Thread(target=countdown)
        self.waiting_timer.daemon = True
        self.waiting_timer.start()
        print(f"Таймер ожидания запущен для комнаты {self.room_id}")

    def start_game(self):
        """Начинает игру"""
        if self.status == 'playing':
            return
            
        self.status = 'playing'
        self.game_start_time = time.time()
        
        print(f"Начинаем игру в комнате {self.room_id} с {len(self.players)} игроками")
        
        # Добавляем ботов, если нужно
        players_count = len(self.players)
        if players_count < MAX_PLAYERS_PER_ROOM:
            bots_needed = MAX_PLAYERS_PER_ROOM - players_count
            print(f"Добавляем {bots_needed} ботов")
            for _ in range(bots_needed):
                self.add_bot()
        
        # Обновляем состояние игры
        self.game_state['game_time'] = GAME_DURATION
        self.game_state['status'] = 'playing'
        self.game_state['start_time'] = self.game_start_time
        
        # Отправляем начало игры всем игрокам
        socketio.emit('game_start', {
            'game_state': self.game_state,
            'message': 'Игра начинается!'
        }, room=self.room_id)
        
        # Запускаем игровой цикл
        self.start_game_loop()

    def start_game_loop(self):
        """Запускает основной игровой цикл"""
        def game_loop():
            last_update_time = time.time()
            
            while self.status == 'playing':
                current_time = time.time()
                delta_time = current_time - last_update_time
                last_update_time = current_time
                
                # Обновляем игровое время
                elapsed_game_time = current_time - self.game_start_time
                remaining_time = max(0, GAME_DURATION - elapsed_game_time)
                self.game_state['game_time'] = remaining_time
                
                # Обновляем ботов
                self.update_bots(delta_time)
                
                # Проверяем сбор предметов (упрощенная версия)
                self.check_item_collection()
                
                # Отправляем обновление состояния
                self.broadcast_game_state()
                
                # Проверяем завершение игры
                if remaining_time <= 0:
                    self.end_game()
                    break
                
                # Ограничиваем FPS
                time.sleep(0.033)  # ~30 FPS
        
        self.game_timer = threading.Thread(target=game_loop)
        self.game_timer.daemon = True
        self.game_timer.start()
        print(f"Игровой цикл запущен для комнаты {self.room_id}")

    def update_bots(self, delta_time):
        """Обновляет позиции ботов"""
        for bot_id in self.bots:
            if bot_id in self.game_state['players']:
                bot = self.game_state['players'][bot_id]
                
                # Случайно меняем направление
                if time.time() - bot['direction_change_time'] > random.uniform(2, 5):
                    bot['move_direction'] = [random.uniform(-1, 1), random.uniform(-1, 1)]
                    length = math.sqrt(bot['move_direction'][0]**2 + bot['move_direction'][1]**2)
                    if length > 0:
                        bot['move_direction'][0] /= length
                        bot['move_direction'][1] /= length
                    bot['direction_change_time'] = time.time()
                
                # Двигаем бота
                speed = 80 * delta_time
                new_x = bot['position'][0] + bot['move_direction'][0] * speed
                new_y = bot['position'][1] + bot['move_direction'][1] * speed
                
                # Ограничиваем движение в пределах поля
                bot['position'][0] = max(30, min(770, new_x))
                bot['position'][1] = max(30, min(570, new_y))

    def check_item_collection(self):
        """Проверяет сбор предметов игроками (упрощенная версия)"""
        # В реальной игре здесь была бы проверка столкновений с предметами
        # Сейчас просто случайно начисляем очки
        for player_id, player in self.game_state['players'].items():
            if random.random() < 0.02:  # 2% шанс получить очко
                player['score'] += 1

    def end_game(self):
        """Завершает игру и определяет победителя"""
        self.status = 'finished'
        self.game_state['status'] = 'finished'
        
        print(f"Игра завершена в комнате {self.room_id}")
        
        # Определяем победителя
        winner = None
        max_score = -1
        
        for player in self.game_state['players'].values():
            if player['score'] > max_score:
                max_score = player['score']
                winner = player
        
        # Подготавливаем результаты
        results = {
            'winner_name': winner['name'] if winner else 'Никто',
            'winner_score': max_score,
            'players': self.game_state['players']
        }
        
        # Отправляем результаты
        socketio.emit('game_over', results, room=self.room_id)
        
        # Очищаем комнату через несколько секунд
        def cleanup():
            time.sleep(5)
            if self.room_id in rooms:
                # Отправляем игроков в меню
                for player_id in self.players:
                    socketio.emit('redirect_to_menu', room=player_id)
                del rooms[self.room_id]
                print(f"Комната {self.room_id} очищена")
        
        threading.Thread(target=cleanup, daemon=True).start()

    def broadcast_room_update(self, time_left=None):
        """Отправляет обновление информации о комнате"""
        if time_left is None:
            time_left = max(0, WAITING_TIME - (time.time() - self.start_time))
        
        room_info = {
            'players_count': len(self.players),
            'max_players': MAX_PLAYERS_PER_ROOM,
            'time_left': int(time_left),
            'room_id': self.room_id
        }
        
        # Добавляем сообщение о добавлении ботов при необходимости
        if time_left <= 0 and len(self.players) < MAX_PLAYERS_PER_ROOM:
            bots_needed = MAX_PLAYERS_PER_ROOM - len(self.players)
            room_info['message'] = f'Добавляем {bots_needed} ботов...'
        
        socketio.emit('room_update', room_info, room=self.room_id)

    def broadcast_game_state(self):
        """Отправляет текущее состояние игры"""
        socketio.emit('game_state', self.game_state, room=self.room_id)

    def update_player_position(self, player_id, dx, dy):
        """Обновляет позицию игрока"""
        if (player_id in self.game_state['players'] and 
            not self.game_state['players'][player_id]['is_bot'] and
            self.status == 'playing'):
            
            player = self.game_state['players'][player_id]
            speed = 5
            
            # Обновляем позицию
            new_x = player['position'][0] + dx * speed
            new_y = player['position'][1] + dy * speed
            
            # Ограничиваем движение в пределах поля
            player['position'][0] = max(30, min(770, new_x))
            player['position'][1] = max(30, min(570, new_y))
            player['last_move'] = time.time()

    def get_random_color(self):
        """Генерирует случайный цвет"""
        return f"#{random.randint(0, 0xFFFFFF):06x}"

def find_available_room():
    """Находит доступную комнату или создает новую"""
    for room_id, room in rooms.items():
        if room.status in ['waiting', 'counting'] and len(room.players) < MAX_PLAYERS_PER_ROOM:
            return room
    
    # Создаем новую комнату
    room_id = f"room_{len(rooms) + 1}_{int(time.time())}"
    new_room = GameRoom(room_id)
    rooms[room_id] = new_room
    print(f"Создана новая комната: {room_id}")
    
    return new_room

# Обработчики WebSocket событий
@socketio.on('connect')
def handle_connect():
    print(f"Клиент подключился: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    player_id = request.sid
    print(f"Клиент отключился: {player_id}")
    
    if player_id in player_rooms:
        room_id = player_rooms[player_id]
        if room_id in rooms:
            rooms[room_id].remove_player(player_id)

@socketio.on('join_game')
def handle_join_game(data):
    """Обработчик запроса на присоединение к игре"""
    player_id = request.sid
    player_name = data.get('name', 'Игрок').strip()
    
    if not player_name:
        player_name = 'Игрок'
    
    print(f"Игрок {player_name} ({player_id}) хочет присоединиться к игре")
    
    # Проверяем, не находится ли игрок уже в комнате
    if player_id in player_rooms:
        emit('error', {'message': 'Вы уже в игре'})
        return
    
    # Находим или создаем комнату
    room = find_available_room()
    
    # Добавляем игрока в комнату
    if room.add_player(player_id, player_name):
        join_room(room.room_id)
        emit('join_success', {
            'room_id': room.room_id,
            'player_id': player_id
        })
        print(f"Игрок {player_name} успешно добавлен в комнату {room.room_id}")
    else:
        emit('error', {'message': 'Не удалось присоединиться к игре'})

@socketio.on('leave_room')
def handle_leave_room():
    """Обработчик выхода из комнаты"""
    player_id = request.sid
    
    if player_id in player_rooms:
        room_id = player_rooms[player_id]
        if room_id in rooms:
            leave_room(room_id)
            rooms[room_id].remove_player(player_id)
            emit('leave_success')
            print(f"Игрок {player_id} покинул комнату {room_id}")

@socketio.on('player_move')
def handle_player_move(data):
    """Обработчик движения игрока"""
    player_id = request.sid
    
    if player_id in player_rooms:
        room_id = player_rooms[player_id]
        if room_id in rooms:
            dx = data.get('dx', 0)
            dy = data.get('dy', 0)
            rooms[room_id].update_player_position(player_id, dx, dy)

# HTTP endpoints для мониторинга
@app.route('/')
def index():
    return {
        'status': 'Server is running',
        'timestamp': datetime.now().isoformat(),
        'active_rooms': len(rooms),
        'active_players': len(players),
        'total_connections': len(player_rooms)
    }

@app.route('/status')
def status():
    """Статус сервера с детальной информацией о комнатах"""
    room_info = []
    for room_id, room in rooms.items():
        room_info.append({
            'room_id': room_id,
            'status': room.status,
            'players': len(room.players),
            'bots': len(room.bots),
            'total_in_game': len(room.game_state['players'])
        })
    
    return {
        'server_time': datetime.now().isoformat(),
        'rooms': room_info,
        'total_players': len(players),
        'total_rooms': len(rooms)
    }

if __name__ == '__main__':
    print("=" * 50)
    print("Запуск игрового сервера")
    print(f"Ожидание на порту: 3000")
    print(f"Максимум игроков в комнате: {MAX_PLAYERS_PER_ROOM}")
    print(f"Время ожидания: {WAITING_TIME} секунд")
    print(f"Длительность игры: {GAME_DURATION} секунд")
    print("=" * 50)
    
    socketio.run(app, host='0.0.0.0', port=3000, debug=False)
