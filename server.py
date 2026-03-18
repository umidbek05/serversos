import asyncio
import websockets
import json
import os

# --- Sozlamalar ---
HOST = '0.0.0.0'
PORT = int(os.environ.get("PORT", 80))

# --- Global o'zgaruvchilar ---
device_connections = {}
authorized_devices = set()
frontend_ws = None

async def handle_client(websocket):
    global frontend_ws
    device_id = None
    
    try:
        # Handshake ni qo'lda tekshirish
        print(f"Yangi ulanish: {websocket.remote_address}")
        
        async for message in websocket:
            # Audio (bytes)
            if isinstance(message, bytes):
                if device_id and device_id in authorized_devices and frontend_ws and frontend_ws.open:
                    try:
                        await frontend_ws.send(message)
                        print(f"Audio yuborildi: {len(message)} bytes")
                    except Exception as e:
                        print(f"Audio yuborishda xato: {e}")
                continue
                
            # JSON xabar
            try:
                data = json.loads(message)
                print(f"Xabar keldi: {data.get('type')}")
            except json.JSONDecodeError:
                print(f"Noto'g'ri JSON: {message[:100]}")
                continue
                
            msg_type = data.get('type')

            if msg_type == 'frontend':
                frontend_ws = websocket
                print("✅ Frontend ulandi")
                
                # Darhol qurilmalar ro'yxatini yuborish
                devices = [
                    {"id": dev_id, "status": "active" if dev_id in authorized_devices else "pending"} 
                    for dev_id in device_connections
                ]
                await websocket.send(json.dumps({"type": "list", "devices": devices}))
            
            elif msg_type == 'register':
                device_id = data.get('deviceId')
                if device_id:
                    device_connections[device_id] = websocket
                    print(f"✅ Qurilma ulandi: {device_id}")
                    
                    # Qurilmaga javob
                    await websocket.send(json.dumps({
                        "type": "registered", 
                        "deviceId": device_id,
                        "status": "pending"
                    }))
                    
                    # Frontendga xabar (agar ulangan bo'lsa)
                    if frontend_ws and frontend_ws.open:
                        try:
                            await frontend_ws.send(json.dumps({
                                "type": "new_pending_device",
                                "device": {"id": device_id, "status": "pending"}
                            }))
                        except Exception as e:
                            print(f"Frontendga xabar yuborishda xato: {e}")

            elif msg_type == 'authorize':
                target_id = data.get('deviceId')
                if target_id and target_id in device_connections:
                    authorized_devices.add(target_id)
                    
                    # Qurilmaga ruxsat xabari
                    try:
                        await device_connections[target_id].send(
                            json.dumps({"type": "authorized", "status": "active"})
                        )
                        print(f"✅ Ruxsat berildi: {target_id}")
                    except Exception as e:
                        print(f"Qurilmaga xabar yuborishda xato: {e}")
                    
                    # Frontendga yangi ro'yxat
                    if frontend_ws and frontend_ws.open:
                        devices = [
                            {"id": dev_id, "status": "active" if dev_id in authorized_devices else "pending"} 
                            for dev_id in device_connections
                        ]
                        await frontend_ws.send(json.dumps({"type": "list", "devices": devices}))

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
                    
                    # Frontendga yangi ro'yxat
                    if frontend_ws and frontend_ws.open:
                        devices = [
                            {"id": dev_id, "status": "active" if dev_id in authorized_devices else "pending"} 
                            for dev_id in device_connections
                        ]
                        await frontend_ws.send(json.dumps({"type": "list", "devices": devices}))

    except websockets.exceptions.ConnectionClosed:
        print(f"Ulanish uzildi: {device_id or 'Noma\'lum'}")
    except Exception as e:
        print(f"Xatolik: {e}")
    finally:
        # Tozalash
        if device_id:
            if device_id in device_connections:
                del device_connections[device_id]
            if device_id in authorized_devices:
                authorized_devices.remove(device_id)
            print(f"Tozalandi: {device_id}")
        
        if websocket == frontend_ws:
            frontend_ws = None
            print("Frontend uzildi")

async def main():
    try:
        # Server sozlamalari
        server = await websockets.serve(
            handle_client,
            HOST,
            PORT,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
            max_size=10_485_760,
            # Muhim: bu headerlarni qabul qilish
            origins=None,  # Barcha originlarga ruxsat
            compression=None  # Compression ni o'chirish
        )
        
        print(f"\n{'='*50}")
        print(f"🚀 WebSocket Server ishga tushdi!")
        print(f"📡 URL: ws://{HOST}:{PORT} yoki wss://your-domain.com")
        print(f"🔌 Port: {PORT}")
        print(f"📊 Qurilmalar: {len(device_connections)}")
        print(f"{'='*50}\n")
        
        # Serverni cheksiz ishlatish
        await asyncio.Future()
        
    except Exception as e:
        print(f"Serverni ishga tushirishda xato: {e}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server to'xtatildi")
    except Exception as e:
        print(f"Kutilmagan xato: {e}")