import py_trees
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
import json
import multiprocessing
import time
import re
from threading import Thread
from datetime import datetime
import os
from datetime import datetime, timedelta
import requests

os.environ["OPENROUTER_API_KEY"] = "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"

app = Flask(__name__)
app.config["SECRET_KEY"] = "kaffee123"
app.config["PERMANENT_SESSION_LIFETIME"] = 1800  # 30 Minuten in Sekunden
socketio = SocketIO(app)

# Globale Variablen
decision_tree_pipe = None
bot_process = None
listen_thread = None
message_queue = []

# Logs-Verzeichnis erstellen, falls es nicht existiert
LOGS_FOLDER = "./logs"
if not os.path.exists(LOGS_FOLDER):
    os.makedirs(LOGS_FOLDER)

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


class LLMInterface:
    def process_prompt(self, prompt, system_prompt=None):
        """Verarbeitet einen Prompt und gibt eine Antwort zurück"""
        raise NotImplementedError("Subklassen müssen diese Methode implementieren")


class OpenRouterLLM(LLMInterface):
    def __init__(self, model_name="meta-llama/llama-3-8b-instruct:free", is_free=True):
        """
        Initialisiert die OpenRouter API mit dem OpenAI SDK.

        Args:
            model_name (str): Der vollständige Modellname bei OpenRouter
            is_free (bool): Zeigt an, ob das Modell kostenlos ist
        """
        self.model_name = model_name
        self.is_free = is_free
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")

        if not self.api_key:
            print("WARNUNG: OPENROUTER_API_KEY nicht gesetzt!")
            self.client = None
            self.client_available = False
        else:
            try:
                from openai import OpenAI

                self.client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=self.api_key,
                )

                self.client_available = True
                print(f"OpenRouter API für {model_name} erfolgreich initialisiert")
            except ImportError:
                print("WARNUNG: 'openai' Paket nicht installiert. Führen Sie 'pip install openai' aus.")
                self.client = None
                self.client_available = False
            except Exception as e:
                print(f"Fehler bei der Initialisierung der OpenRouter API: {e}")
                self.client = None
                self.client_available = False

    def process_prompt(self, prompt, system_prompt=None):
        """Verarbeitet einen Prompt mit der OpenRouter API"""
        if not self.client_available:
            return self._fallback_response(prompt)

        try:
            messages = []

            # Fügt System-Prompt hinzu, wenn vorhanden
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})

            # Fügt Benutzer-Prompt hinzu
            messages.append({"role": "user", "content": prompt})

            completion = self.client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "https://kaffee-assistant.de",
                    "X-Title": "Kaffee-Assistent",
                },
                model=self.model_name,
                messages=messages,
                temperature=0.7,
                max_tokens=800
            )

            # Extrahiert und gibt die Antwort zurück
            return completion.choices[0].message.content

        except Exception as e:
            print(f"Fehler bei der Anfrage an OpenRouter API mit Modell {self.model_name}: {e}")
            return self._fallback_response(prompt)

    def _fallback_response(self, prompt):
        """Fallback-Antwort falls die Generierung fehlschlägt"""
        if "greeting" in prompt.lower():
            return "Hallo! Ich bin dein Kaffee-Assistent. Wie kann ich dir heute helfen? Möchtest du einen leckeren Kaffee zubereiten?"

        elif "wandke_choose_type" in prompt.lower() and "in focus" in prompt.lower():
            return "Welche Art von Kaffee möchtest du? Ich biete Espresso, Cappuccino, Americano oder Latte Macchiato an."

        elif "wandke_choose_strength" in prompt.lower() and "in focus" in prompt.lower():
            return "Wie stark soll dein Kaffee sein? Du kannst zwischen very mild, mild, normal, stark, sehr stark oder einem Double Shot wählen."

        elif "wandke_choose_quantity" in prompt.lower() and "in focus" in prompt.lower():
            if "Espresso" in prompt:
                return "Wie viel Espresso möchtest du? Du kannst zwischen 35ml und 60ml wählen."
            elif "Cappuccino" in prompt:
                return "Wie viel Cappuccino möchtest du? Du kannst zwischen 100ml und 300ml wählen."
            elif "Americano" in prompt:
                return "Wie viel Americano möchtest du? Du kannst zwischen 100ml und 300ml wählen."
            elif "Latte" in prompt:
                return "Wie viel Latte Macchiato möchtest du? Du kannst zwischen 200ml und 400ml wählen."
            else:
                return "Wie viel Kaffee möchtest du? Die verfügbare Menge hängt von der gewählten Kaffeesorte ab."

        elif "wandke_choose_temp" in prompt.lower() and "in focus" in prompt.lower():
            return "Welche Temperatur bevorzugst du für deinen Kaffee? Du kannst zwischen normal, hoch und sehr hoch wählen."

        elif "wandke_production_state" in prompt.lower() and "ready" in prompt.lower():
            return "Dein Kaffee ist fertig! Genieße deinen Kaffee. War sonst noch etwas?"

        else:
            return "Ich verstehe deine Anfrage. Wie kann ich dir mit deinem Kaffee helfen?"


class LLMManager:
    def __init__(self):
        self.llms = {
            # OpenRouter Modelle (kostenlos)
            "llama3-8b": OpenRouterLLM(model_name="meta-llama/llama-3-8b-instruct:free"),
            "phi3-mini": OpenRouterLLM(model_name="microsoft/phi-3-mini-128k-instruct:free"),
            "openchat-3.5": OpenRouterLLM(model_name="openchat/openchat-7b:free")
        }
        self.current_llm = "llama3-8b"  # Standard-LLM

    def set_current_llm(self, llm_name):
        if llm_name in self.llms:
            self.current_llm = llm_name
            return True
        return False

    def process_prompt(self, prompt, system_prompt=None):
        try:
            result = self.llms[self.current_llm].process_prompt(prompt, system_prompt)

            if "role" in result or "user_choice" in result or result.strip().startswith(
                    "{") or result.strip().startswith("["):
                print(f"Fehlerhafte Antwort vom Modell {self.current_llm}, verwende Fallback")
                return self._fallback_response(prompt)

            return result
        except Exception as e:
            print(f"Fehler bei der Verarbeitung mit {self.current_llm}: {e}")
            # Versuche, auf Llama 3 zurückzufallen, wenn ein anderes Modell fehlschlägt
            if self.current_llm != "llama3-8b":
                try:
                    print(f"Versuche Fallback auf Llama 3 8B...")
                    return self.llms["llama3-8b"].process_prompt(prompt, system_prompt)
                except Exception as fallback_error:
                    print(f"Auch Fallback auf Llama 3 fehlgeschlagen: {fallback_error}")

            return self._fallback_response(prompt)

    def _fallback_response(self, prompt):
        """Fallback-Antwort falls alle LLMs fehlschlagen"""
        if "greeting" in prompt.lower():
            return "Hallo! Ich bin dein Kaffee-Assistent. Wie kann ich dir heute helfen? Möchtest du einen leckeren Kaffee zubereiten?"

        elif "wandke_choose_type" in prompt.lower() and "in focus" in prompt.lower():
            return "Welche Art von Kaffee möchtest du? Ich biete Espresso, Cappuccino, Americano oder Latte Macchiato an."

        elif "wandke_choose_strength" in prompt.lower() and "in focus" in prompt.lower():
            return "Wie stark soll dein Kaffee sein? Du kannst zwischen very mild, mild, normal, stark, sehr stark oder einem Double Shot wählen."

        elif "wandke_choose_quantity" in prompt.lower() and "in focus" in prompt.lower():
            if "Espresso" in prompt:
                return "Wie viel Espresso möchtest du? Du kannst zwischen 35ml und 60ml wählen."
            elif "Cappuccino" in prompt:
                return "Wie viel Cappuccino möchtest du? Du kannst zwischen 100ml und 300ml wählen."
            elif "Americano" in prompt:
                return "Wie viel Americano möchtest du? Du kannst zwischen 100ml und 300ml wählen."
            elif "Latte" in prompt:
                return "Wie viel Latte Macchiato möchtest du? Du kannst zwischen 200ml und 400ml wählen."
            else:
                return "Wie viel Kaffee möchtest du? Die verfügbare Menge hängt von der gewählten Kaffeesorte ab."

        elif "wandke_choose_temp" in prompt.lower() and "in focus" in prompt.lower():
            return "Welche Temperatur bevorzugst du für deinen Kaffee? Du kannst zwischen normal, hoch und sehr hoch wählen."

        elif "wandke_production_state" in prompt.lower() and "ready" in prompt.lower():
            return "Dein Kaffee ist fertig! Genieße deinen Kaffee. War sonst noch etwas?"

        else:
            return "Ich verstehe deine Anfrage. Wie kann ich dir mit deinem Kaffee helfen?"


# Erstelle den LLM-Manager
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

        # Kurze Pause, um den Bot-Prozess zu initialisieren
        time.sleep(0.5)

        # Prüft, ob der Prozess gestartet ist
        if not bot_process.is_alive():
            print("WARNUNG: Bot-Prozess wurde gestartet, scheint aber nicht zu laufen!")
            return False

        if listen_thread is not None and listen_thread.is_alive():
            print("Bestehender Listen-Thread läuft bereits")
        else:
            print("Starte neuen Listen-Thread")
            listen_thread = Thread(target=listen_to_decision_tree)
            listen_thread.daemon = True
            listen_thread.start()

        print(f"Bot-Prozess (PID {bot_process.pid}) und Kommunikation gestartet")

        try:
            greeting_message = {"communicative_intent": "greeting"}
            decision_tree_pipe.send(json.dumps(greeting_message))
            print("Begrüßungsnachricht an den Bot gesendet")
        except Exception as greeting_error:
            print(f"Fehler beim Senden der Begrüßungsnachricht: {greeting_error}")

        return True
    except Exception as e:
        print(f"Fehler beim Starten des Bot-Prozesses: {e}")
        import traceback
        traceback.print_exc()
        return False


def update_machine_state_from_user_selection(json_data):
    """Aktualisiert den machine_state direkt basierend auf der Benutzereingabe"""
    global machine_state

    try:
        # Direkte Aktualisierung aus dem JSON
        if isinstance(json_data, dict):
            if "type" in json_data and json_data["type"]:
                machine_state["type"] = json_data["type"]
                print(f"Machine state direkt aktualisiert: type = {json_data['type']}")

            if "strength" in json_data and json_data["strength"]:
                machine_state["strength"] = json_data["strength"]
                print(f"Machine state direkt aktualisiert: strength = {json_data['strength']}")

            if "temp" in json_data and json_data["temp"]:
                machine_state["temp"] = json_data["temp"]
                print(f"Machine state direkt aktualisiert: temp = {json_data['temp']}")

            if "quantity" in json_data and json_data["quantity"]:
                machine_state["quantity"] = json_data["quantity"]
                print(f"Machine state direkt aktualisiert: quantity = {json_data['quantity']}")
    except Exception as e:
        print(f"Fehler bei direkter Aktualisierung des machine_state: {e}")


def is_start_command(message):
    """Prüft, ob eine Nachricht ein Startbefehl für die Kaffeezubereitung ist"""
    start_commands = ["ja", "starten", "start", "kaffee machen", "kaffee starten",
                      "los", "machen", "beginnen", "zubereiten", "ok"]

    # Nachricht normalisieren (Kleinbuchstaben, Leerzeichen entfernen)
    message_lower = message.lower().strip()

    # Prüft auf exakte Übereinstimmung oder als Teil der Nachricht
    return any(cmd == message_lower or cmd in message_lower.split() for cmd in start_commands)


