The operator can send a command via *POST request* using the ***url = "/commands/send"***

Upon receiving the request, the server operates this way:
```
def send():
    data = request.get_json()
    command_id = str(data.get("command_id")).lower()
    operator_id = str(data.get("issued_by")).lower()
    target = dict(data.get("target"))
    # Dispatch the command to the appropriate edge devices
    edge_results = dispatcher.send_command(command=command_id, target=target)
    return jsonify(edge_results)
```