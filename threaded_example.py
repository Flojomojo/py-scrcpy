import logging
import cv2
import numpy as np
import scrcpy_client
import adbutils
import queue
import threading

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


# Thread-safe queue to pass frames
frame_queue = queue.Queue()
# Thread-safe event to signal stopping
stop_event = threading.Event()

def on_frame(frame: np.ndarray | None) -> None:
    if frame is None:
        # Main thread should stop
        stop_event.set()
        return
    try:
        frame_queue.put_nowait(frame)
    except queue.Full:
        # Main thread is lagging; drop frame
        pass

def main():
    try:
        device = adbutils.adb.device()
    except adbutils.AdbError as e:
        logging.info(f"Error connecting to ADB device: {e}")
        return

    client = None
    try:
        client = scrcpy_client.ScrcpyClient(device, "./scrcpy-server.apk")
        client.add_listener(scrcpy_client.ListenEvent.FRAME, on_frame)

        # Start the client in a background thread
        client.start(threaded=True) 
        logging.info("Streaming... Press q in the OpenCV window to stop")

        latest_frame = None
        while not stop_event.is_set():
            try:
                while True:
                    frame = frame_queue.get_nowait()
                    latest_frame = frame
            except queue.Empty:
                pass

            if latest_frame is not None:
                cv2.imshow("frame", latest_frame)

            if cv2.waitKey(10) & 0xFF == ord("q"):
                logging.info("q pressed, stopping...")
                stop_event.set()
                break
    finally:
        logging.info("Cleaning up...")

        if client:
            client.stop()
        cv2.destroyAllWindows()
        logging.info("Client stopped")


if __name__ == "__main__":
    main() 
