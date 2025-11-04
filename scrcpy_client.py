import socket
import subprocess
import threading
import random
from typing import Callable, Any
import adbutils
import av
import numpy as np
import pathlib
import logging
from adbutils import AdbDevice
from enum import Enum

SERVER_VERSION = "3.3.3"
SERVER_REMOTE_PATH = "/data/local/tmp/scrcpy-server.jar"
SOCKET_NAME_PREFIX = "scrcpy"
DEFAULT_BIT_RATE = 8000000
DEFAULT_MAX_FPS = 30

DEVICE_NAME_FIELD_LENGTH = 64
CODEC_ID_FIELD_LENGTH = 4
VIDEO_HEADER_FIELD_LENGTH = (4, 4)  # w, h


class ListenEvent(Enum):
    FRAME = "frame"
    INIT = "init"


class ScrcpyClient:
    """
    A Python client for Scrcpy server.

    This client handles the connection and video stream decoding.
    It uses the default reverse tunnel method to connect to the device.

    Frames are encoded as bgr24
    """

    __logger = logging.getLogger(__name__)

    def __init__(
        self,
        device: AdbDevice,
        server_path: str,
        server_args: dict[str, str] | None = None,
    ):
        """
        Initialize the client.

        Args:
            device_serial: The serial of the device.
            server_path: The local path to the scrcpy server file.
            bit_rate: The desired video bit rate in bits per second.
            max_fps: The desired maximum frames per second.
        """

        real_path = pathlib.Path(server_path)
        if not real_path.exists():
            raise FileNotFoundError(f"scrcpy server not found at `{real_path}`")

        self.device: AdbDevice = device
        self.server_path: pathlib.Path = real_path

        self.scid: int = random.randint(0, 0x7FFFFFFF)
        self.socket_name: str = f"{SOCKET_NAME_PREFIX}_{self.scid:08x}"

        self.listeners: dict[ListenEvent, list[Callable[..., Any]]] = {
            ListenEvent.FRAME: [],
            ListenEvent.INIT: [],
        }  # pyright: ignore[reportExplicitAny]
        self.is_running: bool = False
        self.last_frame: np.ndarray | None = None
        self.resolution: tuple[int, int] | None = None

        self._server_process: subprocess.Popen[bytes] | None = None
        self._video_socket: socket.socket | None = None
        self._control_socket: socket.socket | None = None
        self._stream_thread: threading.Thread | None = None
        self._local_port: int | None = None
        self.device_name: str = "unknown"
        self.video_codec: str = "h264"

        self._custom_server_args: dict[str, str] = (
            {} if server_args is None else server_args
        )

    # TODO add server args
    def _get_server_args(self) -> list[str]:
        """Constructs the arguments to start the scrcpy server on the device."""
        predefined: dict[str, str] = {
            "log_level": "info",
            "video_bit_rate": str(DEFAULT_BIT_RATE),
            "max_fps": str(DEFAULT_MAX_FPS),
            "audio": "false",
        }

        all = predefined | self._custom_server_args

        server_args = [SERVER_VERSION, f"scid={self.scid:x}"]

        for key, value in all.items():
            server_args.append(f"{key}={value}")
        
        return server_args

    def _push_server(self):
        """Pushes the scrcpy-server to the device if it's missing or outdated."""

        self.__logger.debug(
            f"[{self.device.serial}] Checking server on {SERVER_REMOTE_PATH}..."
        )
        try:
            remote_stat = self.device.sync.stat(SERVER_REMOTE_PATH)
            local_stat = self.server_path.stat()

            if remote_stat.size == local_stat.st_size and remote_stat.mtime == int(
                local_stat.st_mtime
            ):
                self.__logger.debug(
                    f"[{self.device.serial}] Server is already up-to-date."
                )
                return  # Server is present and matches, don't push

        except FileNotFoundError:
            self.__logger.debug(f"[{self.device.serial}] Server not found on device.")
            # File doesn't exist, proceed to push
        except Exception as e:
            self.__logger.warning(
                f"[{self.device.serial}] Failed to stat remote server: {e}. Will try to push anyway."
            )
            # Other issue (maybe permission), lets still try to push

        self.__logger.debug(
            f"[{self.device.serial}] Pushing server to {SERVER_REMOTE_PATH}..."
        )
        try:
            _ = self.device.sync.push(self.server_path, SERVER_REMOTE_PATH)
            self.__logger.debug(f"[{self.device.serial}] Server pushed successfully.")
        except Exception as e:
            self.__logger.error(f"[{self.device.serial}] Failed to push server: {e}.")

            # very bad, lets fail
            raise IOError(f"Failed to push scrcpy-server to device: {e}")

    def _start_server(self):
        """Starts the scrcpy server on the device."""
        assert self.device.serial is not None, "Device serial is None"

        self.__logger.debug(f"[{self.device.serial}] Starting server...")
        # Command to execute on the device
        server_args = self._get_server_args()
        command = [
            "CLASSPATH=" + SERVER_REMOTE_PATH,
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            *server_args,
        ]

        # Use adb shell to run the command in the background
        # Note: We can't use device.shell with Popen semantics from adbutils, so we use adb binary directly.
        adb_command: list[str] = [
            adbutils.adb_path(),
            "-s",
            self.device.serial,
            "shell",
            *command,
        ]

        self._server_process = subprocess.Popen(
            adb_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        self.__logger.info(
            f"[{self.device.serial}] Server process started with PID: {self._server_process.pid}"
        )

    def _recv_all(self, sock: socket.socket, n: int) -> bytes:
        """Helper to receive exactly n bytes from a socket."""

        data = bytearray()
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet:
                raise ConnectionAbortedError("Socket connection broken")
            data.extend(packet)
        return bytes(data)

    def _connect_sockets(self) -> bool:
        """Sets up the reverse tunnel and connects the video and control sockets."""
        self.__logger.debug(f"[{self.device.serial}] Setting up reverse tunnel...")

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind(("127.0.0.1", 0))
        self._local_port = server_socket.getsockname()[1]
        server_socket.listen(2)

        self.device.reverse(
            f"localabstract:{self.socket_name}", f"tcp:{self._local_port}"
        )

        self._start_server()

        try:
            self.__logger.debug(
                f"[{self.device.serial}] Waiting for video socket connection..."
            )
            server_socket.settimeout(30)
            self._video_socket, _ = server_socket.accept()  # pyright: ignore[reportAny]
            self.__logger.debug(f"[{self.device.serial}] Video socket connected.")

            self.__logger.debug(
                f"[{self.device.serial}] Waiting for control socket connection..."
            )
            self._control_socket, _ = server_socket.accept()  # pyright: ignore[reportAny]
            self.__logger.debug(f"[{self.device.serial}] Control socket connected.")
            server_socket.settimeout(None)

            # read device metadata (64 bytes)
            device_name_bytes = self._recv_all(
                self._video_socket, DEVICE_NAME_FIELD_LENGTH
            )
            self.device_name = device_name_bytes.decode("utf-8").rstrip("\x00")
            self.__logger.debug(
                f"[{self.device.serial}] Device name: {self.device_name}"
            )

            # read codec ID (4 bytes)
            codec_id_bytes = self._recv_all(self._video_socket, CODEC_ID_FIELD_LENGTH)
            self.video_codec = codec_id_bytes.decode("utf-8")
            self.__logger.debug(
                f"[{self.device.serial}] Video Codec: {self.video_codec}"
            )

            # TODO support more codecs (i think scrcpy supports more)
            if self.video_codec.lower() != "h264":
                self.__logger.error(
                    f"[{self.device.serial}] Unsupported codec: {self.video_codec}. Only h264 is supported."
                )
                return False

            # read video header (4 bytes width + 4 bytes height)
            width_bytes = self._recv_all(
                self._video_socket, VIDEO_HEADER_FIELD_LENGTH[0]
            )
            height_bytes = self._recv_all(
                self._video_socket, VIDEO_HEADER_FIELD_LENGTH[1]
            )
            width = int.from_bytes(width_bytes, byteorder="big")
            height = int.from_bytes(height_bytes, byteorder="big")
            self.resolution = (width, height)

            self.__logger.debug(f"[{self.device.serial}] Resolution: {width}x{height}")

            # Check for bad resolution
            if self.resolution == (0, 0):
                self.__logger.error(
                    f"[{self.device.serial}] Got 0x0 resolution. Is the device screen on?"
                )
                return False

            self._send_to_listeners(ListenEvent.INIT)

            return True
        except socket.timeout:
            self.__logger.error(
                f"[{self.device.serial}] Socket connection timed out. Is the server running?"
            )
            return False
        except (
            socket.error,
            ConnectionAbortedError,
            BrokenPipeError,
            ConnectionResetError,
        ) as e:
            self.__logger.error(
                f"[{self.device.serial}] Failed to connect sockets: {e}"
            )
            return False
        finally:
            server_socket.close()

    def _stream_loop(self):
        """The main loop to receive and decode video frames."""
        assert self._video_socket is not None, "Video socket is None"

        self.__logger.debug(f"[{self.device.serial}] Starting video stream loop...")

        codec = av.CodecContext.create(self.video_codec.lower(), "r")
        data_buffer: bytearray = bytearray()

        while self.is_running:
            try:
                self._video_socket.settimeout(0.1)
                try:
                    chunk = self._video_socket.recv(0x10000)
                    if not chunk:
                        self.__logger.debug(
                            f"[{self.device.serial}] Video stream ended (socket closed)."
                        )
                        break
                    data_buffer.extend(chunk)
                except socket.timeout:
                    continue  # Nothing received, just loop again

                while self.is_running:
                    if len(data_buffer) < 12:
                        break  # Not enough data for a header

                    packet_size = int.from_bytes(data_buffer[8:12], byteorder="big")

                    if len(data_buffer) < 12 + packet_size:
                        break  # Not enough data for the full packet

                    packet_data = data_buffer[12 : 12 + packet_size]
                    del data_buffer[: 12 + packet_size]

                    packets = codec.parse(packet_data)

                    for packet in packets:
                        frames = codec.decode(packet)
                        for frame in frames:
                            self.last_frame = frame.to_ndarray(format="bgr24")
                            self._send_to_listeners(ListenEvent.FRAME, self.last_frame)

            except (socket.error, BrokenPipeError, ConnectionResetError) as e:
                if self.is_running:
                    self.__logger.warning(
                        f"[{self.device.serial}] Socket error, stopping loop: {e}"
                    )
                break
            except av.InvalidDataError as e:
                self.__logger.warning(
                    f"[{self.device.serial}] AV decoding error (skipping packet): {e}"
                )
                continue
            except Exception as e:
                if self.is_running:
                    self.__logger.error(
                        f"[{self.device.serial}] Unexpected stream loop error: {e}",
                        exc_info=True,
                    )
                break

        self.is_running = False
        self.__logger.info(f"[{self.device.serial}] Stream loop stopped.")

    def add_listener(self, event: ListenEvent, listener: Callable[..., Any]):  # pyright: ignore[reportExplicitAny]
        """
        Add a listener for a specific event.

        Args:
            event: The event to listen for ("frame" or "init").
            listener: The callback function.
                      - "frame" listeners receive one argument: the frame (np.ndarray).
                      - "init" listeners receive no arguments.
        """
        if event in self.listeners:
            self.listeners[event].append(listener)
        else:
            raise ValueError(f"Unknown event: {event}")

    def remove_listener(self, event: ListenEvent, listener: Callable[..., Any]):  # pyright: ignore[reportExplicitAny]
        """Remove a listener for a specific event."""
        if event in self.listeners and listener in self.listeners[event]:
            self.listeners[event].remove(listener)

    def _send_to_listeners(self, event: ListenEvent, *args, **kwargs):
        """Send an event to all registered listeners."""
        for listener in self.listeners[event]:
            try:
                listener(*args, **kwargs)
            except Exception as e:
                self.__logger.error(f"Error in listener for event '{event}': {repr(e)}")

    def start(self, threaded: bool = True):
        """
        Start the scrcpy client.

        Args:
            threaded: If True, the video stream runs in a separate thread.
        """
        if self.is_running:
            self.__logger.warning(f"[{self.device.serial}] Client is already running.")
            return

        self._push_server()
        if not self._connect_sockets():
            self.stop()
            return

        self.is_running = True
        if threaded:
            self._stream_thread = threading.Thread(target=self._stream_loop)
            self._stream_thread.start()
        else:
            self._stream_loop()

    def stop(self):
        """Stop the client and clean up resources."""
        self.__logger.info(f"[{self.device.serial}] Stopping client...")
        self.is_running = False

        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join()

        if self._control_socket:
            self._control_socket.close()
        if self._video_socket:
            self._video_socket.close()

        if self._server_process:
            self._server_process.terminate()
            _ = self._server_process.wait()
            self.__logger.debug(f"[{self.device.serial}] Server process terminated.")

        if self._local_port:
            try:
                # TODO wait for adbutils to implement my PR
                # self.device.reverse_remove(f"localabstract:{self.socket_name}")
                _ = self.device.shell(
                    ["reverse", "--remove", f"localabstract:{self.socket_name}"]
                )
                self.__logger.debug(f"[{self.device.serial}] Reverse tunnel removed.")
            except Exception as e:
                self.__logger.warning(
                    f"[{self.device.serial}] Failed to remove reverse tunnel: {e}"
                )

        self.resolution = None
        self.last_frame = None
        self.__logger.info(f"[{self.device.serial}] Client stopped.")
