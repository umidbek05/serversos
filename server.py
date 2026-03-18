import asyncio
import websockets
import json
import os

# --- Sozlamalar ---
HOST = '0.0.0.0'
# Railway portni dinamik beradi, shuning uchun os.environ ishlatamiz
PORT = int(os.environ.get("PORT", 80))
SAMPLE_RATE = 16000
CHANNELS = 1

# --- Global o'zgaruvchilar ---
# audio_queue endi kerak emas, chunki server orqali to'g'ridan-to'g'ri uzatamiz
device_connections = {}  # deviceId -> websocket
authorized_devices = set()
frontend_ws = None

async def notify_frontend():
    if frontend_ws:
        devices = [{"id": d, "status": "active" if d in authorized_devices else "pending"} for d in device_connections]
        try: 
            await frontend_ws.send(json.dumps({"type": "list", "devices": devices}))
        except: 
            pass

async def handle_client(websocket):
    global frontend_ws
    device_id = None
    
    try:
        async for message in websocket:
            # 1. AUDIO (BYTES)
            if isinstance(message, bytes):
                # ESP32 dan kelgan ovozni Frontend ga yo'naltiramiz
                if frontend_ws and device_id in authorized_devices:
                    try:
                        await frontend_ws.send(message)
                    except:
                        pass
                continue
                
            # 2. JSON (TEXT)
            data = json.loads(message)
            msg_type = data.get('type')

            if msg_type == 'frontend':
                frontend_ws = websocket
                print("Frontend ulandi")
                await notify_frontend()
            
            elif msg_type == 'register':
                device_id = data.get('deviceId')
                device_connections[device_id] = websocket
                print(f"Qurilma ulandi: {device_id}")
                await notify_frontend()

            elif msg_type == 'authorize':
                target_id = data.get('deviceId')
                if target_id in device_connections:
                    authorized_devices.add(target_id)
                    # Qurilmaga ruxsat berilgani haqida xabar yuboramiz
                    await device_connections[target_id].send(json.dumps({"type": "authorized"}))
                    await notify_frontend()
                    print(f"Ruxsat berildi: {target_id}")

            elif msg_type == 'close':
                target_id = data.get('deviceId')
                if target_id in authorized_devices: 
                    authorized_devices.remove(target_id)
                if target_id in device_connections:
                    await device_connections[target_id].send(json.dumps({"type": "disconnect"}))
                    await device_connections[target_id].close()
                await notify_frontend()

    except Exception as e:
        print(f"Xatolik: {e}")
    finally:
        # Tozalash ishlari
        if device_id:
            if device_id in device_connections: 
                del device_connections[device_id]
            if device_id in authorized_devices: 
                authorized_devices.remove(device_id)
            await notify_frontend()
        if websocket == frontend_ws: 
            frontend_ws = None

async def main():
    # Railway serverda InputStream bo'lmaydi, shuning uchun uni o'chirib faqat websockets qoldiramiz
    async with websockets.serve(handle_client, HOST, PORT):
        print(f"Server {HOST}:{PORT} da ishlamoqda...")
        await asyncio.Future() # Serverni doimiy ochiq ushlab turadi
    
if __name__ == "__main__":
    asyncio.run(main())