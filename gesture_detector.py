import time
from utils import calculate_distance

class GestureDetector:
    def __init__(self, stability_duration=0.5):
        self.tipIds = [4, 8, 12, 16, 20]
        self.stability_duration = stability_duration
        
        # State tracking for debounce
        self.current_raw_gesture = "UNKNOWN"
        self.gesture_start_time = 0
        self.stable_gesture = "UNKNOWN"

    def fingers_up(self, lmList):
        """Determine which fingers are open. Returns a list of 5 ints [0 or 1]."""
        fingers = []
        if not lmList:
            return fingers
        
        # Thumb - Based on x coords mostly (assumes right hand logic for simplicity)
        if lmList[self.tipIds[0]][1] > lmList[self.tipIds[0] - 1][1]:
            fingers.append(1)
        else:
            fingers.append(0)

        # 4 Fingers - Based on y coords
        for id in range(1, 5):
            if lmList[self.tipIds[id]][2] < lmList[self.tipIds[id] - 2][2]:
                fingers.append(1)
            else:
                fingers.append(0)
                
        return fingers

    def detect_gesture(self, lmList):
        """Classify the current gesture and stabilize the output."""
        if not lmList:
            return "UNKNOWN"
        
        fingers = self.fingers_up(lmList)
        
        # Distance between thumb (4) and index (8) for PINCH
        thumb_tip = lmList[4][1:]
        index_tip = lmList[8][1:]
        pinch_dist = calculate_distance(thumb_tip, index_tip)

        raw_gesture = "UNKNOWN"
        
        # Check CLOSED_PALM explicitly first so it doesn't get confused with PINCH
        # Ignoring the thumb (index 0) because folded thumbs are horribly tracked by X-axis
        if fingers[1:] == [0, 0, 0, 0]:
            raw_gesture = "CLOSED_PALM"
        elif pinch_dist < 40 and fingers[2:] == [0, 0, 0]:
            raw_gesture = "PINCH"
        elif fingers == [0, 1, 0, 0, 0]:
            raw_gesture = "INDEX_UP"
        elif fingers == [0, 1, 1, 0, 0]:
            raw_gesture = "TWO_FINGERS"
        elif fingers == [1, 0, 0, 0, 0] or fingers == [1, 1, 0, 0, 0]: # Adding wiggle room for thumb up
            raw_gesture = "THUMB_UP"
        elif fingers.count(1) >= 4:
            raw_gesture = "OPEN_PALM"
        
        # Gesture Stability Filter (Wait X seconds before locking in a change)
        if raw_gesture == self.current_raw_gesture:
            if time.time() - self.gesture_start_time >= self.stability_duration:
                self.stable_gesture = raw_gesture
        else:
            self.current_raw_gesture = raw_gesture
            self.gesture_start_time = time.time()
            
        return self.stable_gesture
