# llm_integration.py

# Importe
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
import json
import multiprocessing
import time
import re
from threading import Thread
from ollama import Client
from datetime import datetime
import os
from datetime import datetime, timedelta

# Importe für FLAN-T5
from transformers import T5Tokenizer, T5ForConditionalGeneration
import torch

# Konfiguration für Llama
MODEL_NAME = "llama3:latest"  # Ändere dies bei Bedarf
LLM_HOST = "http://localhost:11434"  # Anpassen an den Server, auf dem Ollama läuft

# Flask-App und SocketIO initialisieren
app = Flask(__name__)
app.config["SECRET_KEY"] = "kaffee123"
# Setze Session-Timeout für das automatische Ausloggen
app.config["PERMANENT_SESSION_LIFETIME"] = 1800  # 30 Minuten in Sekunden
socketio = SocketIO(app)

# Globale Variablen
decision_tree_pipe = None
llm_client = None
bot_process = None
listen_thread = None
message_queue = []

# Logs-Verzeichnis erstellen, falls es nicht existiert
LOGS_FOLDER = "./logs"
if not os.path.exists(LOGS_FOLDER):
    os.makedirs(LOGS_FOLDER)

# System-Prompt für das LLM
# Ersetze den SYSTEM_PROMPT in llm_integration.py mit diesem verbesserten Prompt

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
- Menge: abhängig vom Kaffeetyp (Espresso: 35-60ml, Cappuccino: 100-300ml, Americano: 100-300ml, Latte Macchiato: 200-400ml)

WICHTIG - KONVERSATIONSKONTEXT:
- Behalte den gesamten bisherigen Konversationsverlauf im Gedächtnis
- Wenn der Nutzer bereits Parameter ausgewählt hat, beziehe dich in deinen Antworten darauf
- Gib klar an, welche Einstellungen bereits ausgewählt wurden und welche noch ausgewählt werden müssen
- Sei konsistent mit früheren Antworten und widerspreche dir nicht selbst

Du erhältst JSON-Daten vom Entscheidungsbaum der Kaffeemaschine mit folgenden möglichen Schlüsseln:
- communicative_intent: greeting, inform, request_information
- wandke_choose_type, wandke_choose_strength, wandke_choose_temp, wandke_choose_quantity: Informationen über den aktuellen Auswahlzustand
- wandke_production_state: Informationen über den Produktionszustand
- type, strength, temp, quantity: Konkrete Werte für die Einstellungen

Spezifische Anweisungen je nach Situation:
1. Wenn du nach dem Kaffeetyp fragst: Stelle alle verfügbaren Optionen vor
2. Wenn du nach der Stärke fragst: Erwähne zunächst den bereits gewählten Kaffeetyp
3. Wenn du nach der Temperatur fragst: Fasse die bisherigen Einstellungen (Typ, Stärke) zusammen
4. Wenn du nach der Menge fragst: Nenne den passenden Mengenbereich für den gewählten Kaffeetyp
5. Wenn alle Parameter ausgewählt wurden: Fasse alle Einstellungen zusammen und frage, ob der Kaffee so zubereitet werden soll

