document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("loginForm");
  form.addEventListener("submit", function (event) {
    const usernameInput = document.getElementById("usernameinput");
    const username = usernameInput.value.trim();

    if (username === "") {
      // Prevent form submission
      event.preventDefault();

      // Display a message
      const errorMessage = document.getElementById("error-message");
      errorMessage.textContent = "Username cannot be empty.";
      errorMessage.style.color = "red";

      // Highlight the text field
      usernameInput.style.borderColor = "red";
    }
  });
});
