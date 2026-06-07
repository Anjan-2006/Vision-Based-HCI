import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['GLOG_minloglevel'] = '2'

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="google.protobuf")

import platform
import cv2
import time
import numpy as np
from hand_tracker import HandTracker
from gesture_detector import GestureDetector
from controller import SystemController
from utils import FPSCounter, calculate_distance, UIMessageManager, draw_glass_panel, draw_rounded_rect
from platform_utils import PLATFORM
from drawing_dashboard import DrawingDashboard, apply_neon_glow, apply_vignette

def main():
    # Camera Config — auto-detect working camera index
    wCam, hCam = 640, 480
    cap = None
    for cam_idx in [0, 1, 2]:
        test_cap = cv2.VideoCapture(cam_idx)
        if test_cap.isOpened():
            ret, test_frame = test_cap.read()
            if ret and test_frame is not None:
                cap = test_cap
                print(f"[CAMERA] Using camera index {cam_idx}")
                break
        test_cap.release()
    
    if cap is None:
        print("[ERROR] No working camera found. Tried indices 0, 1, 2.")
        print("[ERROR] Please check camera connection and permissions.")
        return
    
    cap.set(3, wCam)
    cap.set(4, hCam)
    
    # Modules
    tracker = HandTracker(max_hands=1, detection_con=0.7, track_con=0.7)
    gesture_detector = GestureDetector(stability_duration=0.1)
    controller = SystemController(wCam, hCam)
    fps_counter = FPSCounter()
    dashboard = DrawingDashboard(wCam, hCam)
    
    # Modes
    MODES = ["MOUSE", "MEDIA", "DRAWING", "BRIGHTNESS"]
    current_mode_idx = 0
    mode_switch_cooldown = 0
    
    CAM_MODES = ["CAM ON", "CAM DIM", "CAM DARK"]
    cam_mode_idx = 0
    last_cam_toggle_time = 0
    
    # State tracking and UI Managers
    last_hand_seen_time = time.time()
    mode_switch_start_time = 0
    is_switching_mode = False
    ui_messages = UIMessageManager(display_duration=1.5)
    system_status = "ACTIVE"
    frame_count = 0
    env_check_counter = 0
    is_fullscreen = False
    
    # Mouse state for dashboard interaction
    mouse_state = {"event": None, "x": -1, "y": -1}
    
    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            mouse_state["event"] = "down"
            mouse_state["x"] = x
            mouse_state["y"] = y
        elif event == cv2.EVENT_MOUSEMOVE and (flags & cv2.EVENT_FLAG_LBUTTON):
            mouse_state["event"] = "drag"
            mouse_state["x"] = x
            mouse_state["y"] = y
        elif event == cv2.EVENT_LBUTTONUP:
            mouse_state["event"] = "up"
    
    print("System Starting... Press 'q' in the window to exit.")

    # Create window with WINDOW_NORMAL for proper fullscreen support
    cv2.namedWindow("Gesture Control HCI", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Gesture Control HCI", wCam, hCam)
    cv2.setMouseCallback("Gesture Control HCI", on_mouse)
    if PLATFORM != "Darwin":
        cv2.setWindowProperty("Gesture Control HCI", cv2.WND_PROP_TOPMOST, 1)


    while True:
        success, frame = cap.read()
        if not success:
            continue
            
        # Flip frame horizontally for intuitive mirroring
        frame = cv2.flip(frame, 1)
        
        # 1. Pipeline: Detect hands
        tracker.find_hands(frame, draw=False)
        
        if CAM_MODES[cam_mode_idx] == "CAM DIM":
            frame = cv2.addWeighted(frame, 0.3, np.zeros_like(frame), 0, 0)
        elif CAM_MODES[cam_mode_idx] == "CAM DARK":
            frame = np.zeros_like(frame)
            
        if tracker.results.multi_hand_landmarks:
            for handLms in tracker.results.multi_hand_landmarks:
                tracker._draw_neon_hand(frame, handLms)
                
        lmList = tracker.get_position(frame)
        
        gesture = "UNKNOWN"
        mode_text = MODES[current_mode_idx]
        
        # --- IDLE DETECTION ---
        if len(lmList) == 0:
            if time.time() - last_hand_seen_time > 2.0:
                system_status = "IDLE"
                # Premium idle indicator — glass pill at center
                idle_text = "Waiting for Hand..."
                (tw, th), _ = cv2.getTextSize(idle_text, cv2.FONT_HERSHEY_DUPLEX, 0.65, 1)
                px, py = wCam//2, hCam//2
                draw_glass_panel(frame, (px - tw//2 - 20, py - th - 10), (px + tw//2 + 20, py + 12),
                                 alpha=0.7, bg_color=(10, 10, 15), border_color=(60, 40, 100), radius=16)
                # Pulsing dot
                pulse = int(3 * abs(np.sin(time.time() * 3)))
                cv2.circle(frame, (px - tw//2 - 6, py - th//2 + 1), 4 + pulse, (0, 100, 255), cv2.FILLED, cv2.LINE_AA)
                cv2.putText(frame, idle_text, (px - tw//2 + 6, py),
                            cv2.FONT_HERSHEY_DUPLEX, 0.65, (160, 160, 180), 1, cv2.LINE_AA)
        else:
            last_hand_seen_time = time.time()
            system_status = "ACTIVE"
            
            # 2. Pipeline: Detect Gestures
            gesture = gesture_detector.detect_gesture(lmList)
            
            # Mode Switching (Fast Close Palm with Progress Bar)
            if gesture == "CLOSED_PALM":
                if not is_switching_mode:
                    is_switching_mode = True
                    mode_switch_start_time = time.time()
                
                hold_duration = time.time() - mode_switch_start_time
                progress = min(hold_duration / 3.0, 1.0) # 3 seconds required
                
                # Glassmorphism Progress Bar
                bar_w = 180
                bx1, by1 = wCam//2 - bar_w//2, 148
                bx2, by2 = wCam//2 + bar_w//2, 168
                draw_glass_panel(frame, (bx1 - 6, by1 - 22), (bx2 + 6, by2 + 6),
                                 alpha=0.7, bg_color=(10, 10, 15), border_color=(80, 60, 120), radius=10)
                # Track
                cv2.rectangle(frame, (bx1, by1 + 2), (bx2, by2 - 2), (30, 30, 35), cv2.FILLED)
                # Fill with neon gradient
                fill_w = int(bar_w * progress)
                if fill_w > 0:
                    neon = (int(255 * (1-progress)), int(255 * progress), 100)
                    cv2.rectangle(frame, (bx1, by1 + 2), (bx1 + fill_w, by2 - 2), neon, cv2.FILLED)
                    cv2.rectangle(frame, (bx1 + fill_w - 2, by1), (bx1 + fill_w, by2), (200, 255, 200), cv2.FILLED)
                # Label
                cv2.putText(frame, "SWITCHING MODE", (bx1 + 20, by1 - 6),
                            cv2.FONT_HERSHEY_DUPLEX, 0.45, (200, 200, 220), 1, cv2.LINE_AA)
                
                # Switch if hold bar completes and cooldown allows
                if progress >= 1.0 and (time.time() - mode_switch_cooldown) > 1.2:
                    current_mode_idx = (current_mode_idx + 1) % len(MODES)
                    mode_switch_cooldown = time.time()
                    is_switching_mode = False
                    
                    # Task 2E: Auto-Clear on Mode Switch
                    if MODES[current_mode_idx] != "DRAWING":
                        controller.clear_canvas()
                        ui_messages.set_message("CANVAS AUTO-CLEARED")
                    else:
                        ui_messages.set_message(f"Switched to {MODES[current_mode_idx]}")
                    
                    controller.stop_drawing()
                    controller.reset_click()
            else:
                is_switching_mode = False # Cancel progress if gesture lost

            # ----- ACTION ROUTING BASED ON MODE -----
            
            x_index, y_index = lmList[8][1], lmList[8][2]
            
            # Global UI: Camera Button Toggle via Pinch
            if gesture == "PINCH":
                if 12 <= x_index <= 120 and 45 <= y_index <= 75:
                    if time.time() - last_cam_toggle_time > 1.0:
                        cam_mode_idx = (cam_mode_idx + 1) % len(CAM_MODES)
                        last_cam_toggle_time = time.time()
                        ui_messages.set_message(CAM_MODES[cam_mode_idx])
                    gesture = "UNKNOWN" # Consume gesture
            
            if mode_text == "MOUSE" and not is_switching_mode:
                # Precision Mode Logic - Remapped to THUMB_UP to free TWO_FINGERS
                is_precision = (gesture == "THUMB_UP")
                if is_precision:
                    ui_messages.set_message("PRECISION MODE ACTIVE")
                
                if gesture == "INDEX_UP" or is_precision:
                    controller.move_mouse(x_index, y_index, precision_mode=is_precision)
                    controller.reset_click()
                    
                    # Virtual cursor at SYNCED smooth coordinates (not raw fingertip)
                    vc_x, vc_y = controller.vcursor_x, controller.vcursor_y
                    hover_action, _ = controller.check_palette_hover(vc_x, vc_y, False)
                    is_hovering = hover_action in ["HOVER", "HOVER_CLEAR"]
                    controller.draw_virtual_cursor(frame, vc_x, vc_y, hovering=is_hovering)
                    
                elif gesture == "PINCH":
                    # Click at last known synced cursor position
                    vc_x, vc_y = controller.vcursor_x, controller.vcursor_y
                    controller.draw_virtual_cursor(frame, vc_x, vc_y, clicking=True)
                    if controller.left_click():
                        ui_messages.set_message("LEFT CLICK")
                        
                elif gesture == "TWO_FINGERS":
                    # Right click at last known synced cursor position
                    vc_x, vc_y = controller.vcursor_x, controller.vcursor_y
                    controller.draw_virtual_cursor(frame, vc_x, vc_y, clicking=True)
                    if controller.right_click():
                        ui_messages.set_message("RIGHT CLICK")
                        
                else:
                    controller.reset_click()
                    
            elif mode_text == "MEDIA" and not is_switching_mode:
                if gesture == "INDEX_UP" or gesture == "OPEN_PALM":
                    thumb_pos = lmList[4][1:]
                    index_pos = lmList[8][1:]
                    dist = calculate_distance(thumb_pos, index_pos)
                    cv2.line(frame, tuple(thumb_pos), tuple(index_pos), (200, 100, 255), 2, cv2.LINE_AA)
                    controller.handle_volume(dist, frame)
                    
            elif mode_text == "DRAWING" and not is_switching_mode:
                
                if gesture == "OPEN_PALM":
                    # ERASER — priority over dashboard
                    palm_x, palm_y = lmList[9][1], lmList[9][2]
                    ex, ey = controller.erase(palm_x, palm_y, radius=30)
                    # Neon eraser ring
                    cv2.circle(frame, (ex, ey), 30, (200, 150, 255), 2, cv2.LINE_AA)
                    cv2.circle(frame, (ex, ey), 32, (100, 60, 140), 1, cv2.LINE_AA)
                    cv2.circle(frame, (ex, ey), 4, (255, 200, 255), cv2.FILLED, cv2.LINE_AA)
                    cv2.putText(frame, "ERASE", (ex + 36, ey + 4),
                                cv2.FONT_HERSHEY_DUPLEX, 0.4, (200, 180, 220), 1, cv2.LINE_AA)
                    controller.stop_drawing()
                
                elif gesture == "INDEX_UP" or gesture == "PINCH":
                    is_pinch = (gesture == "PINCH")
                    # Check dashboard interaction first
                    db_action, db_data = dashboard.check_interaction(x_index, y_index, is_pinching=is_pinch)
                    
                    if db_action == "COLOR":
                        controller.draw_color = dashboard.draw_color
                        ui_messages.set_message(f"COLOR: {db_data}")
                        controller.stop_drawing()
                    elif db_action == "THICKNESS":
                        ui_messages.set_message(f"BRUSH: {db_data}px")
                        controller.stop_drawing()
                    elif db_action == "GLOW":
                        ui_messages.set_message(f"GLOW: {db_data}%")
                        controller.stop_drawing()
                    elif db_action == "UNDO":
                        controller.undo()
                        ui_messages.set_message("UNDO")
                        controller.stop_drawing()
                    elif db_action == "CLEAR":
                        controller.clear_canvas()
                        ui_messages.set_message("CANVAS CLEARED")
                        controller.stop_drawing()
                    elif db_action == "SAVE":
                        controller.save_screenshot(frame)
                        ui_messages.set_message("SAVED!")
                        controller.stop_drawing()
                    elif db_action == "HOVER":
                        controller.stop_drawing()
                    elif gesture == "INDEX_UP":
                        # Not hovering dashboard — draw on canvas
                        controller.save_undo_state() if not hasattr(controller, '_drawing_active') or not controller._drawing_active else None
                        controller._drawing_active = True
                        controller.draw(x_index, y_index, dashboard.thickness * 3)
                    else:
                        controller.stop_drawing()
                
                else:
                    controller.stop_drawing()
                    controller.stop_erasing()
                    controller._drawing_active = False
                    controller.reset_click()
                    
            elif mode_text == "BRIGHTNESS" and not is_switching_mode:
                if gesture == "INDEX_UP" or gesture == "OPEN_PALM":
                    thumb_pos = lmList[4][1:]
                    index_pos = lmList[8][1:]
                    dist = calculate_distance(thumb_pos, index_pos)
                    cv2.line(frame, tuple(thumb_pos), tuple(index_pos), (0, 180, 255), 2, cv2.LINE_AA)
                    controller.handle_brightness(dist, frame)
                    
                    # Periodic environment analysis (every ~60 frames)
                    env_check_counter += 1
                    if env_check_counter % 60 == 0:
                        env_msg = controller.analyze_environment(frame)
                        if env_msg:
                            ui_messages.set_message(env_msg)

        # Merge drawing canvas with neon glow effect
        glow_canvas = apply_neon_glow(controller.canvas, dashboard.glow_intensity)
        gray_canvas = cv2.cvtColor(glow_canvas, cv2.COLOR_BGR2GRAY)
        _, inv_canvas = cv2.threshold(gray_canvas, 20, 255, cv2.THRESH_BINARY_INV)
        inv_canvas = cv2.cvtColor(inv_canvas, cv2.COLOR_GRAY2BGR)
        frame = cv2.bitwise_and(frame, inv_canvas)
        frame = cv2.bitwise_or(frame, glow_canvas)
        
        # --- Handle mouse interaction for Global UI ---
        if mouse_state["event"] == "down":
            mx, my = mouse_state["x"], mouse_state["y"]
            if 12 <= mx <= 120 and 45 <= my <= 75:
                cam_mode_idx = (cam_mode_idx + 1) % len(CAM_MODES)
                ui_messages.set_message(CAM_MODES[cam_mode_idx])
                mouse_state["event"] = None

        # --- Handle mouse interaction on dashboard (DRAWING mode) ---
        if mode_text == "DRAWING" and mouse_state["event"]:
            mx, my = mouse_state["x"], mouse_state["y"]
            mc_action, mc_data = None, None
            
            if mouse_state["event"] == "down":
                mc_action, mc_data = dashboard.handle_mouse_down(mx, my)
            elif mouse_state["event"] == "drag":
                mc_action, mc_data = dashboard.handle_mouse_move(mx, my)
            elif mouse_state["event"] == "up":
                dashboard.handle_mouse_up()
            
            if mc_action == "COLOR":
                controller.draw_color = dashboard.draw_color
                ui_messages.set_message(f"COLOR: {mc_data}")
            elif mc_action == "THICKNESS":
                ui_messages.set_message(f"BRUSH: {mc_data}px")
            elif mc_action == "GLOW":
                ui_messages.set_message(f"GLOW: {mc_data}%")
            elif mc_action == "UNDO":
                controller.undo()
                ui_messages.set_message("UNDO")
            elif mc_action == "CLEAR":
                controller.clear_canvas()
                ui_messages.set_message("CANVAS CLEARED")
            elif mc_action == "SAVE":
                controller.save_screenshot(frame)
                ui_messages.set_message("SAVED!")
            
            mouse_state["event"] = None

        # Apply cinematic vignette across all modes (lighter for non-drawing)
        if mode_text == "DRAWING":
            frame = apply_vignette(frame, strength=0.25)
        else:
            frame = apply_vignette(frame, strength=0.12)

        # 3. Pipeline: Modern Glassmorphism HUD
        fps = fps_counter.update(frame)
        
        # Color palette
        neon_cyan = (255, 255, 0)
        neon_pink = (255, 0, 255)
        neon_green = (0, 255, 100)
        neon_amber = (0, 200, 255)
        
        # --- TOP-LEFT: FPS glass pill ---
        fps_text = f'{int(fps)} FPS'
        (ftw, fth), _ = cv2.getTextSize(fps_text, cv2.FONT_HERSHEY_DUPLEX, 0.45, 1)
        draw_glass_panel(frame, (12, 10), (12 + ftw + 20, 10 + fth + 14),
                         alpha=0.65, bg_color=(10, 10, 15), border_color=(50, 50, 70), radius=10)
        cv2.putText(frame, fps_text, (22, 10 + fth + 4),
                    cv2.FONT_HERSHEY_DUPLEX, 0.45, (140, 140, 160), 1, cv2.LINE_AA)
                    
        # --- TOP-LEFT: Camera Mode glass pill ---
        cam_text = CAM_MODES[cam_mode_idx]
        (ctw, cth), _ = cv2.getTextSize(cam_text, cv2.FONT_HERSHEY_DUPLEX, 0.45, 1)
        draw_glass_panel(frame, (12, 45), (12 + ctw + 20, 45 + cth + 14),
                         alpha=0.65, bg_color=(10, 10, 15), border_color=(50, 70, 50), radius=10)
        cv2.putText(frame, cam_text, (22, 45 + cth + 4),
                    cv2.FONT_HERSHEY_DUPLEX, 0.45, (140, 160, 140), 1, cv2.LINE_AA)
        
        # --- TOP-RIGHT: Mode indicator floating pill ---
        mode_icons = {"MOUSE": "MOUSE", "MEDIA": "MEDIA", "DRAWING": "DRAW", "BRIGHTNESS": "BRIGHT"}
        mode_colors = {"MOUSE": neon_green, "MEDIA": neon_cyan, "DRAWING": neon_pink, "BRIGHTNESS": neon_amber}
        mode_label = mode_icons.get(mode_text, mode_text)
        mode_color = mode_colors.get(mode_text, neon_cyan)
        
        (mtw, mth), _ = cv2.getTextSize(mode_label, cv2.FONT_HERSHEY_DUPLEX, 0.55, 1)
        pill_w = mtw + 40
        pill_x1 = wCam - pill_w - 12
        pill_y1 = 10
        pill_x2 = wCam - 12
        pill_y2 = pill_y1 + mth + 16
        
        # Glass background
        draw_glass_panel(frame, (pill_x1, pill_y1), (pill_x2, pill_y2),
                         alpha=0.7, bg_color=(12, 12, 18), border_color=tuple(max(30, c//2) for c in mode_color), radius=12)
        
        # Glowing dot indicator
        dot_x = pill_x1 + 14
        dot_y = (pill_y1 + pill_y2) // 2
        pulse = int(2 * abs(np.sin(time.time() * 4)))
        cv2.circle(frame, (dot_x, dot_y), 4 + pulse, mode_color, cv2.FILLED, cv2.LINE_AA)
        cv2.circle(frame, (dot_x, dot_y), 7 + pulse, tuple(c//3 for c in mode_color), 1, cv2.LINE_AA)
        
        # Mode text
        cv2.putText(frame, mode_label, (dot_x + 12, pill_y2 - 7),
                    cv2.FONT_HERSHEY_DUPLEX, 0.55, mode_color, 1, cv2.LINE_AA)

        # --- BOTTOM-LEFT: Gesture pill (minimal) ---
        if gesture != "UNKNOWN":
            g_text = gesture.replace("_", " ")
            (gtw, gth), _ = cv2.getTextSize(g_text, cv2.FONT_HERSHEY_DUPLEX, 0.4, 1)
            gx1 = 12
            gy2 = hCam - 12
            gy1 = gy2 - gth - 12
            gx2 = gx1 + gtw + 20
            draw_glass_panel(frame, (gx1, gy1), (gx2, gy2),
                             alpha=0.6, bg_color=(10, 10, 15), border_color=(50, 50, 70), radius=8)
            cv2.putText(frame, g_text, (gx1 + 10, gy2 - 5),
                        cv2.FONT_HERSHEY_DUPLEX, 0.4, (140, 160, 160), 1, cv2.LINE_AA)

        # --- Drawing dashboard ---
        if mode_text == "DRAWING":
            dashboard.render(frame)
            
        # Show UI Messages (Fading)
        ui_messages.draw(frame, wCam, hCam)
        
        # Show Output
        cv2.imshow("Gesture Control HCI", frame)
        # Keep window on top (Linux only — macOS doesn't support this well)
        frame_count += 1
        if PLATFORM == "Linux" and frame_count % 30 == 0:
            cv2.setWindowProperty("Gesture Control HCI", cv2.WND_PROP_TOPMOST, 1)
        
        # Exit behavior
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('f'):
            is_fullscreen = not is_fullscreen
            if is_fullscreen:
                cv2.setWindowProperty("Gesture Control HCI", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            else:
                cv2.setWindowProperty("Gesture Control HCI", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
