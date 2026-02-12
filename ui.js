// ui.js (MQTT-only)
// - Panel MQTT siempre visible
// - Auto-conectar al cargar
// - Auto-iniciar simulación (si tu botón animateBtn arranca/paraa)
// - Mantiene compatibilidad con ids existentes

(() => {
  const q = (sel, root = document) => root.querySelector(sel);

  const mqttPanel = q("#mqttPanel");
  const mqttConnectBtn = q("#mqttConnectBtn");

  const endX = q("#endX");
  const endY = q("#endY");

  const controlsDetails =
    q("#controlsPanel") || q("section.info-boxes details");

  const animateBtn = q("#animateBtn");

  function setDisabled(el, disabled) {
    if (!el) return;
    el.disabled = !!disabled;
    el.setAttribute("aria-disabled", disabled ? "true" : "false");
  }

  function looksLikeStartButton(btn) {
    if (!btn) return false;
    const txt = (btn.textContent || "").toLowerCase();
    return txt.includes("iniciar") || txt.includes("start") || txt.includes("play");
  }

  function init() {
    // MQTT panel visible siempre
    if (mqttPanel) {
      mqttPanel.style.display = "";
      mqttPanel.setAttribute("aria-hidden", "false");
    }

    // En MQTT-only deshabilitamos objetivo manual
    setDisabled(endX, true);
    setDisabled(endY, true);

    // Oculta controles avanzados por default (no los borramos)
    if (controlsDetails) controlsDetails.open = false;

    // Auto-conectar (usa tu handler existente del botón)
    // Nota: si tu código MQTT conecta automáticamente sin botón, esto no estorba.
    setTimeout(() => {
      mqttConnectBtn?.click();
    }, 50);

    // Auto-iniciar simulación: solo si el botón "parece Iniciar"
    setTimeout(() => {
      if (looksLikeStartButton(animateBtn)) animateBtn.click();
    }, 120);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
