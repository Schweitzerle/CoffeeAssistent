# llm_integration.py

# Überprüfe diese Import-Zeile
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
import json
import multiprocessing
import time
import re
from threading import Thread
from ollama import Client

# Konfiguration für Llama
MODEL_NAME = "llama3:latest"  # Ändere dies bei Bedarf
LLM_HOST = "http://localhost:11434"  # Anpassen an den Server, auf dem Ollama läuft

# Flask-App und SocketIO initialisieren
app = Flask(__name__)
app.config["SECRET_KEY"] = "kaffee123"
socketio = SocketIO(app)

# Globale Variablen
decision_tree_pipe = None
llm_client = None
bot_process = None
message_queue = []

# System-Prompt für das LLM
SYSTEM_PROMPT = """
Du bist ein hilfreicher Assistent für eine Kaffeemaschine. Deine Aufgabe ist es, Anfragen von Nutzern zu verstehen und ihnen zu helfen, einen leckeren Kaffee zuzubereiten.

Die Kaffeemaschine kann folgende Kaffeetypen zubereiten:
- Espresso
- Cappuccino
- Americano
- Latte Macchiato

Einstellungsmöglichkeiten:
- Stärke: very mild, mild, normal, strong, very strong, double shot, double shot +, double shot ++
- Temperatur: normal, high, very high
- Menge: abhängig vom Kaffeetyp (Espresso: 35-60ml, Cappuccino: 100-300ml, usw.)

Du erhältst JSON-Daten vom Entscheidungsbaum der Kaffeemaschine mit folgenden möglichen Schlüsseln:
- communicative_intent: greeting, inform, request_information
- wandke_choose_type, wandke_choose_strength, wandke_choose_temp, wandke_choose_quantity: Informationen über den aktuellen Auswahlzustand
- wandke_production_state: Informationen über den Produktionszustand
- type, strength, temp, quantity: Konkrete Werte für die Einstellungen

Antworte in natürlicher, freundlicher Sprache auf Deutsch, als wärst du eine hilfreiche Kaffeemaschine. 
Behalte die wesentlichen Informationen aus dem JSON bei, aber formatiere sie zu einem natürlichen Dialog.
"""


def init_llm_client():
    """Initialisiere den LLM-Client"""
    global llm_client
    try:
        llm_client = Client(host=LLM_HOST)
        print("LLM-Client erfolgreich initialisiert")
        return True
    except Exception as e:
        print(f"Fehler beim Initialisieren des LLM-Clients: {e}")
        return False


def json_to_llm_prompt(json_data):
    """Konvertiert JSON-Daten in einen Prompt für das LLM"""
    try:
        data = json.loads(json_data) if isinstance(json_data, str) else json_data

        # Informationen aus dem JSON extrahieren
        intent = data.get("communicative_intent", "")

        prompt = f"Die Kaffeemaschine sendet folgende Informationen: {json.dumps(data, indent=2, ensure_ascii=False)}\n\n"

        # Je nach Intent unterschiedliche Anweisungen hinzufügen
        if intent == "greeting":
            prompt += "Begrüße den Nutzer freundlich und frage, welchen Kaffee er möchte."

        elif intent == "request_information":
            if data.get("wandke_choose_type") == "in focus":
                prompt += "Frage den Nutzer, welchen Kaffeetyp er gerne hätte. Liste die verfügbaren Optionen auf."
            elif data.get("wandke_choose_strength") == "in focus":
                prompt += "Frage den Nutzer, wie stark der Kaffee sein soll. Erkläre die verfügbaren Optionen."
            elif data.get("wandke_choose_quantity") == "in focus":
                prompt += "Frage den Nutzer, wie viel Kaffee er möchte. Wenn der Kaffeetyp bereits gewählt wurde, nenne den passenden Mengenbereich."
            elif data.get("wandke_choose_temp") == "in focus":
                prompt += "Frage den Nutzer, wie heiß der Kaffee sein soll. Erkläre die verfügbaren Temperaturoptionen."
            elif data.get("wandke_production_state") == "in focus":
                prompt += "Frage den Nutzer, ob die Kaffeezubereitung gestartet werden soll."

        elif intent == "inform":
            # Bei Diagnosen wie 'UserRequestedValueTooLowForType' oder 'TypeNotYetSpecified'
            if data.get("wandke_choose_quantity") in ["UserRequestedValueTooLowForType",
                                                      "UserRequestedValueTooHighForType"]:
                prompt += "Erkläre dem Nutzer freundlich, dass die gewählte Menge nicht zum Kaffeetyp passt. Nenne die passenden Mengenbereiche."
            elif data.get("wandke_choose_quantity") == "TypeNotYetSpecified":
                prompt += "Erkläre dem Nutzer, dass zuerst ein Kaffeetyp gewählt werden muss, bevor die Menge festgelegt werden kann."
            elif data.get("wandke_production_state") == "ready":
                prompt += "Teile dem Nutzer mit, dass der Kaffee fertig zubereitet wird."
            elif any(key in data for key in ["type", "strength", "temp", "quantity"]):
                prompt += "Bestätige die vom Nutzer gewählte Einstellung und frage nach der nächsten Einstellung, falls noch nicht alle gewählt wurden."

        prompt += "\n\nFormuliere eine natürliche, freundliche Antwort auf Deutsch, die die Kaffeemaschine sagen würde:"
        return prompt

    except Exception as e:
        print(f"Fehler bei der Umwandlung von JSON zu Prompt: {e}")
        return f"Antworte auf die Nachricht vom Nutzer als freundliche Kaffeemaschine. JSON-Daten: {json_data}"


