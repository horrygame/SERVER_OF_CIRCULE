from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
import random
import time
import threading
import math
from datetime import datetime
import os
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')

# Настройка CORS для Render
CORS(app, origins=[
    "http://localhost:3000",
    "https://your-frontend-domain.onrender.com",  # Замените на ваш фронтенд URL
    "*"  # Для разработки, в продакшене укажите конкретные домены
])

socketio = SocketIO(app, 
                   cors_allowed_origins="*",
                   async_mode='eventlet',
                   ping_timeout=60,
                   ping_interval=25,
                   logger=True,
                   engineio_logger=True)

# Конфигурация игры
MAX_PLAYERS_PER_ROOM = 6
WAITING_TIME = 30  # секунды
GAME_DURATION = 150  # 2.5 минуты

# Хранилище данных
rooms = {}
players = {}
player_rooms = {}

class GameRoom:
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = []
        self.bots = []
        self.status = 'waiting'
        self.creation_time = time.time()
        self.start_time = None
        self.waiting_timer = None
        self.game_timer = None
        self.game_start_time = None
        self.last_broadcast_time = 0
        self.broadcast_interval = 0.033  # ~30 FPS
        
        self.game_state = {
            'players': {},
            'game_time': GAME_DURATION,
            'status': 'waiting',
            'room_id': room_id
        }

    def add_player(self, player_id, player_name):
        if len(self.players) >= MAX_PLAYERS_PER_ROOM:
            return False, "Комната заполнена"
        
        if player_id in self.players:
            return False, "Игрок уже в комнате"
        
        player_data = {
            'id': player_id,
            'name': player_name,
            'position': [random.randint(100, 700), random.randint(100, 500)],
            'color': self.get_random_color(),
            'score': 0,
            'is_bot': False,
            'last_move': time.time(),
            'room_id': self.room_id
        }
        
        self.players.append(player_id)
        self.game_state['players'][player_id] = player_data
        players[player_id] = player_data
        player_rooms[player_id] = self.room_id
        
        logger.info(f"Игрок {player_name} добавлен в комнату {self.room_id}. Теперь игроков: {len(self.players)}")
        
        # Если это первый игрок, запускаем таймер ожидания
        if len(self.players) == 1 and self.status == 'waiting':
            self.status = 'counting'
            self.start_time = time.time()
            self.start_waiting_timer()
        
        # Отправляем обновление состояния комнаты
        self.broadcast_room_update()
        
        # Если комната заполнена, начинаем игру сразу
        if len(self.players) >= MAX_PLAYERS_PER_ROOM and self.status == 'counting':
            logger.info("Комната заполнена, начинаем игру сразу")
            self.start_game()
            
        return True, "Успешно присоединен"

    def remove_player(self, player_id):
        if player_id in self.players:
            self.players.remove(player_id)
            
        if player_id in self.game_state['players']:
            del self.game_state['players'][player_id]
            
        if player_id in players:
            del players[player_id]
            
        if player_id in player_rooms:
            del player_rooms[player_id]
        
        logger.info(f"Игрок {player_id} удален из комнаты {self.room_id}. Осталось игроков: {len(self.players)}")
        
        # Если комната пустая, удаляем ее
        if len(self.players) == 0 and len(self.bots) == 0:
            if self.waiting_timer and self.status == 'counting':
                self.waiting_timer.cancel()
            if self.room_id in rooms:
                del rooms[self.room_id]
                logger.info(f"Комната {self.room_id} удалена")
        else:
            # Обновляем оставшихся игроков
            self.broadcast_room_update()

    def add_bot(self):
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
            'direction_change_time': time.time(),
            'room_id': self.room_id
        }
        
        # Нормализуем направление
        dx, dy = bot_data['move_direction']
        length = math.sqrt(dx**2 + dy**2)
        if length > 0:
            bot_data['move_direction'] = [dx/length, dy/length]
        
        self.bots.append(bot_id)
        self.game_state['players'][bot_id] = bot_data
        
        logger.info(f"Бот {bot_id} добавлен в комнату {self.room_id}")
        return True

    def start_waiting_timer(self):
        def countdown():
            try:
                start_time = time.time()
                time_left = WAITING_TIME
                
                while time_left > 0 and self.status == 'counting':
                    time.sleep(1)
                    elapsed = time.time() - start_time
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
            except Exception as e:
                logger.error(f"Ошибка в таймере ожидания: {e}")
        
        self.waiting_timer = threading.Thread(target=countdown)
        self.waiting_timer.daemon = True
        self.waiting_timer.start()
        logger.info(f"Таймер ожидания запущен для комнаты {self.room_id}")

    def start_game(self):
        if self.status == 'playing':
            return
            
        self.status = 'playing'
        self.game_start_time = time.time()
        
        logger.info(f"Начинаем игру в комнате {self.room_id} с {len(self.players)} игроками")
        
        # Добавляем ботов, если нужно
        players_count = len(self.players)
        if players_count < MAX_PLAYERS_PER_ROOM:
            bots_needed = MAX_PLAYERS_PER_ROOM - players_count
            logger.info(f"Добавляем {bots_needed} ботов")
            for _ in range(bots_needed):
                self.add_bot()
        
        # Обновляем состояние игры
        self.game_state['game_time'] = GAME_DURATION
        self.game_state['status'] = 'playing'
        self.game_state['start_time'] = self.game_start_time
        
        # Отправляем начало игры всем игрокам
        socketio.emit('game_start', {
            'game_state': self.game_state,
            'message': 'Игра начинается!',
            'room_id': self.room_id
        }, room=self.room_id)
        
        # Запускаем игровой цикл
        self.start_game_loop()

    def start_game_loop(self):
        def game_loop():
            try:
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
                    
                    # Проверяем сбор предметов
                    self.check_item_collection()
                    
                    # Отправляем обновление состояния (ограничиваем частоту)
                    if current_time - self.last_broadcast_time >= self.broadcast_interval:
                        self.broadcast_game_state()
                        self.last_broadcast_time = current_time
                    
                    # Проверяем завершение игры
                    if remaining_time <= 0:
                        self.end_game()
                        break
                    
                    # Ограничиваем FPS
                    time.sleep(0.016)  # ~60 FPS
                    
            except Exception as e:
                logger.error(f"Ошибка в игровом цикле: {e}")
        
        self.game_timer = threading.Thread(target=game_loop)
        self.game_timer.daemon = True
        self.game_timer.start()
        logger.info(f"Игровой цикл запущен для комнаты {self.room_id}")

    def update_bots(self, delta_time):
        for bot_id in self.bots:
            if bot_id in self.game_state['players']:
                bot = self.game_state['players'][bot_id]
                
                # Случайно меняем направление
                if time.time() - bot['direction_change_time'] > random.uniform(2, 5):
                    dx, dy = random.uniform(-1, 1), random.uniform(-1, 1)
                    length = math.sqrt(dx**2 + dy**2)
                    if length > 0:
                        bot['move_direction'] = [dx/length, dy/length]
                    bot['direction_change_time'] = time.time()
                
                # Двигаем бота
                speed = 80 * delta_time
                dx, dy = bot['move_direction']
                new_x = bot['position'][0] + dx * speed
                new_y = bot['position'][1] + dy * speed
                
                # Ограничиваем движение в пределах поля
                bot['position'][0] = max(30, min(770, new_x))
                bot['position'][1] = max(30, min(570, new_y))

    def check_item_collection(self):
        """Упрощенная система сбора очков"""
        for player_id, player in self.game_state['players'].items():
            # Случайное начисление очков (имитация сбора предметов)
            if random.random() < 0.02:  # 2% шанс
                player['score'] += 1

    def end_game(self):
        self.status = 'finished'
        self.game_state['status'] = 'finished'
        
        logger.info(f"Игра завершена в комнате {self.room_id}")
        
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
            'players': self.game_state['players'],
            'room_id': self.room_id
        }
        
        # Отправляем результаты
        socketio.emit('game_over', results, room=self.room_id)
        
        # Очищаем комнату через несколько секунд
        def cleanup():
            time.sleep(5)
            if self.room_id in rooms:
                # Отправляем игроков в меню
                for player_id in self.players:
                    try:
                        socketio.emit('redirect_to_menu', {'room_id': self.room_id}, room=player_id)
                    except Exception as e:
                        logger.error(f"Ошибка отправки redirect_to_menu: {e}")
                del rooms[self.room_id]
                logger.info(f"Комната {self.room_id} очищена")
        
        threading.Thread(target=cleanup, daemon=True).start()

    def broadcast_room_update(self, time_left=None):
        """Отправляет обновление информации о комнате"""
        if time_left is None:
            time_left = max(0, WAITING_TIME - (time.time() - self.start_time))
        
        room_info = {
            'players_count': len(self.players),
            'max_players': MAX_PLAYERS_PER_ROOM,
            'time_left': int(time_left),
            'room_id': self.room_id,
            'status': self.status
        }
        
        # Добавляем сообщение о добавлении ботов при необходимости
        if time_left <= 0 and len(self.players) < MAX_PLAYERS_PER_ROOM:
            bots_needed = MAX_PLAYERS_PER_ROOM - len(self.players)
            room_info['message'] = f'Добавляем {bots_needed} ботов...'
        
        socketio.emit('room_update', room_info, room=self.room_id)

    def broadcast_game_state(self):
        """Отправляет текущее состояние игры"""
        try:
            socketio.emit('game_state', self.game_state, room=self.room_id)
        except Exception as e:
            logger.error(f"Ошибка отправки game_state: {e}")

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
    logger.info(f"Создана новая комната: {room_id}")
    
    return new_room

