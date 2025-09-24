from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import time
import threading
from datetime import datetime, timedelta
import math

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
games = {}

class GameRoom:
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = []
        self.bots = []
        self.status = 'waiting'  # waiting, counting, playing, finished
        self.start_time = None
        self.waiting_timer = None
        self.game_timer = None
        self.game_state = {
            'players': {},
            'game_time': GAME_DURATION,
            'status': 'waiting'
        }

    def add_player(self, player_id, player_name):
        if len(self.players) >= MAX_PLAYERS_PER_ROOM:
            return False
        
        player_data = {
            'id': player_id,
            'name': player_name,
            'position': [random.randint(100, 700), random.randint(100, 500)],
            'color': self.get_random_color(),
            'score': 0,
            'is_bot': False,
            'last_move': time.time()
        }
        
        self.players.append(player_id)
        self.game_state['players'][player_id] = player_data
        players[player_id] = {'room': self.room_id, 'data': player_data}
        
        # Обновляем информацию о комнате для всех игроков
        self.broadcast_room_update()
        
        # Запускаем таймер, если это первый игрок
        if len(self.players) == 1:
            self.start_waiting_timer()
        
        # Если комната заполнена, начинаем игру
        if len(self.players) >= MAX_PLAYERS_PER_ROOM:
            self.start_game()
            
        return True

    def remove_player(self, player_id):
        if player_id in self.players:
            self.players.remove(player_id)
            if player_id in self.game_state['players']:
                del self.game_state['players'][player_id]
            if player_id in players:
                del players[player_id]
            
            # Если игроков не осталось, удаляем комнату
            if len(self.players) == 0 and len(self.bots) == 0:
                if self.waiting_timer:
                    self.waiting_timer.cancel()
                if self.game_timer:
                    self.game_timer.cancel()
                if self.room_id in rooms:
                    del rooms[self.room_id]
                if self.room_id in games:
                    del games[self.room_id]
            else:
                self.broadcast_room_update()
                
                # Если игра идет, продолжаем
                if self.status == 'playing':
                    self.broadcast_game_state()

    def add_bot(self):
        if len(self.game_state['players']) >= MAX_PLAYERS_PER_ROOM:
            return False
        
        bot_id = f"bot_{len(self.bots) + 1}"
        bot_data = {
            'id': bot_id,
            'name': f"Бот_{len(self.bots) + 1}",
            'position': [random.randint(100, 700), random.randint(100, 500)],
            'color': self.get_random_color(),
            'score': 0,
            'is_bot': True,
            'last_move': time.time(),
            'move_direction': [0, 0],
            'direction_change_time': time.time()
        }
        
        self.bots.append(bot_id)
        self.game_state['players'][bot_id] = bot_data
        
        return True

    def start_waiting_timer(self):
        self.status = 'counting'
        self.start_time = time.time()
        
        def countdown():
            time_left = WAITING_TIME
            while time_left > 0 and self.status == 'counting':
                time.sleep(1)
                time_left -= 1
                
                # Отправляем обновление всем игрокам в комнате
                self.broadcast_room_update(time_left)
                
                # Если комната заполнилась, прерываем ожидание
                if len(self.players) >= MAX_PLAYERS_PER_ROOM:
                    break
            
            # По истечении времени начинаем игру
            if self.status == 'counting':
                self.start_game()
        
        self.waiting_timer = threading.Thread(target=countdown)
        self.waiting_timer.daemon = True
        self.waiting_timer.start()

    def start_game(self):
        self.status = 'playing'
        
        # Добавляем ботов, если нужно
        players_count = len(self.players)
        if players_count < MAX_PLAYERS_PER_ROOM:
            bots_needed = MAX_PLAYERS_PER_ROOM - players_count
            for _ in range(bots_needed):
                self.add_bot()
        
        # Обновляем начальное состояние игры
        self.game_state['game_time'] = GAME_DURATION
        self.game_state['status'] = 'playing'
        
        # Уведомляем всех игроков о начале игры
        socketio.emit('game_start', self.game_state, room=self.room_id)
        
        # Запускаем игровой цикл
        self.start_game_loop()

    def start_game_loop(self):
        def game_loop():
            last_update = time.time()
            
            while self.status == 'playing' and self.game_state['game_time'] > 0:
                current_time = time.time()
                delta_time = current_time - last_update
                last_update = current_time
                
                # Обновляем время игры
                self.game_state['game_time'] -= delta_time
                
                # Обновляем позиции ботов
                self.update_bots(delta_time)
                
                # Проверяем столкновения и собираемые предметы
                self.check_collisions()
                
                # Отправляем обновление состояния игры
                self.broadcast_game_state()
                
                # Проверяем завершение игры
                if self.game_state['game_time'] <= 0:
                    self.end_game()
                    break
                
                time.sleep(0.016)  # ~60 FPS
        
        self.game_timer = threading.Thread(target=game_loop)
        self.game_timer.daemon = True
        self.game_timer.start()

    def update_bots(self, delta_time):
        for bot_id in self.bots:
            if bot_id in self.game_state['players']:
                bot = self.game_state['players'][bot_id]
                
                # Меняем направление каждые 2-5 секунд
                if time.time() - bot['direction_change_time'] > random.uniform(2, 5):
                    bot['move_direction'] = [
                        random.uniform(-1, 1),
                        random.uniform(-1, 1)
                    ]
                    # Нормализуем направление
                    length = math.sqrt(bot['move_direction'][0]**2 + bot['move_direction'][1]**2)
                    if length > 0:
                        bot['move_direction'][0] /= length
                        bot['move_direction'][1] /= length
                    
                    bot['direction_change_time'] = time.time()
                
                # Двигаем бота
                speed = 100 * delta_time  # скорость в пикселях в секунду
                bot['position'][0] += bot['move_direction'][0] * speed
                bot['position'][1] += bot['move_direction'][1] * speed
                
                # Ограничиваем позицию в пределах поля
                bot['position'][0] = max(0, min(800, bot['position'][0]))
                bot['position'][1] = max(0, min(600, bot['position'][1]))

    def check_collisions(self):
        # В этой версии просто добавляем случайные очки за "сбор предметов"
        # В реальной игре здесь была бы логика столкновений с объектами
        for player_id, player in self.game_state['players'].items():
            # Случайное увеличение счета (имитация сбора предметов)
            if random.random() < 0.01:  # 1% шанс каждое обновление
                player['score'] += 1

    def end_game(self):
        self.status = 'finished'
        self.game_state['status'] = 'finished'
        
        # Определяем победителя
        winner = max(self.game_state['players'].values(), key=lambda x: x['score'])
        
        # Отправляем результаты игры
        results = {
            'winner': winner['name'],
            'winner_score': winner['score'],
            'players': self.game_state['players']
        }
        
        socketio.emit('game_over', results, room=self.room_id)
        
        # Через 5 секунд очищаем комнату
        def cleanup():
            time.sleep(5)
            for player_id in self.players.copy():
                if player_id in players:
                    # Отключаем игрока
                    socketio.emit('redirect_to_menu', room=player_id)
            
            # Очищаем данные
            if self.room_id in rooms:
                del rooms[self.room_id]
            if self.room_id in games:
                del games[self.room_id]
        
        threading.Thread(target=cleanup).start()

    def broadcast_room_update(self, time_left=None):
        if time_left is None:
            time_left = max(0, WAITING_TIME - (time.time() - self.start_time))
        
        room_info = {
            'players_count': len(self.players),
            'max_players': MAX_PLAYERS_PER_ROOM,
            'time_left': int(time_left)
        }
        
        socketio.emit('room_update', room_info, room=self.room_id)

    def broadcast_game_state(self):
        socketio.emit('game_state', self.game_state, room=self.room_id)

    def get_random_color(self):
        return f"#{random.randint(0, 0xFFFFFF):06x}"

    def update_player_position(self, player_id, dx, dy):
        if player_id in self.game_state['players'] and not self.game_state['players'][player_id]['is_bot']:
            player = self.game_state['players'][player_id]
            
            # Обновляем позицию
            speed = 5
            player['position'][0] = max(0, min(800, player['position'][0] + dx * speed))
            player['position'][1] = max(0, min(600, player['position'][1] + dy * speed))
            player['last_move'] = time.time()

