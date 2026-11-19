"""Send one team payload to TESA MQTT (Python 3.10+).

Install: python -m pip install "paho-mqtt>=2,<3"
Run:     python scripts/mqtt-send.py

Uses secure WebSocket on port 443, just like the public TESA deployment.
The password is your team's MQTT key, NOT your website sign-in password.
Each run sends one message. Run again to submit a newer result.
"""

import getpass
import json
import ssl
import threading
import uuid

try:
    import paho.mqtt.client as mqtt
except ImportError:
    raise SystemExit('Install first: python -m pip install "paho-mqtt>=2,<3"')


def main():
    host = input("Host [tesa-score.c333m.site]: ").strip() or "tesa-score.c333m.site"
    if "/" in host or ":" in host:
        raise ValueError("Enter a hostname only, without https://, a path or port.")
    team_id = input("Team ID: ").strip()
    if not team_id or len(team_id) > 70:
        raise ValueError("Enter your Team ID (at most 70 characters).")
    password = getpass.getpass("Password (team MQTT key): ").strip()
    if not password or any(c in password for c in "/+#"):
        raise ValueError("Enter the MQTT key shown on your My Team page.")
    track = input("Track: Embedded / EdgeAI / Market [Embedded]: ").strip() or "Embedded"
    if track not in ("Embedded", "EdgeAI", "Market"):
        raise ValueError("Track must be Embedded, EdgeAI or Market (case-sensitive).")
    event = input("Event [1]: ").strip() or "1"
    if len(event) > 100 or any(c in "/+#" or ord(c) < 32 or ord(c) == 127 for c in event):
        raise ValueError("Event must be at most 100 characters, without /, +, # or control characters.")

    default_payload = '{"temperature":26,"humidity":60}'
    print("Enter a single-line JSON payload. Press Enter to send: " + default_payload)
    raw = input("Payload: ") or default_payload
    # Check JSON locally, but preserve the exact input bytes sent to the broker.
    json.loads(raw)
    payload = raw.encode("utf-8")
    if len(payload) > 65536:
        raise ValueError("Payload exceeds the broker's 64 KiB limit.")

    client_id = f"{team_id}:python-{uuid.uuid4().hex[:12]}"
    topic = f"/event/{password}/{track}/{event}"
    connected = threading.Event()
    acknowledged = threading.Event()
    connect_errors = []
    publish_errors = []

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            connect_errors.append(str(reason_code))
        connected.set()

    def on_publish(client, userdata, mid, reason_code, properties):
        if reason_code.is_failure:
            publish_errors.append(str(reason_code))
        acknowledged.set()

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        transport="websockets",
        protocol=mqtt.MQTTv5,
        reconnect_on_failure=False,
    )
    client.username_pw_set(team_id, password)
    client.ws_set_options(path="/mqtt/")
    client.tls_set_context(ssl.create_default_context())
    client.connect_timeout = 10
    client.on_connect = on_connect
    client.on_publish = on_publish

    print(f"Connecting to {host}:443/mqtt/ as {team_id}")
    print(f"Client ID: {client_id}")
    print(f"Topic: /event/<your MQTT key>/{track}/{event}")
    started = False
    try:
        client.connect(host, 443, keepalive=30)
        client.loop_start()
        started = True
        if not connected.wait(15):
            raise RuntimeError("Connection timed out. Check the host, /mqtt/ proxy and broker.")
        if connect_errors:
            raise RuntimeError("Login rejected: " + connect_errors[0])
        result = client.publish(topic, payload, qos=1, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError("Publish failed: " + mqtt.error_string(result.rc))
        if not acknowledged.wait(15):
            raise RuntimeError("No acknowledgement received. Check Admin before sending again.")
        if publish_errors:
            raise RuntimeError("Publish rejected: " + publish_errors[0])
        print("Broker acknowledged the message.")
        print(f"Check Admin > MQTT submissions: track {track}, event {event}, team {team_id}.")
        print("This message may replace the latest result for this team/track/event.")
    finally:
        client.disconnect()
        if started:
            client.loop_stop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("\nCancelled.")
    except Exception as exc:
        raise SystemExit(f"Error: {exc}")
