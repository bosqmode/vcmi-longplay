import os
import socket
import requests

SOCKET_PATH = "/tmp/longplay-autosave.sock"
POST_SAVE_URL = "http://saveserver:8000/saves"

if os.path.exists(SOCKET_PATH):
    os.remove(SOCKET_PATH)

print(f"Starting UNIX domain socket server at {SOCKET_PATH}...")

def upload_save_post(filepath: str):
    print(f"saveservice.py::posting {filepath} to {POST_SAVE_URL}")

    with open(filepath, 'rb') as f:
        files = {'file': f}
        response = requests.post(POST_SAVE_URL, files=files)

    if response.status_code == 200:
        print(f"Successfully uploaded save to endpoint {POST_SAVE_URL}")
    else:
        print(f"Failed posting saves: {response.status_code}")

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
    server.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o666)
    server.listen(1)  # Listen for 1 connection at a time
    
    try:
        while True:
            print("\nWaiting for an event from C++...")
            connection, client_address = server.accept()
            
            with connection:
                print("saveservice.py::CONNECTION")
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
                        
                        upload_save_post(filepath)

                        break
                        
    except Exception as e:
        print(e)
    finally:
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)


print("Saveservice finished???")