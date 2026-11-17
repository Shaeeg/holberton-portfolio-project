const thread = document.querySelector("#thread");
const chatForm = document.querySelector("#chat-form");
const chatInput = document.querySelector("#chat-input");
const sessionPill = document.querySelector("#session-pill");
const messageCount = document.querySelector("#message-count");
const statStatus = document.querySelector("#stat-status");
const statMessages = document.querySelector("#stat-messages");
const statChannel = document.querySelector("#stat-channel");
const requestLog = document.querySelector("#request-log");
const restartBtn = document.querySelector("#restart");
const clock = document.querySelector("#clock");

const channelNames = {
  chat: "Canlı söhbət",
  email: "E-poçt",
  phone: "Zəng",
};

let open = true;
let userMessages = 0;

function agentReply(message) {
  const text = message.toLowerCase();
  if (text === "exit" || text === "quit") {
    return { close: true, text: "Session closed. Have a great day!" };
  }
  if (text.includes("problem") || text.includes("kömək")) {
    return {
      close: false,
      text: "Müraciətiniz qeydə alındı. Texniki dəstək komandamız sizinlə əlaqə saxlayacaq.",
    };
  }
  return {
    close: false,
    text: `Mesajınız alındı: '${message}'. Sizə necə kömək edə bilərik?`,
  };
}

function addBubble(kind, who, text) {
  const article = document.createElement("article");
  article.className = `bubble ${kind}`;
  if (kind === "system") {
    article.textContent = text;
  } else {
    article.innerHTML = `<p class="who"></p><p class="body"></p>`;
    article.querySelector(".who").textContent = who;
    article.querySelector(".body").textContent = text;
  }
  thread.append(article);
  thread.scrollTop = thread.scrollHeight;
  return article;
}

function setSession(isOpen) {
  open = isOpen;
  sessionPill.classList.toggle("is-closed", !isOpen);
  sessionPill.lastChild.textContent = isOpen ? " Sessiya açıqdır" : " Sessiya bağlıdır";
  statStatus.textContent = isOpen ? "Açıq" : "Bağlı";
  chatInput.disabled = !isOpen;
  chatForm.querySelector(".send").disabled = !isOpen;
  restartBtn.hidden = isOpen;
}

function updateCount() {
  messageCount.textContent = `${userMessages} mesaj`;
  statMessages.textContent = String(userMessages);
}

function submitChat(raw) {
  const message = raw.trim();
  if (!message || !open) return;
  addBubble("user", "Siz", message);
  userMessages += 1;
  updateCount();
  chatInput.value = "";
  
  const pending = addBubble("agent", "Support Agent", "");
  pending.querySelector(".body").className = "body typing";
  pending.querySelector(".body").innerHTML = "<span></span><span></span><span></span>";
  
  window.setTimeout(() => {
    const reply = agentReply(message);
    pending.querySelector(".body").className = "body";
    pending.querySelector(".body").textContent = reply.text;
    if (reply.close) {
      setSession(false);
      addBubble("system", "", "Sessiya bağlandı. Yenidən başlamaq üçün yan paneldən istifadə edin.");
    }
  }, 450);
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitChat(chatInput.value);
});

chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

document.querySelectorAll(".channel").forEach((button) => {
  button.addEventListener("click", () => {
    const name = button.dataset.channel;
    document.querySelectorAll(".channel").forEach((item) => {
      item.classList.toggle("is-active", item === button);
    });
    document.querySelectorAll(".panel").forEach((panel) => {
      panel.hidden = panel.dataset.panel !== name;
    });
    statChannel.textContent = channelNames[name];
  });
});

document.querySelectorAll("#chips button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector('[data-channel="chat"]').click();
    if (!open) return;
    chatInput.value = button.dataset.prompt;
    chatInput.focus();
  });
});

function remember(title, detail) {
  const empty = requestLog.querySelector(".empty");
  if (empty) empty.remove();
  const item = document.createElement("li");
  item.innerHTML = "<strong></strong><small></small>";
  item.querySelector("strong").textContent = title;
  item.querySelector("small").textContent = detail;
  requestLog.prepend(item);
}

document.querySelector("#email-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  remember(data.get("subject"), `${data.get("name")} · ${data.get("email")}`);
  event.currentTarget.reset();
  document.querySelector("#email-status").textContent = "Müraciət qəbul olundu. Komanda e-poçtla cavab yazacaq.";
});

document.querySelector("#phone-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  remember(`Zəng · ${data.get("slot")}`, `${data.get("name")} · ${data.get("phone")}`);
  event.currentTarget.reset();
  document.querySelector("#phone-status").textContent = "Geri zəng sıraya alındı.";
});

restartBtn.addEventListener("click", () => {
  thread.innerHTML = "";
  addBubble("agent", "Support Agent", "Yeni sessiya açıldı. Probleminizi yazın və ya birbaşa sual verin.");
  userMessages = 0;
  updateCount();
  setSession(true);
  chatInput.focus();
});

function tick() {
  clock.textContent = new Intl.DateTimeFormat("az-AZ", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date());
}

tick();
window.setInterval(tick, 30000);
chatInput.focus();
