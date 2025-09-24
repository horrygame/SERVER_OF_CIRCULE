from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import time
import threading
from datetime import datetime
import eventlet
eventlet.monkey_patch()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*")

# Хранилище данных
rooms = {}
players = {}
bot_counter = 1000

class GameRoom:
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = {}
        self.bots = {}
        self.status = "waiting"  # waiting, counting, playing, finished
        self.countdown_start = None
        self.game_start = None
        self.max_players = 6
        self.countdown_duration = 30
        self.game_duration = 150  # 2.5 minutes
        self.map_size = (800, 600)
        
    def add_player(self, player_id, player_data):
        if len(self.players) >= self.max_players:
            return False, "Room is full"
            
        self.players[player_id] = player_data
        return True, "Player added"
    
    def start_countdown(self):
        self.status = "counting"
        self.countdown_start = datetime.now()
        
        # Запускаем таймер поиска игроков
        timer = threading.Timer(self.countdown_duration, self.start_game)
        timer.daemon = True
        timer.start()
    
    def start_game(self):
        # Добавляем ботов, если нужно
        needed_bots = self.max_players - len(self.players)
        for i in range(needed_bots):
            self.add_bot()
            
        self.status = "playing"
        self.game_start = datetime.now()
        
        # Запускаем таймер окончания игры
        timer = threading.Timer(self.game_duration, self.end_game)
        timer.daemon = True
        timer.start()
        
        # Уведомляем всех игроков о начале игры
        socketio.emit('game_started', {
            'players': {**self.players, **self.bots},
            'game_duration': self.game_duration
        }, room=self.room_id)
    
    def end_game(self):
        self.status = "finished"
        
        # Определяем победителя (простая реализация)
        all_players = {**self.players, **self.bots}
        winner = random.choice(list(all_players.values())) if all_players else None
        
        socketio.emit('game_ended', {
            'winner': winner,
            'players': all_players
        }, room=self.room_id)
        
        # Через 5 секунд удаляем комнату
        timer = threading.Timer(5.0, self.cleanup)
        timer.daemon = True
        timer.start()
    
    def cleanup(self):
        if self.room_id in rooms:
            del rooms[self.room_id]
    
    def add_bot(self):
        global bot_counter
        bot_id = f"bot_{bot_counter}"
        bot_counter += 1
        
        self.bots[bot_id] = {
            'id': bot_id,
            'name': f"Bot_{bot_counter-1000}",
            'position': [random.randint(50, self.map_size[0]-50), 
                        random.randint(50, self.map_size[1]-50)],
            'color': f"#{random.randint(0, 255):02x}{random.randint(0, 255):02x}{random.randint(0, 255):02x}",
            'score': 0,
            'is_bot': True
        }
    
    def update_player_position(self, player_id, x, y):
        if player_id in self.players:
            self.players[player_id]['position'] = [x, y]
    
    def move_bots(self):
        # Простой ИИ для ботов - случайное движение
        for bot_id, bot in self.bots.items():
            if random.random() < 0.02:  # 2% chance to move
                direction = random.choice(['up', 'down', 'left', 'right'])
                speed = 3
                
                if direction == 'up':
                    bot['position'][1] = max(0, bot['position'][1] - speed)
                elif direction == 'down':
                    bot['position'][1] = min(self.map_size[1], bot['position'][1] + speed)
                elif direction == 'left':
                    bot['position'][0] = max(0, bot['position'][0] - speed)
                elif direction == 'right':
                    bot['position'][0] = min(self.map_size[0], bot['position'][0] + speed)

# Обработчики SocketIO
@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")

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
    print(f"Client disconnected: {request.sid}")

@socketio.on('join_game')
def handle_join_game(data):
    player_id = request.sid
    player_name = data.get('name', 'Player')
    
    # Ищем доступную комнату или создаем новую
    room = None
    for r in rooms.values():
        if r.status in ['waiting', 'counting'] and len(r.players) < r.max_players:
            room = r
            break
    
    if not room:
        room_id = f"room_{len(rooms) + 1}"
        room = GameRoom(room_id)
        rooms[room_id] = room
    
    # Добавляем игрока в комнату
    player_data = {
        'id': player_id,
        'name': player_name,
        'position': [random.randint(50, room.map_size[0]-50), 
                    random.randint(50, room.map_size[1]-50)],
        'color': f"#{random.randint(0, 255):02x}{random.randint(0, 255):02x}{random.randint(0, 255):02x}",
        'score': 0,
        'is_bot': False,
        'room_id': room.room_id
    }
    
    success, message = room.add_player(player_id, player_data)
    
    if success:
        players[player_id] = player_data
        join_room(room.room_id)
        
        # Если это первый игрок, начинаем отсчет
        if len(room.players) == 1:
            room.start_countdown()
        
        # Уведомляем игрока
        emit('joined_room', {
            'room_id': room.room_id,
            'players': room.players,
            'status': room.status,
            'countdown': room.countdown_duration
        })
        
        # Уведомляем всех в комнате
        emit('player_joined', {
            'player_id': player_id,
            'player_name': player_name,
            'players_count': len(room.players),
            'max_players': room.max_players
        }, room=room.room_id)
    else:
        emit('error', {'message': message})

@socketio.on('player_move')
def handle_player_move(data):
    player_id = request.sid
    if player_id in players:
        room_id = players[player_id]['room_id']
        if room_id in rooms:
            room = rooms[room_id]
            if room.status == "playing":
                x = data.get('x', players[player_id]['position'][0])
                y = data.get('y', players[player_id]['position'][1])
                
                # Обновляем позицию
                room.update_player_position(player_id, x, y)
                players[player_id]['position'] = [x, y]
                
                # Отправляем обновление всем
                emit('player_moved', {
                    'player_id': player_id,
                    'position': [x, y]
                }, room=room_id)

# Функция для обновления состояния игры
def game_loop():
    while True:
        for room_id, room in rooms.items():
            if room.status == "playing":
                # Двигаем ботов
                room.move_bots()
                
                # Отправляем обновление состояния игры
                time_elapsed = (datetime.now() - room.game_start).total_seconds()
                time_left = max(0, room.game_duration - time_elapsed)
                
                socketio.emit('game_state', {
                    'players': {**room.players, **room.bots},
                    'time_left': time_left
                }, room=room_id)
        
        time.sleep(0.05)  # 20 updates per second

# Запускаем игровой цикл в отдельном потоке
threading.Thread(target=game_loop, daemon=True).start()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
