from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import websockets
import json

# Initialize FastAPI
app = FastAPI()

# List of active WebSocket connections
active_connections = set()

# Global variable to track AI status
AI_BUSY = False  # True - AI занят, False - свободен

# AI WebSocket Server (Main AI Script)
AI_SERVER_URL = "wss://shrokgpt-production.up.railway.app/ws/ai"

# Welcome and busy messages
WELCOME_MESSAGE = "Address me as @ShrokAI and type your message so I can hear you."
BUSY_MESSAGE = "ShrokAI is busy, please wait for the current response to complete."

async def monitor_ai_status():
    """Постоянный мониторинг состояния AI (раз в секунду)."""
    global AI_BUSY
    while True:
        try:
            async with websockets.connect(AI_SERVER_URL) as ai_ws:
                await ai_ws.send(json.dumps({"status_request": True}))  # Запрос статуса AI
                status_response = await ai_ws.recv()  # Получаем ответ
                data = json.loads(status_response)
                AI_BUSY = data.get("processing", False)  # Синхронизация состояния с AI
                print(f"AI_BUSY updated: {AI_BUSY}")  # Логируем состояние AI
        except Exception as e:
            print(f"Error checking AI status: {e}")
            AI_BUSY = False  # Если ошибка соединения — считаем, что AI свободен
        await asyncio.sleep(1)  # Проверяем каждую секунду

async def forward_to_ai(message: str):
    """Отправляет запрос в основной скрипт ИИ и получает ответ."""
    try:
        async with websockets.connect(AI_SERVER_URL) as ai_ws:
            await ai_ws.send(message)  # Отправляем текст в AI

            response = await ai_ws.recv()  # Ждём финальный ответ от ИИ
            data = json.loads(response)  # Разбираем JSON-ответ
            return data.get("response", "ShrokAI is silent...")  # Возвращаем текст
    except Exception as e:
        print(f"Error communicating with AI server: {e}")
        return "ShrokAI encountered an issue. Try again later."

@app.websocket("/ws/proxy")
async def proxy_websocket(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    
    # Отправляем приветственное сообщение
    await websocket.send_text(WELCOME_MESSAGE)
    
    try:
        while True:
            message = await websocket.receive_text()
            print(f"Received message: {message}")

            if AI_BUSY:
                print("ShrokAI is currently busy. Sending busy message.")
                await websocket.send_text(BUSY_MESSAGE)
                continue  # Не передаём сообщение в AI
            
            # AI свободен, пересылаем сообщение
            response = await forward_to_ai(message)
            
            # Рассылаем ответ всем клиентам
            for connection in list(active_connections):
                try:
                    await connection.send_text(response)
                except Exception as e:
                    print(f"Failed to send message to client: {e}")
                    active_connections.remove(connection)

    except WebSocketDisconnect:
        print("WebSocket disconnected")
        active_connections.remove(websocket)
    except Exception as e:
        print(f"Unexpected error: {e}")
        await websocket.close(code=1001)

if __name__ == "__main__":
    import uvicorn
    loop = asyncio.get_event_loop()
    loop.create_task(monitor_ai_status())  # Запускаем постоянный мониторинг AI
    uvicorn.run(app, host="0.0.0.0", port=9000)
