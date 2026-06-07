import cv2
import numpy as np
import mediapipe as mp

# Neon connection map: pairs of landmark indices forming the skeleton
_HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),       # Thumb
    (0,5),(5,6),(6,7),(7,8),       # Index
    (0,9),(9,10),(10,11),(11,12),  # Middle (via 0→9 approximation)
    (0,13),(13,14),(14,15),(15,16),# Ring
    (0,17),(17,18),(18,19),(19,20),# Pinky
    (5,9),(9,13),(13,17),          # Palm cross-connections
]

# Joint categories for color coding
_TIPS = {4, 8, 12, 16, 20}
_MIDS = {3, 7, 11, 15, 19, 6, 10, 14, 18}

class HandTracker:
    def __init__(self, mode=False, max_hands=2, detection_con=0.7, track_con=0.7):
        self.mpHands = mp.solutions.hands
        self.hands = self.mpHands.Hands(
            static_image_mode=mode,
            max_num_hands=max_hands,
            min_detection_confidence=detection_con,
            min_tracking_confidence=track_con
        )
        self.mpDraw = mp.solutions.drawing_utils

    def find_hands(self, frame, draw=True):
        """Processes the frame to detect hands and draws custom neon landmarks."""
        imgRGB = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self.results = self.hands.process(imgRGB)
        
        if self.results.multi_hand_landmarks and draw:
            for handLms in self.results.multi_hand_landmarks:
                self._draw_neon_hand(frame, handLms)
        return frame

    def _draw_neon_hand(self, frame, handLms):
        """Render futuristic neon hand skeleton with glowing joints."""
        h, w, _ = frame.shape
        # Extract pixel coordinates
        pts = {}
        for idx, lm in enumerate(handLms.landmark):
            pts[idx] = (int(lm.x * w), int(lm.y * h))
        
        neon_cyan = (255, 220, 0)
        neon_pink = (255, 80, 200)
        soft_line = (180, 140, 0)
        
        # Draw connections — soft neon lines
        for (i, j) in _HAND_CONNECTIONS:
            if i in pts and j in pts:
                # Outer glow line (wider, dimmer)
                cv2.line(frame, pts[i], pts[j], (80, 60, 0), 3, cv2.LINE_AA)
                # Inner bright line
                cv2.line(frame, pts[i], pts[j], soft_line, 1, cv2.LINE_AA)
        
        # Draw joints — different sizes/colors by type
        for idx, pt in pts.items():
            if idx in _TIPS:
                # Fingertips — larger neon pink glow
                cv2.circle(frame, pt, 6, (120, 40, 100), cv2.FILLED, cv2.LINE_AA)
                cv2.circle(frame, pt, 4, neon_pink, cv2.FILLED, cv2.LINE_AA)
            elif idx == 0:
                # Wrist — cyan accent
                cv2.circle(frame, pt, 5, (100, 80, 0), cv2.FILLED, cv2.LINE_AA)
                cv2.circle(frame, pt, 3, neon_cyan, cv2.FILLED, cv2.LINE_AA)
            elif idx in _MIDS:
                # Mid joints — small subtle dots
                cv2.circle(frame, pt, 3, soft_line, cv2.FILLED, cv2.LINE_AA)
            else:
                # Knuckles — tiny dots
                cv2.circle(frame, pt, 2, (140, 110, 0), cv2.FILLED, cv2.LINE_AA)

    def get_position(self, frame, hand_no=0):
        """Returns a list of landmark positions for the specified hand."""
        lmList = []
        if self.results.multi_hand_landmarks:
            if len(self.results.multi_hand_landmarks) > hand_no:
                myHand = self.results.multi_hand_landmarks[hand_no]
                h, w, c = frame.shape
                for id, lm in enumerate(myHand.landmark):
                    cx, cy = int(lm.x * w), int(lm.y * h)
                    lmList.append([id, cx, cy])
        return lmList
