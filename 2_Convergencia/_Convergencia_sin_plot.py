#LIBRERIAS
import cv2
import numpy as np

import Bluetooth as Bt
import Camera as cam

import funciones_auxiliares as aux
import control_robot as robotx

import json
import threading
import time
import paho.mqtt.client as mqtt

#-----------INICIALIZACION MQTT--------
MQTT_HOST = "127.0.0.1"      # o la IP LAN del broker
MQTT_PORT = 1883
MQTT_TOPIC_GOAL = "huber/robot/goal"

goal_lock = threading.Lock()
xs = 0.0
ys = 0.0
goal_seq = None
goal_t_ms = None
goal_last_rx_s = 0.0

def _set_goal(x_new, y_new, seq=None, t_ms=None):
    global xs, ys, goal_seq, goal_t_ms, goal_last_rx_s
    with goal_lock:
        xs = int(x_new)
        ys = int(y_new)
        goal_seq = seq
        goal_t_ms = t_ms
        goal_last_rx_s = time.time()

def on_connect(client, userdata, flags, rc, properties=None):
    print(f"[MQTT] conectado a {MQTT_HOST}:{MQTT_PORT} rc={rc}")
    client.subscribe(MQTT_TOPIC_GOAL, qos=0)
    print(f"[MQTT] SUB  {MQTT_TOPIC_GOAL}")

def on_disconnect(client, userdata, rc, properties=None):
    print(f"[MQTT] desconectado rc={rc}")

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        data = json.loads(payload)
        # {"x": -250.0, "y": -100.0, "seq": 10684, "t_ms": 1771014229675}
        _set_goal(data["x"], data["y"], seq=data.get("seq"), t_ms=data.get("t_ms"))
    except Exception as e:
        print(f"[MQTT] mensaje invalido en {msg.topic}: {e} | raw={msg.payload[:200]!r}")

# Compatibilidad paho-mqtt v1/v2
try:
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="convergencia_goal")
except Exception:
    mqtt_client = mqtt.Client(client_id="convergencia_goal")

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_message = on_message
mqtt_client.reconnect_delay_set(min_delay=1, max_delay=5)

print(f"[MQTT] conectando a {MQTT_HOST}:{MQTT_PORT} ...")
mqtt_client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=15)
mqtt_client.loop_start()

#------INICIALIZACION CAMARA------
#HD
resolucionx=1280
resoluciony=720
#Full HD
#resolucionx=1920
#resoluciony=1080
camara=cam.initialize(1,resolucionx,resoluciony)
texto_titulo=""

#-----------CONFIG VISTA (SOLO DISPLAY)-----------
# Esto NO afecta la detección ArUco ni el control; solo espejea lo que se ve en pantalla.
MIRROR_VIEW = True
# flip_code:  1 = espejo horizontal (X), 0 = espejo vertical (Y), -1 = ambos (X & Y)
FLIP_CODE = 0

def flip_xy(px: int, py: int, w: int, h: int, flip_code: int):
    """Transforma coordenadas pixel (px,py) como lo hace cv2.flip en una imagen WxH."""
    if flip_code in (1, -1):
        px = (w - 1) - px
    if flip_code in (0, -1):
        py = (h - 1) - py
    return int(px), int(py)

def flip_points(points, w: int, h: int, flip_code: int):
    """Espejea las esquinas ArUco (points) para que los dibujos coincidan con frame espejeado."""
    if points is None or len(points) == 0:
        return points
    out = []
    for mc in points:
        m = mc.copy()              # mc típico: (1,4,2)
        if flip_code in (1, -1):
            m[..., 0] = (w - 1) - m[..., 0]
        if flip_code in (0, -1):
            m[..., 1] = (h - 1) - m[..., 1]
        out.append(m)
    return out

#------INICIALIZACION ROBOT------
# print("Conectando Robot 0.....")
# robot0=Bt.connect("98:D3:21:F7:B5:70")
# print("Robot 0 OK")

print("Conectando Robot 1.....")
robot1=Bt.connect("98:D3:31:FA:17:5B")
print("Robot 1 OK")

# print("Conectando Robot 2.....")
# robot2=Bt.connect("98:D3:71:F6:63:9C")
# print("Robot 2 OK")

# print("Conectando Robot 3.....")
# robot3=Bt.connect("98:D3:21:F7:B4:86")
# print("Robot 3 OK")

robot_bt=robot1
robot_id=1 #ID del QR a detectar
robot=[[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0]]

