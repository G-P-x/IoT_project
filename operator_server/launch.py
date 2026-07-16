from flask import Flask, request

app = Flask(__name__)

@app.route("/", methods = ['GET'])
def home():
    return {"connection": "success"}, 200


# Set up a route that listens for POST requests
@app.route('/webhook/OPERATOR', methods=['POST'])
def receive_payload():
    # Check if the incoming request contains JSON data
    print("RECEIVED ON OPERATOR")
    if request.is_json:
        payload = request.get_json()
        print("--- Received on OPERATOR Payload ---")
        try:
            message = dict(payload.get("message"))
        except Exception:
            print("conversion did't work")
            message = payload.get("message")
            with open("payload.txt", "a") as fl:
                fl.write(f"service: {payload.get("service")}\n")
                fl.write(f"status: {payload.get("service_status")}\n")
                fl.write(f"message: {message}\n\n\n")
    
        print("-----------------------------")
    else:
        # Fallback for raw text, form data, or other formats
        payload = request.get_data(as_text=True)
        print("--- Received Raw Payload ---")
        print(payload)
        print("----------------------------")

    # Respond to the client so it knows the request was successful
    return {"status": "success", "message": "Payload logged successfully"}, 200

@app.route('/webhook/ALERT', methods=['POST'])
def alert_payload():
    # Check if the incoming request contains JSON data
    if request.is_json:
        print("RECEIVED ON ALERT")
        payload = request.get_json()
        print("--- Received JSON Payload ---")
        print(payload)
        print("-----------------------------")
    else:
        # Fallback for raw text, form data, or other formats
        payload = request.get_data(as_text=True)
        print("--- Received Raw Payload ---")
        print(payload)
        print("----------------------------")

    # Respond to the client so it knows the request was successful
    return {"status": "success", "message": "Payload logged successfully"}, 200

@app.route('/webhook/FIELD', methods=['POST'])
def field_payload():
    # Check if the incoming request contains JSON data
    print("RECEIVED ON FIELD")
    if request.is_json:
        payload = request.get_json()
        
    else:
        # Fallback for raw text, form data, or other formats
        payload = request.get_data(as_text=True)
        print("--- Received Raw Payload ---")
        # print(payload)
        print("----------------------------")

    # Respond to the client so it knows the request was successful
    return {"status": "success", "message": "Payload logged successfully"}, 200
if __name__ == '__main__':
    # Start the server on port 5000
    print("Starting server on http://localhost:4500...")
    app.run(host='127.0.0.1', port=4500, debug=True)