def process_user_message(message):
    """Verarbeitet eine Nachricht vom Benutzer und leitet sie an den Entscheidungsbaum weiter"""
    global decision_tree_pipe, conversation_context, machine_state
    try:
        # Sendet sofort eine Statusmeldung, dass die Verarbeitung beginnt (für UI)
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

        # Bestimmt den aktuellen Fokus basierend auf dem letzten Zustand des Entscheidungsbaums
        current_focus = None
        if len(conversation_context) > 1 and len(message_queue) > 0 and "raw_json" in message_queue[-1]:
            try:
                last_message = json.loads(message_queue[-1]["raw_json"])
                if "wandke_choose_type" in last_message and last_message["wandke_choose_type"] == "in focus":
                    current_focus = "type"
                elif "wandke_choose_strength" in last_message and last_message["wandke_choose_strength"] == "in focus":
                    current_focus = "strength"
                elif "wandke_choose_quantity" in last_message and last_message["wandke_choose_quantity"] == "in focus":
                    current_focus = "quantity"
                elif "wandke_choose_temp" in last_message and last_message["wandke_choose_temp"] == "in focus":
                    current_focus = "temp"
                elif "wandke_production_state" in last_message and last_message[
                    "wandke_production_state"] == "in focus":
                    current_focus = "production"
            except Exception as e:
                print(f"Fehler beim Extrahieren des aktuellen Fokus: {e}")

        print(f"Aktueller Fokus des Entscheidungsbaums: {current_focus or 'unbekannt'}")

        if current_focus == "production" and is_start_command(message):
            print(f"Startbefehl erkannt: '{message}' - Starte Kaffeezubereitung direkt")
            json_data = {
                "communicative_intent": "inform",
                "wandke_production_state": "started"
            }

            # Signalisiert, dass der JSON-Verarbeitungsschritt abgeschlossen ist
            socketio.emit(
                "processing_status",
                {
                    "type": "llm_json",
                    "status": "completed"
                }
            )

            # Sendt eine Statusmeldung, dass der Entscheidungsbaum startet
            socketio.emit(
                "processing_status",
                {
                    "type": "decision_tree",
                    "status": "started"
                }
            )

            # Loggt das JSON für Debug-Zwecke
            print(f"Sende direkt an Entscheidungsbaum: {json_data}")

            # Senden der Nachricht an den Entscheidungsbaum
            decision_tree_pipe.send(json.dumps(json_data))
            return True

        message_lower = message.lower()
        is_question = False
        question_indicators = ["was", "wie", "welche", "wann", "wo", "warum", "wieso", "wer", "?", "unterschied",
                               "bedeutet", "erkläre", "nochmal", "gibt es", "zeige", "nenne", "liste", "optionen",
                               "verfügbar"]

        for indicator in question_indicators:
            if indicator in message_lower:
                is_question = True
                break

        info_request_keywords = {
            "strength": ["stärke", "stark", "mild", "intensiv", "double shot", "kräftig"],
            "quantity": ["menge", "milliliter", "ml", "groß", "klein", "viel", "wenig"],
            "temp": ["temperatur", "heiß", "kalt", "warm", "grad"],
            "type": ["sorte", "kaffee", "espresso", "cappuccino", "americano", "latte", "macchiato"]
        }

        requested_info_type = None
        for info_type, keywords in info_request_keywords.items():
            if any(keyword in message_lower for keyword in keywords):
                if is_question:
                    requested_info_type = info_type
                    break

        is_direct_value = False
        direct_value = None

        if current_focus == "strength":
            strength_values = ["very mild", "mild", "normal", "strong", "very strong", "double shot", "double shot +",
                               "double shot ++"]
            for value in strength_values:
                if value.lower() == message_lower or (value.lower() == "normal" and "normal" in message_lower):
                    is_direct_value = True
                    direct_value = value
                    break

        elif current_focus == "temp":
            temp_values = ["normal", "high", "very high"]
            for value in temp_values:
                if value.lower() in message_lower:
                    is_direct_value = True
                    direct_value = value
                    break

        elif current_focus == "type":
            type_values = ["Espresso", "Cappuccino", "Americano", "Latte Macchiato"]
            for value in type_values:
                if value.lower() in message_lower:
                    is_direct_value = True
                    direct_value = value
                    break
                # Zusätzliche Prüfung für Tippfehler
                elif value.lower().startswith(message_lower) or message_lower.startswith(value.lower()):
                    is_direct_value = True
                    direct_value = value
                    break

        elif current_focus == "quantity":
            import re
            quantity_match = re.search(r'(\d+)', message_lower)
            if quantity_match:
                is_direct_value = True
                direct_value = quantity_match.group(1)

        # Wenn eine direkte Wertangabe erkannt wurde, erstellt ein entsprechendes JSON
        if is_direct_value and direct_value and not is_question:
            print(f"Direkte Wertangabe erkannt: {direct_value} für {current_focus}")
            json_data = {"communicative_intent": "inform"}

            if current_focus == "type":
                json_data["type"] = direct_value
                json_data["wandke_choose_type"] = "NoDiagnosis"
                machine_state["type"] = direct_value  # Direkte Aktualisierung
                print(f"Machine state direkt aktualisiert: type = {direct_value}")
            elif current_focus == "strength":
                json_data["strength"] = direct_value
                json_data["wandke_choose_strength"] = "NoDiagnosis"
                machine_state["strength"] = direct_value  # Direkte Aktualisierung
                print(f"Machine state direkt aktualisiert: strength = {direct_value}")
            elif current_focus == "temp":
                json_data["temp"] = direct_value
                json_data["wandke_choose_temp"] = "NoDiagnosis"
                machine_state["temp"] = direct_value  # Direkte Aktualisierung
                print(f"Machine state direkt aktualisiert: temp = {direct_value}")
            elif current_focus == "quantity":
                json_data["quantity"] = direct_value
                json_data["wandke_choose_quantity"] = "NoDiagnosis"
                machine_state["quantity"] = direct_value  # Direkte Aktualisierung
                print(f"Machine state direkt aktualisiert: quantity = {direct_value}")

            # Signalisiert, dass der JSON-Verarbeitungsschritt abgeschlossen ist
            socketio.emit(
                "processing_status",
                {
                    "type": "llm_json",
                    "status": "completed"
                }
            )

            # Sendet eine Statusmeldung, dass der Entscheidungsbaum startet (für UI)
            socketio.emit(
                "processing_status",
                {
                    "type": "decision_tree",
                    "status": "started"
                }
            )

            print(f"Sende an Entscheidungsbaum: {json_data}")

            # Senden der Nachricht an den Entscheidungsbaum
            decision_tree_pipe.send(json.dumps(json_data))
            return True

        if is_question:
            if requested_info_type and current_focus and requested_info_type == current_focus:
                # Erstellt eine detaillierte Informationsantwort für den aktuellen Fokus
                info_json = {"communicative_intent": "request_information"}
                if current_focus == "type":
                    info_json["wandke_choose_type"] = "in focus"
                elif current_focus == "strength":
                    info_json["wandke_choose_strength"] = "in focus"
                elif current_focus == "temp":
                    info_json["wandke_choose_temp"] = "in focus"
                elif current_focus == "quantity":
                    info_json["wandke_choose_quantity"] = "in focus"

                print(
                    f"Erkannte Informationsanfrage über {requested_info_type} im aktuellen Fokus, generiere LLM-Antwort")

                # Generiert eine maßgeschneiderte LLM-Antwort
                llm_info_prompt = create_info_prompt(current_focus, machine_state)
                detailed_info = llm_manager.process_prompt(llm_info_prompt, SYSTEM_PROMPT)

                # Erstellt eine einzigartige ID für die Nachricht
                message_id = int(time.time() * 1000)

                # Sendet die Antwort direkt als Chat-Nachricht
                socketio.emit("chat_message", {
                    "sender": "assistant",
                    "message": detailed_info,
                    "id": message_id
                })

                # Fügt die Nachricht zum Verlauf hinzu
                message_queue.append({
                    "sender": "assistant",
                    "message": detailed_info,
                    "raw_json": json.dumps(info_json),
                    "id": message_id
                })

                # Fügt die Antwort zum Konversationskontext hinzu
                conversation_context.append({
                    "role": "assistant",
                    "content": detailed_info
                })

                # Signalisiert, dass die Verarbeitung abgeschlossen ist
                socketio.emit(
                    "processing_status",
                    {
                        "type": "llm_json",
                        "status": "completed"
                    }
                )

                socketio.emit(
                    "processing_status",
                    {
                        "type": "decision_tree",
                        "status": "completed"
                    }
                )

                # Stelle nach kurzer Pause den ursprünglichen Fokus wieder her
                time.sleep(0.5)
                refocus_json = {"communicative_intent": "request_information"}
                if current_focus == "type":
                    refocus_json["wandke_choose_type"] = "in focus"
                elif current_focus == "strength":
                    refocus_json["wandke_choose_strength"] = "in focus"
                elif current_focus == "temp":
                    refocus_json["wandke_choose_temp"] = "in focus"
                elif current_focus == "quantity":
                    refocus_json["wandke_choose_quantity"] = "in focus"

                # Direkt an den Entscheidungsbaum senden
                print(f"Stelle ursprünglichen Fokus wieder her: {refocus_json}")
                decision_tree_pipe.send(json.dumps(refocus_json))
                return True

            elif requested_info_type:
                # Wir haben eine Informationsanfrage zu einem anderen Parameter als dem aktuellen Fokus
                json_data = {"communicative_intent": "request_information"}
                if requested_info_type == "type":
                    json_data["wandke_choose_type"] = "in focus"
                elif requested_info_type == "strength":
                    json_data["wandke_choose_strength"] = "in focus"
                elif requested_info_type == "temp":
                    json_data["wandke_choose_temp"] = "in focus"
                elif requested_info_type == "quantity":
                    json_data["wandke_choose_quantity"] = "in focus"

                print(f"Erkannte Informationsanfrage über {requested_info_type}, verwende JSON: {json_data}")
            elif current_focus:
                # Anfrage im aktuellen Fokus ohne spezifischen Typ
                json_data = {"communicative_intent": "request_information"}
                if current_focus == "type":
                    json_data["wandke_choose_type"] = "in focus"
                elif current_focus == "strength":
                    json_data["wandke_choose_strength"] = "in focus"
                elif current_focus == "temp":
                    json_data["wandke_choose_temp"] = "in focus"
                elif current_focus == "quantity":
                    json_data["wandke_choose_quantity"] = "in focus"
                elif current_focus == "production":
                    json_data["wandke_production_state"] = "in focus"

                print(f"Allgemeine Informationsanfrage im aktuellen Fokus: {current_focus}, verwende JSON: {json_data}")
            else:
                # Allgemeine Anfrage ohne bekannten Fokus
                json_data = {"communicative_intent": "request_information"}
                print("Allgemeine Informationsanfrage ohne Fokus")
        else:
            # Ein klarer Prompt für das LLM
            interpretation_prompt = f"""
            Du bist ein Interpret für einen Kaffee-Assistenten. Deine Aufgabe ist es, Benutzernachrichten in JSON-Befehle für den Entscheidungsbaum zu übersetzen.

            AKTUELLER KONTEXT:
            - Die Kaffeemaschine fragt gerade nach: {current_focus or "unbekannt"}
            - Aktueller Status: Typ: {machine_state["type"] or "nicht gewählt"}, Stärke: {machine_state["strength"] or "nicht gewählt"}, Temperatur: {machine_state["temp"] or "nicht gewählt"}, Menge: {machine_state["quantity"] or "nicht gewählt"}

            BENUTZERNACHRICHT:
            "{message}"

            WICHTIG:
            - Sei sehr tolerant bei Rechtschreibfehlern
            - Bei unklaren Eingaben, berücksichtige den aktuellen Fokus der Kaffeemaschine
            - Wenn der Text eine FRAGE ist (z.B. "Was sind die Stärken?"), erstelle ein Objekt mit:
              {{"communicative_intent": "request_information"}}
              und füge den aktuellen Fokus hinzu, z.B. "wandke_choose_strength": "in focus"
            - Bei einer Auswahl (z.B. "Ich möchte einen Espresso"), erstelle ein Objekt mit:
              {{"communicative_intent": "inform"}} und den entsprechenden Werten

            GÜLTIGE WERTE:
            - Kaffeetypen: "Espresso", "Cappuccino", "Americano", "Latte Macchiato"
            - Stärken: "very mild", "mild", "normal", "strong", "very strong", "double shot", "double shot +", "double shot ++"
            - Temperaturen: "normal", "high", "very high"
            - Mengen: Numerische Werte in ml

            AUSGABEFORMAT FÜR AUSWAHLEN:
            - Bei Typ-Auswahl: {{"communicative_intent": "inform", "type": "ERKANNTER_TYP", "wandke_choose_type": "NoDiagnosis"}}
            - Bei Stärke-Auswahl: {{"communicative_intent": "inform", "strength": "ERKANNTE_STÄRKE", "wandke_choose_strength": "NoDiagnosis"}}
            - Bei Temperatur-Auswahl: {{"communicative_intent": "inform", "temp": "ERKANNTE_TEMPERATUR", "wandke_choose_temp": "NoDiagnosis"}}
            - Bei Mengen-Auswahl: {{"communicative_intent": "inform", "quantity": "ERKANNTE_MENGE", "wandke_choose_quantity": "NoDiagnosis"}}
            - Bei Startbefehl: {{"communicative_intent": "inform", "wandke_production_state": "started"}}

            AUSGABEFORMAT FÜR FRAGEN/NACHFRAGEN:
            - Bei Fragen zum Typ: {{"communicative_intent": "request_information", "wandke_choose_type": "in focus"}}
            - Bei Fragen zur Stärke: {{"communicative_intent": "request_information", "wandke_choose_strength": "in focus"}}
            - Bei Fragen zur Temperatur: {{"communicative_intent": "request_information", "wandke_choose_temp": "in focus"}}
            - Bei Fragen zur Menge: {{"communicative_intent": "request_information", "wandke_choose_quantity": "in focus"}}
            - Bei Fragen zur Produktion: {{"communicative_intent": "request_information", "wandke_production_state": "in focus"}}

            BEISPIELE:
            1. Bei "Ich möchte einen Espresso": {{"communicative_intent": "inform", "type": "Espresso", "wandke_choose_type": "NoDiagnosis"}}
            2. Bei "Was sind die verschiedenen Stärken?": {{"communicative_intent": "request_information", "wandke_choose_strength": "in focus"}}
            3. Bei "Welche Temperaturen gibt es?": {{"communicative_intent": "request_information", "wandke_choose_temp": "in focus"}}
            4. Bei "Strong": {{"communicative_intent": "inform", "strength": "strong", "wandke_choose_strength": "NoDiagnosis"}}

            Gib NUR das JSON-Objekt zurück, keinen anderen Text!
            """

            if current_focus:
                interpretation_prompt += f"""

                WICHTIGER HINWEIS:
                Da der aktuelle Fokus "{current_focus}" ist, ist es wahrscheinlich, dass die Benutzereingabe "{message}" sich auf diesen Parameter bezieht.
                """

            # LLM-Antwort generieren
            llm_response = llm_manager.process_prompt(interpretation_prompt)
            print(f"LLM-Interpretation der Benutzereingabe: {llm_response}")

            # Versucht, die LLM-Antwort als JSON zu parsen
            try:
                # Versucht es zuerst mit der direkten Antwort
                json_data = json.loads(llm_response)
            except json.JSONDecodeError:
                try:
                    # Wenn die direkte Antwort kein valides JSON ist, versuche mit regex
                    import re
                    json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
                    if json_match:
                        json_data = json.loads(json_match.group(0))
                    else:
                        # Wenn keine JSON-Struktur gefunden wurde, erstellen eines absoluten Fallback
                        if current_focus:
                            # Bei erkannten Werten im aktuellen Fokus
                            if is_direct_value and direct_value:
                                json_data = {"communicative_intent": "inform"}
                                if current_focus == "type":
                                    json_data["type"] = direct_value
                                    json_data["wandke_choose_type"] = "NoDiagnosis"
                                elif current_focus == "strength":
                                    json_data["strength"] = direct_value
                                    json_data["wandke_choose_strength"] = "NoDiagnosis"
                                elif current_focus == "temp":
                                    json_data["temp"] = direct_value
                                    json_data["wandke_choose_temp"] = "NoDiagnosis"
                                elif current_focus == "quantity":
                                    json_data["quantity"] = direct_value
                                    json_data["wandke_choose_quantity"] = "NoDiagnosis"
                            else:
                                # Verwendet den aktuellen Fokus für Nachfragen
                                json_data = {"communicative_intent": "request_information"}
                                if current_focus == "type":
                                    json_data["wandke_choose_type"] = "in focus"
                                elif current_focus == "strength":
                                    json_data["wandke_choose_strength"] = "in focus"
                                elif current_focus == "temp":
                                    json_data["wandke_choose_temp"] = "in focus"
                                elif current_focus == "quantity":
                                    json_data["wandke_choose_quantity"] = "in focus"
                                elif current_focus == "production":
                                    json_data["wandke_production_state"] = "in focus"
                        else:
                            # Allgemeiner Fallback
                            json_data = {"communicative_intent": "request_information"}

                        print(f"Konnte kein JSON aus LLM-Antwort extrahieren, verwende Fallback: {json_data}")
                except Exception as parse_error:
                    print(f"Fehler beim JSON-Parsing: {parse_error}")
                    # Absoluter Fallback
                    json_data = {"communicative_intent": "request_information"}

        # Entfernt alle Schlüssel mit None/null-Werten
        if isinstance(json_data, dict):
            json_data = {k: v for k, v in json_data.items() if v is not None}

        update_machine_state_from_user_selection(json_data)

        # Signalisiert, dass der JSON-Verarbeitungsschritt abgeschlossen ist
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

        # Logge das endgültige JSON für Debug-Zwecke
        print(f"Sende an Entscheidungsbaum: {json_data}")

        # Senden der Nachricht an den Entscheidungsbaum
        decision_tree_pipe.send(json.dumps(json_data))
        return True
    except Exception as e:
        print(f"Fehler bei der Verarbeitung der Benutzernachricht: {e}")
        import traceback
        traceback.print_exc()
        socketio.emit(
            "processing_status",
            {
                "type": "decision_tree",
                "status": "error",
                "error": str(e)
            }
        )
        return False


