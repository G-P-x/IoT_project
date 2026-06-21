"""
Test standalone CoAP: invia un POST all'ESP e aspetta la risposta.
NON serve il gateway in esecuzione.
Esegui: python coap_standalone_test.py
"""
import socket
import struct
import json
import time

ESP_HOST    = "10.162.53.78"
ESP_PORT    = 5683
LOCAL_PORT  = 5684          # porta locale fissa
TIMEOUT     = 10.0
PATH        = "cmd"
PAYLOAD     = json.dumps({"command": "cmd_01", "sensors": []}).encode()

# ── Costruisce pacchetto CoAP CON POST ──────────────────────────────────────
msg_id = 0x1234
header = struct.pack("!BBH", 0x40, 0x02, msg_id)         # CON POST
path_b = PATH.encode()
option = bytes([(0xB << 4) | len(path_b)]) + path_b      # Uri-Path
packet = header + option + b"\xff" + PAYLOAD

print("=" * 55)
print(f"  Invio CoAP POST a {ESP_HOST}:{ESP_PORT}/{PATH}")
print(f"  Porta locale: {LOCAL_PORT}")
print(f"  Payload: {PAYLOAD.decode()}")
print(f"  Pacchetto hex: {packet.hex(' ')}")
print("=" * 55)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

try:
    sock.bind(("0.0.0.0", LOCAL_PORT))
    print(f"[OK] Socket bindato su 0.0.0.0:{LOCAL_PORT}")
except OSError as e:
    print(f"[ERR] Bind fallito: {e}")
    print("      Porta occupata? Chiudi il gateway prima di eseguire questo test.")
    exit(1)

sock.settimeout(TIMEOUT)
sock.sendto(packet, (ESP_HOST, ESP_PORT))
print(f"[>>] Pacchetto inviato alle {time.strftime('%H:%M:%S')}")
print(f"     In attesa di risposta per {TIMEOUT}s...")

try:
    while True:
        data, addr = sock.recvfrom(4096)
        print(f"\n[<<] RICEVUTO {len(data)} bytes da {addr}")
        print(f"     hex: {data.hex(' ')}")

        # Estrai payload (cerca 0xFF marker)
        tkl = data[0] & 0x0F
        idx = 4 + tkl
        payload_raw = b""
        while idx < len(data):
            if data[idx] == 0xFF:
                payload_raw = data[idx+1:]
                break
            # salta opzione
            ln = data[idx] & 0x0F
            idx += 1 + ln

        if payload_raw:
            try:
                decoded = json.loads(payload_raw)
                print(f"\n[OK] PAYLOAD JSON:")
                print(json.dumps(decoded, indent=2))
                print("\n[SUCCESSO] La comunicazione funziona!")
            except Exception as e:
                print(f"     payload raw (non JSON): {payload_raw}")
        else:
            coap_code = data[1] if len(data) > 1 else 0
            print(f"     code=0x{coap_code:02X} — ACK vuoto o risposta senza payload, aspetto ancora...")

except socket.timeout:
    print(f"\n[TIMEOUT] Nessuna risposta in {TIMEOUT}s")
    print()
    print("Possibili cause:")
    print("  1. Windows Firewall blocca UDP in ingresso su porta 5684")
    print("     -> Esegui come Admin in PowerShell:")
    print('     netsh advfirewall firewall add rule name="CoAP_Test" protocol=UDP dir=in localport=5684 action=allow')
    print()
    print("  2. Il pacchetto non raggiunge l'ESP (verifica che l'ESP sia online)")
    print("     -> Prova: ping 10.162.53.78")
    print()
    print("  3. La risposta dell'ESP va su una porta diversa")
    print("     -> Esegui Wireshark su questa macchina e filtra: udp and ip.src==10.162.53.78")

finally:
    sock.close()