#INICIALIZACION DE VALORES ROBOT FISICO 1
wd=0
wi=0
wmax=150 #Velocidad angular robot maxima
l=25 #distancia del centro del robot al centro de las llantas
r=58 #radio llanta (pixeles)
L=120 #distancia entre centros de llantas (pixeles)

#INICIALIZACION DE VARIABLES DE CONTROL
x=0
y=0
th=0
t=0
ex=0
ey=0
ux=0
uy=0

#------VALORES CONTROL------
xs=0 #valor esperado de x
ys=0 #valor y deseado
k=130 #ganancia del control


while (True):

    with goal_lock:
        xs_loop = xs
        ys_loop = ys
        seq_loop = goal_seq
        last_rx = goal_last_rx_s

    #-------BUSQUEDA DE QR´s------
    #print("Buscamos aruco")
    frame, points, ids =cam.buscar_Aruco(camara, resolucionx, resoluciony)
    #print(ids)

    if len(points)>0:
        robot=cam.buscar_robots(points, ids, robot)
        #print("robot0(x="+str(robot[0][0])+",y="+str(robot[0][1])+",th="+str(robot[0][2])+")")

        #------LEY DE CONTROL CONVERGENCIA------

        x=robot[robot_id][0]-(resolucionx/2) #Obtenemos valor X de QR robot 
        y=robot[robot_id][1]-(resoluciony/2) #Obtenemos valor Y de QR robot 
        th=robot[robot_id][2] #Obtenemos valor Th de robot 

        x=x+(l*np.cos(th))
        y=y+(l*np.sin(th))

        A=np.array([[np.cos(th), -l*np.sin(th)],
                    [np.sin(th), l*np.cos(th)]])

        ex,ey,ux,uy=robotx.convergencia(x, y, xs_loop, ys_loop, k) #Calculo de errores y vector velocidad

        B=np.array([ux,uy]) #Arreglo de Vector velocidad

        U=np.linalg.solve(A,B)
        #U=np.linalg.inv(A)*B  No sirve

        V=U[0] #Velocidad Lineal
        W=U[1]  #Velocidad Angular
   
        
        #-------MODELO CINEMATICO ROBOT-------- 
        wd= (V/r)+((L*W)/(2*r)) #Calulo de wd robot unicilo
        wi= (V/r)-((L*W)/(2*r)) #Calulo de wi robot unicilo

        if(wd>wmax):
            wd=wmax
        elif(wd<-wmax):
            wd=-wmax

        if(wi>wmax):
            wi=wmax
        elif(wi<-wmax):
            wi=-wmax

        #print("wd="+str(wd)+"wi="+str(wi))
        #print("robot0(x="+str("%.0f" % x[i])+"y="+str("%.0f" % y[i])+"th="+str("%.2f" % th[i])+", ux="+str("%.0f" % ux[i])+", uy="+str("%.0f" % uy[i])+", V="+str("%.0f" % V)+", W="+str("%.0f" % W)+", wd="+str("%.0f" % wd)+"wi="+str("%.0f" % wi))
       
        Bt.move(robot_bt,wd, wi)

    #-------VENTANA DE CAMARA (SOLO DISPLAY)--------
    # Nota: cálculos usan frame/points originales; aquí solo espejeamos para ver.
    frame_view = frame
    points_view = points
    if MIRROR_VIEW:
        frame_view = cv2.flip(frame_view, FLIP_CODE)
        points_view = flip_points(points_view, resolucionx, resoluciony, FLIP_CODE)

    texto_titulo="CONVERGENCIA (auto)"
    color=(0, 0, 255)
    cam.dibujar_aruco(frame_view, points_view, ids, resolucionx, resoluciony)
    cam.draw_texto_titulo(frame_view, texto_titulo, color)

    # Punto deseado (en pixeles)
    px = int(xs_loop + (resolucionx // 2))
    py = int(ys_loop + (resoluciony // 2))
    if MIRROR_VIEW:
        px, py = flip_xy(px, py, resolucionx, resoluciony, FLIP_CODE)

    cam.draw_punto(frame_view, "XS,YS", (0,0,255), px, py, resolucionx, resoluciony)
    cv2.imshow('Camara detector qr', frame_view)

    if cv2.waitKey(1) & 0xFF == 27: #Presiona esc para salir 
        break

#-------RUTINA DE CIERRE-------- 
Bt.move(robot_bt,0,0)  #Apagamos motores en Robot

mqtt_client.loop_stop()
mqtt_client.disconnect()
Bt.disconnect(robot_bt) #Desconectamos Bluetooth
camara.release() #Liberamos Camara
cv2.destroyAllWindows() #Cerramos ventanas