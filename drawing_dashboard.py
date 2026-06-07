"""
Drawing Dashboard — Clean minimal floating toolbar for drawing mode.
Design inspired by air-draw reference: frosted dark panel, well-spaced
color grid, clean vertical sliders, icon action buttons.
Full mouse support: click colors, drag sliders, click buttons.
"""

import cv2
import numpy as np
import time
from utils import calculate_distance, draw_rounded_rect


class DrawingDashboard:
    """Clean floating drawing toolbar rendered via OpenCV."""

    def __init__(self, cam_w, cam_h):
        self.cam_w = cam_w
        self.cam_h = cam_h

        # Panel — narrow, tall, right-edge
        self.panel_w = 100
        self.panel_h = cam_h - 75
        self.panel_x = cam_w - self.panel_w - 10
        self.panel_y = 65

        # --- COLORS (2 rows x 4 cols) ---
        self.colors = [
            (255, 255, 0),   (255, 0, 255),  (0, 255, 0),    (255, 255, 255),
            (0, 0, 255),     (255, 0, 0),    (200, 0, 200),  (0, 255, 255),
        ]
        self.color_names = [
            "CYAN", "PINK", "GREEN", "WHITE",
            "RED", "BLUE", "PURPLE", "YELLOW",
        ]
        self.selected_color_idx = 0
        self.draw_color = self.colors[0]

        self.dot_r = 10
        dot_gap = 22
        grid_w = dot_gap * 3
        grid_x0 = self.panel_x + (self.panel_w - grid_w) // 2
        grid_y0 = self.panel_y + 45
        self.color_positions = []
        for row in range(2):
            for col in range(4):
                self.color_positions.append(
                    (grid_x0 + col * dot_gap, grid_y0 + row * (dot_gap + 8))
                )

        # --- THICKNESS slider ---
        self.thickness = 5
        self.min_thickness = 2
        self.max_thickness = 25
        sx = self.panel_x + self.panel_w // 2
        self.thick_track_top = grid_y0 + 85
        self.thick_track_bot = self.thick_track_top + 55
        self.thick_x = sx

        # --- GLOW slider ---
        self.glow_intensity = 60
        self.glow_track_top = self.thick_track_bot + 45
        self.glow_track_bot = self.glow_track_top + 55
        self.glow_x = sx

        # --- Action buttons ---
        btn_start_y = self.glow_track_bot + 35
        self.btn_x = sx
        self.btn_r = 13
        self.btn_gap = 32
        self.btn_positions = [
            (self.btn_x, btn_start_y),
            (self.btn_x, btn_start_y + self.btn_gap),
            (self.btn_x, btn_start_y + self.btn_gap * 2),
        ]

        # --- Interaction state ---
        self.hovered_element = None
        self.last_action_time = 0
        self.action_cooldown = 0.35
        self.pulse_idx = -1
        self.pulse_time = 0
        self.dragging = None  # "thickness" or "glow" while mouse dragging

    # ====== VALUE MAPPING ======
    def _val_to_y(self, val, vmin, vmax, ytop, ybot):
        return int(np.interp(val, [vmin, vmax], [ytop, ybot]))

    def _y_to_val(self, y, vmin, vmax, ytop, ybot):
        return int(np.interp(np.clip(y, ytop, ybot), [ytop, ybot], [vmin, vmax]))

    # ====== MOUSE HANDLERS ======
    def handle_mouse_down(self, x, y):
        """Handle mouse press. Returns (action, data) or (None, None)."""
        now = time.time()
        # Colors
        for i, (cx, cy) in enumerate(self.color_positions):
            if calculate_distance((x, y), (cx, cy)) <= self.dot_r + 5:
                self.selected_color_idx = i
                self.draw_color = self.colors[i]
                self.pulse_idx = i
                self.pulse_time = now
                return "COLOR", self.color_names[i]

        # Thickness slider region
        if (abs(x - self.thick_x) < 22 and
                self.thick_track_top - 8 <= y <= self.thick_track_bot + 8):
            self.dragging = "thickness"
            self.thickness = self._y_to_val(
                y, self.min_thickness, self.max_thickness,
                self.thick_track_top, self.thick_track_bot)
            return "THICKNESS", self.thickness

        # Glow slider region
        if (abs(x - self.glow_x) < 22 and
                self.glow_track_top - 8 <= y <= self.glow_track_bot + 8):
            self.dragging = "glow"
            self.glow_intensity = self._y_to_val(
                y, 0, 100, self.glow_track_top, self.glow_track_bot)
            return "GLOW", self.glow_intensity

        # Buttons
        for i, (bx, by) in enumerate(self.btn_positions):
            if calculate_distance((x, y), (bx, by)) <= self.btn_r + 5:
                if now - self.last_action_time > self.action_cooldown:
                    self.last_action_time = now
                    return ["UNDO", "CLEAR", "SAVE"][i], None

        return None, None

    def handle_mouse_move(self, x, y):
        """Handle mouse drag for sliders. Returns (action, data) or (None, None)."""
        if self.dragging == "thickness":
            self.thickness = self._y_to_val(
                y, self.min_thickness, self.max_thickness,
                self.thick_track_top, self.thick_track_bot)
            return "THICKNESS", self.thickness
        elif self.dragging == "glow":
            self.glow_intensity = self._y_to_val(
                y, 0, 100, self.glow_track_top, self.glow_track_bot)
            return "GLOW", self.glow_intensity
        return None, None

    def handle_mouse_up(self):
        self.dragging = None

    # ====== GESTURE INTERACTION (existing pinch logic) ======
    def check_interaction(self, x, y, is_pinching=False):
        now = time.time()
        self.hovered_element = None

        for i, (cx, cy) in enumerate(self.color_positions):
            if calculate_distance((x, y), (cx, cy)) <= self.dot_r + 8:
                self.hovered_element = ("color", i)
                if is_pinching and (now - self.last_action_time > self.action_cooldown):
                    self.selected_color_idx = i
                    self.draw_color = self.colors[i]
                    self.last_action_time = now
                    self.pulse_idx = i
                    self.pulse_time = now
                    return "COLOR", self.color_names[i]
                return "HOVER", None

        if (abs(x - self.thick_x) < 22 and
                self.thick_track_top - 10 <= y <= self.thick_track_bot + 10):
            self.hovered_element = ("thickness",)
            if is_pinching:
                self.thickness = self._y_to_val(
                    y, self.min_thickness, self.max_thickness,
                    self.thick_track_top, self.thick_track_bot)
                return "THICKNESS", self.thickness
            return "HOVER", None

        if (abs(x - self.glow_x) < 22 and
                self.glow_track_top - 10 <= y <= self.glow_track_bot + 10):
            self.hovered_element = ("glow",)
            if is_pinching:
                self.glow_intensity = self._y_to_val(
                    y, 0, 100, self.glow_track_top, self.glow_track_bot)
                return "GLOW", self.glow_intensity
            return "HOVER", None

        for i, (bx, by) in enumerate(self.btn_positions):
            if calculate_distance((x, y), (bx, by)) <= self.btn_r + 8:
                self.hovered_element = ("btn", i)
                if is_pinching and (now - self.last_action_time > self.action_cooldown):
                    self.last_action_time = now
                    return ["UNDO", "CLEAR", "SAVE"][i], None
                return "HOVER", None

        if (self.panel_x - 5 <= x <= self.panel_x + self.panel_w + 5 and
                self.panel_y - 5 <= y <= self.panel_y + self.panel_h + 5):
            return "HOVER", None

        return None, None

    # ====== RENDER ======
    def render(self, frame):
        x1, y1 = self.panel_x, self.panel_y
        x2, y2 = x1 + self.panel_w, y1 + self.panel_h

        # Frosted dark glass panel
        overlay = frame.copy()
        draw_rounded_rect(overlay, (x1, y1), (x2, y2), (22, 22, 28), -1,
                          radius=16, filled=True)
        cv2.addWeighted(overlay, 0.82, frame, 0.18, 0, frame)
        # Subtle border
        draw_rounded_rect(frame, (x1, y1), (x2, y2), (55, 45, 65), 1, radius=16)

        lbl_c = (170, 170, 175)
        dim_c = (100, 100, 110)
        cx = self.panel_x + self.panel_w // 2  # center x

        # ── COLORS ──
        self._put_centered(frame, "COLORS", cx, self.panel_y + 25, 0.38, lbl_c)
        for i, (px, py) in enumerate(self.color_positions):
            r = self.dot_r
            if i == self.pulse_idx and (time.time() - self.pulse_time < 0.25):
                r += int(3 * np.sin((time.time() - self.pulse_time) * np.pi / 0.25))
            if self.hovered_element == ("color", i):
                r += 2
            # Selected ring
            if i == self.selected_color_idx:
                cv2.circle(frame, (px, py), r + 3, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.circle(frame, (px, py), r, self.colors[i], cv2.FILLED, cv2.LINE_AA)

        # ── THICKNESS ──
        sep1 = self.thick_track_top - 28
        cv2.line(frame, (x1 + 12, sep1), (x2 - 12, sep1), (35, 35, 40), 1, cv2.LINE_AA)
        self._put_centered(frame, "THICKNESS", cx, self.thick_track_top - 14, 0.33, lbl_c)
        # Track
        cv2.line(frame, (self.thick_x, self.thick_track_top),
                 (self.thick_x, self.thick_track_bot), (50, 50, 55), 3, cv2.LINE_AA)
        # Fill
        ty = self._val_to_y(self.thickness, self.min_thickness, self.max_thickness,
                            self.thick_track_top, self.thick_track_bot)
        cv2.line(frame, (self.thick_x, self.thick_track_top),
                 (self.thick_x, ty), (140, 100, 180), 2, cv2.LINE_AA)
        # Thumb
        tr = 7 if self.hovered_element != ("thickness",) else 9
        cv2.circle(frame, (self.thick_x, ty), tr, (240, 240, 245), cv2.FILLED, cv2.LINE_AA)
        # Value
        self._put_centered(frame, f"{self.thickness}px", cx, self.thick_track_bot + 16, 0.33, dim_c)

        # ── GLOW ──
        sep2 = self.glow_track_top - 28
        cv2.line(frame, (x1 + 12, sep2), (x2 - 12, sep2), (35, 35, 40), 1, cv2.LINE_AA)
        self._put_centered(frame, "GLOW", cx, self.glow_track_top - 14, 0.33, lbl_c)
        cv2.line(frame, (self.glow_x, self.glow_track_top),
                 (self.glow_x, self.glow_track_bot), (50, 50, 55), 3, cv2.LINE_AA)
        gy = self._val_to_y(self.glow_intensity, 0, 100,
                            self.glow_track_top, self.glow_track_bot)
        cv2.line(frame, (self.glow_x, self.glow_track_top),
                 (self.glow_x, gy), (180, 120, 200), 2, cv2.LINE_AA)
        gr = 7 if self.hovered_element != ("glow",) else 9
        cv2.circle(frame, (self.glow_x, gy), gr, (240, 240, 245), cv2.FILLED, cv2.LINE_AA)
        self._put_centered(frame, f"{self.glow_intensity}%", cx, self.glow_track_bot + 16, 0.33, dim_c)

        # ── BUTTONS ──
        sep3 = self.btn_positions[0][1] - 18
        cv2.line(frame, (x1 + 12, sep3), (x2 - 12, sep3), (35, 35, 40), 1, cv2.LINE_AA)
        icons = [self._icon_undo, self._icon_clear, self._icon_save]
        for i, (bx, by) in enumerate(self.btn_positions):
            hov = self.hovered_element == ("btn", i)
            br = self.btn_r + (2 if hov else 0)
            cv2.circle(frame, (bx, by), br, (30, 30, 35), cv2.FILLED, cv2.LINE_AA)
            bc = (160, 160, 165) if hov else (90, 90, 100)
            cv2.circle(frame, (bx, by), br, bc, 1, cv2.LINE_AA)
            icons[i](frame, bx, by, hov)

    # ── Helpers ──
    def _put_centered(self, frame, text, cx, y, scale, color):
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, 1)
        cv2.putText(frame, text, (cx - tw // 2, y),
                    cv2.FONT_HERSHEY_DUPLEX, scale, color, 1, cv2.LINE_AA)

    def _icon_undo(self, f, cx, cy, h):
        c = (230, 230, 235) if h else (150, 150, 160)
        pts = np.array([[cx-5,cy-2],[cx-2,cy-5],[cx+3,cy-5],
                        [cx+5,cy-2],[cx+5,cy+2],[cx+2,cy+2]], np.int32)
        cv2.polylines(f, [pts], False, c, 1, cv2.LINE_AA)
        cv2.line(f, (cx-5,cy-2), (cx-5,cy-6), c, 1, cv2.LINE_AA)
        cv2.line(f, (cx-5,cy-2), (cx-1,cy-2), c, 1, cv2.LINE_AA)

    def _icon_clear(self, f, cx, cy, h):
        c = (230, 230, 235) if h else (150, 150, 160)
        cv2.rectangle(f, (cx-4,cy-5), (cx+4,cy+5), c, 1)
        cv2.line(f, (cx-3,cy-3), (cx+3,cy+3), c, 1, cv2.LINE_AA)
        cv2.line(f, (cx+3,cy-3), (cx-3,cy+3), c, 1, cv2.LINE_AA)

    def _icon_save(self, f, cx, cy, h):
        c = (230, 230, 235) if h else (150, 150, 160)
        cv2.line(f, (cx,cy-5), (cx,cy+2), c, 2, cv2.LINE_AA)
        cv2.line(f, (cx-4,cy-1), (cx,cy+3), c, 1, cv2.LINE_AA)
        cv2.line(f, (cx+4,cy-1), (cx,cy+3), c, 1, cv2.LINE_AA)
        cv2.line(f, (cx-5,cy+5), (cx+5,cy+5), c, 1, cv2.LINE_AA)


# ==================================================
# EFFECTS
# ==================================================

def apply_neon_glow(canvas, glow_intensity=60):
    if glow_intensity <= 0:
        return canvas
    blur_size = int(np.interp(glow_intensity, [0, 100], [3, 21]))
    if blur_size % 2 == 0:
        blur_size += 1
    glow_alpha = np.interp(glow_intensity, [0, 100], [0.2, 0.8])
    glow = cv2.GaussianBlur(canvas, (blur_size, blur_size), 0)
    return cv2.addWeighted(canvas, 1.0, glow, glow_alpha, 0)


def apply_vignette(frame, strength=0.3):
    h, w = frame.shape[:2]
    X = cv2.getGaussianKernel(w, w * 0.6)
    Y = cv2.getGaussianKernel(h, h * 0.6)
    mask = Y * X.T
    mask = mask / mask.max()
    vignette = np.ones_like(frame, dtype=np.float32)
    for c in range(3):
        vignette[:, :, c] = mask
    result = (frame.astype(np.float32) * (1.0 - strength + strength * vignette))
    return np.clip(result, 0, 255).astype(np.uint8)