def process_with_llm(json_data):
    """Verarbeitet JSON-Daten mit dem LLM und gibt natürlichsprachliche Antwort zurück"""
    if not llm_client:
        if not init_llm_client():
            return "Entschuldigung, ich kann momentan nicht auf die Sprachverarbeitung zugreifen. Bitte versuche es später noch einmal."

    try:
        prompt = json_to_llm_prompt(json_data)

        response = llm_client.chat(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ]
        )

        return response['message']['content']
    except Exception as e:
        print(f"Fehler bei der LLM-Verarbeitung: {e}")
        return "Entschuldigung, bei der Verarbeitung ist ein Fehler aufgetreten. Wie kann ich dir mit deinem Kaffee helfen?"


def process_user_message(message):
    """Verarbeitet eine Nachricht vom Benutzer und leitet sie an den Entscheidungsbaum weiter"""
    global decision_tree_pipe

    try:
        # Nachricht an den Entscheidungsbaum senden
        # Hier müssten wir die natürlichsprachliche Nachricht analysieren und in JSON umwandeln
        # Das ist komplex und würde eigentlich ein eigenes NLU-System erfordern
        # Vereinfacht senden wir einfach ein JSON mit der Nachricht

        # Beispiel für einfache Schlüsselwort-Erkennung
        message_lower = message.lower()

        json_data = {"message": message}

        # Sehr einfache Erkennung von Kaffeetypen
        if any(coffee_type in message_lower for coffee_type in ["espresso", "cappuccino", "americano", "latte"]):
            for coffee_type in ["espresso", "cappuccino", "americano", "latte macchiato"]:
                if coffee_type in message_lower:
                    json_data = {
                        "communicative_intent": "inform",
                        "type": coffee_type.capitalize(),
                        "wandke_choose_type": "NoDiagnosis"
                    }
                    break

        # Erkennung von Stärke
        elif any(strength in message_lower for strength in ["mild", "stark", "strong", "normal", "double shot"]):
            for strength in ["very mild", "mild", "normal", "strong", "very strong", "double shot", "double shot +",
                             "double shot ++"]:
                if strength.lower() in message_lower:
                    json_data = {
                        "communicative_intent": "inform",
                        "strength": strength,
                        "wandke_choose_strength": "NoDiagnosis"
                    }
                    break

        # Erkennung von Temperatur
        elif any(temp in message_lower for temp in ["temperatur", "heiß", "warm", "temperature"]):
            for temp in ["normal", "high", "very high"]:
                if temp.lower() in message_lower:
                    json_data = {
                        "communicative_intent": "inform",
                        "temp": temp,
                        "wandke_choose_temp": "NoDiagnosis"
                    }
                    break

        # Erkennung von Menge (ml oder Zahlen)
        elif "ml" in message_lower or any(str(num) in message_lower for num in range(30, 401)):
            # Zahlen aus dem Text extrahieren
            numbers = re.findall(r'\d+', message_lower)
            if numbers:
                json_data = {
                    "communicative_intent": "inform",
                    "quantity": numbers[0],
                    "wandke_choose_quantity": "NoDiagnosis"
                }

        # Erkennung von Start/Bestätigung
        elif any(word in message_lower for word in ["start", "beginne", "mach", "los", "ok", "ja", "bitte"]):
            json_data = {
                "communicative_intent": "inform",
                "wandke_production_state": "started"
            }

        # Senden der Nachricht an den Entscheidungsbaum
        print(f"Sende an Entscheidungsbaum: {json_data}")
        decision_tree_pipe.send(json.dumps(json_data))

        return True
    except Exception as e:
        print(f"Fehler bei der Verarbeitung der Benutzernachricht: {e}")
        return False


