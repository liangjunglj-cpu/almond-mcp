"""
Rhino Bridge for MCP Plugin (v1.2)

Runs INSIDE Rhino's Python editor. Listens on a TCP socket for script payloads
from the MCP server, queues them, and executes them safely on Rhino's Main UI
Thread via the RhinoApp.Idle event.

Features:
  - Background daemon thread for socket listening (no UI freeze)
  - RhinoApp.Idle event for thread-safe geometry creation
  - Length-prefix TCP protocol for reliable message framing
  - Undo sandboxing for atomic script execution
  - AIA layer caching (created once per session)
  - Optimized bounding box calculation via RhinoCommon
"""
import socket
import json
import traceback
import threading

try:
    import rhinoscriptsyntax as rs
    import scriptcontext as sc
    import Rhino
    IN_RHINO = True
except ImportError:
    IN_RHINO = False


class RhinoBridgeServer:
    def __init__(self, host='127.0.0.1', port=5000):
        self.host = host
        self.port = port
        self.running = False
        self._layers_created = False  # Cache flag: only create AIA layers once

        # Thread-safe execution queue
        self.execution_queue = []
        self.queue_lock = threading.Lock()

        # Signaling between background socket thread and main thread
        self.current_result_event = threading.Event()
        self.current_result_data = None

        if IN_RHINO:
            Rhino.RhinoApp.Idle += self._on_idle

    def start(self):
        """Start the background socket listener."""
        if self.running:
            return
        self.running = True

        self.listener_thread = threading.Thread(target=self._listen_loop)
        self.listener_thread.daemon = True
        self.listener_thread.start()
        print(f"Rhino Bridge listening on {self.host}:{self.port}")
        print("To stop: mcp_server_instance.stop()")

    def stop(self):
        """Stop the bridge and unsubscribe from Idle event."""
        self.running = False
        if IN_RHINO:
            try:
                Rhino.RhinoApp.Idle -= self._on_idle
            except:
                pass
        print("Rhino Bridge stopped.")

    # ── TCP Listener (Background Thread) ─────────────────────────────────────

    def _listen_loop(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.settimeout(1.0)

        try:
            srv.bind((self.host, self.port))
            srv.listen(1)
        except Exception as e:
            print(f"Failed to bind: {e}")
            self.running = False
            return

        while self.running:
            try:
                conn, addr = srv.accept()
                with conn:
                    data = self._recv_message(conn)
                    if not data:
                        continue

                    request = json.loads(data)
                    script = request.get('script', '')

                    # Queue for main thread execution
                    self.current_result_event.clear()
                    self.current_result_data = None

                    with self.queue_lock:
                        self.execution_queue.append(script)

                    # Wait for main thread to finish (timeout 30s)
                    completed = self.current_result_event.wait(timeout=30.0)

                    if not completed:
                        response = {"status": "error", "message": "Timed out waiting for Rhino main thread.", "guids": []}
                    else:
                        response = self.current_result_data

                    self._send_message(conn, json.dumps(response).encode('utf-8'))

            except socket.timeout:
                continue
            except Exception as e:
                print(f"Connection error: {e}")

        srv.close()

    def _recv_message(self, conn: socket.socket) -> str:
        """Receive a length-prefixed message: 4-byte big-endian length + payload."""
        header = b''
        while len(header) < 4:
            chunk = conn.recv(4 - len(header))
            if not chunk:
                return ''
            header += chunk

        msg_length = int.from_bytes(header, 'big')

        data = b''
        while len(data) < msg_length:
            chunk = conn.recv(min(16384, msg_length - len(data)))
            if not chunk:
                return ''
            data += chunk

        return data.decode('utf-8')

    def _send_message(self, conn: socket.socket, payload: bytes):
        """Send a length-prefixed message: 4-byte big-endian length + payload."""
        conn.sendall(len(payload).to_bytes(4, 'big'))
        conn.sendall(payload)

    # ── Main Thread Execution (RhinoApp.Idle) ────────────────────────────────

    def _on_idle(self, sender, e):
        """Fires on the Main Rhino UI Thread. Pops one queued script and executes it."""
        if not self.running:
            return

        script_to_run = None
        with self.queue_lock:
            if self.execution_queue:
                script_to_run = self.execution_queue.pop(0)

        if script_to_run is not None:
            result = self._execute_script(script_to_run)
            self.current_result_data = result
            self.current_result_event.set()

    # ── AIA Layers ───────────────────────────────────────────────────────────

    def _ensure_aia_layers(self):
        """Create AIA Standard Layers once per session."""
        if not IN_RHINO or self._layers_created:
            return

        aia_layers = {
            "A-WALL": (0, 0, 0),
            "A-STRC": (255, 0, 0),
            "A-GLAZ": (0, 255, 255),
        }
        for name, color in aia_layers.items():
            if not rs.IsLayer(name):
                rs.AddLayer(name, color)

        self._layers_created = True

    # ── Bounding Box & Dimensioning ──────────────────────────────────────────

    def _add_scale_dimensions(self, guids):
        """Add an aligned dimension spanning the bounding box of created geometry."""
        if not IN_RHINO or not guids:
            return

        bbox = Rhino.Geometry.BoundingBox.Empty
        for guid_str in guids:
            try:
                guid = System.Guid(guid_str) if 'System' in dir() else Rhino.RhinoMath.UnsetIntIndex
                obj = sc.doc.Objects.FindId(guid)
                if obj and obj.Geometry:
                    bbox.Union(obj.Geometry.GetBoundingBox(True))
            except:
                pass

        if not bbox.IsValid:
            return

        try:
            pt0 = bbox.Min
            pt1 = Rhino.Geometry.Point3d(bbox.Max.X, bbox.Min.Y, bbox.Min.Z)
            plane = Rhino.Geometry.Plane.WorldXY
            plane.Origin = pt0

            dim = Rhino.Geometry.LinearDimension.Create(
                Rhino.Geometry.AnnotationType.Aligned,
                sc.doc.DimStyles.Current,
                plane, plane.XAxis, pt0, pt1, pt0, 0
            )
            if dim:
                sc.doc.Objects.AddLinearDimension(dim)
        except Exception as e:
            print(f"Dimension error: {e}")

    # ── Script Execution ─────────────────────────────────────────────────────

    def _execute_script(self, script_code: str) -> dict:
        """Execute a script inside Rhino with undo sandboxing."""
        self._ensure_aia_layers()

        exec_globals = {
            "rs": rs if IN_RHINO else None,
            "sc": sc if IN_RHINO else None,
            "Rhino": Rhino if IN_RHINO else None,
            "created_objects": [],
        }

        result = {"status": "success", "message": "", "guids": [], "error_trace": None}

        undo_sn = sc.doc.BeginUndoRecord("MCP Geometry Generation") if IN_RHINO else 0

        try:
            exec(script_code, exec_globals)
            guids = [str(g) for g in exec_globals.get("created_objects", [])]
            result["guids"] = guids

            if guids:
                self._add_scale_dimensions(guids)

            if IN_RHINO:
                sc.doc.EndUndoRecord(undo_sn)
                sc.doc.Views.Redraw()

        except Exception as e:
            # Undo any partial geometry on failure
            if IN_RHINO:
                sc.doc.EndUndoRecord(undo_sn)
                sc.doc.Undo()

            result["status"] = "error"
            result["message"] = str(e)
            result["error_trace"] = traceback.format_exc()

        return result


# ── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if 'mcp_server_instance' not in globals() or not globals()['mcp_server_instance'].running:
        mcp_server_instance = RhinoBridgeServer(port=5000)
        mcp_server_instance.start()
    else:
        print("Already running. Call mcp_server_instance.stop() to restart.")
