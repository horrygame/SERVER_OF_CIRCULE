import os
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import time
import threading
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Хранилище данных
rooms = {}
players = {}
bot_counter = 1000

class GameRoom:
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = {}
        self.bots = {}
        self.status = "waiting"
        self.countdown_start = None
        self.game_start = None
        self.max_players = 6
        self.countdown_duration = 30
        self.game_duration = 150
        self.map_size = (800, 600)
        
    def add_player(self, player_id, player_data):
        if len(self.players) >= self.max_players:
            return False, "Комната заполнена"
            
        self.players[player_id] = player_data
        return True, "Игрок добавлен"
    
    def start_countdown(self):
        self.status = "counting"
        self.countdown_start = datetime.now()
        
        def start_game_wrapper():
            time.sleep(self.countdown_duration)
            self.start_game()
            
        timer = threading.Thread(target=start_game_wrapper)
        timer.daemon = True
        timer.start()
    
    def start_game(self):
        # Добавляем ботов если нужно
        needed_bots = self.max_players - len(self.players)
        for i in range(needed_bots):
            self.add_bot()
            
        self.status = "playing"
        self.game_start = datetime.now()
        
        def end_game_wrapper():
            time.sleep(self.game_duration)
            self.end_game()
            
        timer = threading.Thread(target=end_game_wrapper)
        timer.daemon = True
        timer.start()
        
        # Уведомляем всех о начале игры
        socketio.emit('game_started', {
            'players': {**self.players, **self.bots},
            'game_duration': self.game_duration
        }, room=self.room_id)
    
    def end_game(self):
        self.status = "finished"
        all_players = {**self.players, **self.bots}
        winner = random.choice(list(all_players.values())) if all_players else None
        
        socketio.emit('game_ended', {
            'winner': winner,
            'players': all_players
        }, room=self.room_id)
        
        # Удаляем комнату через 5 секунд
        def cleanup_wrapper():
            time.sleep(5)
            if self.room_id in rooms:
                del rooms[self.room_id]
                
        timer = threading.Thread(target=cleanup_wrapper)
        timer.daemon = True
        timer.start()
    
    def add_bot(self):
        global bot_counter
        bot_id = f"bot_{bot_counter}"
        bot_counter += 1
        
        self.bots[bot_id] = {
            'id': bot_id,
            'name': f"Бот_{bot_counter-1000}",
            'position': [random.randint(50, self.map_size[0]-50), 
                        random.randint(50, self.map_size[1]-50)],
            'color': self.generate_color(),
            'score': 0,
            'is_bot': True
        }
        return True
    
    def update_player_position(self, player_id, x, y):
        if player_id in self.players:
            self.players[player_id]['position'] = [x, y]
    
    def move_bots(self):
        for bot_id, bot in self.bots.items():
            if random.random() < 0.02:
                direction = random.choice(['up', 'down', 'left', 'right'])
                speed = 2
                
                if direction == 'up':
                    bot['position'][1] = max(0, bot['position'][1] - speed)
                elif direction == 'down':
                    bot['position'][1] = min(self.map_size[1], bot['position'][1] + speed)
                elif direction == 'left':
                    bot['position'][0] = max(0, bot['position'][0] - speed)
                elif direction == 'right':
                    bot['position'][0] = min(self.map_size[0], bot['position'][0] + speed)
    
    def generate_color(self):
        return f"#{random.randint(0, 255):02x}{random.randint(0, 255):02x}{random.randint(0, 255):02x}"
    
    def get_countdown(self):
        if self.status != 'counting' or not self.countdown_start:
            return 0
        elapsed = (datetime.now() - self.countdown_start).total_seconds()
        return max(0, self.countdown_duration - elapsed)
    
    def get_game_time(self):
        if self.status != 'playing' or not self.game_start:
            return 0
        elapsed = (datetime.now() - self.game_start).total_seconds()
        return max(0, self.game_duration - elapsed)

