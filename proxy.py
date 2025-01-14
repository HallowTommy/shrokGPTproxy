from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import websockets
import json

app = FastAPI()
active_connections = set()
is_processing = False  # Флаг блокировки новых запросов
block_time = 0  # Время блокировки

AI_SERVER_URL = "wss://shrokgpt-production.up.railway.app/ws/ai"

WELCOME_MESSAGE = "Address me as @ShrokAI and type your message so I can hear you."
BUSY_MESSAGE = "ShrokAI is busy, please wait for the current response to complete."

async def forward_to_ai(message: str):
    """Отправляет запрос в основной скрипт ИИ и получает ответ."""
    global is_processing, block_time
    try:
        async with websockets.connect(AI_SERVER_URL) as ai_ws:
            await ai_ws.send(message)
            response = await ai_ws.recv()
            data = json.loads(response)
            block_time = data.get("audio_length", 0) + 10  # Время блокировки
            return data.get("response", "ShrokAI is silent...")
    except Exception as e:
        print(f"Error communicating with AI server: {e}")
        return "ShrokAI encountered an issue. Try again later."

@app.websocket("/ws/proxy")
async def proxy_websocket(websocket: WebSocket):
    global is_processing
    await websocket.accept()
    active_connections.add(websocket)

    await websocket.send_text(WELCOME_MESSAGE)  # Отправка приветствия
    
    try:
        while True:
            message = await websocket.receive_text()
            print(f"Received message: {message}")

            if is_processing:
                print("ShrokAI is currently busy. Sending busy message.")
                await websocket.send_text(BUSY_MESSAGE)
                continue

            # ✅ 1. Устанавливаем `is_processing = True` СРАЗУ
            is_processing = True
            print("Processing started. Blocking new requests.")

            # ✅ 2. Оповещаем всех пользователей, что ИИ занят
            for connection in list(active_connections):
                try:
                    await connection.send_text(BUSY_MESSAGE)
                except Exception as e:
                    print(f"Failed to send busy message to a client: {e}")
                    active_connections.remove(connection)

            # ✅ 3. Передаём сообщение в ИИ
            response = await forward_to_ai(message)

            # ✅ 4. Отправляем ответ всем пользователям
            for connection in list(active_connections):
                try:
                    await connection.send_text(response)
                except Exception as e:
                    print(f"Failed to send message to client: {e}")
                    active_connections.remove(connection)

            # ✅ 5. Запускаем таймер разблокировки
            asyncio.create_task(unblock_after_delay())

    except WebSocketDisconnect:
        print("WebSocket disconnected")
        active_connections.remove(websocket)
    except Exception as e:
        print(f"Unexpected error: {e}")
        await websocket.close(code=1001)

async def unblock_after_delay():
    """Функция для снятия блокировки после задержки."""
    global is_processing
    print(f"Blocking requests for {block_time} seconds...")
    await asyncio.sleep(block_time)
    is_processing = False
    print("Unblocking requests.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