def create_info_prompt(focus_type, machine_state):
    """Erstellt einen Prompt für das LLM, um detaillierte Informationen zu einem Fokustyp zu liefern"""
    if focus_type == "type":
        return f"""
        Der Benutzer fragt nach Informationen über die verfügbaren Kaffeetypen.

        Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die folgende Kaffeetypen erklärt:
        - Espresso: Ein kleiner, konzentrierter Kaffee mit intensivem Geschmack
        - Cappuccino: Espresso mit aufgeschäumter Milch, cremig und ausgewogen
        - Americano: Espresso mit heißem Wasser verlängert, ähnlich schwarzem Kaffee
        - Latte Macchiato: Aufgeschäumte Milch mit Espresso, mild und cremig

        Aktueller Maschinenstatus:
        - Kaffeetyp: {machine_state["type"] or "noch nicht gewählt"}
        - Stärke: {machine_state["strength"] or "noch nicht gewählt"}
        - Menge: {machine_state["quantity"] or "noch nicht gewählt"} ml
        - Temperatur: {machine_state["temp"] or "noch nicht gewählt"}

        Formuliere eine freundliche, detaillierte Antwort, die alle Kaffeetypen erklärt und ihre Unterschiede hervorhebt.
        Wenn bereits ein Kaffeetyp gewählt wurde, erwähne dies in deiner Antwort und schlage vor, die Auswahl zu bestätigen oder zu ändern.
        """

    elif focus_type == "strength":
        return f"""
        Der Benutzer fragt nach Informationen über die verfügbaren Kaffeestärken.

        Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die folgende Stärken erklärt:
        - very mild: Sehr mild und dezent, für einen sanften Kaffeegenuss
        - mild: Leicht und sanft, aber etwas intensiver als very mild
        - normal: Ausgewogene Stärke, Standard für die meisten Kaffeetrinker
        - strong: Kräftig und intensiv, für Liebhaber von stärkerem Kaffee
        - very strong: Besonders kräftig, mit vollem Körper und intensivem Geschmack
        - double shot: Mit doppelter Kaffeemenge für Extra-Intensität
        - double shot +: Noch intensiverer doppelter Schuss
        - double shot ++: Maximale Intensität mit doppeltem Schuss

        Aktueller Maschinenstatus:
        - Kaffeetyp: {machine_state["type"] or "noch nicht gewählt"}
        - Stärke: {machine_state["strength"] or "noch nicht gewählt"}
        - Menge: {machine_state["quantity"] or "noch nicht gewählt"} ml
        - Temperatur: {machine_state["temp"] or "noch nicht gewählt"}

        Formuliere eine freundliche, detaillierte Antwort, die alle Stärkegrade erklärt und ihre Unterschiede hervorhebt. 
        Wenn bereits eine Stärke gewählt wurde, erwähne dies in deiner Antwort und frage, ob der Benutzer diese bestätigen oder ändern möchte.
        """

    elif focus_type == "temp":
        return f"""
        Der Benutzer fragt nach Informationen über die verfügbaren Temperaturen.

        Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die folgende Temperaturen detailliert erklärt:
        - normal: Standardtemperatur (ca. 85-90°C), angenehm heiß für die meisten Kaffeetrinker
        - high: Erhöhte Temperatur (ca. 90-95°C), für Liebhaber von heißerem Kaffee
        - very high: Maximale Temperatur (ca. 95-98°C), für besonders heiße Getränke

        Aktueller Maschinenstatus:
        - Kaffeetyp: {machine_state["type"] or "noch nicht gewählt"}
        - Stärke: {machine_state["strength"] or "noch nicht gewählt"}
        - Menge: {machine_state["quantity"] or "noch nicht gewählt"} ml
        - Temperatur: {machine_state["temp"] or "noch nicht gewählt"}

        Formuliere eine freundliche, ausführliche Antwort, die alle Temperaturoptionen erklärt und ihre Unterschiede und Auswirkungen auf den Geschmack hervorhebt.
        Wenn bereits eine Temperatur gewählt wurde, erwähne dies in deiner Antwort und frage, ob der Benutzer diese bestätigen oder ändern möchte.
        """

    elif focus_type == "quantity":
        type_specific = ""
        if machine_state["type"] == "Espresso":
            type_specific = """
            Für Espresso wird üblicherweise eine Menge zwischen 35ml und 60ml empfohlen:
            - 35ml für einen sehr konzentrierten, intensiven Espresso (Ristretto-Stil)
            - 45ml für einen klassischen Espresso (Standard)
            - 60ml für einen längeren Espresso (Lungo-Stil)
            """
        elif machine_state["type"] == "Cappuccino":
            type_specific = """
            Für Cappuccino kannst du eine Menge zwischen 100ml und 300ml wählen:
            - 100-150ml für einen kleinen, intensiven Cappuccino
            - 180-220ml für einen mittelgroßen Cappuccino (Standard)
            - 250-300ml für einen großen Cappuccino
            """
        elif machine_state["type"] == "Americano":
            type_specific = """
            Für Americano kannst du eine Menge zwischen 100ml und 300ml wählen:
            - 100-150ml für einen kleinen, intensiven Americano
            - 180-220ml für einen mittelgroßen Americano (Standard)
            - 250-300ml für einen großen Americano
            """
        elif machine_state["type"] == "Latte Macchiato":
            type_specific = """
            Für Latte Macchiato kannst du eine Menge zwischen 200ml und 400ml wählen:
            - 200-250ml für einen kleinen Latte Macchiato
            - 280-320ml für einen mittelgroßen Latte Macchiato (Standard)
            - 350-400ml für einen großen Latte Macchiato
            """
        else:
            type_specific = """
            Die mögliche Menge hängt vom gewählten Kaffeetyp ab:
            - Espresso: 35-60ml
            - Cappuccino und Americano: 100-300ml
            - Latte Macchiato: 200-400ml
            """

        return f"""
        Der Benutzer fragt nach Informationen über die verfügbaren Mengen für Kaffee.

        {type_specific}

        Aktueller Maschinenstatus:
        - Kaffeetyp: {machine_state["type"] or "noch nicht gewählt"}
        - Stärke: {machine_state["strength"] or "noch nicht gewählt"}
        - Menge: {machine_state["quantity"] or "noch nicht gewählt"} ml
        - Temperatur: {machine_state["temp"] or "noch nicht gewählt"}

        Formuliere eine freundliche, ausführliche Antwort, die verschiedene Mengenoptionen erklärt und wie sich die Menge auf den Geschmack auswirkt.
        Wenn bereits eine Menge gewählt wurde, erwähne dies in deiner Antwort und frage, ob der Benutzer diese bestätigen oder ändern möchte.
        """

    elif focus_type == "production":
        return f"""
        Der Benutzer fragt nach Informationen über die Kaffeezubereitung.

        Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die erklärt:
        - Alle Parameter für den Kaffee sind bereits ausgewählt
        - Der Benutzer kann jetzt die Zubereitung starten
        - Er muss nur "Ja", "Starten" oder "Kaffee machen" sagen

        Aktueller Maschinenstatus:
        - Kaffeetyp: {machine_state["type"] or "noch nicht gewählt"}
        - Stärke: {machine_state["strength"] or "noch nicht gewählt"}
        - Menge: {machine_state["quantity"] or "noch nicht gewählt"} ml
        - Temperatur: {machine_state["temp"] or "noch nicht gewählt"}

        Formuliere eine freundliche, ausführliche Antwort, die alle ausgewählten Parameter zusammenfasst und den Benutzer fragt, ob der Kaffee mit diesen Einstellungen zubereitet werden soll.
        """

    else:
        return f"""
        Der Benutzer fragt nach Informationen.

        Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die den aktuellen Status der Kaffeemaschine erklärt:

        Aktueller Maschinenstatus:
        - Kaffeetyp: {machine_state["type"] or "noch nicht gewählt"}
        - Stärke: {machine_state["strength"] or "noch nicht gewählt"}
        - Menge: {machine_state["quantity"] or "noch nicht gewählt"} ml
        - Temperatur: {machine_state["temp"] or "noch nicht gewählt"}

        Formuliere eine freundliche, ausführliche Antwort, die den aktuellen Status erklärt und vorschlägt, welcher Parameter als nächstes festgelegt werden sollte.
        Wenn noch kein Kaffeetyp gewählt wurde, sollte dieser zuerst festgelegt werden.
        """

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

            # WICHTIG: Zugriff auf task_state um die tatsächlichen Werte zu bekommen
            try:
                from py_trees.blackboard import Client
                task_state = Client(name="State of the coffee production task",
                                    namespace="task_state")
                task_state.register_key(key="type", access=py_trees.common.Access.READ)
                task_state.register_key(key="strength", access=py_trees.common.Access.READ)
                task_state.register_key(key="quantity", access=py_trees.common.Access.READ)
                task_state.register_key(key="temp", access=py_trees.common.Access.READ)

                # Aktualisiert machine_state mit den tatsächlichen Werten aus task_state
                if task_state.type != 'default':
                    machine_state["type"] = task_state.type
                if task_state.strength != 'default':
                    machine_state["strength"] = task_state.strength
                if task_state.temp != 'default':
                    machine_state["temp"] = task_state.temp
                if task_state.quantity != 'default':
                    machine_state["quantity"] = task_state.quantity
            except Exception as e:
                print(f"Fehler beim Zugriff auf task_state: {e}")

            # Dann noch Aktualisierungen aus dem aktuellen data/json
            if "type" in data and data["type"] != "default":
                machine_state["type"] = data["type"]
            elif "strength" in data and data["strength"] != "default":
                machine_state["strength"] = data["strength"]
            elif "temp" in data and data["temp"] != "default":
                machine_state["temp"] = data["temp"]
            elif "quantity" in data and data["quantity"] != "default":
                machine_state["quantity"] = data["quantity"]

            # Debug: Ausgabe des aktuellen Maschinenstatus
            print(f"Aktueller Maschinenstatus: {machine_state}")
        except Exception as e:
            print(f"Fehler beim Aktualisieren des Maschinenstatus: {e}")
            import traceback
            traceback.print_exc()  # Detaillierte Fehlerausgabe für Debugging

        # Bestimme den aktuellen Fokus des Entscheidungsbaums
        current_focus = None
        if isinstance(data, dict):
            if "wandke_choose_type" in data and data["wandke_choose_type"] == "in focus":
                current_focus = "type"
            elif "wandke_choose_strength" in data and data["wandke_choose_strength"] == "in focus":
                current_focus = "strength"
            elif "wandke_choose_quantity" in data and data["wandke_choose_quantity"] == "in focus":
                current_focus = "quantity"
            elif "wandke_choose_temp" in data and data["wandke_choose_temp"] == "in focus":
                current_focus = "temp"
            elif "wandke_production_state" in data and data["wandke_production_state"] == "in focus":
                current_focus = "production"
            elif "wandke_production_state" in data and data["wandke_production_state"] == "ready":
                current_focus = "ready"

        # Überprüfe, ob es eine Anfrage nach Informationen ist
        is_information_request = False
        if isinstance(data, dict) and data.get("communicative_intent") == "request_information":
            is_information_request = True

        # Zusammenfassung des aktuellen Status für das LLM
        status_summary = f"""
        - Kaffeetyp: {machine_state["type"] or "noch nicht gewählt"}
        - Stärke: {machine_state["strength"] or "noch nicht gewählt"}
        - Menge: {machine_state["quantity"] or "noch nicht gewählt"} ml
        - Temperatur: {machine_state["temp"] or "noch nicht gewählt"}
        """

        # Bestimme, welche Art von Antwort generiert werden soll
        if is_information_request:
            # Bei einer Informationsanfrage, generiere eine detaillierte Antwort
            if current_focus == "type":
                info_prompt = f"""
                Der Benutzer fragt nach Informationen über die verfügbaren Kaffeetypen.

                Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die folgende Kaffeetypen erklärt:
                - Espresso: Ein kleiner, konzentrierter Kaffee mit intensivem Geschmack
                - Cappuccino: Espresso mit aufgeschäumter Milch, cremig und ausgewogen
                - Americano: Espresso mit heißem Wasser verlängert, ähnlich schwarzem Kaffee
                - Latte Macchiato: Aufgeschäumte Milch mit Espresso, mild und cremig

                Aktueller Maschinenstatus:
                {status_summary}

                Formuliere eine freundliche, detaillierte Antwort, die alle Kaffeetypen erklärt und ihre Unterschiede hervorhebt.
                Vermeide zu kurze Antworten - der Benutzer wünscht detaillierte Informationen.
                Wenn bereits ein Kaffeetyp gewählt wurde, erwähne dies in deiner Antwort und schlage vor, die Auswahl zu bestätigen oder zu ändern.
                """
            elif current_focus == "strength":
                info_prompt = f"""
                Der Benutzer fragt nach Informationen über die verfügbaren Kaffeestärken.

                Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die folgende Stärken erklärt:
                - very mild: Sehr mild und dezent, für einen sanften Kaffeegenuss
                - mild: Leicht und sanft, aber etwas intensiver als very mild
                - normal: Ausgewogene Stärke, Standard für die meisten Kaffeetrinker
                - strong: Kräftig und intensiv, für Liebhaber von stärkerem Kaffee
                - very strong: Besonders kräftig, mit vollem Körper und intensivem Geschmack
                - double shot: Mit doppelter Kaffeemenge für Extra-Intensität
                - double shot +: Noch intensiverer doppelter Schuss
                - double shot ++: Maximale Intensität mit doppeltem Schuss

                Aktueller Maschinenstatus:
                {status_summary}

                Formuliere eine freundliche, detaillierte Antwort, die alle Stärkegrade erklärt und ihre Unterschiede hervorhebt. 
                Vermeide zu kurze Antworten - der Benutzer wünscht detaillierte Informationen.
                Wenn bereits eine Stärke gewählt wurde, erwähne dies in deiner Antwort und frage, ob der Benutzer diese bestätigen oder ändern möchte.
                """
            elif current_focus == "temp":
                info_prompt = f"""
                Der Benutzer fragt nach Informationen über die verfügbaren Temperaturen.

                Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die folgende Temperaturen detailliert erklärt:
                - normal: Standardtemperatur (ca. 85-90°C), angenehm heiß für die meisten Kaffeetrinker
                - high: Erhöhte Temperatur (ca. 90-95°C), für Liebhaber von heißerem Kaffee
                - very high: Maximale Temperatur (ca. 95-98°C), für besonders heiße Getränke

                Aktueller Maschinenstatus:
                {status_summary}

                Formuliere eine freundliche, ausführliche Antwort, die alle Temperaturoptionen erklärt und ihre Unterschiede und Auswirkungen auf den Geschmack hervorhebt.
                Vermeide zu kurze Antworten - der Benutzer wünscht detaillierte Informationen.
                Wenn bereits eine Temperatur gewählt wurde, erwähne dies in deiner Antwort und frage, ob der Benutzer diese bestätigen oder ändern möchte.
                """
            elif current_focus == "quantity":
                # Mengenoptionen hängen vom gewählten Kaffeetyp ab
                if machine_state["type"] == "Espresso":
                    info_prompt = f"""
                    Der Benutzer fragt nach Informationen über die verfügbaren Mengen für Espresso.

                    Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die Folgendes detailliert erklärt:
                    - Für Espresso kannst du zwischen 35ml und 60ml wählen
                    - 35ml für einen sehr konzentrierten, intensiven Espresso
                    - 45ml für einen klassischen Espresso (Standard)
                    - 60ml für einen längeren Espresso (Lungo)

                    Aktueller Maschinenstatus:
                    {status_summary}

                    Formuliere eine freundliche, ausführliche Antwort, die verschiedene Mengenoptionen erklärt und wie sich die Menge auf den Geschmack auswirkt.
                    Vermeide zu kurze Antworten - der Benutzer wünscht detaillierte Informationen.
                    Wenn bereits eine Menge gewählt wurde, erwähne dies in deiner Antwort und frage, ob der Benutzer diese bestätigen oder ändern möchte.
                    """
                elif machine_state["type"] == "Cappuccino":
                    info_prompt = f"""
                    Der Benutzer fragt nach Informationen über die verfügbaren Mengen für Cappuccino.

                    Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die Folgendes detailliert erklärt:
                    - Für Cappuccino kannst du zwischen 100ml und 300ml wählen
                    - 100-150ml für einen kleinen, intensiven Cappuccino
                    - 180-220ml für einen mittelgroßen Cappuccino (Standard)
                    - 250-300ml für einen großen Cappuccino

                    Aktueller Maschinenstatus:
                    {status_summary}

                    Formuliere eine freundliche, ausführliche Antwort, die verschiedene Mengenoptionen erklärt und wie sich die Menge auf das Verhältnis von Kaffee zu Milchschaum auswirkt.
                    Vermeide zu kurze Antworten - der Benutzer wünscht detaillierte Informationen.
                    Wenn bereits eine Menge gewählt wurde, erwähne dies in deiner Antwort und frage, ob der Benutzer diese bestätigen oder ändern möchte.
                    """
                elif machine_state["type"] == "Americano":
                    info_prompt = f"""
                    Der Benutzer fragt nach Informationen über die verfügbaren Mengen für Americano.

                    Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die Folgendes detailliert erklärt:
                    - Für Americano kannst du zwischen 100ml und 300ml wählen
                    - 100-150ml für einen kleinen, intensiven Americano
                    - 180-220ml für einen mittelgroßen Americano (Standard)
                    - 250-300ml für einen großen Americano

                    Aktueller Maschinenstatus:
                    {status_summary}

                    Formuliere eine freundliche, ausführliche Antwort, die verschiedene Mengenoptionen erklärt und wie sich die Menge auf die Intensität des Kaffees auswirkt.
                    Vermeide zu kurze Antworten - der Benutzer wünscht detaillierte Informationen.
                    Wenn bereits eine Menge gewählt wurde, erwähne dies in deiner Antwort und frage, ob der Benutzer diese bestätigen oder ändern möchte.
                    """
                elif machine_state["type"] == "Latte Macchiato":
                    info_prompt = f"""
                    Der Benutzer fragt nach Informationen über die verfügbaren Mengen für Latte Macchiato.

                    Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die Folgendes detailliert erklärt:
                    - Für Latte Macchiato kannst du zwischen 200ml und 400ml wählen
                    - 200-250ml für einen kleinen Latte Macchiato
                    - 280-320ml für einen mittelgroßen Latte Macchiato (Standard)
                    - 350-400ml für einen großen Latte Macchiato

                    Aktueller Maschinenstatus:
                    {status_summary}

                    Formuliere eine freundliche, ausführliche Antwort, die verschiedene Mengenoptionen erklärt und wie sich die Menge auf das Verhältnis von Kaffee zu Milch auswirkt.
                    Vermeide zu kurze Antworten - der Benutzer wünscht detaillierte Informationen.
                    Wenn bereits eine Menge gewählt wurde, erwähne dies in deiner Antwort und frage, ob der Benutzer diese bestätigen oder ändern möchte.
                    """
                else:
                    info_prompt = f"""
                    Der Benutzer fragt nach Informationen über die verfügbaren Kaffeemengen.

                    Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die Folgendes detailliert erklärt:
                    - Die mögliche Menge hängt vom gewählten Kaffeetyp ab:
                    - Espresso: 35-60ml
                    - Cappuccino und Americano: 100-300ml
                    - Latte Macchiato: 200-400ml

                    Aktueller Maschinenstatus:
                    {status_summary}

                    Formuliere eine freundliche, ausführliche Antwort, die erklärt, warum die Menge vom Kaffeetyp abhängt und welche Mengen für verschiedene Kaffeetypen typisch sind.
                    Vermeide zu kurze Antworten - der Benutzer wünscht detaillierte Informationen.
                    Wenn noch kein Kaffeetyp gewählt wurde, erwähne dies und erkläre, dass zuerst ein Typ gewählt werden muss, bevor die passende Menge festgelegt werden kann.
                    """
            elif current_focus == "production":
                info_prompt = f"""
                Der Benutzer fragt nach Informationen über die Kaffeezubereitung.

                Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die erklärt:
                - Alle Parameter für den Kaffee sind bereits ausgewählt
                - Der Benutzer kann jetzt die Zubereitung starten
                - Er muss nur "Ja", "Starten" oder "Kaffee machen" sagen

                Aktueller Maschinenstatus:
                {status_summary}

                Formuliere eine freundliche, ausführliche Antwort, die alle ausgewählten Parameter zusammenfasst und den Benutzer fragt, ob der Kaffee mit diesen Einstellungen zubereitet werden soll.
                """
            else:
                info_prompt = f"""
                Der Benutzer fragt nach Informationen.

                Deine Aufgabe ist es, eine informative, freundliche Antwort auf Deutsch zu formulieren, die den aktuellen Status der Kaffeemaschine erklärt:
                {status_summary}

                Formuliere eine freundliche, ausführliche Antwort, die den aktuellen Status erklärt und vorschlägt, welcher Parameter als nächstes festgelegt werden sollte.
                Wenn noch kein Kaffeetyp gewählt wurde, sollte dieser zuerst festgelegt werden.
                """

            # LLM-Antwort für Informationsanfragen generieren
            llm_response = llm_manager.process_prompt(info_prompt, SYSTEM_PROMPT)

            # Antwort zum Konversationskontext hinzufügen
            conversation_context.append({
                "role": "assistant",
                "content": llm_response
            })

            return llm_response
        else:
            # Bei normalen Nachrichten, generiert eine Antwort basierend auf dem Fokus wie bisher
            next_action_prompt = ""
            if current_focus == "type":
                next_action_prompt = """
                Bitte wählen Sie einen Kaffeetyp aus den folgenden Optionen:
                - Espresso: Kleiner, konzentrierter Kaffee mit intensivem Geschmack
                - Cappuccino: Espresso mit aufgeschäumter Milch, angenehm cremig
                - Americano: Espresso mit zusätzlichem heißem Wasser, ähnlich dem schwarzen Filterkaffee
                - Latte Macchiato: Aufgeschäumte Milch mit Espresso, mild und cremig

                Welche Kaffeesorte möchtest du?
                """
            elif current_focus == "strength":
                next_action_prompt = f"""
                Für deinen {machine_state["type"] or "Kaffee"} kannst du folgende Stärkegrade wählen:
                - very mild: Besonders mild und dezent
                - mild: Leicht und sanft
                - normal: Ausgewogene Stärke
                - strong: Kräftig und intensiv
                - very strong: Besonders kräftig
                - double shot: Mit doppelter Kaffeemenge
                - double shot +: Noch intensiverer doppelter Schuss
                - double shot ++: Maximale Intensität mit doppeltem Schuss

                Welche Stärke bevorzugst du?
                """
            elif current_focus == "quantity":
                if machine_state["type"] == "Espresso":
                    next_action_prompt = f"""
                    Für Espresso wird üblicherweise eine Menge zwischen 35ml und 60ml empfohlen.
                    - 35ml für einen sehr konzentrierten Espresso
                    - 45ml für einen klassischen Espresso
                    - 60ml für einen längeren Espresso (Lungo)

                    Welche Menge möchtest du für deinen Espresso (zwischen 35ml und 60ml)?
                    """
                elif machine_state["type"] == "Cappuccino":
                    next_action_prompt = f"""
                    Für Cappuccino kannst du eine Menge zwischen 100ml und 300ml wählen.
                    - 100-150ml für einen kleinen, intensiven Cappuccino
                    - 180-220ml für einen mittelgroßen Cappuccino (häufigste Wahl)
                    - 250-300ml für einen großen Cappuccino

                    Welche Menge möchtest du für deinen Cappuccino (zwischen 100ml und 300ml)?
                    """
                elif machine_state["type"] == "Americano":
                    next_action_prompt = f"""
                    Für Americano kannst du eine Menge zwischen 100ml und 300ml wählen.
                    - 100-150ml für einen kleinen, intensiven Americano
                    - 180-220ml für einen mittelgroßen Americano (übliche Größe)
                    - 250-300ml für einen großen Americano

                    Welche Menge möchtest du für deinen Americano (zwischen 100ml und 300ml)?
                    """
                elif machine_state["type"] == "Latte Macchiato":
                    next_action_prompt = f"""
                    Für Latte Macchiato kannst du eine Menge zwischen 200ml und 400ml wählen.
                    - 200-250ml für einen kleinen Latte Macchiato
                    - 280-320ml für einen mittelgroßen Latte Macchiato (Standardgröße)
                    - 350-400ml für einen großen Latte Macchiato

                    Welche Menge möchtest du für deinen Latte Macchiato (zwischen 200ml und 400ml)?
                    """
                else:
                    next_action_prompt = "Bitte wählen Sie die Menge für Ihren Kaffee. Die verfügbaren Optionen hängen von der gewählten Kaffeesorte ab."
            elif current_focus == "temp":
                next_action_prompt = f"""
                Für deinen {machine_state["type"] or "Kaffee"} kannst du zwischen drei Temperaturstufen wählen:
                - normal: Standardtemperatur, die für die meisten Kaffeetrinker angenehm ist
                - high: Erhöhte Temperatur für einen heißeren Kaffee
                - very high: Maximale Temperatur für besonders heiße Getränke

                Welche Temperatur bevorzugst du?
                """
            elif current_focus == "production":
                # Zusammenfassung und Bestätigungsaufforderung mit anschaulichen Beschreibungen
                strength_desc = ""
                if machine_state["strength"] == "very mild":
                    strength_desc = "sehr milden"
                elif machine_state["strength"] == "mild":
                    strength_desc = "milden"
                elif machine_state["strength"] == "normal":
                    strength_desc = "normal starken"
                elif machine_state["strength"] == "strong":
                    strength_desc = "starken"
                elif machine_state["strength"] == "very strong":
                    strength_desc = "sehr starken"
                elif machine_state["strength"] and "double shot" in machine_state["strength"]:
                    strength_desc = machine_state["strength"]
                else:
                    strength_desc = machine_state["strength"] or "normalen"

                temp_desc = ""
                if machine_state["temp"] == "normal":
                    temp_desc = "normaler Temperatur"
                elif machine_state["temp"] == "high":
                    temp_desc = "hoher Temperatur"
                elif machine_state["temp"] == "very high":
                    temp_desc = "sehr hoher Temperatur"
                else:
                    temp_desc = f"Temperatur '{machine_state['temp'] or 'normal'}'"

                amount_desc = f"{machine_state['quantity'] or '?'} ml"

                next_action_prompt = f"""
                Perfekt! Du hast alle Parameter für deinen Kaffee ausgewählt:

                - Kaffeetyp: {machine_state["type"]}
                - Stärke: {strength_desc}
                - Temperatur: {temp_desc}
                - Menge: {amount_desc}

                Möchtest du jetzt die Zubereitung starten? Sage einfach "Ja", "Starten" oder "Kaffee machen".
                """
            elif current_focus == "ready":
                next_action_prompt = "Dein Kaffee ist fertig! Genieße deinen Kaffee. Möchtest du später einen weiteren Kaffee zubereiten?"
            else:
                next_action_prompt = "Was möchtest du als nächstes tun?"

            # Verbesserter Prompt für das LLM mit nuancierteren Anweisungen
            prompt = f"""
            Die Kaffeemaschine sendet folgende Informationen: {json.dumps(json_data, indent=2, ensure_ascii=False)}

            Aktueller Maschinenstatus:
            {status_summary}

            WICHTIG: Der Entscheidungsbaum fragt aktuell nach: {current_focus or "unbekannt"}

            BESONDERS WICHTIG: 
            - Wenn der Fokus auf "production" ist, wurde bereits alles festgelegt und du solltest nur danach fragen, ob der Kaffee jetzt zubereitet werden soll. Frage in diesem Fall NICHT erneut nach Parametern wie Temperatur oder Stärke!
            - Wenn der Fokus auf "ready" ist, ist der Kaffee bereits fertig zubereitet. Teile dem Benutzer mit, dass sein Kaffee fertig ist, und frage ihn, ob er noch etwas anderes möchte.
            - Bei Fragen des Nutzers nach möglichen Werten (z.B. "Welche Stärken gibt es?"), gib detaillierte Informationen.
            - Sei tolerant gegenüber ungenauen oder umgangssprachlichen Ausdrücken. Verstehe, was der Nutzer meint, auch wenn es nicht exakt den Fachbegriffen entspricht.

            Nächste Aktion vom Benutzer: {next_action_prompt}

            Bisheriger Konversationsverlauf:
            {json.dumps(conversation_context[-3:] if len(conversation_context) > 3 else conversation_context, indent=2, ensure_ascii=False)}

            Formuliere eine natürliche, freundliche Antwort auf Deutsch, die die Kaffeemaschine sagen würde.
            Beziehe dich auf alle bereits ausgewählten Parameter und frage nur nach dem Parameter, den der Entscheidungsbaum aktuell fokussiert.
            Verwende eine persönliche, freundliche Sprache und vermeide technische Begriffe, die ein Laie nicht verstehen würde.
            """

            # LLM-Antwort generieren
            llm_response = llm_manager.process_prompt(prompt, SYSTEM_PROMPT)

            # Wenn der Kaffee fertig ist, ersetze die Antwort immer durch eine korrekte Bestätigung
            if current_focus == "ready":
                try:
                    # Vor der Erstellung der Abschlussnachricht die Zustandsinformationen aktualisieren
                    reconstruct_machine_state()

                    # Parameter sammeln, wie bisher
                    kaffeetyp = machine_state["type"] or "Espresso"
                    staerke = machine_state["strength"] or "normal"
                    temperatur = machine_state["temp"] or "normal"
                    menge = machine_state["quantity"] or "40"

                    # Spezieller Prompt für die "Kaffee fertig"-Nachricht
                    coffee_ready_prompt = f"""
                    Der Kaffee des Benutzers ist jetzt fertig zubereitet.

                    Folgende Parameter wurden verwendet:
                    - Kaffeetyp: {kaffeetyp}
                    - Stärke: {staerke}
                    - Temperatur: {temperatur}
                    - Menge: {menge}ml

                    Formuliere eine freundliche, enthusiastische Nachricht auf Deutsch, die:
                    1. Mitteilt, dass der Kaffee fertig ist
                    2. Die gewählten Parameter erwähnt
                    3. Dem Benutzer einen guten Genuss wünscht
                    4. Anbietet, später einen weiteren Kaffee zuzubereiten

                    Verwende einen fröhlichen, serviceorientierten Ton, wie ein freundlicher Barista.
                    Du kannst gerne Emojis verwenden, aber nicht zu viele.
                    """

                    llm_response = llm_manager.process_prompt(coffee_ready_prompt, SYSTEM_PROMPT)

                    if not llm_response or len(llm_response.strip()) < 20:
                        print("LLM-Antwort zu kurz, verwende Fallback")
                        llm_response = f"""
                        Dein {kaffeetyp} ist fertig zubereitet! 🎉

                        Hier ist dein {kaffeetyp} mit {staerke} Stärke, {temperatur} Temperatur und {menge}ml.

                        Genieße deinen frisch zubereiteten Kaffee! Wenn du später einen weiteren Kaffee möchtest oder Fragen zur Kaffeemaschine hast, stehe ich dir gerne zur Verfügung.
                        """
                except Exception as e:
                    print(f"Fehler beim Erstellen der Ready-Nachricht: {e}")
                    import traceback
                    traceback.print_exc()
                    llm_response = "Dein Kaffee ist jetzt fertig! Genieße deinen Kaffee. Kann ich dir sonst noch etwas anbieten?"

                    for msg in reversed(message_queue):
                        if "raw_json" in msg:
                            try:
                                raw_data = json.loads(msg["raw_json"])
                                # Sammle Typ-Information
                                if "type" in raw_data and raw_data["type"] not in [None, "default",
                                                                                   "None"] and selected_type is None:
                                    selected_type = raw_data["type"]
                                # Sammle Stärke-Information
                                if "strength" in raw_data and raw_data["strength"] not in [None, "default",
                                                                                           "None"] and selected_strength is None:
                                    selected_strength = raw_data["strength"]
                                # Sammle Temperatur-Information
                                if "temp" in raw_data and raw_data["temp"] not in [None, "default",
                                                                                   "None"] and selected_temp is None:
                                    selected_temp = raw_data["temp"]
                                # Sammle Mengen-Information
                                if "quantity" in raw_data and raw_data["quantity"] not in [None, "default",
                                                                                           "None"] and selected_quantity is None:
                                    selected_quantity = raw_data["quantity"]
                            except:
                                pass

                        if "message" in msg:
                            if selected_type is None and any(typ in msg["message"].lower() for typ in
                                                             ["espresso", "cappuccino", "americano",
                                                              "latte macchiato"]):
                                for typ in ["Espresso", "Cappuccino", "Americano", "Latte Macchiato"]:
                                    if typ.lower() in msg["message"].lower():
                                        selected_type = typ
                                        break

                    for msg in conversation_context:
                        if msg["role"] == "user" and selected_type is None:
                            if any(typ in msg["content"].lower() for typ in
                                   ["espresso", "cappuccino", "americano", "latte macchiato"]):
                                for typ in ["Espresso", "Cappuccino", "Americano", "Latte Macchiato"]:
                                    if typ.lower() in msg["content"].lower():
                                        selected_type = typ
                                        break
                        elif msg["role"] == "user" and selected_strength is None:
                            if any(strength in msg["content"].lower() for strength in
                                   ["very mild", "mild", "normal", "strong", "very strong", "double shot"]):
                                for strength in ["very mild", "mild", "normal", "strong", "very strong", "double shot"]:
                                    if strength in msg["content"].lower():
                                        selected_strength = strength
                                        break

                    kaffeetyp = selected_type or machine_state["type"] or "Espresso"
                    staerke = selected_strength or machine_state["strength"] or "normal"
                    temperatur = selected_temp or machine_state["temp"] or "normal"
                    menge = selected_quantity or machine_state["quantity"] or "40"

                    # Debug-Ausgabe
                    print(
                        f"Gefundene Parameter für Abschlussnachricht: Typ={kaffeetyp}, Stärke={staerke}, Temp={temperatur}, Menge={menge}")

                    # Erstellen einer freundlichen, ansprechenden Nachricht
                    llm_response = f"""
                    Dein {kaffeetyp} ist fertig zubereitet! 🎉

                    Hier ist dein {kaffeetyp} mit {staerke} Stärke, {temperatur} Temperatur und {menge}ml.

                    Genieße deinen frisch zubereiteten Kaffee! Wenn du später einen weiteren Kaffee möchtest oder Fragen zur Kaffeemaschine hast, stehe ich dir gerne zur Verfügung.
                    """
                except Exception as e:
                    print(f"Fehler beim Erstellen der Ready-Nachricht: {e}")
                    import traceback
                    traceback.print_exc()
                    llm_response = "Dein Kaffee ist jetzt fertig! Genieße deinen Kaffee. Kann ich dir sonst noch etwas anbieten?"

            elif current_focus == "production" and (
                    "stärke" in llm_response.lower() or "temperatur" in llm_response.lower()):
                try:
                    kaffeetyp = machine_state["type"] if machine_state["type"] not in [None, "default",
                                                                                       "None"] else "Kaffee"
                    staerke = machine_state["strength"] if machine_state["strength"] not in [None, "default",
                                                                                             "None"] else "normal"
                    temperatur = machine_state["temp"] if machine_state["temp"] not in [None, "default",
                                                                                        "None"] else "normal"
                    menge = machine_state["quantity"] if machine_state["quantity"] not in [None, "default",
                                                                                           "None"] else "Standard"

                    # Spezielle Prompt für die Bestätigungsnachricht
                    confirmation_prompt = f"""
                    Alle Parameter für die Kaffeezubereitung wurden ausgewählt und sind wie folgt:
                    - Kaffeetyp: {kaffeetyp}
                    - Stärke: {staerke}
                    - Temperatur: {temperatur}
                    - Menge: {menge}ml

                    Formuliere eine freundliche, übersichtliche Zusammenfassung auf Deutsch, die:
                    1. Bestätigt, dass alle Einstellungen ausgewählt wurden
                    2. Die gewählten Parameter klar auflistet
                    3. Den Benutzer fragt, ob er mit diesen Einstellungen den Kaffee zubereiten möchte
                    4. Erwähnt, dass der Benutzer einfach "Ja", "Starten" oder "Kaffee machen" sagen kann

                    Verwende einen serviceorientierten, freundlichen Ton. Der Benutzer sollte klar verstehen, 
                    dass er jetzt nur noch bestätigen muss, um den Kaffee zu starten.
                    """

                    # LLM-Antwort für die Bestätigungsnachricht generieren
                    llm_response = llm_manager.process_prompt(confirmation_prompt, SYSTEM_PROMPT)

                    if not llm_response or len(llm_response.strip()) < 20:
                        print("LLM-Antwort zu kurz, verwende Fallback")
                        llm_response = f"""
                        Super! Alle Einstellungen sind perfekt:

                        - {kaffeetyp}
                        - Stärke: {staerke}
                        - Temperatur: {temperatur}
                        - Menge: {menge}ml

                        Möchtest du jetzt deinen {kaffeetyp} zubereiten lassen? Sage einfach "Ja" oder "Kaffee starten".
                        """
                except Exception as e:
                    print(f"Fehler beim Erstellen der Produktionsbestätigungs-Nachricht: {e}")
                    llm_response = "Alles eingestellt! Möchtest du die Kaffeezubereitung jetzt starten?"

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
        import traceback
        traceback.print_exc()  # Detaillierte Fehlerausgabe für Debugging
        return "Entschuldigung, bei der Verarbeitung ist ein Fehler aufgetreten. Wie kann ich dir mit deinem Kaffee helfen?"


