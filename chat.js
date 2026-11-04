(() => {
  const form = document.querySelector("#chat-form");
  if (!form) return;
  const input = document.querySelector("#message-input");
  const conversation = document.querySelector("#conversation");
  let emptyState = document.querySelector("#empty-state");
  const sendButton = document.querySelector("#send-button");
  const newChatButton = document.querySelector("#new-chat");
  const history = [];

  function addMessage(role, text, extraClass = "", sources = []) {
    if (emptyState) emptyState.remove();
    const bubble = document.createElement("article");
    const visualRole = role === "assistant" ? "bot" : "user";
    bubble.className = `message ${visualRole} ${extraClass}`.trim();
    bubble.setAttribute("aria-label", role === "user" ? "Your message" : "Gemma's response");
    const label = document.createElement("div");
    label.className = "label";
    label.textContent = role === "user" ? "YOU" : "GEMMA";
    bubble.append(label);
    const content = document.createElement("div");
    content.className = "bubble";
    if (role === "assistant") {
      const body = document.createElement("div");
      body.className = "message-body";
      appendLinkedText(body, text);
      content.append(body);
    } else {
      content.textContent = text;
    }
    bubble.append(content);
    if (role === "assistant" && sources.length) {
      const sourceList = document.createElement("div");
      sourceList.className = "message-sources";
      const title = document.createElement("span");
      title.textContent = "Sources: ";
      sourceList.append(title);
      sources.forEach((source, index) => {
        if (index) sourceList.append(document.createTextNode(", "));
        const link = document.createElement("a");
        link.href = source.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = `${source.name}${source.page ? `, p. ${source.page}` : ""}`;
        sourceList.append(link);
      });
      content.append(sourceList);
    }
    conversation.append(bubble);
    conversation.scrollTop = conversation.scrollHeight;
    return bubble;
  }

  // Render links as DOM nodes, never as model-provided HTML.
  function appendLinkedText(container, text) {
    const urlPattern = /https?:\/\/[^\s<>"']+/gi;
    let lastIndex = 0;
    for (const match of text.matchAll(urlPattern)) {
      const start = match.index;
      const raw = match[0];
      let url = raw;
      let trailing = "";
      while (/[.,!?;:)\]}]$/.test(url)) {
        trailing = url.slice(-1) + trailing;
        url = url.slice(0, -1);
      }
      container.append(document.createTextNode(text.slice(lastIndex, start)));
      try {
        const parsed = new URL(url);
        if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error("Unsupported URL");
        const link = document.createElement("a");
        link.href = parsed.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = url;
        container.append(link);
      } catch (_) {
        container.append(document.createTextNode(url));
      }
      if (trailing) container.append(document.createTextNode(trailing));
      lastIndex = start + raw.length;
    }
    container.append(document.createTextNode(text.slice(lastIndex)));
  }

  async function submitMessage(text) {
    history.push({ role: "user", content: text });
    addMessage("user", text);
    sendButton.disabled = true;
    newChatButton.disabled = true;
    input.disabled = true;
    const pending = addMessage("assistant", "Gemma is thinking…", "pending");
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history })
      });
      const data = await response.json();
      pending.remove();
      if (!response.ok) {
        history.pop();
        addMessage("assistant", data.error || "The request failed. Please try again.", "error-message");
        return;
      }
      history.push({ role: "assistant", content: data.reply });
      addMessage("assistant", data.reply, "", data.sources || []);
    } catch (_) {
      pending.remove();
      history.pop();
      addMessage("assistant", "Could not reach the local app. Check that it is running, then try again.", "error-message");
    } finally {
      sendButton.disabled = false;
      newChatButton.disabled = false;
      input.disabled = false;
      input.focus();
    }
  }

  form.addEventListener("submit", event => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || sendButton.disabled) return;
    input.value = "";
    submitMessage(text);
  });
  input.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  newChatButton.addEventListener("click", () => {
    history.length = 0;
    conversation.replaceChildren();
    const prompt = document.createElement("div");
    prompt.id = "empty-state";
    prompt.className = "empty-state";
    const message = document.createElement("p");
    message.textContent = "Ask Gemma anything to get started.";
    prompt.append(message);
    conversation.append(prompt);
    emptyState = prompt;
    input.value = "";
    input.focus();
  });
})();