# HTTP endpoints
@app.route('/')
def index():
    """Статус сервера"""
    return jsonify({
        'status': 'Server is running',
        'timestamp': datetime.now().isoformat(),
        'active_rooms': len(rooms),
        'active_players': len(players),
        'version': '1.0.0'
    })

@app.route('/health')
def health():
    """Health check для Render"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.route('/api/status')
def api_status():
    """Детальный статус сервера"""
    room_info = []
    for room_id, room in rooms.items():
        room_info.append({
            'room_id': room_id,
            'status': room.status,
            'players': len(room.players),
            'bots': len(room.bots),
            'game_time': room.game_state.get('game_time', 0)
        })
    
    return jsonify({
        'server_time': datetime.now().isoformat(),
        'rooms': room_info,
        'total_players': len(players),
        'total_rooms': len(rooms),
        'config': {
            'max_players': MAX_PLAYERS_PER_ROOM,
            'waiting_time': WAITING_TIME,
            'game_duration': GAME_DURATION
        }
    })

# WebSocket handlers
@socketio.on('connect')
def handle_connect():
    """Обработчик подключения клиента"""
    logger.info(f"Клиент подключился: {request.sid}")
    emit('connection_established', {
        'player_id': request.sid,
        'message': 'Подключение установлено'
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Обработчик отключения клиента"""
    player_id = request.sid
    logger.info(f"Клиент отключился: {player_id}")
    
    if player_id in player_rooms:
        room_id = player_rooms[player_id]
        if room_id in rooms:
            rooms[room_id].remove_player(player_id)