def listen_to_decision_tree():
    """Hört auf Antworten vom Entscheidungsbaum und verarbeitet sie mit dem LLM"""
    global decision_tree_pipe, message_queue, machine_state, conversation_context

    # Speichere den aktuellen Fokus für bessere Kontinuität
    current_focus = None
    last_focus_time = 0

    while True:
        try:
            if decision_tree_pipe and decision_tree_pipe.poll():
                # Nachricht vom Entscheidungsbaum empfangen
                tree_message = decision_tree_pipe.recv()
                print(f"Vom Entscheidungsbaum empfangen: {tree_message}")

                try:
                    json_message = json.loads(tree_message) if isinstance(tree_message, str) else tree_message
                    print(f"Entscheidungsbaum-Nachricht als JSON: {json_message}")

                    reconstruct_machine_state()

                    if "wandke_choose_type" in json_message and json_message["wandke_choose_type"] == "in focus":
                        current_focus = "type"
                        last_focus_time = time.time()
                    elif "wandke_choose_strength" in json_message and json_message[
                        "wandke_choose_strength"] == "in focus":
                        current_focus = "strength"
                        last_focus_time = time.time()
                    elif "wandke_choose_quantity" in json_message and json_message[
                        "wandke_choose_quantity"] == "in focus":
                        current_focus = "quantity"
                        last_focus_time = time.time()
                    elif "wandke_choose_temp" in json_message and json_message["wandke_choose_temp"] == "in focus":
                        current_focus = "temp"
                        last_focus_time = time.time()
                    elif "wandke_production_state" in json_message and json_message[
                        "wandke_production_state"] == "in focus":
                        current_focus = "production"
                        last_focus_time = time.time()

                    if "message" in json_message and json_message.get("communicative_intent") == "request_information":

                        direct_message = json_message["message"]

                        # Erstelle eine einzigartige ID für die Nachricht
                        message_id = int(time.time() * 1000)

                        # Sende die direkte Antwort an den Client
                        socketio.emit("chat_message", {
                            "sender": "assistant",
                            "message": direct_message,
                            "id": message_id
                        })

                        print(f"Direkte Informationsantwort gesendet: {direct_message}")

                        # An die Warteschlange anhängen
                        message_queue.append({
                            "sender": "assistant",
                            "message": direct_message,
                            "raw_json": tree_message,
                            "id": message_id
                        })

                        # Füge die Antwort zum Konversationskontext hinzu
                        conversation_context.append({
                            "role": "assistant",
                            "content": direct_message
                        })

                        if current_focus and (time.time() - last_focus_time) < 60:
                            focus_message = {"communicative_intent": "request_information"}

                            if current_focus == "type":
                                focus_message["wandke_choose_type"] = "in focus"
                            elif current_focus == "strength":
                                focus_message["wandke_choose_strength"] = "in focus"
                            elif current_focus == "quantity":
                                focus_message["wandke_choose_quantity"] = "in focus"
                            elif current_focus == "temp":
                                focus_message["wandke_choose_temp"] = "in focus"
                            elif current_focus == "production":
                                focus_message["wandke_production_state"] = "in focus"

                            # Verarbeite den Fokus mit dem LLM, um eine natürlichere Antwort zu generieren
                            llm_response = process_with_llm(json.dumps(focus_message))

                            # Erstelle eine einzigartige ID für die Fokus-Nachricht
                            focus_message_id = int(time.time() * 1000) + 1  # +1 um Duplikate zu vermeiden

                            # Sende die Fokus-Nachricht nach einer kurzen Verzögerung
                            time.sleep(0.5)  # Kleine Verzögerung, damit die Nachfrage-Antwort zuerst angezeigt wird

                            socketio.emit("chat_message", {
                                "sender": "assistant",
                                "message": llm_response,
                                "id": focus_message_id
                            })

                            # An die Warteschlange anhängen
                            message_queue.append({
                                "sender": "assistant",
                                "message": llm_response,
                                "raw_json": json.dumps(focus_message),
                                "id": focus_message_id
                            })

                            # Zum Konversationskontext hinzufügen
                            conversation_context.append({
                                "role": "assistant",
                                "content": llm_response
                            })

                            print(f"Fokus-Nachricht gesendet: {llm_response}")
                        else:
                            # Wenn kein aktueller Fokus bekannt ist, versuche ihn zu finden
                            try:
                                for msg in reversed(
                                        message_queue[:-1]):  # Überspringe die gerade hinzugefügte Nachricht
                                    if "raw_json" in msg:
                                        last_json = json.loads(msg["raw_json"])
                                        if "wandke_choose_type" in last_json and last_json[
                                            "wandke_choose_type"] == "in focus":
                                            current_focus = "type"
                                            break
                                        elif "wandke_choose_strength" in last_json and last_json[
                                            "wandke_choose_strength"] == "in focus":
                                            current_focus = "strength"
                                            break
                                        elif "wandke_choose_quantity" in last_json and last_json[
                                            "wandke_choose_quantity"] == "in focus":
                                            current_focus = "quantity"
                                            break
                                        elif "wandke_choose_temp" in last_json and last_json[
                                            "wandke_choose_temp"] == "in focus":
                                            current_focus = "temp"
                                            break
                                        elif "wandke_production_state" in last_json and last_json[
                                            "wandke_production_state"] == "in focus":
                                            current_focus = "production"
                                            break

                                if current_focus:
                                    # Wenn ein Fokus gefunden wurde, verwende ihn
                                    focus_message = {"communicative_intent": "request_information"}
                                    if current_focus == "type":
                                        focus_message["wandke_choose_type"] = "in focus"
                                    elif current_focus == "strength":
                                        focus_message["wandke_choose_strength"] = "in focus"
                                    elif current_focus == "quantity":
                                        focus_message["wandke_choose_quantity"] = "in focus"
                                    elif current_focus == "temp":
                                        focus_message["wandke_choose_temp"] = "in focus"
                                    elif current_focus == "production":
                                        focus_message["wandke_production_state"] = "in focus"

                                    # Verarbeite den Fokus mit dem LLM
                                    llm_response = process_with_llm(json.dumps(focus_message))

                                    # Erstelle eine einzigartige ID für die Fokus-Nachricht
                                    focus_message_id = int(time.time() * 1000) + 1

                                    time.sleep(0.5)

                                    socketio.emit("chat_message", {
                                        "sender": "assistant",
                                        "message": llm_response,
                                        "id": focus_message_id
                                    })

                                    # An die Warteschlange anhängen
                                    message_queue.append({
                                        "sender": "assistant",
                                        "message": llm_response,
                                        "raw_json": json.dumps(focus_message),
                                        "id": focus_message_id
                                    })

                                    # Zum Konversationskontext hinzufügen
                                    conversation_context.append({
                                        "role": "assistant",
                                        "content": llm_response
                                    })

                                    print(f"Nachträglich ermittelter Fokus-Nachricht gesendet: {llm_response}")
                            except Exception as focus_error:
                                print(f"Fehler beim Wiederherstellen des Fokus: {focus_error}")

                        continue

                except Exception as e:
                    print(f"Fehler beim Parsen der Nachricht: {e}")

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

                # Erstelle eine einzigartige ID für die Nachricht
                message_id = int(time.time() * 1000)  # Unix-Timestamp in Millisekunden

                # WICHTIG: Nachricht an den Client senden
                socketio.emit("chat_message", {
                    "sender": "assistant",
                    "message": llm_response,
                    "id": message_id
                })

                # Debug-Ausgabe
                print(f"SocketIO-Nachricht gesendet: id={message_id}, sender=assistant")

                # An die Warteschlange für die Übertragung an den Client anhängen (für spätere Verwendung)
                message_queue.append({
                    "sender": "assistant",
                    "message": llm_response,
                    "raw_json": tree_message,
                    "id": message_id
                })

                try:
                    data = json.loads(tree_message) if isinstance(tree_message, str) else tree_message
                    if "wandke_production_state" in data and data["wandke_production_state"] == "ready":
                        kaffeetyp = None
                        staerke = None
                        temperatur = None
                        menge = None

                        for msg in reversed(message_queue):
                            if "raw_json" in msg:
                                try:
                                    raw_data = json.loads(msg["raw_json"])
                                    # Sammle Typ-Information
                                    if "type" in raw_data and raw_data["type"] not in [None, "default",
                                                                                       "None"] and kaffeetyp is None:
                                        kaffeetyp = raw_data["type"]
                                    # Sammle Stärke-Information
                                    if "strength" in raw_data and raw_data["strength"] not in [None, "default",
                                                                                               "None"] and staerke is None:
                                        staerke = raw_data["strength"]
                                    # Sammle Temperatur-Information
                                    if "temp" in raw_data and raw_data["temp"] not in [None, "default",
                                                                                       "None"] and temperatur is None:
                                        temperatur = raw_data["temp"]
                                    # Sammle Mengen-Information
                                    if "quantity" in raw_data and raw_data["quantity"] not in [None, "default",
                                                                                               "None"] and menge is None:
                                        menge = raw_data["quantity"]
                                except:
                                    pass

                        if kaffeetyp is None:
                            for msg in message_queue:
                                if "message" in msg:
                                    msg_text = msg["message"].lower()
                                    if "espresso" in msg_text and kaffeetyp is None:
                                        kaffeetyp = "Espresso"
                                    elif "cappuccino" in msg_text and kaffeetyp is None:
                                        kaffeetyp = "Cappuccino"
                                    elif "americano" in msg_text and kaffeetyp is None:
                                        kaffeetyp = "Americano"
                                    elif "latte" in msg_text and kaffeetyp is None:
                                        kaffeetyp = "Latte Macchiato"

                        kaffeetyp = kaffeetyp or "Kaffee"
                        staerke = staerke or "normal"
                        temperatur = temperatur or "normal"
                        menge = menge or "Standard"

                        # Kurze Pause, damit die Fertigmeldung zuerst angezeigt wird
                        time.sleep(2)

                        # Sende eine System-Nachricht zur Bestätigung des Abschlusses
                        completion_message = f"Interaktion erfolgreich abgeschlossen! Die Kaffeemaschine hat Ihren {kaffeetyp} zubereitet. Vielen Dank für die Nutzung des Kaffee-Assistenten."

                        socketio.emit("chat_message", {
                            "sender": "System",
                            "message": completion_message,
                            "id": int(time.time() * 1000)
                        })

                        # Deaktiviert die Eingabe über ein spezielles Event
                        socketio.emit("interaction_complete", {
                            "status": "complete",
                            "message": "Interaktion abgeschlossen",
                            "kaffee_details": {
                                "typ": kaffeetyp,
                                "staerke": staerke,
                                "temperatur": temperatur,
                                "menge": menge
                            }
                        })

                        # Log ohne Session-Zugriff
                        print(f"ERFOLGREICHE INTERAKTION ABGESCHLOSSEN:")
                        print(f"  Kaffeetyp: {kaffeetyp}")
                        print(f"  Stärke: {staerke}")
                        print(f"  Temperatur: {temperatur}")
                        print(f"  Menge: {menge}")

                        # Log-Datei anlegen über eine separate Funktion
                        try:
                            log_file = os.path.join(LOGS_FOLDER, "completed_interactions.log")
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            log_entry = f"{timestamp} - ERFOLGREICHE INTERAKTION:\n"
                            log_entry += f"  Kaffeetyp: {kaffeetyp}\n"
                            log_entry += f"  Stärke: {staerke}\n"
                            log_entry += f"  Temperatur: {temperatur}\n"
                            log_entry += f"  Menge: {menge}\n"
                            log_entry += "---------------------------------------------\n"

                            with open(log_file, "a") as f:
                                f.write(log_entry)
                        except Exception as log_error:
                            print(f"Fehler beim Loggen: {log_error}")
                except Exception as e:
                    print(f"Fehler beim Senden der Abschlussnachricht: {e}")
                    import traceback
                    traceback.print_exc()

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
            time.sleep(5)
            try:
                start_bot_process()
            except Exception as e:
                print(f"Fehler beim Neustart des Bot-Prozesses: {e}")
                time.sleep(10)
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

