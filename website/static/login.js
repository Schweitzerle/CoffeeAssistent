document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("loginForm");
  if (form) {
    form.addEventListener("submit", function (event) {
      const usernameInput = document.getElementById("usernameinput");
      if (!usernameInput || usernameInput.value.trim() === "") {
        // Verhindere das Absenden des Formulars
        event.preventDefault();

        // Zeige Fehlermeldung
        usernameInput.classList.add("is-invalid");

        // Setze den Fokus auf das Eingabefeld
        usernameInput.focus();
      }
    });
  }
});