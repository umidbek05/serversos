import asyncio
import websockets
import json
import os

# --- Sozlamalar ---
HOST = '0.0.0.0'
PORT = int(os.environ.get("PORT", 80))

# --- Global o'zgaruvchilar ---
device_connections = {}  # deviceId -> websocket
authorized_devices = set()
frontend_ws = None

async def notify_frontend():
    """Frontendga qurilmalar ro'yxatini yuborish"""
    if frontend_ws and frontend_ws.open:
        devices = [
            {"id": dev_id, "status": "active" if dev_id in authorized_devices else "pending"} 
            for dev_id in device_connections
        ]
        try:
            await frontend_ws.send(json.dumps({"type": "list", "devices": devices}))
        except Exception as e:
            print(f"Frontendga xabar yuborishda xato: {e}")

async def handle_client(websocket):
    global frontend_ws
    device_id = None
    
    try:
        async for message in websocket:
            # 1. AUDIO (BYTES) - ESP32 dan keladi
            if isinstance(message, bytes):
                # Ovozli aloqa faqat authorized qurilmalardan qabul qilinadi
                if device_id and device_id in authorized_devices and frontend_ws and frontend_ws.open:
                    try:
                        # Audio ma'lumotlarni frontendga yuborish
                        await frontend_ws.send(message)
                        print(f"Audio yuborildi: {len(message)} bytes")
                    except Exception as e:
                        print(f"Audio yuborishda xato: {e}")
                continue
                
            # 2. JSON (TEXT)
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                print(f"Noto'g'ri JSON format: {message[:100]}")
                continue
                
            msg_type = data.get('type')
            print(f"Xabar keldi: {msg_type}")

            if msg_type == 'frontend':
                frontend_ws = websocket
                print("✅ Frontend ulandi")
                await notify_frontend()
            
            elif msg_type == 'register':
                device_id = data.get('deviceId')
                if device_id:
                    device_connections[device_id] = websocket
                    print(f"✅ Qurilma ulandi: {device_id}")
                    # Qurilmaga ulanganligi haqida javob
                    await websocket.send(json.dumps({"type": "registered", "deviceId": device_id}))
                    await notify_frontend()

            elif msg_type == 'authorize':
                target_id = data.get('deviceId')
                if target_id and target_id in device_connections:
                    authorized_devices.add(target_id)
                    # Qurilmaga ruxsat berilgani haqida xabar
                    try:
                        await device_connections[target_id].send(
                            json.dumps({"type": "authorized", "status": "active"})
                        )
                        print(f"✅ Ruxsat berildi: {target_id}")
                    except Exception as e:
                        print(f"Qurilmaga ruxsat xabarini yuborishda xato: {e}")
                    
                    # Frontendga yangi statusni yuborish
                    await notify_frontend()

            elif msg_type == 'close':
                target_id = data.get('deviceId')
                if target_id:
                    if target_id in authorized_devices:
                        authorized_devices.remove(target_id)
                    
                    if target_id in device_connections:
                        try:
                            await device_connections[target_id].send(
                                json.dumps({"type": "disconnect"})
                            )
                            await device_connections[target_id].close()
                        except:
                            pass
                        del device_connections[target_id]
                    
                    print(f"❌ Uzildi: {target_id}")
                    await notify_frontend()
                    
            elif msg_type == 'ping':
                # Keep-alive uchun
                await websocket.send(json.dumps({"type": "pong"}))

    except websockets.exceptions.ConnectionClosed:
        print(f"Uzilish: {device_id or 'Noma\'lum'}")
    except Exception as e:
        print(f"Xatolik: {e}")
    finally:
        # Tozalash ishlari
        if device_id:
            if device_id in device_connections:
                del device_connections[device_id]
            if device_id in authorized_devices:
                authorized_devices.remove(device_id)
            print(f"Tozalandi: {device_id}")
            await notify_frontend()
        
        if websocket == frontend_ws:
            frontend_ws = None
            print("Frontend uzildi")

async def main():
    """Serverni ishga tushirish"""
    try:
        async with websockets.serve(
            handle_client, 
            HOST, 
            PORT,
            ping_interval=30,  # 30 sekundda bir ping
            ping_timeout=10,    # 10 sekundda javob bo'lmasa uziladi
            max_size=10_485_760  # Maksimum 10MB
        ):
            print(f"\n{'='*50}")
            print(f"🚀 Server ishga tushdi!")
            print(f"📡 URL: ws://{HOST}:{PORT}")
            print(f"🔌 Port: {PORT}")
            print(f"{'='*50}\n")
            
            # Serverni doimiy ishlatish
            await asyncio.Future()
            
    except Exception as e:
        print(f"Serverni ishga tushirishda xato: {e}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server to'xtatildi")