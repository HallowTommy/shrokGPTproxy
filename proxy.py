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
AI_SERVER_URL = "wss://shrokgpt-production.up.railway.app/ws/ai"  # Адрес WebSocket ИИ

# Welcome and busy messages
WELCOME_MESSAGE = "Address me as @ShrokAI and type your message so I can hear you."
BUSY_MESSAGE = "ShrokAI is busy, please wait for the current response to complete."

async def forward_to_ai(message: str):
    """Отправляет запрос в основной скрипт ИИ и получает ответ."""
    global is_processing, block_time
    try:
        async with websockets.connect(AI_SERVER_URL) as ai_ws:
            await ai_ws.send(message)  # Отправляем запрос в основной ИИ
            
            # Ждём сигнал, что обработка началась
            processing_signal = await ai_ws.recv()
            processing_data = json.loads(processing_signal)
            if processing_data.get("processing"):
                is_processing = True  # Моментально ставим флаг, что ИИ занят

            # Ждём финальный ответ от ИИ
            response = await ai_ws.recv()
            
            # 🔥 Проверяем, является ли response корректным JSON
            try:
                data = json.loads(response)
            except json.JSONDecodeError:
                print(f"❌ Ошибка декодирования JSON: {response}")
                return "ShrokAI encountered an issue. Invalid response from AI server."
            
            # Проверяем, есть ли в JSON нужные данные
            if "response" not in data or "audio_length" not in data:
                print(f"⚠️ Некорректный JSON-ответ от AI: {data}")
                return "ShrokAI encountered an issue. Missing response data."

            block_time = data["audio_length"] + 10  # Устанавливаем время блокировки
            return data["response"]
    except Exception as e:
        print(f"❌ Ошибка связи с AI сервером: {e}")
        return "ShrokAI encountered an issue. Try again later."

@app.websocket("/ws/proxy")
async def proxy_websocket(websocket: WebSocket):
    global is_processing
    await websocket.accept()
    active_connections.add(websocket)
    
    # Send welcome message
    await websocket.send_text(WELCOME_MESSAGE)
    
    try:
        while True:
            message = await websocket.receive_text()
            print(f"Received message: {message}")

            # ⚡️ Если AI уже обрабатывает запрос, отправляем заглушку сразу же!
            if is_processing:
                await websocket.send_text(BUSY_MESSAGE)
                continue  # Прерываем выполнение для этого пользователя
            
            # ⚡️ Устанавливаем блокировку мгновенно!
            is_processing = True  

            # Forward message to AI server
            response = await forward_to_ai(message)

            # Рассылаем ответ от ИИ всем пользователям
            for connection in list(active_connections):
                try:
                    await connection.send_text(response)
                except Exception as e:
                    print(f"Failed to send message to client: {e}")
                    active_connections.remove(connection)
                    
            # Стартуем таймер разблокировки
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
