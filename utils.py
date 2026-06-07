import math
import time
import cv2
import numpy as np

def calculate_distance(p1, p2):
    """Calculate Euclidean distance between two points."""
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

class EMAFilter:
    """Exponential Moving Average filter for smoothing coordinates to prevent jitter."""
    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self.val = None

    def update(self, new_val):
        if self.val is None:
            self.val = new_val
        else:
            self.val = (self.alpha * new_val) + ((1 - self.alpha) * self.val)
        return self.val

class FPSCounter:
    """Calculates and renders FPS overlay on the frame."""
    def __init__(self):
        self.pTime = 0

    def update(self, frame):
        cTime = time.time()
        fps = 1 / (cTime - self.pTime) if (cTime - self.pTime) > 0 else 0
        self.pTime = cTime
        return fps


# =============================================
# GLASSMORPHISM UI HELPERS
# =============================================

def draw_rounded_rect(frame, pt1, pt2, color, thickness, radius=12, filled=False):
    """Draw a rounded rectangle using lines and corner ellipses."""
    x1, y1 = pt1
    x2, y2 = pt2
    r = min(radius, (x2 - x1) // 2, (y2 - y1) // 2)
    if r < 1:
        r = 1

    if filled:
        cv2.rectangle(frame, (x1 + r, y1), (x2 - r, y2), color, cv2.FILLED)
        cv2.rectangle(frame, (x1, y1 + r), (x2, y2 - r), color, cv2.FILLED)
        for cx, cy in [(x1+r, y1+r), (x2-r, y1+r), (x1+r, y2-r), (x2-r, y2-r)]:
            cv2.circle(frame, (cx, cy), r, color, cv2.FILLED)
    else:
        cv2.line(frame, (x1 + r, y1), (x2 - r, y1), color, thickness, cv2.LINE_AA)
        cv2.line(frame, (x1 + r, y2), (x2 - r, y2), color, thickness, cv2.LINE_AA)
        cv2.line(frame, (x1, y1 + r), (x1, y2 - r), color, thickness, cv2.LINE_AA)
        cv2.line(frame, (x2, y1 + r), (x2, y2 - r), color, thickness, cv2.LINE_AA)
        cv2.ellipse(frame, (x1+r, y1+r), (r,r), 180, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(frame, (x2-r, y1+r), (r,r), 270, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(frame, (x1+r, y2-r), (r,r), 90, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(frame, (x2-r, y2-r), (r,r), 0, 0, 90, color, thickness, cv2.LINE_AA)


def draw_glass_panel(frame, pt1, pt2, alpha=0.7, bg_color=(15, 15, 22),
                     border_color=(80, 60, 120), radius=12):
    """Draw a glassmorphism semi-transparent panel with rounded corners and neon border."""
    overlay = frame.copy()
    draw_rounded_rect(overlay, pt1, pt2, bg_color, -1, radius=radius, filled=True)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    draw_rounded_rect(frame, pt1, pt2, border_color, 1, radius=radius)


class UIMessageManager:
    """Premium glassmorphism toast notification system with smooth fade animations."""
    def __init__(self, display_duration=1.5):
        self.message = ""
        self.start_time = 0
        self.display_duration = display_duration

    def set_message(self, message):
        self.message = message
        self.start_time = time.time()

    def draw(self, frame, width, height):
        elapsed = time.time() - self.start_time
        if elapsed >= self.display_duration:
            return

        # Fade animation
        fade_in = 0.15
        fade_out = 0.35
        if elapsed < fade_in:
            alpha = elapsed / fade_in
        elif elapsed > self.display_duration - fade_out:
            alpha = (self.display_duration - elapsed) / fade_out
        else:
            alpha = 1.0
        alpha = max(0.0, min(1.0, alpha))
        if alpha < 0.05:
            return

        # Measure text for dynamic card
        font = cv2.FONT_HERSHEY_DUPLEX
        (tw, th), baseline = cv2.getTextSize(self.message, font, 0.6, 1)
        pad_x, pad_y = 24, 12
        card_w = tw + pad_x * 2
        card_h = th + pad_y * 2 + baseline
        cx = width // 2
        cy = 88
        x1, y1 = cx - card_w // 2, cy - card_h // 2
        x2, y2 = cx + card_w // 2, cy + card_h // 2

        # Glass background
        overlay = frame.copy()
        draw_rounded_rect(overlay, (x1, y1), (x2, y2), (12, 12, 18), -1, radius=14, filled=True)
        cv2.addWeighted(overlay, 0.75 * alpha, frame, 1 - 0.75 * alpha, 0, frame)

        # Neon border
        bi = int(120 * alpha)
        draw_rounded_rect(frame, (x1, y1), (x2, y2), (bi, int(60*alpha), int(140*alpha)), 1, radius=14)

        # Top accent line
        aw = min(card_w - 30, 80)
        ai = int(255 * alpha)
        cv2.line(frame, (cx - aw//2, y1), (cx + aw//2, y1), (ai, ai, 0), 2, cv2.LINE_AA)

        # Text
        tc = int(230 * alpha)
        cv2.putText(frame, self.message, (cx - tw//2, cy + th//2 - 1),
                    font, 0.6, (tc, tc, int(240*alpha)), 1, cv2.LINE_AA)
