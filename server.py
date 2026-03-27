#!/usr/bin/env python
import asyncio
import websockets
import json
import os
import signal
import sys

# --- Sozlamalar ---
# Railway.app faqat bitta PORT o'zgaruvchisini beradi.
# WebSocket serverni aynan shu portda ishga tushiramiz.
PORT = int(os.environ.get("PORT", 8080))
HOST = "0.0.0.0"

# --- Global o'zgaruvchilar ---
device_connections = {}    # device_id -> websocket
authorized_devices = set() # ruxsat berilgan device_id'lar
frontend_connections = set() # barcha ulangan frontend websocket'lari

# --- WebSocket Handler ---
async def websocket_handler(websocket):
    """WebSocket ulanishlarini boshqarish (ESP32 va Frontend)"""
    global frontend_connections
    current_device_id = None
    is_frontend = False
    
    try:
        print(f"🔌 Yangi ulanish: {websocket.remote_address}")
        
        async for message in websocket:
            # 1. AUDIO MA'LUMOT (BINARY)
            if isinstance(message, bytes):
                # Agar bu ESP32 bo'lsa va ruxsat berilgan bo'lsa -> Frontendga yuborish
                if current_device_id and current_device_id in authorized_devices:
                    for f_ws in frontend_connections:
                        if f_ws.open:
                            await f_ws.send(message)
                
                # Agar bu Frontend bo'lsa -> Barcha ruxsat berilgan ESP32'larga yuborish
                elif is_frontend:
                    for d_id in authorized_devices:
                        d_ws = device_connections.get(d_id)
                        if d_ws and d_ws.open:
                            await d_ws.send(message)
                continue
            
            # 2. JSON XABARLAR (CONTROL)
            try:
                data = json.loads(message)
                msg_type = data.get("type")
                
                # FRONTEND ULANISHI
                if msg_type == "frontend":
                    is_frontend = True
                    frontend_connections.add(websocket)
                    print("✅ Frontend ulandi")
                    
                    # Mavjud qurilmalar ro'yxatini yuborish
                    devices_list = []
                    for dev_id in device_connections:
                        status = "active" if dev_id in authorized_devices else "pending"
                        devices_list.append({"id": dev_id, "status": status})
                    
                    await websocket.send(json.dumps({
                        "type": "list",
                        "devices": devices_list
                    }))
                
                # ESP32 RO'YXATDAN O'TISHI
                elif msg_type == "register":
                    current_device_id = data.get("deviceId")
                    if current_device_id:
                        device_connections[current_device_id] = websocket
                        print(f"✅ Qurilma ro'yxatdan o'tdi: {current_device_id}")
                        
                        await websocket.send(json.dumps({
                            "type": "registered",
                            "deviceId": current_device_id,
                            "status": "pending"
                        }))
                        
                        # Frontendga xabar berish
                        for f_ws in frontend_connections:
                            if f_ws.open:
                                await f_ws.send(json.dumps({
                                    "type": "new_pending_device",
                                    "device": {"id": current_device_id, "status": "pending"}
                                }))
                
                # FRONTEND TOMONIDAN RUXSAT BERISH
                elif msg_type == "authorize":
                    target_id = data.get("deviceId")
                    if target_id and target_id in device_connections:
                        authorized_devices.add(target_id)
                        print(f"✅ Ruxsat berildi: {target_id}")
                        
                        # ESP32 ga ruxsat xabarini yuborish
                        d_ws = device_connections[target_id]
                        if d_ws.open:
                            await d_ws.send(json.dumps({
                                "type": "authorized",
                                "status": "active"
                            }))
                
                # ULANISHNI YOPISH
                elif msg_type == "close":
                    target_id = data.get("deviceId")
                    if target_id in device_connections:
                        if target_id in authorized_devices:
                            authorized_devices.remove(target_id)
                        # ESP32 ga uzilish xabarini yuborish
                        try:
                            await device_connections[target_id].send(json.dumps({"type": "disconnect"}))
                            await device_connections[target_id].close()
                        except: pass
                        del device_connections[target_id]
                
                elif msg_type == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
                    
            except json.JSONDecodeError:
                pass
                
    except websockets.exceptions.ConnectionClosed:
        print(f"🔌 Ulanish uzildi")
    except Exception as e:
        print(f"❌ Xatolik: {e}")
    finally:
        # TOZALASH
        if is_frontend:
            frontend_connections.discard(websocket)
            print("👋 Frontend uzildi")
        
        if current_device_id:
            if current_device_id in device_connections:
                del device_connections[current_device_id]
            if current_device_id in authorized_devices:
                authorized_devices.remove(current_device_id)
            print(f"🧹 Qurilma tozalandi: {current_device_id}")

# --- Asosiy server ---
async def main():
    print(f"🚀 Audio Exchange Server ishga tushmoqda...")
    
    # Railway-da WebSocket-ni PORT-da ishga tushiramiz.
    async with websockets.serve(
        websocket_handler,
        HOST,
        PORT, 
        ping_interval=20,
        ping_timeout=20
    ):
        print(f"✅ WebSocket server ishga tushdi: port {PORT}")
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server to'xtatildi")
