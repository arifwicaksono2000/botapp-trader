from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        try:
            await websocket.accept()
            self.active_connections.append(websocket)
        except Exception as e:
            print(f"[!] WebSocket accept failed: {e}")


    async def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, data: dict):
        to_remove = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except RuntimeError:
                # Client already disconnected
                to_remove.append(connection)
            except Exception as e:
                print(f"[!] Unexpected WebSocket error: {e}")
                to_remove.append(connection)
        for conn in to_remove:
            await self.disconnect(conn)


manager = ConnectionManager()

@app.websocket("/ws/positions")
async def positions_stream(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        await manager.disconnect(websocket)

@app.post("/broadcast")
async def broadcast(data: dict):
    await manager.broadcast(data)
    return {"status": "sent"}

@app.get("/status")
def status():
    return {"status": "ok"}
