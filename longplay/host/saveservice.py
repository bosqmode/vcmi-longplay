import os
import socket

SOCKET_PATH = "/tmp/longplay-autosave.sock"

if os.path.exists(SOCKET_PATH):
    os.remove(SOCKET_PATH)

print(f"Starting UNIX domain socket server at {SOCKET_PATH}...")

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
    server.bind(SOCKET_PATH)
    server.listen(1)  # Listen for 1 connection at a time
    
    try:
        while True:
            print("\nWaiting for an event from C++...")
            connection, client_address = server.accept()
            
            with connection:
                print("C++ application connected!")
                buffer = ""
                
                while True:
                    data = connection.recv(1024).decode('utf-8')
                    if not data:
                        break
                    
                    buffer += data
                    if '\n' in buffer:
                        # Split the path from the rest of the stream
                        filepath, _ = buffer.split('\n', 1)
                        
                        print(f"[EVENT TRIGGERED] Python received filepath: {filepath}")
                        
                        f = open("/home/abc/saveservicelog.txt", "w")
                        f.write(filepath)
                        f.close()

                        break
                        
    except Exception as e:
        print(e)
    finally:
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)


print("Saveservice finished???")