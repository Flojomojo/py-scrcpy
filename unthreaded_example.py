import cv2
import logging
import numpy as np
import scrcpy_client
import adbutils

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

class StreamViewer:
    def __init__(self, client: scrcpy_client.ScrcpyClient):
        self.client: scrcpy_client.ScrcpyClient = client

    def on_frame(self, frame: np.ndarray | None) -> None:
        if frame is None:
            self.client.stop()
            return

        cv2.imshow("frame", frame)

        if cv2.waitKey(10) & 0xFF == ord("q"):
            logging.info("q pressed, stopping...")
            self.client.stop()


def main():
    logging.debug("started")
    try:
        device = adbutils.adb.device()
    except adbutils.AdbError as e:
        logging.info(f"Error connecting to ADB device: {e}")
        return

    client = scrcpy_client.ScrcpyClient(device, "./scrcpy-server.apk")
    viewer = StreamViewer(client)

    client.add_listener(scrcpy_client.ListenEvent.FRAME, viewer.on_frame)

    logging.info("Starting unthreaded client... Press q in window to stop")

    client.start(threaded=False)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
