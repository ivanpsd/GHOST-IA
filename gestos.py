import cv2
import pyautogui
import threading
import time

camera_ativa = False
thread_camera_ref = None

def loop_monitor_camera():
    global camera_ativa
    try:
        cap = cv2.VideoCapture(0)
        ult_acao = 0

        while camera_ativa and cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape

            # Área restrita de detecção
            cv2.rectangle(frame, (int(w*0.3), int(h*0.1)), (int(w*0.7), int(h*0.5)), (255, 0, 0), 2)
            cv2.putText(frame, "GHOST - Aproxime a mao", (20, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            roi = frame[int(h*0.1):int(h*0.5), int(w*0.3):int(w*0.7)]
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, (15, 15), 0)
            
            # Limiar ajustado para evitar falsos positivos
            _, thresh = cv2.threshold(blur, 60, 255, cv2.THRESH_BINARY_INV)

            contornos, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

            if contornos:
                maior_contorno = max(contornos, key=cv2.contourArea)
                area = cv2.contourArea(maior_contorno)

                # Exige movimento nítido dentro do retângulo
                if area > 18000:
                    cv2.drawContours(roi, [maior_contorno], -1, (0, 255, 0), 2)
                    agora = time.time()

                    # Trava de tempo para evitar múltiplos disparos falsos
                    if agora - ult_acao > 4.0:
                        if area > 35000:
                            pyautogui.press("volumemute")
                            ult_acao = agora
                        elif area > 18000:
                            pyautogui.press("playpause")
                            ult_acao = agora

            cv2.imshow("GHOST - Detector de Gestos", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()
    except Exception as e:
        print(f"Erro na câmera: {e}")
    finally:
        camera_ativa = False

def alternar_camera(ligar=True, falar_callback=None):
    global camera_ativa, thread_camera_ref
    if ligar and not camera_ativa:
        camera_ativa = True
        thread_camera_ref = threading.Thread(target=loop_monitor_camera, daemon=True)
        thread_camera_ref.start()
        if falar_callback:
            falar_callback("Câmera de gestos ativada, senhor.")
    elif not ligar and camera_ativa:
        camera_ativa = False
        if falar_callback:
            falar_callback("Câmera de gestos desativada, senhor.")