def reconstruct_machine_state():
        """Rekonstruiert den machine_state aus verschiedenen Quellen"""
        global machine_state, message_queue, conversation_context

        print("Rekonstruiere den machine_state aus allen Quellen...")

        try:
            from py_trees.blackboard import Client
            task_state = Client(name="State of the coffee production task",
                                namespace="task_state")
            task_state.register_key(key="type", access=py_trees.common.Access.READ)
            task_state.register_key(key="strength", access=py_trees.common.Access.READ)
            task_state.register_key(key="quantity", access=py_trees.common.Access.READ)
            task_state.register_key(key="temp", access=py_trees.common.Access.READ)

            # Aktualisiet machine_state mit den tatsächlichen Werten aus task_state
            if task_state.type != 'default':
                machine_state["type"] = task_state.type
                print(f"Aus task_state: type = {task_state.type}")
            if task_state.strength != 'default':
                machine_state["strength"] = task_state.strength
                print(f"Aus task_state: strength = {task_state.strength}")
            if task_state.temp != 'default':
                machine_state["temp"] = task_state.temp
                print(f"Aus task_state: temp = {task_state.temp}")
            if task_state.quantity != 'default':
                machine_state["quantity"] = task_state.quantity
                print(f"Aus task_state: quantity = {task_state.quantity}")
        except Exception as e:
            print(f"Fehler beim Zugriff auf task_state: {e}")

        try:
            for msg in reversed(message_queue):
                if "raw_json" in msg:
                    try:
                        raw_data = json.loads(msg["raw_json"])

                        if raw_data.get("communicative_intent") == "inform":
                            if "type" in raw_data and raw_data["type"] not in [None, "default",
                                                                               "None"] and raw_data.get(
                                    "wandke_choose_type") == "NoDiagnosis":
                                machine_state["type"] = raw_data["type"]
                                print(f"Aus Nachrichtenverlauf: type = {raw_data['type']}")

                            if "strength" in raw_data and raw_data["strength"] not in [None, "default",
                                                                                       "None"] and raw_data.get(
                                    "wandke_choose_strength") == "NoDiagnosis":
                                machine_state["strength"] = raw_data["strength"]
                                print(f"Aus Nachrichtenverlauf: strength = {raw_data['strength']}")

                            if "temp" in raw_data and raw_data["temp"] not in [None, "default",
                                                                               "None"] and raw_data.get(
                                    "wandke_choose_temp") == "NoDiagnosis":
                                machine_state["temp"] = raw_data["temp"]
                                print(f"Aus Nachrichtenverlauf: temp = {raw_data['temp']}")

                            if "quantity" in raw_data and raw_data["quantity"] not in [None, "default",
                                                                                       "None"] and raw_data.get(
                                    "wandke_choose_quantity") == "NoDiagnosis":
                                machine_state["quantity"] = raw_data["quantity"]
                                print(f"Aus Nachrichtenverlauf: quantity = {raw_data['quantity']}")
                    except Exception as e:
                        print(f"Fehler beim Parsen der Nachricht: {e}")
                        continue
        except Exception as e:
            print(f"Fehler beim Durchsuchen des Nachrichtenverlaufs: {e}")

        try:
            # Prüfe auf Kaffeetyp
            if machine_state["type"] is None:
                for msg in conversation_context:
                    if msg["role"] == "user":
                        msg_lower = msg["content"].lower()
                        for typ in ["espresso", "cappuccino", "americano", "latte macchiato"]:
                            if typ in msg_lower:
                                machine_state["type"] = typ.capitalize()
                                print(f"Aus Konversation: type = {typ.capitalize()}")
                                break

            # Prüfe auf Stärke
            if machine_state["strength"] is None:
                for msg in conversation_context:
                    if msg["role"] == "user":
                        msg_lower = msg["content"].lower()
                        for strength in ["very mild", "mild", "normal", "strong", "very strong", "double shot",
                                         "double shot +", "double shot ++"]:
                            if strength in msg_lower:
                                machine_state["strength"] = strength
                                print(f"Aus Konversation: strength = {strength}")
                                break

            # Prüfe auf Temperatur
            if machine_state["temp"] is None:
                for msg in conversation_context:
                    if msg["role"] == "user":
                        msg_lower = msg["content"].lower()
                        for temp in ["normal", "high", "very high"]:
                            if temp in msg_lower:
                                machine_state["temp"] = temp
                                print(f"Aus Konversation: temp = {temp}")
                                break

            # Prüfe auf Menge
            if machine_state["quantity"] is None:
                for msg in conversation_context:
                    if msg["role"] == "user":
                        msg_lower = msg["content"].lower()
                        import re
                        quantity_match = re.search(r'(\d+)', msg_lower)
                        if quantity_match:
                            machine_state["quantity"] = quantity_match.group(1)
                            print(f"Aus Konversation: quantity = {quantity_match.group(1)}")
        except Exception as e:
            print(f"Fehler beim Durchsuchen der Konversationshistorie: {e}")

        print(f"Aktueller Maschinenstatus nach Rekonstruktion: {machine_state}")

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
        selected_llm = request.form.get("llm", "llama3-8b")

        # In Session speichern
        session["username"] = username
        if fullname:
            session["fullname"] = fullname
        if vpid:
            session["vpid"] = vpid
        if selected_llm:
            session["selected_llm"] = selected_llm
            llm_manager.set_current_llm(selected_llm)

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
    global bot_process, conversation_context, machine_state
    if bot_process is not None and bot_process.is_alive():
        try:
            bot_process.terminate()
            bot_process.join(timeout=2)
            print(f"Bot-Prozess bei Logout von {username} beendet")
        except Exception as e:
            print(f"Fehler beim Beenden des Bot-Prozesses bei Logout: {e}")

    # Maschineneinstellungen zurücksetzen
    conversation_context = []
    machine_state = {
        "type": None,
        "strength": None,
        "temp": None,
        "quantity": None
    }

    # Aktivität loggen, falls ein Benutzer eingeloggt war
    try:
        if "username" in session:
            log_user_activity("logout", {"username": username})
    except Exception as e:
        print(f"Fehler beim Loggen des Logouts: {e}")

    # Session leeren
    session.clear()

    return redirect(url_for("login"))


