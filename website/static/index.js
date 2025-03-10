document.addEventListener("DOMContentLoaded", () => {
  let client_id = "";

  const socket = io();

  const sendBtn = document.getElementById("sendBtn");
  const msgInput = document.getElementById("msgInput");
  const fileInput = document.getElementById("fileInput");
  const chatDiv = document.getElementById("chatDiv");

  function sendMsg() {
    const message = msgInput.value.trim();
    if (message !== "") {
      socket.emit("message", { message }); // Send message to the server
      msgInput.value = ""; // Clear input field after sending message
    }
  }
  sendBtn.addEventListener("click", () => {
    sendMsg();
  });
  msgInput.addEventListener("keypress", (e) => {
    if (e.key == "Enter") {
      sendMsg();
    }
  });
  socket.on("connection_response", ({ client_id: id }) => {
    client_id = id;
  });

  socket.on("chat_message", function (data) {
    const messageElement = document.createElement("div");
    const senderElement = document.createElement("span");
    const contentElement = document.createElement("p");
    if (data.sender == "System") {
      messageElement.classList.add("message", "system");
      contentElement.textContent = `${data.message}`;
      messageElement.appendChild(contentElement);
      chatDiv.appendChild(messageElement);
    } else {
      if (data.sender == "assistant") {
        messageElement.classList.add("message", "received"); // Add a CSS class to indicate that the message was sent by the current user
      } else {
        messageElement.classList.add("message", "sent"); // Add a CSS class to indicate that the message was received
      }
      senderElement.textContent = `${data.sender}`;
      contentElement.textContent = `${data.message}`;

      messageElement.appendChild(senderElement);
      messageElement.appendChild(contentElement);
      chatDiv.appendChild(messageElement);
    }
  });

  //when someone clicks on add file
  fileInput.onchange = function () {
    const file = this.files[0];
    socket.emit("upload", { file, name: file.name });
  };

  socket.on("file_uploaded", function ({ filename, file_url }) {
    const name = filename;
    const fileUrl = file_url;
    // Provide a way for the user to download the file
    const downloadDiv = document.createElement("div");
    const downloadLink = document.createElement("a");
    downloadLink.setAttribute("href", fileUrl);
    downloadDiv.classList.add("message", "system", "file");
    downloadLink.innerHTML = name;
    downloadDiv.appendChild(downloadLink);
    chatDiv.appendChild(downloadDiv);
  });

  socket.on("disconnect", () => {
    socket.close();
  });
});
