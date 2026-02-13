// llm_ui.js
// - Prompt "hero": loader, clear textbox, disable button while sending
// - Botones: círculo/figura8 pasan por LLM
// - Botones: detener/centro publican directo al tópico MQTT (sin LLM/planner)
// Requiere que tu cliente MQTT del navegador sea accesible como window.mqttClient
// (si no lo es, ver nota al final)

(() => {
  const promptEl = document.getElementById("llmPrompt");
  const btn = document.getElementById("llmSendBtn");
  const st = document.getElementById("llmStatus");

  const btnStop = document.getElementById("btnStop");
  const btnCenter = document.getElementById("btnCenter");
  const btnCircle = document.getElementById("btnCircle");
  const btnFigure8 = document.getElementById("btnFigure8");

  const topicEl = document.getElementById("mqttTopic");

  // API base (Live Server -> :8000)
  const apiBase = (location.port && location.port !== "8000")
    ? `${location.protocol}//${location.hostname}:8000`
    : "";

  function setStatus(mode, text) {
    st.classList.remove("offline", "online", "loading");
    st.classList.add(mode);
    st.textContent = text;
  }

    // --- UI: prompt gris tras enviar y se limpia al primer input nuevo ---
  function markPromptAsSent() {
    if (!promptEl) return;
    promptEl.classList.add("llm-sent");
    promptEl.dataset.sent = "1";
  }

  function clearSentState() {
    if (!promptEl) return;
    promptEl.classList.remove("llm-sent");
    delete promptEl.dataset.sent;
  }

  // Si el prompt está en modo "sent", al primer intento de escribir/pegar/borrar
  // lo limpiamos y quitamos el gris ANTES de que entre el primer caracter.
  promptEl?.addEventListener(
    "beforeinput",
    () => {
      if (promptEl.dataset.sent === "1") {
        promptEl.value = "";
        clearSentState();
      }
    },
    true
  );

  function getPoseFallback() {
    // 1) robot global
    if (window.robot && typeof window.robot.x === "number" && typeof window.robot.y === "number") {
      return { x: window.robot.x, y: window.robot.y };
    }
    // 2) función global opcional
    if (typeof window.getRobotPose === "function") {
      const p = window.getRobotPose();
      if (p && typeof p.x === "number" && typeof p.y === "number") return p;
    }
    return { x: 0, y: 0 };
  }

  function getMqttClient() {
    return window.mqttClient || window.client || null;
  }

  function publishGoal(x, y) {
    const client = getMqttClient();
    const topic = (topicEl?.value || "").trim();
    if (!client || !client.connected) {
      setStatus("offline", "MQTT: no conectado");
      return;
    }
    if (!topic) {
      setStatus("offline", "MQTT: tópico vacío");
      return;
    }
    const msg = JSON.stringify({ x: Math.round(x), y: Math.round(y) });
    client.publish(topic, msg);
    setStatus("online", `MQTT: publicado ${msg}`);
  }

    async function sendToLLM(text) {
    const t = (text || "").trim();
    if (!t) return;

    // Si viene de botones rápidos (circle/stop/etc), reflejamos lo enviado en el textbox
    if (promptEl && promptEl.value.trim() !== t) promptEl.value = t;

    btn.disabled = true;
    promptEl.readOnly = true;     // evita que editen mientras se envía
    markPromptAsSent();           // lo dejamos en gris “post-envío”
    setStatus("loading", "LLM: enviando...");

    try {
      const res = await fetch(`${apiBase}/api/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: t })
      });

      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.detail || "Error");

      setStatus("online", `LLM: OK · intent=${data.cmd?.intent || "?"}`);
      // Importante: NO lo borramos aquí. Se borrará al primer input del usuario.
    } catch (e) {
      // Si falló, quitamos el modo gris para que el usuario vea que no se envió bien
      clearSentState();
      setStatus("offline", `LLM: ERROR (${e.message})`);
    } finally {
      btn.disabled = false;
      promptEl.readOnly = false;
      promptEl.focus();
    }
  }


  // Enviar desde textbox
  function sendFromBox() {
    sendToLLM(promptEl.value);
  }

  // Botón enviar
  btn?.addEventListener("click", sendFromBox);

  // Ctrl+Enter enviar
  promptEl?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      sendFromBox();
    }
  });

  // Chips de ayuda
  document.querySelectorAll(".chip[data-prompt]").forEach((b) => {
    b.addEventListener("click", () => {
      const p = b.getAttribute("data-prompt") || "";
      promptEl.value = p;
      promptEl.focus();
    });
  });

  // Botones que AHORA pasan por el LLM (igual que círculo/8)
  btnCenter?.addEventListener("click", () =>
    sendToLLM("Ve al centro (0,0) y detente.")
  );

  btnStop?.addEventListener("click", () =>
    sendToLLM("STOP. Detente ahora mismo y mantén tu posición actual.")
  );

  // Botones que pasan por LLM
  btnCircle?.addEventListener("click", () =>
    sendToLLM("Traza un círculo de radio 200mm en 30s centrado en (0,0).")
  );
  btnFigure8?.addEventListener("click", () =>
    sendToLLM("Traza una figura en 8 centrada en (0,0) con amplitud 200mm en 40s.")
  );

  // Estado inicial
  setStatus("offline", "LLM: idle");
})();
