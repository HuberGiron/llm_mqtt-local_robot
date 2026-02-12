# pip install fastapi uvicorn paho-mqtt requests
# python run_stack.py

import os, sys, subprocess, signal, socket, time, shutil
from pathlib import Path

CMD_TOPIC  = os.getenv("CMD_TOPIC",  "huber/robot/plan/cmd")
GOAL_TOPIC = os.getenv("GOAL_TOPIC", "huber/robot/goal")

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))           # TCP local para Python
MQTT_TRANSPORT = os.getenv("MQTT_TRANSPORT", "tcp")       # tcp para planner/api en Python
MQTT_TLS = os.getenv("MQTT_TLS", "0")                     # 0 en LAN
MQTT_WS_PATH = os.getenv("MQTT_WS_PATH", "/mqtt")         # no afecta en tcp
MQTT_KEEPALIVE = os.getenv("MQTT_KEEPALIVE", "60")

def _can_connect(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def _wait_port(host: str, port: int, timeout_s: float = 6.0) -> bool:
    t0 = time.time()
    while (time.time() - t0) < timeout_s:
        if _can_connect(host, port):
            return True
        time.sleep(0.10)
    return False

def start_mosquitto_if_needed():
    """
    Arranca mosquitto.exe como subproceso si NO hay un broker ya escuchando en MQTT_PORT.
    Devuelve (proc, logfile_handle) o (None, None) si no se arrancó.
    """
    auto = os.getenv("MOSQUITTO_AUTO", "1").strip().lower() not in {"0", "false", "no", "off"}
    if not auto:
        print("[MOSQ] MOSQUITTO_AUTO=0 -> no arranco mosquitto")
        return None, None

    check_host = os.getenv("MOSQUITTO_CHECK_HOST", "127.0.0.1")
    check_port = int(os.getenv("MOSQUITTO_CHECK_PORT", str(MQTT_PORT)))

    if _can_connect(check_host, check_port):
        print(f"[MOSQ] ya hay broker en {check_host}:{check_port} -> no arranco mosquitto")
        return None, None

    mosq_bin = os.getenv("MOSQUITTO_BIN", "").strip()
    if not mosq_bin:
        win_default = r"C:\Program Files\mosquitto\mosquitto.exe"
        if os.name == "nt" and os.path.exists(win_default):
            mosq_bin = win_default
        else:
            mosq_bin = shutil.which("mosquitto") or "mosquitto"

    mosq_conf = os.getenv("MOSQUITTO_CONF", "").strip()
    if not mosq_conf:
        mosq_conf = r"C:\mqtt\mosquitto.conf" if os.name == "nt" else "./mosquitto.conf"

    args = [mosq_bin, "-c", mosq_conf]

    # Si quieres ver logs del broker en consola, pon MOSQUITTO_VERBOSE=1
    if os.getenv("MOSQUITTO_VERBOSE", "0").strip().lower() in {"1", "true", "yes", "on"}:
        args.append("-v")

    # Evitar depender de "log_dest file" (tu problema de permisos):
    # - si pones MOSQUITTO_LOGFILE, redirigimos stdout/stderr a ese archivo
    # - si no, por defecto lo mandamos a DEVNULL para no ensuciar consola
    log_fh = None
    log_path = os.getenv("MOSQUITTO_LOGFILE", "").strip()
    if log_path:
        Path(os.path.dirname(log_path) or ".").mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "a", encoding="utf-8", errors="ignore")
        stdout = log_fh
        stderr = log_fh
    else:
        quiet = os.getenv("MOSQUITTO_QUIET", "1").strip().lower() in {"1", "true", "yes", "on"}
        if quiet:
            stdout = subprocess.DEVNULL
            stderr = subprocess.STDOUT
        else:
            stdout = None
            stderr = None

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    print(f"[MOSQ] arrancando: {args}")
    proc = subprocess.Popen(args, stdout=stdout, stderr=stderr, creationflags=creationflags)

    if not _wait_port(check_host, check_port, timeout_s=6.0):
        try:
            proc.terminate()
        except Exception:
            pass
        raise RuntimeError(f"[MOSQ] no abrió {check_host}:{check_port}. Revisa MOSQUITTO_CONF={mosq_conf}")

    print(f"[MOSQ] listo en {check_host}:{check_port}")
    return proc, log_fh

def stop_proc(proc, name: str, log_fh=None):
    if proc is None:
        return
    try:
        if os.name == "nt":
            # En Windows, CTRL_BREAK_EVENT puede funcionar si está en su propio process group.
            try:
                proc.send_signal(getattr(signal, "CTRL_BREAK_EVENT"))
                proc.wait(timeout=3)
            except Exception:
                proc.terminate()
                proc.wait(timeout=3)
        else:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    finally:
        if log_fh:
            try:
                log_fh.close()
            except Exception:
                pass
        print(f"[STOP] {name}")

def main():
    py = sys.executable

    # ENV común para planner + api_server (tu stack ya lo hace). :contentReference[oaicite:3]{index=3}
    env = os.environ.copy()
    env.update({
        "MQTT_HOST": MQTT_HOST,
        "MQTT_PORT": str(MQTT_PORT),
        "MQTT_TRANSPORT": MQTT_TRANSPORT,
        "MQTT_TLS": MQTT_TLS,
        "MQTT_WS_PATH": MQTT_WS_PATH,
        "CMD_TOPIC": CMD_TOPIC,
        "GOAL_TOPIC": GOAL_TOPIC,
        "MQTT_KEEPALIVE": MQTT_KEEPALIVE,
        "PYTHONUNBUFFERED": "1",
    })

    # 1) Broker local (subproceso)
    mosq, mosq_log = start_mosquitto_if_needed()

    # 2) Planner
    planner = subprocess.Popen([
        py, "planner_mqtt.py",
        "--host", MQTT_HOST,
        "--port", str(MQTT_PORT),
        "--cmd_topic", CMD_TOPIC,
        "--goal_topic", GOAL_TOPIC,
        "--dt", "0.1"
    ], env=env)

    # 3) API + sitio web (FastAPI sirve estáticos). :contentReference[oaicite:4]{index=4}
    web = subprocess.Popen([
        py, "-m", "uvicorn",
        "api_server:app",
        "--host", "0.0.0.0",
        "--port", "8000"
    ], env=env)

    try:
        web.wait()
    except KeyboardInterrupt:
        pass
    finally:
        # Apaga clientes primero, broker al final.
        stop_proc(web, "uvicorn")
        stop_proc(planner, "planner")
        stop_proc(mosq, "mosquitto", log_fh=mosq_log)

if __name__ == "__main__":
    main()
