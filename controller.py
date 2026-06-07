import pyautogui
import numpy as np
import cv2
import os
import time
from utils import EMAFilter, calculate_distance, draw_glass_panel, draw_rounded_rect
from platform_utils import set_brightness, set_volume, analyze_frame_brightness, get_platform_name

# PyAutoGUI Failsafe and Setup
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

class SystemController:
    def __init__(self, cam_w, cam_h):
        self.cam_w = cam_w
        self.cam_h = cam_h
        self.screen_w, self.screen_h = pyautogui.size()
        
        # Smoothers
        self.ema_x = EMAFilter(alpha=0.2)
        self.ema_y = EMAFilter(alpha=0.2)
        
        # Active States
        self.is_clicking = False
        self.last_click_time = 0
        self.click_cooldown = 0.5
        
        # Drawing Canvas
        self.canvas = np.zeros((self.cam_h, self.cam_w, 3), np.uint8)
        self.draw_color = (255, 0, 255) # Magenta
        self.colors = [(255, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255)]
        self.color_names = ["MAGENTA", "GREEN", "BLUE", "YELLOW"]
        self.color_idx = 0
        self.prev_draw_pt = None
        
        # Undo stack
        self.undo_stack = []
        self.max_undo = 10
        
        # Color Palette Settings
        self.last_color_change_time = 0
        self.palette_radius = 20
        self.pulse_idx = -1
        self.pulse_time = 0
        start_x = (self.cam_w // 2) - 90
        # Centers for floating palette at the top
        self.palette_centers = [(start_x + (i * 60), 95) for i in range(4)]
        
        # Volume Box
        self.vol_bar = 400
        self.vol_per = 0
        self.last_vol_per = 0
        
        # Brightness Control
        self.brightness_bar = 400
        self.brightness_per = 50
        self.last_brightness_per = 50
        self.brightness_ema = EMAFilter(alpha=0.15)
        
        # Adaptive Environment
        self.env_brightness = "NORMAL"
        self.env_sensitivity = 1.0
        self.last_env_check = 0
        
        # Click Animation State
        self.click_ripple_active = False
        self.click_ripple_start = 0
        self.click_ripple_pos = (0, 0)
        
        # Platform info
        self.platform_name = get_platform_name()
        
        # Virtual cursor position (camera-space, synced with system cursor)
        self.vcursor_x = cam_w // 2
        self.vcursor_y = cam_h // 2

    def move_mouse(self, index_x, index_y, precision_mode=False):
        """Advanced cursor targeting with predictive smoothing and true cursor physics."""
        # 1A. COMFORTABLE CONTROL REGION — small border only
        frame_r = 30
        
        # 1B. FULL-SCREEN INTERPOLATION
        idx_x = np.clip(index_x, frame_r, self.cam_w - frame_r)
        idx_y = np.clip(index_y, frame_r, self.cam_h - frame_r)
        
        base_target_x = np.interp(idx_x, (frame_r, self.cam_w - frame_r), (0, self.screen_w))
        base_target_y = np.interp(idx_y, (frame_r, self.cam_h - frame_r), (0, self.screen_h))
        
        if not hasattr(self, 'mouse_prev_pt'):
            self.mouse_prev_pt = (base_target_x, base_target_y)
            self.mouse_ema_x = EMAFilter(alpha=0.5)
            self.mouse_ema_y = EMAFilter(alpha=0.5)
            
        # Velocity calculation for dynamic scaling
        dist = calculate_distance((base_target_x, base_target_y), self.mouse_prev_pt)
        self.live_velocity = dist
        
        # 2B. DEAD-ZONE FILTER (Ignore tiny tremors perfectly)
        if dist < 6:
            base_target_x, base_target_y = self.mouse_prev_pt
            self.live_velocity = 0 # Update UI clearly
            
        self.mouse_prev_pt = (base_target_x, base_target_y)
        
        # 1C. NON-LINEAR EDGE ACCELERATION
        # Compute distance from center of screen to boost edge speeds
        screen_cx, screen_cy = self.screen_w / 2, self.screen_h / 2
        dist_to_center = calculate_distance((base_target_x, base_target_y), (screen_cx, screen_cy))
        max_dist_center = calculate_distance((0,0), (screen_cx, screen_cy))
        
        # Edge multiplier increases dramatically near the edges
        edge_multiplier = np.interp(dist_to_center, [max_dist_center * 0.4, max_dist_center], [1.0, 2.5])
        
        # 2A & 2C. DYNAMIC EMA SMOOTHING & VELOCITY MOTION
        if precision_mode:
            self.speed_mode_text = "PRECISION"
            alpha = 0.05
        else:
            # Low velocity = tight smoothing. High velocity = high alpha (snappy, fast).
            alpha = np.interp(self.live_velocity, [0, 150], [0.15, 0.85])
            
            # Apply edge multiplier to make reaching edges effortless
            alpha = min(1.0, alpha * edge_multiplier)
            
            if dist > 80:
                self.speed_mode_text = "FAST"
            else:
                self.speed_mode_text = "NORMAL"
                
        self.live_alpha = alpha
        self.mouse_ema_x.alpha = alpha
        self.mouse_ema_y.alpha = alpha
        
        smooth_x = self.mouse_ema_x.update(base_target_x)
        smooth_y = self.mouse_ema_y.update(base_target_y)
        
        # 4. PREDICTIVE TRACKING (Zero lag behind fingertip)
        if not hasattr(self, 'last_smooth_x'):
            self.last_smooth_x, self.last_smooth_y = smooth_x, smooth_y
            
        vel_x = smooth_x - self.last_smooth_x
        vel_y = smooth_y - self.last_smooth_y
        
        # Extrapolate slightly ahead of pure smoothed value
        predict_x = int(smooth_x + (vel_x * 0.4))
        predict_y = int(smooth_y + (vel_y * 0.4))
        
        self.last_smooth_x, self.last_smooth_y = smooth_x, smooth_y
        self.live_coords = (predict_x, predict_y)
        
        # REVERSE-MAP: screen coords → camera coords for virtual cursor sync
        self.vcursor_x = int(np.interp(predict_x, (0, self.screen_w), (frame_r, self.cam_w - frame_r)))
        self.vcursor_y = int(np.interp(predict_y, (0, self.screen_h), (frame_r, self.cam_h - frame_r)))
        
        
        try:
            pyautogui.moveTo(predict_x, predict_y)
        except Exception as e:
            print(f"[CURSOR ERROR] pyautogui.moveTo failed: {e}")

    def left_click(self):
        """Perform a single left click with cooldown."""
        if not self.is_clicking and (time.time() - self.last_click_time > self.click_cooldown):
            pyautogui.click()
            self.is_clicking = True
            self.last_click_time = time.time()
            return True
        return False

    def right_click(self):
        """Perform a single right click with cooldown."""
        if not self.is_clicking and (time.time() - self.last_click_time > self.click_cooldown):
            pyautogui.click(button='right')
            self.is_clicking = True
            self.last_click_time = time.time()
            return True
        return False
            
    def reset_click(self):
        """Reset click debounce state."""
        self.is_clicking = False

    def handle_volume(self, dist, frame):
        """Map distance to volume increments and draw UI using thresholds."""
        dist = max(30, min(dist, 200))
        self.vol_bar = np.interp(dist, [30, 200], [400, 150])
        self.vol_per = np.interp(dist, [30, 200], [0, 100])
        
        if abs(self.vol_per - self.last_vol_per) > 5:
            target_vol = int(self.vol_per)
            set_volume(target_vol)
            self.last_vol_per = self.vol_per
            
        # Glassmorphism Volume Bar
        bar_x1, bar_x2 = 42, 88
        draw_glass_panel(frame, (bar_x1 - 8, 130), (bar_x2 + 8, 450),
                         alpha=0.7, bg_color=(12, 12, 18), border_color=(60, 120, 80), radius=14)
        
        # Track background
        cv2.line(frame, ((bar_x1+bar_x2)//2, 155), ((bar_x1+bar_x2)//2, 400),
                 (40, 40, 45), 4, cv2.LINE_AA)
        
        # Fill glow
        fill_top = int(self.vol_bar)
        neon_green = (100, 255, 120)
        cv2.rectangle(frame, (bar_x1 + 6, fill_top), (bar_x2 - 6, 400), neon_green, cv2.FILLED)
        # Glow accent at top of fill
        cv2.rectangle(frame, (bar_x1 + 4, fill_top), (bar_x2 - 4, fill_top + 3), (150, 255, 200), cv2.FILLED)
        
        # Speaker icon (simple)
        icx = (bar_x1 + bar_x2) // 2
        cv2.rectangle(frame, (icx - 4, 138), (icx + 4, 148), (200, 200, 200), cv2.FILLED)
        pts = np.array([[icx - 8, 138], [icx - 12, 134], [icx - 12, 152], [icx - 8, 148]], np.int32)
        cv2.fillPoly(frame, [pts], (200, 200, 200))
        
        # Percentage text
        pct = f'{int(self.vol_per)}%'
        (tw, _), _ = cv2.getTextSize(pct, cv2.FONT_HERSHEY_DUPLEX, 0.55, 1)
        cv2.putText(frame, pct, (icx - tw//2, 430),
                    cv2.FONT_HERSHEY_DUPLEX, 0.55, (200, 255, 200), 1, cv2.LINE_AA)

    def draw(self, x, y, dist_for_thickness=100):
        """Draw on the virtual canvas with predictive interpolation."""
        # Task 2B: Stronger Drawing Smoothness (Visibly better flow)
        if not hasattr(self, 'draw_ema_x'):
            self.draw_ema_x = EMAFilter(alpha=0.35) # Smooth but zero lag
            self.draw_ema_y = EMAFilter(alpha=0.35)
            
        # Strongly smooth trajectory specifically for fluid drawing tracking
        smooth_x = self.draw_ema_x.update(x)
        smooth_y = self.draw_ema_y.update(y)
        
        # Calculate velocity for predictive interpolation
        if not hasattr(self, 'last_smooth_x'):
            self.last_smooth_x, self.last_smooth_y = smooth_x, smooth_y

        vel_x = smooth_x - self.last_smooth_x
        vel_y = smooth_y - self.last_smooth_y
        
        # Super-predict ahead to fully counteract extreme EMA lag resulting in unbroken bezier-like curves
        predict_x = int(smooth_x + vel_x * 0.25)
        predict_y = int(smooth_y + vel_y * 0.25)
        
        self.last_smooth_x, self.last_smooth_y = smooth_x, smooth_y
        
        # Map finger distance to brush thickness
        thickness = int(np.interp(dist_for_thickness, [40, 150], [5, 25]))
        
        if self.prev_draw_pt is None:
            self.prev_draw_pt = (predict_x, predict_y)
            
        # Fluid connect line interpolation
        cv2.line(self.canvas, self.prev_draw_pt, (predict_x, predict_y), self.draw_color, thickness)
        self.prev_draw_pt = (predict_x, predict_y)
        
    def stop_drawing(self):
        """Reset drawing connection point."""
        self.prev_draw_pt = None
        if hasattr(self, 'draw_ema_x'): # reset drawing filters on lift
            self.draw_ema_x.val = None
            self.draw_ema_y.val = None
        if hasattr(self, 'last_smooth_x'):
            del self.last_smooth_x
            del self.last_smooth_y
        
    def clear_canvas(self):
        """Erase the drawing canvas."""
        self.save_undo_state()
        self.canvas = np.zeros((self.cam_h, self.cam_w, 3), np.uint8)

    def save_undo_state(self):
        """Save current canvas to undo stack."""
        if len(self.undo_stack) >= self.max_undo:
            self.undo_stack.pop(0)
        self.undo_stack.append(self.canvas.copy())

    def undo(self):
        """Restore previous canvas state."""
        if self.undo_stack:
            self.canvas = self.undo_stack.pop()
            return True
        return False

    def save_screenshot(self, frame):
        """Save the current frame with drawing overlay."""
        import os
        timestamp = int(time.time())
        filename = f"drawing_{timestamp}.png"
        cv2.imwrite(filename, frame)
        print(f"[SAVE] Screenshot saved: {filename}")
        return filename

    def erase(self, x, y, radius=30):
        """Erase content on the canvas by drawing black circles at the given position."""
        # Smooth eraser movement
        if not hasattr(self, 'eraser_ema_x'):
            self.eraser_ema_x = EMAFilter(alpha=0.3)
            self.eraser_ema_y = EMAFilter(alpha=0.3)
        
        smooth_x = int(self.eraser_ema_x.update(x))
        smooth_y = int(self.eraser_ema_y.update(y))
        
        # Erase by drawing black on the canvas
        cv2.circle(self.canvas, (smooth_x, smooth_y), radius, (0, 0, 0), cv2.FILLED)
        
        # Return position for visual feedback
        return smooth_x, smooth_y

    def stop_erasing(self):
        """Reset eraser smoothing filters."""
        if hasattr(self, 'eraser_ema_x'):
            self.eraser_ema_x.val = None
            self.eraser_ema_y.val = None
        
    def check_palette_hover(self, x, y, is_pinching=False):
        """Check if index finger is hovering over a color palette button. Returns (action_type, color_name)."""
        # Task 2C: Expanded forgiving radius for extremely reliable click locking
        for i, center in enumerate(self.palette_centers):
            dist = calculate_distance((x, y), center)
            if dist <= self.palette_radius + 20: # Drastically increased interaction radius
                if is_pinching and (time.time() - self.last_color_change_time > 0.3):
                    self.color_idx = i
                    self.draw_color = self.colors[i]
                    self.last_color_change_time = time.time()
                    # Trigger animation state
                    self.pulse_idx = i
                    self.pulse_time = time.time()
                    return "PINCH", self.color_names[i]
                elif not is_pinching and (time.time() - self.last_color_change_time > 0.3):
                    if self.color_idx != i: # Only trigger hover change if it's a new color
                        self.color_idx = i
                        self.draw_color = self.colors[i]
                        self.last_color_change_time = time.time()
                        return "HOVER", self.color_names[i]
                return "IGNORE", self.color_names[i] # Waiting for cooldown or just hovering
                
        # Check Dashboard Clear Button
        clear_center = (self.cam_w - 90, 80)
        dist_clear = calculate_distance((x, y), clear_center)
        if dist_clear <= 40:
            if is_pinching and (time.time() - self.last_color_change_time > 0.3):
                self.clear_canvas()
                self.last_color_change_time = time.time()
                return "CLEAR", "DASHBOARD"
            return "HOVER_CLEAR", None
            
        return None, None

    # =============================================
    # BRIGHTNESS CONTROL
    # =============================================

    def handle_brightness(self, dist, frame):
        """Map thumb-index distance to screen brightness with smooth interpolation and neon UI."""
        dist = max(30, min(dist, 200))
        effective_range_max = int(200 * self.env_sensitivity)
        raw_per = np.interp(dist, [30, effective_range_max], [5, 100])
        smooth_per = self.brightness_ema.update(raw_per)
        self.brightness_bar = np.interp(smooth_per, [0, 100], [400, 150])
        self.brightness_per = smooth_per
        
        if abs(self.brightness_per - self.last_brightness_per) > 3:
            set_brightness(int(self.brightness_per))
            self.last_brightness_per = self.brightness_per
        
        # Glassmorphism Brightness Bar (right side)
        bar_x1, bar_x2 = self.cam_w - 93, self.cam_w - 52
        draw_glass_panel(frame, (bar_x1 - 10, 130), (bar_x2 + 10, 450),
                         alpha=0.7, bg_color=(12, 12, 18), border_color=(80, 100, 60), radius=14)
        
        # Track
        cx = (bar_x1 + bar_x2) // 2
        cv2.line(frame, (cx, 155), (cx, 400), (40, 40, 45), 4, cv2.LINE_AA)
        
        # Warm amber fill
        fill_top = int(self.brightness_bar)
        cv2.rectangle(frame, (bar_x1 + 4, fill_top), (bar_x2 - 4, 400), (0, 200, 255), cv2.FILLED)
        cv2.rectangle(frame, (bar_x1 + 2, fill_top), (bar_x2 - 2, fill_top + 3), (0, 255, 255), cv2.FILLED)
        
        # Sun icon
        self._draw_sun_icon(frame, cx, 140)
        
        # Percentage
        pct = f'{int(self.brightness_per)}%'
        (tw, _), _ = cv2.getTextSize(pct, cv2.FONT_HERSHEY_DUPLEX, 0.55, 1)
        cv2.putText(frame, pct, (cx - tw//2, 428),
                    cv2.FONT_HERSHEY_DUPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
        
        # Environment badge
        if self.env_brightness == "LOW_LIGHT":
            cv2.putText(frame, "LOW LIGHT", (bar_x1 - 8, 448),
                        cv2.FONT_HERSHEY_PLAIN, 0.8, (0, 150, 255), 1, cv2.LINE_AA)
        elif self.env_brightness == "BRIGHT":
            cv2.putText(frame, "ADAPTIVE", (bar_x1 - 5, 448),
                        cv2.FONT_HERSHEY_PLAIN, 0.8, (0, 255, 200), 1, cv2.LINE_AA)

    def _draw_sun_icon(self, frame, cx, cy):
        """Draw a glowing sun icon for the brightness bar."""
        # Core sun circle
        cv2.circle(frame, (cx, cy), 8, (0, 255, 255), cv2.FILLED)
        cv2.circle(frame, (cx, cy), 10, (0, 200, 255), 2)
        
        # Radiating lines (8 rays)
        ray_len = 6
        for angle_deg in range(0, 360, 45):
            rad = np.radians(angle_deg)
            x1 = int(cx + 12 * np.cos(rad))
            y1 = int(cy + 12 * np.sin(rad))
            x2 = int(cx + (12 + ray_len) * np.cos(rad))
            y2 = int(cy + (12 + ray_len) * np.sin(rad))
            cv2.line(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)

    def analyze_environment(self, frame):
        """Analyze ambient light from webcam frame and adjust brightness sensitivity."""
        mean_brightness = analyze_frame_brightness(frame)
        
        if mean_brightness < 60:
            self.env_brightness = "LOW_LIGHT"
            self.env_sensitivity = 0.8  # Reduce sensitivity in dark rooms
            return "LOW LIGHT DETECTED"
        elif mean_brightness > 160:
            self.env_brightness = "BRIGHT"
            self.env_sensitivity = 1.2  # Higher responsiveness in bright rooms
            return "ADAPTIVE BRIGHTNESS ACTIVE"
        else:
            self.env_brightness = "NORMAL"
            self.env_sensitivity = 1.0
            return None

    # =============================================
    # VIRTUAL CURSOR SYSTEM
    # =============================================

    def draw_virtual_cursor(self, frame, x, y, hovering=False, clicking=False):
        """Render a premium neon virtual cursor with glow effects."""
        neon_cyan = (255, 255, 0)
        neon_pink = (255, 0, 255)
        soft_glow = (120, 120, 0)
        
        if clicking:
            # Click burst — neon magenta flash with outer glow ring
            cv2.circle(frame, (x, y), 22, neon_pink, cv2.FILLED, cv2.LINE_AA)
            cv2.circle(frame, (x, y), 28, (200, 100, 255), 2, cv2.LINE_AA)
            cv2.circle(frame, (x, y), 36, (150, 50, 200), 1, cv2.LINE_AA)
            self.click_ripple_active = True
            self.click_ripple_start = time.time()
            self.click_ripple_pos = (x, y)
        elif hovering:
            # Hover — pulsing ring with soft outer glow
            pulse = int(3 * np.sin(time.time() * 6))
            r = 18 + pulse
            cv2.circle(frame, (x, y), r + 8, soft_glow, 1, cv2.LINE_AA)
            cv2.circle(frame, (x, y), r, neon_cyan, 2, cv2.LINE_AA)
            cv2.circle(frame, (x, y), 5, neon_pink, cv2.FILLED, cv2.LINE_AA)
        else:
            # Normal — clean neon ring + center dot
            cv2.circle(frame, (x, y), 16, neon_cyan, 2, cv2.LINE_AA)
            cv2.circle(frame, (x, y), 22, soft_glow, 1, cv2.LINE_AA)
            cv2.circle(frame, (x, y), 4, neon_pink, cv2.FILLED, cv2.LINE_AA)
        
        self._draw_click_ripple(frame)

    def _draw_click_ripple(self, frame):
        """Expanding neon ring ripple animation triggered on click events."""
        if not self.click_ripple_active:
            return
        elapsed = time.time() - self.click_ripple_start
        duration = 0.45
        if elapsed > duration:
            self.click_ripple_active = False
            return
        progress = elapsed / duration
        radius = int(22 + 50 * progress)
        alpha = 1.0 - progress
        ci = int(255 * alpha)
        if ci > 0:
            cv2.circle(frame, self.click_ripple_pos, radius,
                       (int(ci*0.5), 0, ci), 2, cv2.LINE_AA)
            cv2.circle(frame, self.click_ripple_pos, radius + 8,
                       (int(ci*0.2), 0, int(ci*0.4)), 1, cv2.LINE_AA)
