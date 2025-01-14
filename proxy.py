from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import websockets
import json

# Initialize FastAPI
app = FastAPI()

# List of active WebSocket connections
active_connections = set()

# Очередь запросов от пользователей
message_queue = asyncio.Queue()

# AI Server WebSocket URL
AI_SERVER_URL = "wss://shrokgpt-production.up.railway.app/ws/ai"

# Глобальные переменные статуса
is_processing = False  # AI в процессе обработки?
block_time = 0  # Время блокировки перед следующим запросом

# Сообщения пользователям
WELCOME_MESSAGE = "Address me as @ShrokAI and type your message so I can hear you."
BUSY_MESSAGE = "ShrokAI is busy, please wait for the current response to complete."
REQUEST_RECEIVED_MESSAGE = "Request received. Thinking of a reply..."

async def process_queue():
    """Функция, которая обрабатывает очередь входящих сообщений."""
    global is_processing

    while True:
        # Ждём следующий запрос из очереди
        message, websocket = await message_queue.get()

        # Если AI уже обрабатывает другой запрос — мгновенно отправляем BUSY_MESSAGE
        if is_processing:
            print("[BUSY] AI уже занят, отправляем заглушку клиенту")
            await websocket.send_text(BUSY_MESSAGE)
            continue  # Пропускаем обработку и ждём следующий запрос
        
        # AI теперь в обработке
        is_processing = True
        print(f"[PROCESSING] AI принял новый запрос: {message}")

        # Сообщаем пользователю, что запрос принят
        await websocket.send_text(REQUEST_RECEIVED_MESSAGE)

        # Запускаем обработку запроса
        response = await forward_to_ai(message)

        # Рассылаем ответ от AI всем пользователям
        for connection in list(active_connections):
            try:
                await connection.send_text(response)
            except Exception as e:
                print(f"[ERROR] Ошибка отправки ответа клиенту: {e}")
                active_connections.remove(connection)

        # Разблокируем обработку новых запросов
        asyncio.create_task(unblock_after_delay())

async def forward_to_ai(message: str):
    """Отправляет запрос в AI и получает ответ."""
    global is_processing, block_time

    print(f"[FORWARD] Отправка запроса в AI: {message}")

    try:
        async with websockets.connect(AI_SERVER_URL) as ai_ws:
            await ai_ws.send(message)

            # Ждём сигнал, что AI начал обработку
            processing_signal = await ai_ws.recv()
            processing_data = json.loads(processing_signal)

            if processing_data.get("processing"):
                print("[FORWARD] AI подтвердил, что начал обработку")

            # Ждём финальный ответ от AI
            response = await ai_ws.recv()

            try:
                data = json.loads(response)
            except json.JSONDecodeError:
                print(f"[ERROR] Ошибка декодирования JSON: {response}")
                return "ShrokAI encountered an issue. Invalid response from AI server."

            if "response" not in data or "audio_length" not in data:
                print(f"[ERROR] Некорректный JSON-ответ от AI: {data}")
                return "ShrokAI encountered an issue. Missing response data."

            block_time = data["audio_length"] + 10  # Блокируем новые запросы на время
            print(f"[FORWARD] Получен ответ от AI: {data['response']} (block_time={block_time}s)")

            return data["response"]

    except Exception as e:
        print(f"[ERROR] Ошибка связи с AI сервером: {e}")
        return "ShrokAI encountered an issue. Try again later."

@app.websocket("/ws/proxy")
async def proxy_websocket(websocket: WebSocket):
    global is_processing
    await websocket.accept()
    active_connections.add(websocket)
    
    print(f"[CONNECT] Новый клиент подключен ({len(active_connections)} всего)")

    # Отправляем приветственное сообщение
    await websocket.send_text(WELCOME_MESSAGE)
    
    try:
        while True:
            message = await websocket.receive_text()
            print(f"[MESSAGE] Получено сообщение: {message}")

            # Добавляем запрос в очередь
            await message_queue.put((message, websocket))

    except WebSocketDisconnect:
        print("[DISCONNECT] Клиент отключился")
        active_connections.remove(websocket)
    except Exception as e:
        print(f"[ERROR] Неожиданная ошибка: {e}")
        await websocket.close(code=1001)

async def unblock_after_delay():
    """Функция для снятия блокировки после задержки."""
    global is_processing
    print(f"[TIMER] Блокируем запросы на {block_time} секунд...")
    await asyncio.sleep(block_time)
    is_processing = False
    print("[TIMER] AI снова свободен, принимаем новые запросы")

# Запускаем обработку очереди в фоне
asyncio.create_task(process_queue())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