def get_available_room():
    # Ищем комнату с ожидающими игроками
    for room_id, room in rooms.items():
        if room.status == 'waiting' or room.status == 'counting':
            if len(room.players) < MAX_PLAYERS_PER_ROOM:
                return room
    
    # Создаем новую комнату
    room_id = f"room_{len(rooms) + 1}"
    new_room = GameRoom(room_id)
    rooms[room_id] = new_room
    games[room_id] = new_room.game_state
    
    return new_room

# Обработчики SocketIO
@socketio.on('connect')
def handle_connect():
    print(f"Клиент подключился: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    player_id = request.sid
    print(f"Клиент отключился: {player_id}")
    
    if player_id in players:
        room_id = players[player_id]['room']
        if room_id in rooms:
            rooms[room_id].remove_player(player_id)

@socketio.on('join_game')
def handle_join_game(data):
    player_id = request.sid
    player_name = data.get('name', 'Игрок')
    
    print(f"Игрок {player_name} ({player_id}) пытается присоединиться к игре")
    
    # Находим или создаем комнату
    room = get_available_room()
    
    # Добавляем игрока в комнату
    if room.add_player(player_id, player_name):
        join_room(room.room_id)
        emit('join_success', {'room_id': room.room_id})
        print(f"Игрок {player_name} добавлен в комнату {room.room_id}")
    else:
        emit('join_error', {'message': 'Комната заполнена'})

@socketio.on('leave_room')
def handle_leave_room():
    player_id = request.sid
    
    if player_id in players:
        room_id = players[player_id]['room']
        if room_id in rooms:
            leave_room(room_id)
            rooms[room_id].remove_player(player_id)
            emit('leave_success')

@socketio.on('player_move')
def handle_player_move(data):
    player_id = request.sid
    
    if player_id in players:
        room_id = players[player_id]['room']
        if room_id in rooms and rooms[room_id].status == 'playing':
            dx = data.get('dx', 0)
            dy = data.get('dy', 0)
            rooms[room_id].update_player_position(player_id, dx, dy)

@app.route('/')
def index():
    return {
        'status': 'Server is running',
        'active_rooms': len(rooms),
        'active_players': len(players),
        'timestamp': datetime.now().isoformat()
    }

@app.route('/stats')
def stats():
    room_stats = []
    for room_id, room in rooms.items():
        room_stats.append({
            'room_id': room_id,
            'status': room.status,
            'players': len(room.players),
            'bots': len(room.bots)
        })
    
    return {
        'rooms': room_stats,
        'total_players': len(players),
        'total_rooms': len(rooms)
    }

if __name__ == '__main__':
    print("Запуск игрового сервера на http://localhost:3000")
    socketio.run(app, host='0.0.0.0', port=3000, debug=True)