@app.route("/restart_interaction", methods=["GET"])
def restart_interaction():
    """Setzt den Bot zurück und startet eine neue Interaktion"""
    try:
        global conversation_context, machine_state, message_queue

        # Konversationskontext und Maschinenstatus zurücksetzen
        conversation_context = []
        machine_state = {
            "type": None,
            "strength": None,
            "temp": None,
            "quantity": None
        }

        # Nachrichtenverlauf löschen
        message_queue = []

        # Logge den Neustart der Interaktion
        if "username" in session:
            log_user_activity("new_interaction", {"username": session.get("username", "unbekannt")})
            print(f"Neue Interaktion für Benutzer {session.get('username', 'unbekannt')} gestartet")

        # Stellt sicher, dass die Session nicht abläuft
        if 'username' in session:
            session.modified = True

        # Kleine Verzögerung, um sicherzustellen, dass alle Prozesse beendet sind
        time.sleep(0.5)

        # Bot-Prozess neu starten
        success = start_bot_process()
        if not success:
            print("FEHLER: Konnte Bot-Prozess nicht neu starten")

        return redirect(url_for("home"))
    except Exception as e:
        print(f"Fehler beim Neustart der Interaktion: {e}")
        import traceback
        traceback.print_exc()
        return redirect(url_for("home"))