# Игровой цикл
def game_loop():
    while True:
        for room_id, room in list(rooms.items()):
            if room.status == "playing":
                room.move_bots()
                
                socketio.emit('game_update', {
                    'players': {**room.players, **room.bots},
                    'time_left': room.get_game_time(),
                    'status': room.status
                }, room=room_id)
        
        time.sleep(0.1)

# Запускаем игровой цикл
game_thread = threading.Thread(target=game_loop)
game_thread.daemon = True
game_thread.start()

# Обработчики SocketIO
@socketio.on('connect')
def handle_connect():
    print(f"Клиент подключился: {request.sid}")
    emit('connected', {'message': 'Подключено к серверу', 'id': request.sid})

@socketio.on('disconnect')
def handle_disconnect():
    player_id = request.sid
    if player_id in players:
        room_id = players[player_id]['room_id']
        if room_id in rooms:
            room = rooms[room_id]
            if player_id in room.players:
                del room.players[player_id]
                emit('player_left', {'player_id': player_id}, room=room_id)
        del players[player_id]
    print(f"Клиент отключился: {request.sid}")

@socketio.on('join_game')
def handle_join_game(data):
    player_id = request.sid
    player_name = data.get('name', 'Игрок')
    
    # Ищем доступную комнату
    room = None
    for r in rooms.values():
        if r.status in ['waiting', 'counting'] and len(r.players) < r.max_players:
            room = r
            break
    
    # Создаем новую комнату если нужно
    if not room:
        room_id = f"room_{len(rooms) + 1}"
        room = GameRoom(room_id)
        rooms[room_id] = room
    
    # Добавляем игрока
    player_data = {
        'id': player_id,
        'name': player_name,
        'position': [random.randint(50, room.map_size[0]-50), 
                    random.randint(50, room.map_size[1]-50)],
        'color': room.generate_color(),
        'score': 0,
        'is_bot': False,
        'room_id': room.room_id
    }
    
    success, message = room.add_player(player_id, player_data)
    
    if success:
        players[player_id] = player_data
        join_room(room.room_id)
        
        # Начинаем отсчет если это первый игрок
        if len(room.players) == 1 and room.status == 'waiting':
            room.start_countdown()
        
        emit('joined_room', {
            'room_id': room.room_id,
            'players_count': len(room.players),
            'countdown': room.countdown_duration,
            'status': room.status
        })
        
        emit('player_joined', {
            'player_id': player_id,
            'player_name': player_name,
            'players_count': len(room.players),
            'countdown': room.get_countdown()
        }, room=room.room_id)
    else:
        emit('error', {'message': message})

@socketio.on('player_move')
def handle_player_move(data):
    player_id = request.sid
    if player_id in players:
        direction = data.get('direction')
        room_id = players[player_id]['room_id']
        
        if room_id in rooms:
            room = rooms[room_id]
            if room.status == "playing":
                player = room.players[player_id]
                speed = 5
                x, y = player['position']
                
                if direction == 'up':
                    y = max(0, y - speed)
                elif direction == 'down':
                    y = min(room.map_size[1], y + speed)
                elif direction == 'left':
                    x = max(0, x - speed)
                elif direction == 'right':
                    x = min(room.map_size[0], x + speed)
                
                room.update_player_position(player_id, x, y)
                players[player_id]['position'] = [x, y]
                
                emit('player_moved', {
                    'player_id': player_id,
                    'position': [x, y],
                    'direction': direction
                }, room=room_id)

@app.route('/')
def index():
    return {'status': 'Server is running', 'active_rooms': len(rooms)}

@app.route('/health')
def health():
    return {'status': 'healthy'}

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    if debug:
        socketio.run(app, host='0.0.0.0', port=port, debug=True)
    else:
        # Для продакшена используем простой запуск
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        application = DispatcherMiddleware(app)
        
        if __name__ == "__main__":
            from werkzeug.serving import run_simple
            run_simple('0.0.0.0', port, application, threaded=True)
