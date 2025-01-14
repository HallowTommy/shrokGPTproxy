from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import websockets
import json

# Initialize FastAPI
app = FastAPI()

# List of active WebSocket connections
active_connections = set()

# Global control variables
is_processing = False  # Blocks new requests while a response is being generated
block_time = 0  # Stores the time (in seconds) for which new requests are blocked

# AI WebSocket Server (Main AI Script)
AI_SERVER_URL = "wss://shrokgpt-production.up.railway.app/ws/ai"

# Welcome and busy messages
WELCOME_MESSAGE = "Address me as @ShrokAI and type your message so I can hear you."
BUSY_MESSAGE = "ShrokAI is busy, please wait for the current response to complete."

async def forward_to_ai(message: str):
    """Отправляет запрос в основной скрипт ИИ и получает ответ."""
    global is_processing, block_time

    print(f"[FORWARD] Отправка запроса в AI: {message}")

    try:
        async with websockets.connect(AI_SERVER_URL) as ai_ws:
            await ai_ws.send(message)

            # Ждём сигнал, что обработка началась
            processing_signal = await ai_ws.recv()
            processing_data = json.loads(processing_signal)

            if processing_data.get("processing"):
                is_processing = True  # AI занят
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

            block_time = data["audio_length"] + 10  # Устанавливаем блокировку
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

    # Send welcome message
    await websocket.send_text(WELCOME_MESSAGE)
    
    try:
        while True:
            message = await websocket.receive_text()
            print(f"[MESSAGE] Получено сообщение: {message}")

            # ⚡️ Если AI уже обрабатывает запрос, отправляем заглушку сразу же!
            if is_processing:
                print("[BUSY] AI уже занят, отправляем заглушку клиенту")
                await websocket.send_text(BUSY_MESSAGE)
                continue  # Прерываем выполнение для этого клиента
            
            # ⚡️ Устанавливаем блокировку мгновенно!
            is_processing = True
            print("[PROCESSING] AI взял запрос в обработку")

            # Forward message to AI server
            response = await forward_to_ai(message)

            # Рассылаем ответ от ИИ всем пользователям
            for connection in list(active_connections):
                try:
                    await connection.send_text(response)
                except Exception as e:
                    print(f"[ERROR] Ошибка отправки ответа клиенту: {e}")
                    active_connections.remove(connection)
                    
            # Стартуем таймер разблокировки
            asyncio.create_task(unblock_after_delay())

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)