def listen_to_decision_tree():
    """Hört auf Antworten vom Entscheidungsbaum und verarbeitet sie mit dem LLM"""
    global decision_tree_pipe, message_queue

    while True:
        if decision_tree_pipe and decision_tree_pipe.poll():
            # Nachricht vom Entscheidungsbaum empfangen
            tree_message = decision_tree_pipe.recv()
            print(f"Vom Entscheidungsbaum empfangen: {tree_message}")

            # Verarbeitung mit LLM
            llm_response = process_with_llm(tree_message)
            print(f"LLM-Antwort: {llm_response}")

            # An die Warteschlange für die Übertragung an den Client anhängen
            message_queue.append({
                "sender": "assistant",
                "message": llm_response,
                "raw_json": tree_message
            })

            # Über SocketIO an den Client senden
            socketio.emit("chat_message", {
                "sender": "assistant",
                "message": llm_response
            })

        time.sleep(0.1)


def start_bot_process():
    """Startet den Bot-Prozess und richtet die Kommunikation ein"""
    global decision_tree_pipe, bot_process

    from virtual_agent import create_chatbot

    # Pipe für die Kommunikation mit dem Bot erstellen
    parent_pipe, child_pipe = multiprocessing.Pipe()
    decision_tree_pipe = parent_pipe

    # Bot-Prozess starten
    bot_process = multiprocessing.Process(target=create_chatbot, args=(child_pipe,))
    bot_process.start()

    # Thread zum Abhören der Antworten starten
    listen_thread = Thread(target=listen_to_decision_tree)
    listen_thread.daemon = True
    listen_thread.start()

    print("Bot-Prozess und Kommunikation gestartet")


@app.route("/")
@app.route("/home")
def home():
    """Hauptseite der Anwendung"""
    return render_template("index.html", username=session.get("username", "Gast"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login-Seite"""
    if request.method == "POST":
        username = request.form["username"]
        session["username"] = username
        return redirect(url_for("home"))
    else:
        return render_template("login.html")


@socketio.on("connect")
def handle_connect():
    """Verbindung mit dem Client herstellen"""
    session["client_id"] = request.sid
    print(f"Client verbunden: {request.sid}")

    # Wenn der Bot-Prozess noch nicht läuft, starten
    global bot_process
    if bot_process is None or not bot_process.is_alive():
        start_bot_process()


@socketio.on("message")
def handle_message(data):
    """Nachricht vom Client verarbeiten"""
    sender = session.get("username", "Gast")
    message = data["message"]

    print(f"Nachricht von {sender}: {message}")

    # Nachricht an alle Clients senden
    emit(
        "chat_message",
        {
            "sender": sender,
            "message": message,
            "client_id": session.get("client_id"),
        },
        broadcast=True,
    )

    # Nachricht an den Entscheidungsbaum weiterleiten
    process_user_message(message)


@socketio.on("disconnect")
def handle_disconnect():
    """Verbindung mit dem Client trennen"""
    print(f"Client getrennt: {request.sid}")

    if "username" in session:
        username = session["username"]
        emit(
            "chat_message",
            {"sender": "System", "message": f"{username} hat den Chat verlassen"},
            broadcast=True,
        )
        session.pop("username", None)
        session.pop("client_id", None)


if __name__ == "__main__":
    # LLM-Client initialisieren
    init_llm_client()

    # Bot-Prozess starten
    start_bot_process()

    # Flask-App starten
    socketio.run(app, host="0.0.0.0", port=5001, debug=True)