@socketio.on('join_game')
def handle_join_game(data):
    """Обработчик запроса на присоединение к игре"""
    player_id = request.sid
    
    # Проверяем, не находится ли игрок уже в игре
    if player_id in player_rooms:
        emit('error', {'message': 'Вы уже в игре', 'type': 'join_error'})
        return
    
    player_name = data.get('name', 'Игрок').strip()
    if not player_name:
        player_name = 'Игрок'
    
    logger.info(f"Игрок {player_name} ({player_id}) хочет присоединиться к игре")
    
    # Находим или создаем комнату
    room = find_available_room()
    
    # Добавляем игрока в комнату
    success, message = room.add_player(player_id, player_name)
    
    if success:
        join_room(room.room_id)
        emit('join_success', {
            'room_id': room.room_id,
            'player_id': player_id,
            'message': message
        })
        logger.info(f"Игрок {player_name} успешно добавлен в комнату {room.room_id}")
    else:
        emit('error', {'message': message, 'type': 'join_error'})

@socketio.on('leave_room')
def handle_leave_room():
    """Обработчик выхода из комнаты"""
    player_id = request.sid
    
    if player_id in player_rooms:
        room_id = player_rooms[player_id]
        if room_id in rooms:
            leave_room(room_id)
            rooms[room_id].remove_player(player_id)
            emit('leave_success', {'room_id': room_id})
            logger.info(f"Игрок {player_id} покинул комнату {room_id}")
    else:
        emit('error', {'message': 'Вы не в комнате', 'type': 'leave_error'})

@socketio.on('player_move')
def handle_player_move(data):
    """Обработчик движения игрока"""
    player_id = request.sid
    
    if player_id in player_rooms:
        room_id = player_rooms[player_id]
        if room_id in rooms and rooms[room_id].status == 'playing':
            dx = data.get('dx', 0)
            dy = data.get('dy', 0)
            rooms[room_id].update_player_position(player_id, dx, dy)
            # Подтверждаем получение движения
            emit('move_acknowledged', {'received': True}, room=player_id)

@socketio.on('ping')
def handle_ping():
    """Обработчик ping для проверки соединения"""
    emit('pong', {'timestamp': time.time()})

# Обработка ошибок
@socketio.on_error_default
def default_error_handler(e):
    """Обработчик ошибок по умолчанию"""
    logger.error(f"Ошибка WebSocket: {e}")
    emit('error', {'message': 'Внутренняя ошибка сервера', 'type': 'server_error'})

if __name__ == '__main__':
    # Конфигурация для Render
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    
    logger.info("=" * 50)
    logger.info("Запуск игрового сервера")
    logger.info(f"Хост: {host}")
    logger.info(f"Порт: {port}")
    logger.info(f"Максимум игроков в комнате: {MAX_PLAYERS_PER_ROOM}")
    logger.info(f"Время ожидания: {WAITING_TIME} секунд")
    logger.info(f"Длительность игры: {GAME_DURATION} секунд")
    logger.info("=" * 50)
    
    # Запуск сервера
    socketio.run(app, host=host, port=port, debug=False)
