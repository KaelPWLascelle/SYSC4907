"""Run a uvicorn app in a background thread (used for the couch guest server)."""
import socket
import threading
import time

import uvicorn


class ServerThread:
    """Binds first, so "address in use" surfaces here as OSError instead of dying inside the thread."""

    def __init__(self, app_factory, host, port):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((host, port))
        except OSError:
            self.socket.close()
            raise
        self.port = self.socket.getsockname()[1]
        config = uvicorn.Config(app_factory(self.port), log_level='warning', access_log=False, lifespan='off')
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, kwargs={'sockets': [self.socket]}, daemon=True)

    def start(self, timeout=5.0):
        self.thread.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                self.stop()
                raise RuntimeError('The server did not start')
            time.sleep(0.01)
        return self

    def stop(self, timeout=5.0):
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout)
        self.socket.close()
