document.addEventListener("DOMContentLoaded", () => {
  let client_id = "";
  // Speichert bereits verarbeitete Nachrichten-IDs
  const processedMessageIds = new Set();
  // Set zum Speichern der bereits bewerteten Nachrichten-IDs
  const ratedMessageIds = new Set();
  // Set zum Speichern aller Assistenten-Nachrichten, die bewertet werden müssen
  const pendingRatings = new Set();

  const socket = io();

  const sendBtn = document.getElementById("sendBtn");
  const resetBtn = document.getElementById("resetBtn");
  const msgInput = document.getElementById("msgInput");
  const chatDiv = document.getElementById("chatDiv");

  // Diese alten Status-Indikatoren werden durch inline-Nachrichten ersetzt
  const decisionTreeIndicator = document.getElementById("decisionTreeIndicator");
  const llmProcessingIndicator = document.getElementById("llmProcessingIndicator");

  // Globale Variablen für Status-Elemente
  let decisionTreeStatusElement = null;
  let llmStatusElement = null;

  // Versuche, die Elements für VP-ID und LLM zu finden, falls sie existieren
  const displayVpid = document.getElementById("displayVpid");
  const llmBadge = document.getElementById("llmBadge");

  // Funktion zum Prüfen, ob alle Nachrichten bewertet wurden
  function checkAllMessagesRated() {
    if (pendingRatings.size > 0) {
      // Es gibt noch unbewertete Nachrichten
      updateInputState(true); // Deaktiviere den Senden-Button

      // Füge Warnhinweise zu unbewerteten Nachrichten hinzu
      pendingRatings.forEach(messageId => {
        const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
        if (messageElement) {
          // Prüfe, ob bereits ein Warnhinweis vorhanden ist
          if (!messageElement.querySelector('.rating-reminder')) {
            const ratingReminder = document.createElement('div');
            ratingReminder.classList.add('rating-reminder');
            ratingReminder.textContent = '⚠️ Bitte bewerte diese Nachricht, bevor du fortfährst';
            messageElement.appendChild(ratingReminder);
          }
        }
      });

      // Zeige eine globale Nachricht an
      if (!document.getElementById('rating-alert')) {
        const ratingAlert = document.createElement('div');
        ratingAlert.id = 'rating-alert';
        ratingAlert.classList.add('rating-alert');
        ratingAlert.innerHTML = `
          <div class="alert-icon">⚠️</div>
          <div class="alert-text">Bitte bewerte alle Nachrichten, bevor du eine neue Nachricht sendest (${pendingRatings.size} unbewertete Nachricht${pendingRatings.size !== 1 ? 'en' : ''})</div>
        `;
        document.body.appendChild(ratingAlert);

        // Zeige den Alert mit Animation
        setTimeout(() => {
          ratingAlert.classList.add('active');
        }, 10);

        // Verstecke den Alert nach 5 Sekunden
        setTimeout(() => {
          if (ratingAlert.parentNode) {
            ratingAlert.classList.remove('active');
            setTimeout(() => {
              if (ratingAlert.parentNode) {
                ratingAlert.parentNode.removeChild(ratingAlert);
              }
            }, 300);
          }
        }, 5000);
      }

      return false;
    } else {
      // Alle Nachrichten wurden bewertet
      updateInputState(false); // Aktiviere den Senden-Button
      return true;
    }
  }

  // Verbesserte Scroll-Funktion für neue Nachrichten
  function scrollToBottom() {
    // Stelle sicher, dass wir den richtigen Container haben
    if (!chatDiv) return;

    // Forciertes Layout-Update, bevor wir scrollen
    chatDiv.style.display = "none";
    chatDiv.offsetHeight; // Löst ein Reflow aus
    chatDiv.style.display = "";

    // Scroll mit Animation für bessere Benutzererfahrung
    setTimeout(() => {
      chatDiv.scrollTo({
        top: chatDiv.scrollHeight,
        behavior: 'smooth'
      });

      // Zweites Timeout als Fallback, falls die Animation nicht richtig funktioniert
      setTimeout(() => {
        chatDiv.scrollTop = chatDiv.scrollHeight;
        console.log(`Scrolling-Fallback ausgeführt: scrollHeight=${chatDiv.scrollHeight}, scrollTop=${chatDiv.scrollTop}`);
      }, 100);
    }, 50);
  }

// Funktion zur Überprüfung und Behandlung von Hängezuständen
function checkAndHandleHangingState() {
  // Diese Funktion soll im regelmäßigen Intervall aufgerufen werden,
  // um zu prüfen, ob der Entscheidungsbaum hängt

  // Prüfe, ob der Entscheidungsbaum-Status immer noch angezeigt wird
  if (decisionTreeStatusElement && decisionTreeStatusElement.parentNode) {
    // Prüfe, wie lange der Status schon angezeigt wird
    const statusTime = decisionTreeStatusElement.getAttribute('data-time');
    if (statusTime) {
      const timeElapsed = Date.now() - parseInt(statusTime);

      // Wenn mehr als 45 Sekunden vergangen sind, zeige eine Warnung an
      if (timeElapsed > 45000 && !decisionTreeStatusElement.classList.contains('warning-shown')) {
        // Markiere, dass eine Warnung angezeigt wurde
        decisionTreeStatusElement.classList.add('warning-shown');

        // Aktualisiere den Statustext
        const statusText = decisionTreeStatusElement.querySelector('span');
        if (statusText) {
          statusText.innerHTML = '<strong>Der Entscheidungsbaum reagiert nicht...</strong> Du kannst den Reset-Button verwenden.';
          statusText.style.color = '#ff5252';
        }

        // Füge einen Reset-Button direkt beim Status ein
        const resetButton = document.createElement('button');
        resetButton.textContent = 'Bot zurücksetzen';
        resetButton.classList.add('btn', 'btn-sm', 'btn-danger', 'ml-2');
        resetButton.style.marginLeft = '10px';
        resetButton.style.padding = '2px 8px';
        resetButton.style.fontSize = '12px';

        resetButton.addEventListener('click', function() {
          // Führe den gleichen Code wie der Reset-Button aus
          document.getElementById('resetBtn').click();
        });

        decisionTreeStatusElement.appendChild(resetButton);
      }
    } else {
      // Setze einen Zeitstempel, wenn keiner vorhanden ist
      decisionTreeStatusElement.setAttribute('data-time', Date.now().toString());
    }
  }
}

// Starte ein Intervall zur Überprüfung von Hängezuständen
setInterval(checkAndHandleHangingState, 5000); // A
  // Diese Funktion fügt Statusnachrichten als normale Nachrichten im Chat ein
function updateStatusMessage(type, status, error = null) {
  // Deklariere Variablen für die verschiedenen Status-Elemente
  let statusElement = null;

  // Wähle das richtige Status-Element basierend auf dem Typ
  if (type === "decision_tree") {
    statusElement = decisionTreeStatusElement;
  } else if (type === "llm") {
    statusElement = llmStatusElement;
  } else if (type === "llm_json") {
    statusElement = document.getElementById("llm-json-processing");
  }

  // Entferne alte Status-Elemente, wenn Status "completed" ist
  if (status === "completed") {
    if (statusElement && statusElement.parentNode) {
      statusElement.parentNode.removeChild(statusElement);

      // Setze die entsprechende globale Variable zurück
      if (type === "decision_tree") {
        decisionTreeStatusElement = null;
      } else if (type === "llm") {
        llmStatusElement = null;
      }
    }
    return;
  }

  // Wenn Status "error" ist, zeige eine Fehlermeldung
  if (status === "error") {
    const errorElement = document.createElement("div");
    errorElement.classList.add("message", "system", "error");
    const errorContent = document.createElement("p");

    if (type === "decision_tree") {
      errorContent.textContent = `Fehler im Entscheidungsbaum: ${error || "Unbekannter Fehler"}`;
    } else if (type === "llm") {
      errorContent.textContent = `Fehler bei LLM-Generierung: ${error || "Unbekannter Fehler"}`;
    } else if (type === "llm_json") {
      errorContent.textContent = `Fehler bei der Interpretation deiner Anfrage: ${error || "Unbekannter Fehler"}`;
    }

    errorElement.appendChild(errorContent);
    chatDiv.appendChild(errorElement);
    scrollToBottom();
    return;
  }

  // Erstelle oder aktualisiere die Statusnachricht
  if (status === "started" && !statusElement) {
      statusElement.setAttribute('data-time', Date.now().toString());

    // Erstelle ein Status-Element
    statusElement = document.createElement("div");
    statusElement.classList.add("status-message");

    // Spinner und Text
    const spinner = document.createElement("div");
    spinner.classList.add("spinner");
    statusElement.appendChild(spinner);

    const statusText = document.createElement("span");
    if (type === "decision_tree") {
      statusText.textContent = "Entscheidungsbaum verarbeitet Anfrage...";
      decisionTreeStatusElement = statusElement;
    } else if (type === "llm") {
      statusText.textContent = "KI generiert Antwort...";
      llmStatusElement = statusElement;
    } else if (type === "llm_json") {
      statusText.textContent = "Interpretiere deine Anfrage...";
      // Keine globale Variable nötig, da wir sie durch ID identifizieren
      statusElement.id = "llm-json-processing";
    }

    statusElement.appendChild(statusText);

    // Füge das Element zum Chat hinzu
    chatDiv.appendChild(statusElement);
    scrollToBottom();
  }
}

  // Disable the send button when processing
  function updateInputState(isProcessing) {
    if (isProcessing) {
      sendBtn.disabled = true;
      sendBtn.classList.add("disabled");
      msgInput.disabled = true;
    } else {
      // Prüfe, ob es unbewertete Nachrichten gibt
      if (pendingRatings.size === 0) {
        sendBtn.disabled = false;
        sendBtn.classList.remove("disabled");
        msgInput.disabled = false;

        // Entferne alle Rating-Reminder
        document.querySelectorAll('.rating-reminder').forEach(reminder => {
          reminder.parentNode.removeChild(reminder);
        });

        // Entferne globalen Alert
        const alert = document.getElementById('rating-alert');
        if (alert) {
          alert.parentNode.removeChild(alert);
        }
      } else {
        // Es gibt noch unbewertete Nachrichten
        sendBtn.disabled = true;
        sendBtn.classList.add("disabled");
        msgInput.disabled = false; // Erlaube dem Nutzer, seinen Text zu schreiben
      }
    }
  }

  // Hier den bestehenden Code modifizieren - im sendMsg()-Teil
function sendMsg() {
  const message = msgInput.value.trim();
  if (message !== "") {
    // Prüfe, ob alle Nachrichten bewertet wurden
    if (!checkAllMessagesRated()) {
      // Es gibt noch unbewertete Nachrichten
      console.log("Es gibt noch unbewertete Nachrichten. Bitte alle bewerten, bevor du eine neue Nachricht sendest.");
      return;
    }

    // Füge einen frühen Prozessindikator hinzu, bevor Socket-Kommunikation beginnt
    // Dies informiert den Nutzer sofort, dass seine Nachricht verarbeitet wird
    const processingElement = document.createElement("div");
    processingElement.classList.add("status-message");
    processingElement.id = "llm-json-processing";

    const spinner = document.createElement("div");
    spinner.classList.add("spinner");
    processingElement.appendChild(spinner);

    const statusText = document.createElement("span");
    statusText.textContent = "Verarbeite deine Anfrage...";
    processingElement.appendChild(statusText);

    chatDiv.appendChild(processingElement);
    scrollToBottom();

    // Deaktiviere Eingabefeld und Button sofort
    updateInputState(true);

    // Sende die Nachricht zum Server
    socket.emit("message", { message });

    // Leere das Eingabefeld
    msgInput.value = "";
  }
}

// Überarbeiteter Event-Handler für Verarbeitungsstatus
socket.on("processing_status", function(data) {
  console.log(`Processing status: ${data.type} - ${data.status}`);

  // Aktualisiere UI-Status für Buttons
  if ((data.type === "decision_tree" || data.type === "llm_json") && data.status === "started") {
    updateInputState(true); // Buttons deaktivieren
  } else if (data.type === "llm" && data.status === "completed") {
    updateInputState(false); // Buttons aktivieren wenn LLM fertig ist
    // Prüfe, ob alle Nachrichten bewertet wurden
    checkAllMessagesRated();
  }

  // Zeige Status inline im Chat an
  updateStatusMessage(data.type, data.status, data.error);

  // Prüfe auf Timeout des Entscheidungsbaums
  if (data.type === "decision_tree" && data.status === "started") {
    // Setze einen Timer für Timeout-Überprüfung (nach 30 Sekunden)
    const timeoutId = setTimeout(() => {
      const statusElement = decisionTreeStatusElement;
      if (statusElement && statusElement.parentNode) {
        // Der Status ist immer noch da, der Entscheidungsbaum könnte hängen
        const timeoutWarning = document.createElement("div");
        timeoutWarning.classList.add("message", "system", "error");
        const warningContent = document.createElement("p");
        warningContent.innerHTML = "Der Entscheidungsbaum scheint zu hängen. <br>Du kannst versuchen, den Bot mit dem <strong>Reset</strong>-Button zurückzusetzen.";
        timeoutWarning.appendChild(warningContent);
        chatDiv.appendChild(timeoutWarning);
        scrollToBottom();
      }
    }, 30000); // 30 Sekunden Timeout

    // Speichere die Timer-ID, um sie zu löschen, wenn der Entscheidungsbaum antwortet
    window.decisionTreeTimeoutId = timeoutId;
  }

  // Lösche den Timeout-Timer, wenn eine Antwort vom Entscheidungsbaum kommt
  if (data.type === "decision_tree" && data.status === "completed") {
    if (window.decisionTreeTimeoutId) {
      clearTimeout(window.decisionTreeTimeoutId);
      window.decisionTreeTimeoutId = null;
    }
  }
});

// Füge diesen Code in deine index.js-Datei ein, um Keep-Alive-Pings zu senden

// Keep-Alive-Funktionalität, um die Session aktiv zu halten
function setupKeepAlive() {
  // Sende alle 5 Minuten einen Keep-Alive-Ping
  const KEEP_ALIVE_INTERVAL = 5 * 60 * 1000; // 5 Minuten in Millisekunden

  // Initiale Keep-Alive-Referenz
  let keepAliveInterval = null;

  // Funktion zum Senden eines Keep-Alive-Pings
  function sendKeepAlive() {
    if (socket && socket.connected) {
      console.log("Sende Keep-Alive-Ping");
      socket.emit("keep_alive");
    }
  }

  // Starte den Keep-Alive-Mechanismus
  function startKeepAlive() {
    // Stoppe zuerst einen eventuell laufenden Intervall
    stopKeepAlive();

    // Starte einen neuen Intervall
    keepAliveInterval = setInterval(sendKeepAlive, KEEP_ALIVE_INTERVAL);
    console.log("Keep-Alive-Mechanismus gestartet");
  }

  // Stoppe den Keep-Alive-Mechanismus
  function stopKeepAlive() {
    if (keepAliveInterval) {
      clearInterval(keepAliveInterval);
      keepAliveInterval = null;
      console.log("Keep-Alive-Mechanismus gestoppt");
    }
  }

  // Event-Listener für Verbindungsstatus
  socket.on("connect", startKeepAlive);
  socket.on("disconnect", stopKeepAlive);

  // Event-Listener für Benutzerinteraktionen (optional)
  document.addEventListener("click", sendKeepAlive);
  document.addEventListener("keydown", sendKeepAlive);

  // Initial starten, falls die Verbindung bereits besteht
  if (socket.connected) {
    startKeepAlive();
  }
}

  // Verbesserte Funktion zum Erstellen der Bewertungskomponente
  function createRatingComponent(messageId) {
    // Füge die Nachricht zur Liste der zu bewertenden Nachrichten hinzu
    pendingRatings.add(messageId);

    const ratingContainer = document.createElement("div");
    ratingContainer.classList.add("message-rating");

    // Hinweis-Element für unbewertete Nachrichten
    const reminderElement = document.createElement("div");
    reminderElement.classList.add("rating-required");
    reminderElement.textContent = "Bewertung erforderlich";

    // Erstelle das Bewertungs-Icon
    const ratingIcon = document.createElement("span");
    ratingIcon.classList.add("rating-icon");
    ratingIcon.innerHTML = '<i class="fa fa-star-o"></i>';
    ratingIcon.title = "Nachricht bewerten (erforderlich)";

    // Erstelle das Dropdown für die Bewertung
    const ratingDropdown = document.createElement("div");
    ratingDropdown.classList.add("rating-dropdown");
    ratingDropdown.innerHTML = `
      <div class="rating-header">Wie nützlich war diese Nachricht?</div>
      <div class="rating-options">
        <div class="rating-option" data-value="1">1 - Überhaupt nicht nützlich</div>
        <div class="rating-option" data-value="2">2</div>
        <div class="rating-option" data-value="3">3</div>
        <div class="rating-option" data-value="4">4 - Neutral</div>
        <div class="rating-option" data-value="5">5</div>
        <div class="rating-option" data-value="6">6</div>
        <div class="rating-option" data-value="7">7 - Sehr nützlich</div>
      </div>
    `;

    // Verstecke das Dropdown initial
    ratingDropdown.style.display = "none";

    // Toggle Dropdown beim Klick auf das Icon mit verbessertem Positionierungsmanagement
    ratingIcon.addEventListener("click", (e) => {
      e.stopPropagation(); // Verhindere Bubbling

      // Schließe alle anderen offenen Dropdowns
      document.querySelectorAll(".rating-dropdown").forEach(dropdown => {
        if (dropdown !== ratingDropdown) {
          dropdown.style.display = "none";
        }
      });

      // Toggle dieses Dropdown
      if (ratingDropdown.style.display === "none") {
        ratingDropdown.style.display = "block";

        // Überprüfe die Position, um sicherzustellen, dass das Dropdown sichtbar ist
        setTimeout(() => {
          const rect = ratingDropdown.getBoundingClientRect();
          const viewportHeight = window.innerHeight;

          // Wenn das Dropdown unten aus dem Viewport ragt
          if (rect.bottom > viewportHeight) {
            // Zeige das Dropdown oben statt unten an
            ratingDropdown.style.top = "auto";
            ratingDropdown.style.bottom = "100%";
            ratingDropdown.style.marginTop = "0";
            ratingDropdown.style.marginBottom = "5px";
          }

          // Wenn das Dropdown rechts aus dem Viewport ragt
          const viewportWidth = window.innerWidth;
          if (rect.right > viewportWidth) {
            ratingDropdown.style.left = "auto";
            ratingDropdown.style.right = "0";
          }
        }, 0);
      } else {
        ratingDropdown.style.display = "none";
      }
    });

    // Event-Listener für Bewertungsoptionen
    ratingDropdown.querySelectorAll(".rating-option").forEach((option) => {
      option.addEventListener("click", (e) => {
        const ratingValue = e.currentTarget.getAttribute("data-value");

        // Ändere das Icon zur Anzeige, dass bewertet wurde
        ratingIcon.innerHTML = '<i class="fa fa-star"></i>';
        ratingIcon.classList.add("rated"); // Stoppe die Animation
        ratingIcon.title = `Bewertet mit ${ratingValue}/7`;

        // Verstecke das Dropdown
        ratingDropdown.style.display = "none";

        // Sende die Bewertung an den Server
        socket.emit("message_rating", {
          messageId: messageId,
          rating: parseInt(ratingValue)
        });

        // Entferne die Nachricht aus der Liste der zu bewertenden Nachrichten
        pendingRatings.delete(messageId);
        ratedMessageIds.add(messageId);

        // Entferne den Warnhinweis
        const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
        if (messageElement) {
          const reminder = messageElement.querySelector('.rating-reminder');
          if (reminder) {
            reminder.parentNode.removeChild(reminder);
          }
          // Entferne auch das "Bewertung erforderlich" Element
          reminderElement.style.display = "none";
        }

        // Prüfe, ob alle Nachrichten bewertet wurden
        checkAllMessagesRated();

        // Zeige kurzes Feedback an
        const feedbackElement = document.createElement("div");
        feedbackElement.textContent = `✓ Bewertet mit ${ratingValue}/7`;
        feedbackElement.style.fontSize = "12px";
        feedbackElement.style.color = "#28a745";
        feedbackElement.style.marginTop = "4px";

        const oldFeedback = ratingContainer.querySelector(".rating-feedback");
        if (oldFeedback) {
          ratingContainer.removeChild(oldFeedback);
        }

        feedbackElement.classList.add("rating-feedback");
        ratingContainer.appendChild(feedbackElement);

        // Blende das Feedback nach 3 Sekunden aus
        setTimeout(() => {
          if (feedbackElement.parentNode === ratingContainer) {
            feedbackElement.style.opacity = "0";
            feedbackElement.style.transition = "opacity 0.5s";
            setTimeout(() => {
              if (feedbackElement.parentNode === ratingContainer) {
                ratingContainer.removeChild(feedbackElement);
              }
            }, 500);
          }
        }, 3000);
      });
    });

    // Schließe Dropdown wenn außerhalb geklickt wird
    document.addEventListener("click", (e) => {
      if (!ratingContainer.contains(e.target)) {
        ratingDropdown.style.display = "none";
      }
    });

    ratingContainer.appendChild(reminderElement);
    ratingContainer.appendChild(ratingIcon);
    ratingContainer.appendChild(ratingDropdown);

    return ratingContainer;
  }

  // WICHTIG: Neuer Event-Handler für chat_message, der alte Implementierungen überschreibt
  // und doppelte Nachrichten verhindert
  socket.on("chat_message", function (data) {
    // Stelle sicher, dass jede Nachricht eine ID hat
    const messageId = data.id || Date.now().toString();

    // Debug-Ausgabe
    console.log(`Nachricht empfangen: ID=${messageId}, Sender=${data.sender}, Inhalt=${data.message.substring(0, 30)}...`);

    // Prüfe, ob diese Nachricht bereits verarbeitet wurde
    if (processedMessageIds.has(messageId)) {
      console.log(`Doppelte Nachricht verhindert: ${messageId}`);
      return; // Beende die Funktion frühzeitig, wenn die Nachricht bereits verarbeitet wurde
    }

    // Füge die Nachrichten-ID zur Liste der verarbeiteten Nachrichten hinzu
    processedMessageIds.add(messageId);
    console.log(`Nachricht zur Verarbeitung hinzugefügt: ${messageId}`);

    // Begrenze die Größe des Sets, um Speicherlecks zu vermeiden
    if (processedMessageIds.size > 100) {
      // Entferne die älteste ID (nicht optimal, aber funktioniert)
      const firstId = processedMessageIds.values().next().value;
      processedMessageIds.delete(firstId);
    }

    // Entferne Statusindikatoren, wenn eine Nachricht vom Assistenten empfangen wird
    if (data.sender === "assistant") {
      updateStatusMessage("decision_tree", "completed");
      updateStatusMessage("llm", "completed");
      updateInputState(false);
    }

    const messageElement = document.createElement("div");
    messageElement.setAttribute("data-message-id", messageId);

    const senderElement = document.createElement("span");
    const contentElement = document.createElement("p");

    if (data.sender === "System") {
      messageElement.classList.add("message", "system");
      contentElement.textContent = `${data.message}`;
      messageElement.appendChild(contentElement);
      chatDiv.appendChild(messageElement);
    } else {
      if (data.sender === "assistant") {
        messageElement.classList.add("message", "received");

        // Erstelle und füge die Bewertungskomponente für Assistenten-Nachrichten hinzu
        const ratingComponent = createRatingComponent(messageId);

        senderElement.textContent = `${data.sender}`;
        contentElement.textContent = `${data.message}`;

        messageElement.appendChild(senderElement);
        messageElement.appendChild(contentElement);

        // Füge die Bewertungskomponente zur Nachricht hinzu
        messageElement.appendChild(ratingComponent);

        // Prüfe direkt, ob alle Nachrichten bewertet wurden
        checkAllMessagesRated();

      } else {
        messageElement.classList.add("message", "sent");
        senderElement.textContent = `${data.sender}`;
        contentElement.textContent = `${data.message}`;

        messageElement.appendChild(senderElement);
        messageElement.appendChild(contentElement);
      }

      chatDiv.appendChild(messageElement);
    }

    // Scroll zum Ende des Chats
    scrollToBottom();
  });

  sendBtn.addEventListener("click", () => {
    sendMsg();
  });

  msgInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      sendMsg();
    }
  });

  // Reset-Button-Handler
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      // System-Nachricht anzeigen
      const messageElement = document.createElement("div");
      messageElement.classList.add("message", "system");
      const contentElement = document.createElement("p");
      contentElement.textContent = "Bot wird zurückgesetzt...";
      messageElement.appendChild(contentElement);
      chatDiv.appendChild(messageElement);
      scrollToBottom();

      // Reset-Anfrage senden
      fetch('/reset_bot', {
        method: 'POST',
      })
      .then(response => response.json())
      .then(data => {
        const resultElement = document.createElement("div");
        resultElement.classList.add("message", "system");
        const resultContent = document.createElement("p");

        if (data.status === "success") {
          resultContent.textContent = "Bot wurde erfolgreich zurückgesetzt.";
        } else {
          resultContent.textContent = "Fehler beim Zurücksetzen des Bots: " + (data.message || "Unbekannter Fehler");
          resultElement.classList.add("error");
        }

        resultElement.appendChild(resultContent);
        chatDiv.appendChild(resultElement);
        scrollToBottom();

        // Status-Indikatoren zurücksetzen
        updateStatusMessage("decision_tree", "completed");
        updateStatusMessage("llm", "completed");

        // Beim Reset alle Bewertungspflichten zurücksetzen
        pendingRatings.clear();
        ratedMessageIds.clear();
        updateInputState(false);
      })
      .catch(error => {
        console.error('Fehler:', error);
        const errorElement = document.createElement("div");
        errorElement.classList.add("message", "system", "error");
        const errorContent = document.createElement("p");
        errorContent.textContent = "Fehler bei der Verbindung zum Server: " + error;
        errorElement.appendChild(errorContent);
        chatDiv.appendChild(errorElement);
        scrollToBottom();

        // Status-Indikatoren zurücksetzen
        updateStatusMessage("decision_tree", "completed");
        updateStatusMessage("llm", "completed");
        updateInputState(false);
      });
    });
  }

  socket.on("connection_response", ({ client_id: id }) => {
    client_id = id;
  });

  // Überarbeiteter Event-Handler für Verarbeitungsstatus
  socket.on("processing_status", function(data) {
    // Aktualisiere UI-Status für Buttons
    if (data.type === "decision_tree" && data.status === "started") {
      updateInputState(true); // Buttons deaktivieren
    } else if (data.type === "llm" && data.status === "completed") {
      updateInputState(false); // Buttons aktivieren
    }

    // Zeige Status inline im Chat an
    updateStatusMessage(data.type, data.status, data.error);
  });

  socket.on("disconnect", () => {
    socket.close();
  });
  setupKeepAlive();
});