@app.route("/reset_context", methods=["POST"])
def reset_context():
    """Setzt den Konversationskontext zurück"""
    try:
        # Konversationskontext zurücksetzen
        global conversation_context, machine_state
        conversation_context = []
        machine_state = {
            "type": None,
            "strength": None,
            "temp": None,
            "quantity": None
        }

        return jsonify({"status": "success", "message": "Konversationskontext wurde zurückgesetzt"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/reset_bot", methods=["POST"])
def reset_bot():
    """Setzt den Bot-Prozess und den Konversationskontext zurück, wenn er hängen bleibt"""
    try:
        global conversation_context, machine_state

        # Bot-Prozess zurücksetzen
        start_bot_process()

        # Konversationskontext zurücksetzen
        conversation_context = []
        machine_state = {
            "type": None,
            "strength": None,
            "temp": None,
            "quantity": None
        }

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


# Korrigierte Socket.IO connect-Funktion für llm_integration.py
@socketio.on("connect")
def handle_connect():
    """Verbindung mit dem Client herstellen"""
    # Überprüfe, ob ein Benutzer eingeloggt ist
    if "username" not in session:
        # Wenn kein Benutzer eingeloggt ist, lehne die Verbindung ab
        return False

    session["client_id"] = request.sid
    print(f"Client verbunden: {request.sid}")

    # Zurücksetzen des globalen Maschinenstatus für neue Verbindungen
    global machine_state, conversation_context
    machine_state = {
        "type": None,
        "strength": None,
        "temp": None,
        "quantity": None
    }
    conversation_context = []

    print("Globaler Maschinenstatus zurückgesetzt")

    # Starte den Bot-Prozess neu, wenn ein Benutzer verbindet
    try:
        success = start_bot_process()
        print(f"Bot-Prozess gestartet: {success}")

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
            print(f"LLM auf {session['selected_llm']} gesetzt")
    except Exception as e:
        print(f"Fehler beim Starten des Bot-Prozesses: {e}")
        import traceback
        traceback.print_exc()
        socketio.emit(
            "chat_message",
            {
                "sender": "System",
                "message": f"Fehler beim Starten des Kaffee-Assistenten: {e}"
            },
            room=request.sid
        )

@socketio.on("select_llm")
def handle_llm_selection(data):
    """Verarbeitet die Auswahl eines LLMs"""
    global llm_manager

    llm_name = data.get("llm", "llama3-8b")
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


@socketio.on("message_rating")
def handle_message_rating_event(data):
    """Verarbeitet die Bewertung einer Nachricht"""
    try:
        message_id = data.get("messageId", "unbekannt")
        rating = data.get("rating", 0)
        username = session.get("username", "unbekannt")
        vpid = session.get("vpid", "unbekannt")
        current_llm = session.get("selected_llm", "unbekannt")

        print(f"Bewertung erhalten: Nachricht {message_id} von {username} mit {rating}/7 bewertet")

        # Finde die bewertete Nachricht im message_queue
        rated_message_content = None
        last_user_message = None

        for idx, msg in enumerate(message_queue):
            if "id" in msg and str(msg["id"]) == str(message_id):
                rated_message_content = msg.get("message", "Nachricht nicht gefunden")
                # Versuche, die vorherige Benutzernachricht zu finden
                if idx > 0 and message_queue[idx - 1].get("sender") != "assistant":
                    last_user_message = message_queue[idx - 1].get("message", "Keine vorherige Nachricht")
                break

        # Wenn wir die vorherige Nachricht nicht gefunden haben, suche in conversation_context
        if last_user_message is None and len(conversation_context) >= 2:
            for i in range(len(conversation_context) - 1, 0, -1):
                if conversation_context[i]["role"] == "assistant" and conversation_context[i - 1]["role"] == "user":
                    last_user_message = conversation_context[i - 1].get("content", "Keine vorherige Nachricht")
                    break

        # Logge die Bewertung
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file = os.path.join(LOGS_FOLDER, "message_ratings.log")

        # Erweiterte Log-Informationen
        log_entry = f"{timestamp} - BEWERTUNG:\n"
        log_entry += f"  VP-ID: {vpid}\n"
        log_entry += f"  Benutzer: {username}\n"
        log_entry += f"  LLM-Modell: {current_llm}\n"
        log_entry += f"  Nachricht-ID: {message_id}\n"
        log_entry += f"  Bewertung: {rating}/7\n"

        if last_user_message:
            log_entry += f"  Vorherige Benutzernachricht: {last_user_message}\n"

        if rated_message_content:
            log_entry += f"  Bewertete Bot-Antwort: {rated_message_content}\n"

        log_entry += "---------------------------------------------\n"

        with open(log_file, "a") as f:
            f.write(log_entry)

        return {"status": "success"}
    except Exception as e:
        print(f"Fehler bei der Verarbeitung der Nachrichtenbewertung: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import os

    try:
        if os.path.exists("flask_session"):
            import shutil

            shutil.rmtree("flask_session")
        app.config["SESSION_TYPE"] = "filesystem"
        app.config["SESSION_FILE_DIR"] = "./flask_session"
        from flask_session import Session

        Session(app)
    except Exception as e:
        print(f"Info: Konnte Session nicht löschen: {e}")

    print("Starte Flask-Server auf Port 5001...")

    # Flask-App starten
    socketio.run(app, host="0.0.0.0", port=5001, debug=True)




