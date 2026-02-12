# api_server.py
import os, json, time, threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Reusamos tu lógica (Ollama + schema + fallback + MQTT publisher)
from llm_plan_mqtt import (
    ollama_generate,
    fallback_cmd,
    _clamp_cmd_inplace,
    MqttPub,
    OLLAMA_URL_DEFAULT,
)

MQTT_HOST   = os.getenv("MQTT_HOST", "test.mosquitto.org")
MQTT_PORT   = int(os.getenv("MQTT_PORT", "1883"))
CMD_TOPIC   = os.getenv("CMD_TOPIC", "huber/robot/plan/cmd")

OLLAMA_URL  = os.getenv("OLLAMA_URL", OLLAMA_URL_DEFAULT)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral-nemo:12b-instruct-2407-q4_0")

# Warmup (default: 5) - NO publica
WARMUP_N = int(os.getenv("WARMUP", "5"))
WARMUP_ENABLED = os.getenv("WARMUP_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}

# Seguridad mínima opcional (LAN demo: déjalo vacío)
API_KEY = os.getenv("API_KEY", "")  # si lo pones, el cliente debe mandarlo

_pub_lock = threading.Lock()

MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))

pub = MqttPub(MQTT_HOST, MQTT_PORT, keepalive=MQTT_KEEPALIVE, client_id=f"api_{int(time.time())}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    pub.connect(timeout_s=15.0)

    # Warmup del LLM: 5 corridas por defecto (NO publica a MQTT)
    if WARMUP_ENABLED and WARMUP_N > 0:
        warm_prompts = [
            "vete al centro",
            "derecha 100",
            "izquierda 100",
            "haz un circulo",
            "haz una elipse",
        ]
        print(f"\n[WARMUP] {WARMUP_N} corridas (NO publica). Model={OLLAMA_MODEL}")
        for i in range(WARMUP_N):
            txt = warm_prompts[i % len(warm_prompts)]
            cmd, raw = None, ""
            try:
                cmd, raw = ollama_generate(OLLAMA_MODEL, txt, OLLAMA_URL)
                used = (cmd is not None)
            except Exception as e:
                raw = f"ERROR: {e}"
                used = False

            if not cmd:
                cmd = fallback_cmd(txt)

            # clamp (para calentar también esa ruta)
            cmd = _clamp_cmd_inplace(cmd)

            # NO publica: solo log corto
            tag = "LLM" if used else "fallback/err"
            print(f"  [{i+1}/{WARMUP_N}] {tag}: '{txt}'")

        print("[WARMUP] listo.\n")

    yield
    pub.close()

app = FastAPI(lifespan=lifespan)

# Si sirves la web con este mismo server, no necesitas CORS.
# Si decides seguir con Live Server (puerto 5500), esto te salva.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # para demo; en producción limita a tus dominios
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {"ok": True, "mqtt": f"{MQTT_HOST}:{MQTT_PORT}", "cmd_topic": CMD_TOPIC}

@app.post("/api/plan")
def plan(payload: dict):
    # API key opcional
    if API_KEY:
        got = payload.get("api_key", "")
        if got != API_KEY:
            raise HTTPException(status_code=401, detail="Bad api_key")

    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text'")

    cmd, raw = None, ""
    try:
        cmd, raw = ollama_generate(OLLAMA_MODEL, text, OLLAMA_URL)
        used_llm = cmd is not None
    except Exception as e:
        raw = f"ERROR: {e}"
        used_llm = False

    if not cmd:
        cmd = fallback_cmd(text)

    cmd = _clamp_cmd_inplace(cmd)

    msg = {"cmd": cmd, "t_ms": int(time.time() * 1000)}
    wire = json.dumps(msg, ensure_ascii=False)

    with _pub_lock:
        pub.publish(CMD_TOPIC, wire, qos=0, retain=False)

    return {"ok": True, "used_llm": used_llm, "cmd": cmd, "raw_head": (raw[:180] if raw else "")}

# Sirve tu sitio (estático) desde la carpeta actual
# Asegúrate de tener index.html y tus .js/.css aquí.
app.mount("/", StaticFiles(directory=".", html=True), name="site")