Antworte in natürlicher, freundlicher Sprache auf Deutsch, als wärst du eine hilfreiche Kaffeemaschine.
Gestalte die Konversation flüssig und natürlich, ohne künstlich zu wirken.
"""

# LLM-Interfaces und Implementierungen
class LLMInterface:
    def process_prompt(self, prompt, system_prompt=None):
        """Verarbeitet einen Prompt und gibt eine Antwort zurück"""
        raise NotImplementedError("Subklassen müssen diese Methode implementieren")


class TogetherLLM(LLMInterface):
    def __init__(self, model_name="togethercomputer/llama-3-8b-instruct"):
        self.model_name = model_name
        self.api_key = "YOUR_API_KEY"  # Besser aus Umgebungsvariablen laden
        self.base_url = "https://api.together.xyz/v1/completions"
        print(f"Together.ai LLM für {model_name} initialisiert")

    def process_prompt(self, prompt, system_prompt=SYSTEM_PROMPT):
        try:
            import requests

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": self.model_name,
                "prompt": f"{system_prompt}\n\n{prompt}",
                "max_tokens": 1024,
                "temperature": 0.7,
                "top_p": 0.9,
                "top_k": 50,
                "repetition_penalty": 1.0,
                "stop": ["</s>", "Human:", "human:", "Assistant:", "assistant:"]
            }

            response = requests.post(self.base_url, headers=headers, json=data)
            response.raise_for_status()

            result = response.json()
            return result['choices'][0]['text'].strip()
        except Exception as e:
            print(f"Fehler bei der Anfrage an Together.ai: {e}")
            return f"Entschuldigung, bei der Verarbeitung mit {self.model_name} ist ein Fehler aufgetreten: {e}"


class FLANT5LLM(LLMInterface):
    def __init__(self, model_name="google/flan-t5-base"):
        try:
            self.tokenizer = T5Tokenizer.from_pretrained(model_name)
            self.model = T5ForConditionalGeneration.from_pretrained(model_name)
            if torch.cuda.is_available():
                self.model = self.model.to("cuda")
            print(f"FLAN-T5 Modell {model_name} erfolgreich geladen")
        except Exception as e:
            print(f"Fehler beim Laden des FLAN-T5 Modells: {e}")
            self.tokenizer = None
            self.model = None

    def process_prompt(self, prompt, system_prompt=None):
        if not self.tokenizer or not self.model:
            return "FLAN-T5 Modell konnte nicht geladen werden."

        try:
            # Kombiniere System-Prompt und Benutzer-Prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"
            else:
                full_prompt = prompt

            # Tokenisiere und generiere
            inputs = self.tokenizer(full_prompt, return_tensors="pt", max_length=512, truncation=True)
            if torch.cuda.is_available():
                inputs = {k: v.to("cuda") for k, v in inputs.items()}

            outputs = self.model.generate(**inputs, max_length=150)

            # Dekodiere die Ausgabe
            result = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            return result
        except Exception as e:
            print(f"Fehler bei der Verarbeitung mit FLAN-T5: {e}")
            return f"Entschuldigung, bei der Verarbeitung mit FLAN-T5 ist ein Fehler aufgetreten: {e}"


class MockLLM(LLMInterface):
    """Ein Mock-LLM für Godel, da es nicht direkt verfügbar ist"""

    def __init__(self, model_name="godel"):
        self.model_name = model_name
        print(f"Mock-LLM für {model_name} initialisiert")

    def process_prompt(self, prompt, system_prompt=None):
        # Eine einfache Simulation von Godel-Antworten
        if "greeting" in prompt.lower():
            return "Hallo! Ich bin der Godel-Assistent für deine Kaffeemaschine. Wie kann ich dir helfen?"
        elif "type" in prompt.lower() and "focus" in prompt.lower():
            return "Welche Kaffeesorte möchtest du heute genießen? Ich kann dir Espresso, Cappuccino, Americano oder Latte Macchiato zubereiten."
        elif "strength" in prompt.lower() and "focus" in prompt.lower():
            return "Wie stark soll dein Kaffee sein? Du kannst zwischen sehr mild, mild, normal, stark, sehr stark oder einem Double Shot wählen."
        elif "quantity" in prompt.lower() and "focus" in prompt.lower():
            return "Wie viel Kaffee möchtest du? Die verfügbare Menge hängt von der gewählten Kaffeesorte ab."
        elif "temp" in prompt.lower() and "focus" in prompt.lower():
            return "Welche Temperatur bevorzugst du für deinen Kaffee? Normal, hoch oder sehr hoch?"
        elif "production" in prompt.lower() and "ready" in prompt.lower():
            return "Dein Kaffee ist fertig! Viel Genuss!"
        else:
            return f"Ich habe deine Anfrage verstanden. Als Godel-Assistent würde ich dir bei der Kaffeezubereitung helfen. Du hast Folgendes angefragt: {prompt}"


class LLMManager:
    def __init__(self):
        self.llms = {
            "llama3": TogetherLLM(model_name="togethercomputer/llama-3-8b-instruct"),
            "godel": MockLLM(model_name="godel"),
            "flant5": FLANT5LLM()
        }
        self.current_llm = "llama3"  # Standard-LLM

    def set_current_llm(self, llm_name):
        if llm_name in self.llms:
            self.current_llm = llm_name
            return True
        return False

    def process_prompt(self, prompt, system_prompt=SYSTEM_PROMPT):
        try:
            return self.llms[self.current_llm].process_prompt(prompt, system_prompt)
        except Exception as e:
            print(f"Fehler bei der Verarbeitung mit {self.current_llm}: {e}")
            return f"Entschuldigung, beim Verarbeiten mit {self.current_llm} ist ein Fehler aufgetreten: {e}"


# Initialisiere den LLM-Manager als globale Variable
llm_manager = LLMManager()


# Funktion zum Loggen von Benutzeraktivitäten
def log_user_activity(activity_type, user_data=None):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file = os.path.join(LOGS_FOLDER, "user_activity.log")

        if activity_type == "login":
            log_entry = f"{timestamp} - LOGIN: Benutzer: {user_data.get('username', 'unbekannt')}, Voller Name: {user_data.get('fullname', 'unbekannt')}, VP-ID: {user_data.get('vpid', 'unbekannt')}, LLM: {user_data.get('llm', 'unbekannt')}\n"
        elif activity_type == "logout":
            log_entry = f"{timestamp} - LOGOUT: Benutzer: {user_data.get('username', 'unbekannt')}\n"
        elif activity_type == "llm_change":
            log_entry = f"{timestamp} - LLM WECHSEL: Benutzer: {user_data.get('username', 'unbekannt')}, Neues LLM: {user_data.get('llm', 'unbekannt')}\n"
        else:
            log_entry = f"{timestamp} - {activity_type.upper()}: Benutzer: {user_data.get('username', 'unbekannt')}\n"

        with open(log_file, "a") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Fehler beim Loggen der Benutzeraktivität: {e}")


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


def start_bot_process():
    """Startet den Bot-Prozess und richtet die Kommunikation ein"""
    global decision_tree_pipe, bot_process, listen_thread

    # Wenn ein bestehender Prozess läuft, beenden
    if bot_process is not None and bot_process.is_alive():
        try:
            bot_process.terminate()
            bot_process.join(timeout=2)
            print("Bestehender Bot-Prozess beendet")
        except Exception as e:
            print(f"Fehler beim Beenden des bestehenden Bot-Prozesses: {e}")

    try:
        from virtual_agent import create_chatbot

        # Pipe für die Kommunikation mit dem Bot erstellen
        parent_pipe, child_pipe = multiprocessing.Pipe()
        decision_tree_pipe = parent_pipe

        # Bot-Prozess starten
        bot_process = multiprocessing.Process(target=create_chatbot, args=(child_pipe,))
        bot_process.daemon = True  # Prozess wird beendet, wenn Hauptprozess endet
        bot_process.start()

        # Verwalte die Hör-Threads
        if 'listen_thread' in globals() and listen_thread is not None and listen_thread.is_alive():
            print("Bestehender Listen-Thread läuft bereits")
        else:
            print("Starte neuen Listen-Thread")
            listen_thread = Thread(target=listen_to_decision_tree)
            listen_thread.daemon = True
            listen_thread.start()

        print(f"Bot-Prozess (PID {bot_process.pid}) und Kommunikation gestartet")
        return True
    except Exception as e:
        print(f"Fehler beim Starten des Bot-Prozesses: {e}")
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


# Globale Variablen für den Konversationskontext und Maschinenstatus
conversation_context = []
machine_state = {
    "type": None,
    "strength": None,
    "temp": None,
    "quantity": None
}


def process_with_llm(json_data):
    """Verarbeitet JSON-Daten mit dem LLM und gibt natürlichsprachliche Antwort zurück"""
    global llm_manager, conversation_context, machine_state

    try:
        # JSON-Daten analysieren, um den Maschinenstatus zu aktualisieren
        try:
            data = json.loads(json_data) if isinstance(json_data, str) else json_data

            # Maschinenstatus aktualisieren
            if "type" in data and data["type"] != "default":
                machine_state["type"] = data["type"]
            if "strength" in data and data["strength"] != "default":
                machine_state["strength"] = data["strength"]
            if "temp" in data and data["temp"] != "default":
                machine_state["temp"] = data["temp"]
            if "quantity" in data and data["quantity"] != "default":
                machine_state["quantity"] = data["quantity"]
        except:
            pass

        # Prompt für das LLM erstellen
        prompt = f"""
        Die Kaffeemaschine sendet folgende Informationen: {json.dumps(json_data, indent=2, ensure_ascii=False)}

        Aktueller Maschinenstatus:
        - Kaffeetyp: {machine_state["type"] or "noch nicht gewählt"}
        - Stärke: {machine_state["strength"] or "noch nicht gewählt"}
        - Temperatur: {machine_state["temp"] or "noch nicht gewählt"}
        - Menge: {machine_state["quantity"] or "noch nicht gewählt"}

        Bisheriger Konversationsverlauf:
        {json.dumps(conversation_context, indent=2, ensure_ascii=False)}

        Formuliere eine natürliche, freundliche Antwort auf Deutsch, die die Kaffeemaschine sagen würde.
        Beziehe dich auf den aktuellen Status und halte den Konversationsfluss aufrecht.
        """

        # LLM-Antwort generieren
        llm_response = llm_manager.process_prompt(prompt, SYSTEM_PROMPT)

        # Antwort zum Konversationskontext hinzufügen
        conversation_context.append({
            "role": "assistant",
            "content": llm_response
        })

        # Konversationskontext auf eine vernünftige Größe begrenzen (letzte 10 Nachrichten)
        if len(conversation_context) > 10:
            conversation_context = conversation_context[-10:]

        return llm_response
    except Exception as e:
        print(f"Fehler bei der LLM-Verarbeitung: {e}")
        return "Entschuldigung, bei der Verarbeitung ist ein Fehler aufgetreten. Wie kann ich dir mit deinem Kaffee helfen?"


def process_user_message(message):
    """Verarbeitet eine Nachricht vom Benutzer und leitet sie an den Entscheidungsbaum weiter"""
    global decision_tree_pipe, llm_client, conversation_context
    try:
        # Sende sofort eine Statusmeldung, dass die Verarbeitung beginnt (für UI)
        socketio.emit(
            "processing_status",
            {
                "type": "llm_json",
                "status": "started"
            }
        )

        # Nachricht zum Kontext hinzufügen
        conversation_context.append({
            "role": "user",
            "content": message
        })

        # LLM nutzen, um die Benutzereingabe zu interpretieren
        interpretation_prompt = f"""
        Als KI-Assistent für eine Kaffeemaschine sollst du Benutzereingaben interpretieren und in ein strukturiertes JSON-Format umwandeln.
        Die Kaffeemaschine unterstützt folgende Parameter:
        - Kaffeetypen: Espresso, Cappuccino, Americano, Latte Macchiato
        - Stärke: very mild, mild, normal, strong, very strong, double shot, double shot +, double shot ++
        - Temperatur: normal, high, very high
        - Menge: numerischer Wert in ml, abhängig vom Kaffeetyp (Espresso: 35-60ml, usw.)

        Analysiere die Benutzernachricht: "{message}"

        Erstelle ein JSON-Objekt mit NUR den erkannten Parametern. Füge KEINE Schlüssel mit null-Werten hinzu.
        Mögliche Felder sind:
        - "communicative_intent": "greeting", "inform", oder "request_information"
        - "type": Kaffeetyp (falls in der Nachricht erwähnt)
        - "strength": Stärke (falls in der Nachricht erwähnt)
        - "temp": Temperatur (falls in der Nachricht erwähnt)
        - "quantity": Menge in ml (falls in der Nachricht erwähnt)

        Für jeden erkannten Parameter (type, strength, temp, quantity) füge auch einen entsprechenden "wandke_choose_X": "NoDiagnosis" Eintrag hinzu.

        Beispiel:
        Wenn der Benutzer "Ich möchte einen Espresso" sagt, sollte das JSON nur sein:
        {{
          "communicative_intent": "inform",
          "type": "Espresso",
          "wandke_choose_type": "NoDiagnosis"
        }}

        Falls der Benutzer Start oder Bestätigung erwähnt, füge "wandke_production_state": "started" hinzu.
        Falls keine spezifischen Parameter erwähnt werden, aber die Nachricht eine Begrüßung ist, setze nur "communicative_intent": "greeting".

        Antworte NUR mit dem JSON-Objekt, ohne zusätzlichen Text oder Erklärungen.
        """

        # Interpret the user message using the LLM
        llm_response = llm_manager.process_prompt(interpretation_prompt)
        print(f"LLM-Interpretation der Benutzereingabe: {llm_response}")

        # Versuche, die LLM-Antwort als JSON zu parsen
        try:
            json_data = json.loads(llm_response)

            # Entferne alle Schlüssel mit None/null-Werten
            json_data = {k: v for k, v in json_data.items() if v is not None}

        except json.JSONDecodeError:
            # Wenn das LLM kein valides JSON zurückgibt, extrahiere es mit regex
            import re
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if json_match:
                try:
                    json_data = json.loads(json_match.group(0))
                    # Entferne alle Schlüssel mit None/null-Werten
                    json_data = {k: v for k, v in json_data.items() if v is not None}
                except:
                    # Fallback zur einfachen Nachricht
                    json_data = {"message": message}
            else:
                # Fallback zur einfachen Nachricht
                json_data = {"message": message}

        # Signalisiere, dass der JSON-Verarbeitungsschritt abgeschlossen ist
        socketio.emit(
            "processing_status",
            {
                "type": "llm_json",
                "status": "completed"
            }
        )

        # Sende eine Statusmeldung, dass der Entscheidungsbaum startet (für UI)
        socketio.emit(
            "processing_status",
            {
                "type": "decision_tree",
                "status": "started"
            }
        )

        # Senden der Nachricht an den Entscheidungsbaum
        print(f"Sende an Entscheidungsbaum: {json_data}")
        decision_tree_pipe.send(json.dumps(json_data))
        return True
    except Exception as e:
        print(f"Fehler bei der Verarbeitung der Benutzernachricht: {e}")
        # Informiere den Client über den Fehler (für UI)
        socketio.emit(
            "processing_status",
            {
                "type": "decision_tree",
                "status": "error",
                "error": str(e)
            }
        )
        return False

def listen_to_decision_tree():
    """Hört auf Antworten vom Entscheidungsbaum und verarbeitet sie mit dem LLM"""
    global decision_tree_pipe, message_queue

    while True:
        try:
            if decision_tree_pipe and decision_tree_pipe.poll():
                # Nachricht vom Entscheidungsbaum empfangen
                tree_message = decision_tree_pipe.recv()
                print(f"Vom Entscheidungsbaum empfangen: {tree_message}")

                # Signalisiere, dass der Entscheidungsbaum fertig ist und LLM beginnt (für UI)
                socketio.emit(
                    "processing_status",
                    {
                        "type": "decision_tree",
                        "status": "completed"
                    }
                )

                socketio.emit(
                    "processing_status",
                    {
                        "type": "llm",
                        "status": "started"
                    }
                )

                # Verarbeitung mit LLM
                llm_response = process_with_llm(tree_message)
                print(f"LLM-Antwort: {llm_response}")

                # Signalisiere, dass das LLM fertig ist (für UI)
                socketio.emit(
                    "processing_status",
                    {
                        "type": "llm",
                        "status": "completed"
                    }
                )

                # An die Warteschlange für die Übertragung an den Client anhängen
                message_id = int(time.time() * 1000)  # Unix-Timestamp in Millisekunden
                message_queue.append({
                    "sender": "assistant",
                    "message": llm_response,
                    "raw_json": tree_message,
                    "id": message_id
                })

                # Nur die LLM-Antwort über SocketIO an den Client senden
                # Füge eine eindeutige ID hinzu, um doppelte Nachrichten zu vermeiden
                socketio.emit("chat_message", {
                    "sender": "assistant",
                    "message": llm_response,
                    "id": message_id
                })

            time.sleep(0.1)
        except BrokenPipeError:
            print("Die Verbindung zum Entscheidungsbaum wurde unterbrochen. Versuche Neustart...")
            socketio.emit(
                "processing_status",
                {
                    "type": "decision_tree",
                    "status": "error",
                    "error": "Verbindung zum Entscheidungsbaum unterbrochen"
                }
            )
            time.sleep(5)  # Warte 5 Sekunden vor dem Versuch eines Neustarts
            try:
                start_bot_process()  # Versuche, den Bot-Prozess neu zu starten
            except Exception as e:
                print(f"Fehler beim Neustart des Bot-Prozesses: {e}")
                time.sleep(10)  # Warte länger, wenn der Neustart fehlschlägt
        except Exception as e:
            print(f"Fehler beim Abhören des Entscheidungsbaums: {e}")
            socketio.emit(
                "processing_status",
                {
                    "type": "llm",
                    "status": "error",
                    "error": str(e)
                }
            )
            time.sleep(2)


# Füge diesen Code zu llm_integration.py hinzu, um die Session-Lebensdauer zu verwalten

# Füge diesen Import hinzu, falls noch nicht vorhanden


@app.before_request
def before_request():
    """Verlängert die Session-Lebensdauer, wenn der Benutzer aktiv ist"""
    session.permanent = True
    app.permanent_session_lifetime = timedelta(minutes=30)  # 30 Minuten Timeout

    # Session-Ablaufzeit aktualisieren, wenn der Benutzer aktiv ist
    if 'username' in session:
        session.modified = True


@socketio.on("keep_alive")
def handle_keep_alive():
    """Behandelt Keep-Alive-Pings vom Client, um die Session aktiv zu halten"""
    if 'username' in session:
        session.modified = True
        return {"status": "success"}

# Flask-Routen
@app.route("/")
@app.route("/home")
def home():
    """Hauptseite der Anwendung"""
    # Überprüfe, ob ein Benutzer eingeloggt ist
    if "username" not in session:
        return redirect(url_for("login"))
    return render_template("index.html", username=session.get("username", "Gast"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login-Seite"""
    if request.method == "POST":
        # Formularfelder auslesen
        username = request.form.get("username", "")

        # Prüfen, ob der Benutzername vorhanden ist
        if not username:
            return render_template("login.html", error="Benutzername ist erforderlich")

        # Optionale Felder
        fullname = request.form.get("fullname", "")
        vpid = request.form.get("vpid", "")
        selected_llm = request.form.get("llm", "llama3")

        # In Session speichern
        session["username"] = username
        if fullname:
            session["fullname"] = fullname
        if vpid:
            session["vpid"] = vpid
        if selected_llm:
            session["selected_llm"] = selected_llm
            # Setze auch das aktuelle LLM
            llm_manager.set_current_llm(selected_llm)

        # Versuche Aktivität zu loggen, aber fahre fort auch wenn Logging fehlschlägt
        try:
            log_user_activity("login", {
                "username": username,
                "fullname": fullname,
                "vpid": vpid,
                "llm": selected_llm
            })
        except Exception as e:
            print(f"Fehler beim Loggen des Logins: {e}")

        return redirect(url_for("home"))
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Logout-Funktion"""
    username = session.get("username", "unbekannt")

    # Bot-Prozess beenden, wenn er existiert
    global bot_process
    if bot_process is not None and bot_process.is_alive():
        try:
            bot_process.terminate()
            bot_process.join(timeout=2)
            print(f"Bot-Prozess bei Logout von {username} beendet")
        except Exception as e:
            print(f"Fehler beim Beenden des Bot-Prozesses bei Logout: {e}")

    # Aktivität loggen, falls ein Benutzer eingeloggt war
    try:
        if "username" in session:
            log_user_activity("logout", {"username": username})
    except Exception as e:
        print(f"Fehler beim Loggen des Logouts: {e}")

    # Session leeren
    session.clear()

    return redirect(url_for("login"))


# Füge diese Funktion zu llm_integration.py hinzu, um den Konversationskontext zurückzusetzen

@app.route("/reset_context", methods=["POST"])
def reset_context():
    """Setzt den Konversationskontext zurück"""
    try:
        # Konversationskontext zurücksetzen
        session["conversation_context"] = []
        session["machine_state"] = {
            "type": None,
            "strength": None,
            "temp": None,
            "quantity": None
        }
        session.modified = True

        return jsonify({"status": "success", "message": "Konversationskontext wurde zurückgesetzt"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# Ändere auch die bestehende reset_bot Funktion, um den Kontext zurückzusetzen

@app.route("/reset_bot", methods=["POST"])
def reset_bot():
    """Setzt den Bot-Prozess und den Konversationskontext zurück, wenn er hängen bleibt"""
    try:
        # Bot-Prozess zurücksetzen
        start_bot_process()

        # Konversationskontext zurücksetzen
        if "conversation_context" in session:
            session["conversation_context"] = []
        if "machine_state" in session:
            session["machine_state"] = {
                "type": None,
                "strength": None,
                "temp": None,
                "quantity": None
            }
        session.modified = True

        return jsonify({"status": "success", "message": "Bot und Konversationskontext wurden zurückgesetzt"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/message", methods=["POST"])
def handle_synthetic_message():
    """Verarbeitet Nachrichten, die direkt vom Bot gesendet werden"""
    try:
        sender = request.form.get("username", "System")
        message = request.form.get("message", "")

        socketio.emit(
            "chat_message",
            {
                "sender": sender,
                "message": message,
            }
        )

        return jsonify({"status": "success"})
    except Exception as e:
        print(f"Fehler bei der Verarbeitung einer synthetischen Nachricht: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500




# Socket.IO-Events
@socketio.on("connect")
def handle_connect():
    """Verbindung mit dem Client herstellen"""
    # Überprüfe, ob ein Benutzer eingeloggt ist
    if "username" not in session:
        # Wenn kein Benutzer eingeloggt ist, lehne die Verbindung ab
        return False

    session["client_id"] = request.sid
    print(f"Client verbunden: {request.sid}")

    # Starte den Bot-Prozess neu, wenn ein Benutzer verbindet
    try:
        start_bot_process()

        # Sende eine Begrüßungsnachricht, dass der Bot gestartet wurde
        socketio.emit(
            "chat_message",
            {
                "sender": "System",
                "message": "Kaffee-Assistent wird gestartet..."
            },
            room=request.sid
        )

        # Setze das LLM aus der Session, falls verfügbar
        if "selected_llm" in session:
            llm_manager.set_current_llm(session["selected_llm"])
    except Exception as e:
        print(f"Fehler beim Starten des Bot-Prozesses: {e}")
        socketio.emit(
            "chat_message",
            {
                "sender": "System",
                "message": f"Fehler beim Starten des Kaffee-Assistenten: {e}"
            },
            room=request.sid
        )


# Finde in llm_integration.py auch die Funktion handle_message und ersetze sie mit folgendem Code,
# um eindeutige IDs für Benutzernachrichten hinzuzufügen:

@socketio.on("message")
def handle_message(data):
    """Nachricht vom Client verarbeiten"""
    sender = session.get("username", "Gast")
    message = data["message"]
    message_id = int(time.time() * 1000)  # Unix-Timestamp in Millisekunden

    print(f"Nachricht von {sender}: {message}")

    # Nachricht an alle Clients senden
    emit(
        "chat_message",
        {
            "sender": sender,
            "message": message,
            "client_id": session.get("client_id"),
            "id": message_id
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
        # Benutzername und Client-ID werden erst beim nächsten Login entfernt


@socketio.on("select_llm")
def handle_llm_selection(data):
    """Verarbeitet die Auswahl eines LLMs"""
    global llm_manager

    llm_name = data.get("llm", "llama3")
    username = session.get("username", "unbekannt")

    if llm_manager.set_current_llm(llm_name):
        # Aktualisiere die Session mit der neuen LLM-Auswahl
        session["selected_llm"] = llm_name

        # Aktivität loggen
        log_user_activity("llm_change", {
            "username": username,
            "llm": llm_name
        })

        emit(
            "chat_message",
            {
                "sender": "System",
                "message": f"LLM gewechselt zu: {llm_name}",
            },
            broadcast=True,
        )
    else:
        emit(
            "chat_message",
            {
                "sender": "System",
                "message": f"Fehler: LLM {llm_name} ist nicht verfügbar.",
            },
        )


# Füge diese neue Route zur llm_integration.py hinzu
@socketio.on("message_rating")
def handle_message_rating(data):
    """Verarbeitet die Bewertung einer Nachricht"""
    try:
        message_id = data.get("messageId", "unbekannt")
        rating = data.get("rating", 0)
        username = session.get("username", "unbekannt")

        print(f"Bewertung erhalten: Nachricht {message_id} von {username} mit {rating}/7 bewertet")

        # Logge die Bewertung
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file = os.path.join(LOGS_FOLDER, "message_ratings.log")

        log_entry = f"{timestamp} - BEWERTUNG: Benutzer: {username}, Nachricht-ID: {message_id}, Bewertung: {rating}/7\n"

        with open(log_file, "a") as f:
            f.write(log_entry)

        # Bestätigung an den Client senden
        return {"status": "success"}
    except Exception as e:
        print(f"Fehler bei der Verarbeitung der Nachrichtenbewertung: {e}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    # Session-Datei löschen, wenn vorhanden (für Entwicklungsumgebung)
    import os

    try:
        if os.path.exists("flask_session"):
            import shutil

            shutil.rmtree("flask_session")
        # Alternative: Flask verwendet standardmäßig einen signierten Cookie
        app.config["SESSION_TYPE"] = "filesystem"
        app.config["SESSION_FILE_DIR"] = "./flask_session"
        from flask_session import Session

        Session(app)
    except Exception as e:
        print(f"Info: Konnte Session nicht löschen: {e}")

    # LLM-Client initialisieren
    init_llm_client()

    # Bot-Prozess wird nicht mehr hier gestartet, sondern erst wenn ein Client verbindet

    # Flask-App starten
    socketio.run(app, host="0.0.0.0", port=5001, debug=True)