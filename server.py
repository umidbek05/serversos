#!/usr/bin/env python
import asyncio
import websockets
import json
import os
import signal
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# --- Sozlamalar ---
PORT = int(os.environ.get("PORT", 8080))
HOST = "0.0.0.0"

# --- Global o'zgaruvchilar ---
device_connections = {}
authorized_devices = set()
frontend_ws = None

# --- HTTP Server (Railway health check uchun) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Server is running!')
    
    def log_message(self, format, *args):
        return  # Loglarni o'chirish

def run_http_server():
    try:
        httpd = HTTPServer((HOST, PORT), HealthCheckHandler)
        print(f"📡 HTTP Health check server running on port {PORT}")
        httpd.serve_forever()
    except Exception as e:
        print(f"❌ HTTP server xatosi: {e}")

# HTTP serverni alohida threadda ishga tushirish
http_thread = threading.Thread(target=run_http_server, daemon=True)
http_thread.start()

# --- WebSocket Handler ---
async def websocket_handler(websocket):
    """WebSocket ulanishlarini boshqarish"""
    global frontend_ws
    device_id = None
    
    try:
        print(f"🔌 Yangi ulanish: {websocket.remote_address}")
        
        async for message in websocket:
            # Audio ma'lumot (binary)
            if isinstance(message, bytes):
                print(f"🎤 Audio keldi: {len(message)} bytes")
                if frontend_ws and frontend_ws.open:
                    try:
                        await frontend_ws.send(message)
                        print(f"✅ Audio frontendga yuborildi")
                    except Exception as e:
                        print(f"❌ Audio yuborishda xato: {e}")
                continue
            
            # JSON xabar
            try:
                data = json.loads(message)
                msg_type = data.get('type')
                print(f"📨 Xabar: {msg_type}")
                
                if msg_type == 'frontend':
                    frontend_ws = websocket
                    print("✅ Frontend ulandi")
                    
                    # Qurilmalar ro'yxatini yuborish
                    devices_list = []
                    for dev_id in device_connections:
                        status = "active" if dev_id in authorized_devices else "pending"
                        devices_list.append({"id": dev_id, "status": status})
                    
                    await websocket.send(json.dumps({
                        "type": "list",
                        "devices": devices_list
                    }))
                    print(f"📋 Qurilmalar ro'yxati yuborildi: {len(devices_list)} ta")
                
                elif msg_type == 'register':
                    device_id = data.get('deviceId')
                    if device_id:
                        device_connections[device_id] = websocket
                        print(f"✅ Qurilma ro'yxatdan o'tdi: {device_id}")
                        
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
                                    "device": {
                                        "id": device_id,
                                        "status": "pending"
                                    }
                                }))
                                print(f"📱 Yangi qurilma frontendga yuborildi: {device_id}")
                            except Exception as e:
                                print(f"❌ Frontendga xabar yuborishda xato: {e}")
                
                elif msg_type == 'authorize':
                    target_id = data.get('deviceId')
                    if target_id and target_id in device_connections:
                        authorized_devices.add(target_id)
                        print(f"✅ Ruxsat berildi: {target_id}")
                        
                        # Qurilmaga ruxsat xabari
                        try:
                            await device_connections[target_id].send(
                                json.dumps({
                                    "type": "authorized",
                                    "status": "active"
                                })
                            )
                            print(f"📱 Qurilmaga ruxsat xabari yuborildi: {target_id}")
                        except Exception as e:
                            print(f"❌ Qurilmaga xabar yuborishda xato: {e}")
                        
                        # Frontendga yangi ro'yxat
                        if frontend_ws and frontend_ws.open:
                            devices_list = []
                            for dev_id in device_connections:
                                status = "active" if dev_id in authorized_devices else "pending"
                                devices_list.append({"id": dev_id, "status": status})
                            
                            await frontend_ws.send(json.dumps({
                                "type": "list",
                                "devices": devices_list
                            }))
                            print(f"📋 Yangi ro'yxat frontendga yuborildi")
                
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
                            devices_list = []
                            for dev_id in device_connections:
                                status = "active" if dev_id in authorized_devices else "pending"
                                devices_list.append({"id": dev_id, "status": status})
                            
                            await frontend_ws.send(json.dumps({
                                "type": "list",
                                "devices": devices_list
                            }))
                
                elif msg_type == 'ping':
                    await websocket.send(json.dumps({"type": "pong"}))
                    
            except json.JSONDecodeError as e:
                print(f"❌ JSON xato: {e}")
                
    except websockets.exceptions.ConnectionClosed:
        # TUZATILDI: backslash muammosi hal qilindi
        device_info = device_id if device_id else "Noma lum"
        print(f"🔌 Ulanish uzildi: {device_info}")
    except Exception as e:
        print(f"❌ Xatolik: {e}")
    finally:
        # Tozalash
        if device_id:
            if device_id in device_connections:
                del device_connections[device_id]
            if device_id in authorized_devices:
                authorized_devices.remove(device_id)
            print(f"🧹 Tozalandi: {device_id}")
        
        if websocket == frontend_ws:
            frontend_ws = None
            print("👋 Frontend uzildi")

# --- Asosiy server ---
async def main():
    """WebSocket serverni ishga tushirish"""
    try:
        # WebSocket server (boshqa portda)
        ws_port = PORT + 1  # HTTP port + 1
        print(f"\n{'='*50}")
        print(f"🚀 SERVER ISHGA TUSHMOQDA")
        print(f"{'='*50}")
        print(f"📡 HTTP Health check: http://{HOST}:{PORT}")
        print(f"🔌 WebSocket: ws://{HOST}:{ws_port} yoki wss://your-domain.com")
        print(f"📊 Qurilmalar: 0")
        print(f"{'='*50}\n")
        
        async with websockets.serve(
            websocket_handler,
            HOST,
            ws_port,
            ping_interval=20,
            ping_timeout=20,
            max_size=10_485_760
        ):
            print(f"✅ WebSocket server ishga tushdi: port {ws_port}")
            await asyncio.Future()  # Cheksiz ishlaydi
            
    except Exception as e:
        print(f"❌ Server xatosi: {e}")
        sys.exit(1)

# --- Signal handler ---
def signal_handler(sig, frame):
    print("\n👋 Server to'xtatilmoqda...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server to'xtatildi")
    except Exception as e:
        print(f"❌ Kutilmagan xato: {e}")
        sys.exit(1)