from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import websockets
import json
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI()

# List of active WebSocket connections
active_connections = set()

# Очередь запросов от пользователей
message_queue = asyncio.Queue()

# AI Server WebSocket URL
AI_SERVER_URL = "wss://your-ai-server-url/ws/ai"

# Глобальные переменные статуса
is_processing = False  # AI в процессе обработки?
block_time = 0  # Время блокировки перед следующим запросом

# Сообщения пользователям
WELCOME_MESSAGE = "Mention @ShrokAI, and I’ll respond… probably. If I’m not lost in a mushroom trip."
BUSY_MESSAGE = "Thinking... but the mushrooms have other plans for my brain."
REQUEST_RECEIVED_MESSAGE = "Loud and clear! Now, how about some mushrooms to enhance the conversation?"

async def process_queue():
    """Функция, которая обрабатывает очередь входящих сообщений."""
    global is_processing

    while True:
        message, websocket = await message_queue.get()

        # Если AI уже занят
        if is_processing:
            logger.info("[BUSY] AI уже занят, отправляем заглушку клиенту.")
            try:
                await websocket.send_text(BUSY_MESSAGE)
            except WebSocketDisconnect:
                logger.warning("[DISCONNECT] Клиент отключился во время отправки заглушки.")
            continue

        # AI теперь в обработке
        is_processing = True
        logger.info(f"[PROCESSING] AI принял новый запрос: {message}")

        # Сообщаем пользователю, что запрос принят
        try:
            await websocket.send_text(REQUEST_RECEIVED_MESSAGE)
        except WebSocketDisconnect:
            logger.warning("[DISCONNECT] Клиент отключился во время отправки 'Request received'.")

        # Запускаем обработку запроса
        response = await forward_to_ai(message)

        # Рассылаем ответ от AI всем пользователям
        for connection in list(active_connections):
            try:
                await connection.send_text(response)
            except Exception as e:
                logger.error(f"[ERROR] Ошибка отправки ответа клиенту: {e}")
                active_connections.remove(connection)

        # Разблокируем обработку новых запросов
        asyncio.create_task(unblock_after_delay())

async def forward_to_ai(message: str):
    """Отправляет запрос в AI и получает ответ."""
    global is_processing, block_time

    logger.info(f"[FORWARD] Отправка запроса в AI: {message}")

    try:
        async with websockets.connect(AI_SERVER_URL, ping_interval=10, ping_timeout=None) as ai_ws:
            # Отправка сообщения в AI сервер
            await ai_ws.send(message)
            logger.info("[AI] Сообщение отправлено AI серверу.")

            while True:
                try:
                    response = await ai_ws.recv()  # Ждем ответ от AI
                except websockets.ConnectionClosed:
                    logger.error("[ERROR] AI WebSocket закрыл соединение неожиданно!")
                    return "Overdosed on swamp shrooms—brain.exe not found."

                try:
                    data = json.loads(response)
                except json.JSONDecodeError:
                    logger.error(f"[ERROR] Ошибка декодирования JSON: {response}")
                    return "Overdosed on swamp shrooms—brain.exe not found."

                # Если это сигнал о начале обработки
                if "processing" in data:
                    logger.info("[INFO] AI подтвердил начало обработки, ждём реальный ответ...")
                    continue

                # Проверяем валидность ответа
                if "response" not in data or "audio_length" not in data:
                    logger.error(f"[ERROR] Некорректный JSON-ответ от AI: {data}")
                    return "Overdosed on swamp shrooms—brain.exe not found."

                # Обработка корректного ответа
                block_time = data["audio_length"] + 10  # Время блокировки
                logger.info(f"[FORWARD] Получен ответ от AI: {data['response']} (block_time={block_time}s).")
                return json.dumps(data)  # Отправляем полный ответ как JSON

    except Exception as e:
        logger.error(f"[ERROR] Ошибка связи с AI сервером: {e}")
        return "Overdosed on swamp shrooms—brain.exe not found."

@app.websocket("/ws/proxy")
async def proxy_websocket(websocket: WebSocket):
    global is_processing
    await websocket.accept()
    active_connections.add(websocket)
    
    logger.info(f"[CONNECT] Новый клиент подключен ({len(active_connections)} всего).")

    # Отправляем приветственное сообщение
    await websocket.send_text(WELCOME_MESSAGE)
    
    try:
        while True:
            message = await websocket.receive_text()
            logger.info(f"[MESSAGE] Получено сообщение: {message}")

            # Если AI занят, отправляем BUSY_MESSAGE
            if is_processing:
                logger.info("[BUSY] AI уже занят, мгновенно отправляем заглушку клиенту.")
                await websocket.send_text(BUSY_MESSAGE)
                continue

            # Добавляем запрос в очередь
            await message_queue.put((message, websocket))

    except WebSocketDisconnect:
        logger.info("[DISCONNECT] Клиент отключился.")
        active_connections.remove(websocket)
    except Exception as e:
        logger.error(f"[ERROR] Неожиданная ошибка: {e}")
        await websocket.close(code=1001)

async def unblock_after_delay():
    """Функция для снятия блокировки после задержки."""
    global is_processing
    logger.info(f"[TIMER] Блокируем запросы на {block_time} секунд...")
    await asyncio.sleep(block_time)
    is_processing = False
    logger.info("[TIMER] AI снова свободен, принимаем новые запросы.")

# Запускаем обработку очереди в фоне
asyncio.create_task(process_queue())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
