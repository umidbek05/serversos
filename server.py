import asyncio
import websockets
import sounddevice as sd
import numpy as np
import queue
import threading
import json
import os

# --- Sozlamalar ---
HOST = '0.0.0.0'
PORT = int(os.environ.get("PORT", 80))
SAMPLE_RATE = 16000
CHANNELS = 1

# --- Global o'zgaruvchilar ---
audio_queue = queue.Queue(maxsize=20)
device_connections = {}  # deviceId -> websocket
authorized_devices = set()
frontend_ws = None

def audio_callback(indata, frames, time, status):
    if not authorized_devices: return
    try:
        if audio_queue.full(): audio_queue.get_nowait()
        audio_queue.put_nowait(indata.tobytes())
    except: pass

async def audio_sender(websocket, device_id):
    loop = asyncio.get_event_loop()
    try:
        while device_id in authorized_devices and device_id in device_connections:
            data = await loop.run_in_executor(None, audio_queue.get)
            await websocket.send(data)
    except: pass

async def notify_frontend():
    if frontend_ws:
        devices = [{"id": d, "status": "active" if d in authorized_devices else "pending"} for d in device_connections]
        try: await frontend_ws.send(json.dumps({"type": "list", "devices": devices}))
        except: pass

async def handle_client(websocket):
    global frontend_ws
    device_id = None
    
    # ESP32 dan kelgan audioni ijro etish uchun oqim
    stream = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=np.int32)
    stream.start()

    try:
        async for message in websocket:
            # 1. AUDIO (BYTES)
            if isinstance(message, bytes):
                if device_id in authorized_devices:
                    stream.write(message) # ESP32 dan kelgan ovozni ijro etish
                continue
                
            # 2. JSON (TEXT)
            data = json.loads(message)
            msg_type = data.get('type')

            if msg_type == 'frontend':
                frontend_ws = websocket
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
                    await device_connections[target_id].send(json.dumps({"type": "authorized"}))
                    asyncio.create_task(audio_sender(device_connections[target_id], target_id))
                    await notify_frontend()
                    print(f"Ruxsat berildi: {target_id}")

            elif msg_type == 'close':
                target_id = data.get('deviceId')
                if target_id in authorized_devices: authorized_devices.remove(target_id)
                if target_id in device_connections:
                    await device_connections[target_id].send(json.dumps({"type": "disconnect"}))
                    await device_connections[target_id].close()
                await notify_frontend()

    except Exception as e:
        print(f"Xatolik: {e}")
    finally:
        stream.stop(); stream.close()
        if device_id:
            if device_id in device_connections: del device_connections[device_id]
            if device_id in authorized_devices: authorized_devices.remove(device_id)
            await notify_frontend()
        if websocket == frontend_ws: frontend_ws = None

async def main():
    mic_stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=np.int16, blocksize=800, callback=audio_callback)
    async with websockets.serve(handle_client, HOST, PORT):
        with mic_stream:
            print(f"Server {HOST}:{PORT} da ishlamoqda...")
            await asyncio.Future()
    
if __name__ == "__main__":
    asyncio.run(main())
