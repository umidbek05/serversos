#!/usr/bin/env python
import asyncio
import websockets
import json
import os
import signal
import sys

# --- Sozlamalar ---
# Railway-da PORT o'zgaruvchisi bitta bo'ladi
PORT = int(os.environ.get("PORT", 8080))
HOST = "0.0.0.0"

# --- Global o'zgaruvchilar ---
device_connections = {}
authorized_devices = set()
frontend_ws = None

# --- WebSocket Handler ---
async def websocket_handler(websocket, path):
    """WebSocket ulanishlarini boshqarish"""
    global frontend_ws
    device_id = None
    
    # Railway health check uchun oddiy HTTP GET so'roviga javob berish
    # websockets kutubxonasi buni process_request orqali ham qilishi mumkin, 
    # lekin bu yerda eng oddiy usuli - ulanishni boshqarish.
    
    try:
        print(f"🔌 Yangi ulanish: {websocket.remote_address}")
        
        async for message in websocket:
            # Audio ma'lumot (binary)
            if isinstance(message, bytes):
                if frontend_ws and frontend_ws.open:
                    try:
                        await frontend_ws.send(message)
                    except Exception as e:
                        print(f"❌ Audio yuborishda xato: {e}")
                continue
            
            # JSON xabar
            try:
                data = json.loads(message)
                msg_type = data.get('type')
                
                if msg_type == 'frontend':
                    frontend_ws = websocket
                    print("✅ Frontend ulandi")
                    devices_list = [{"id": dev_id, "status": "active" if dev_id in authorized_devices else "pending"} for dev_id in device_connections]
                    await websocket.send(json.dumps({"type": "list", "devices": devices_list}))
                
                elif msg_type == 'register':
                    device_id = data.get('deviceId')
                    if device_id:
                        device_connections[device_id] = websocket
                        print(f"✅ Qurilma ro'yxatdan o'tdi: {device_id}")
                        await websocket.send(json.dumps({"type": "registered", "deviceId": device_id, "status": "pending"}))
                        if frontend_ws and frontend_ws.open:
                            await frontend_ws.send(json.dumps({"type": "new_pending_device", "device": {"id": device_id, "status": "pending"}}))
                
                elif msg_type == 'authorize':
                    target_id = data.get('deviceId')
                    if target_id and target_id in device_connections:
                        authorized_devices.add(target_id)
                        await device_connections[target_id].send(json.dumps({"type": "authorized", "status": "active"}))
                
                elif msg_type == 'ping':
                    await websocket.send(json.dumps({"type": "pong"}))
                    
            except json.JSONDecodeError:
                pass
                
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if device_id:
            if device_id in device_connections: del device_connections[device_id]
            if device_id in authorized_devices: authorized_devices.remove(device_id)
        if websocket == frontend_ws: frontend_ws = None

# --- Asosiy server ---
async def main():
    print(f"🚀 Railway server ishga tushmoqda: port {PORT}")
    async with websockets.serve(
        websocket_handler,
        HOST,
        PORT,
        ping_interval=20,
        ping_timeout=20
    ):
        await asyncio.Future()

if name == "main":
    asyncio.run(main())