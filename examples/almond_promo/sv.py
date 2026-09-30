"""Send structure_view requests to the Almond bridge (visualize_structure without the MCP hop)."""
import json, socket, sys


def request(msg, timeout=120):
    payload = json.dumps(msg).encode()
    with socket.create_connection(('127.0.0.1', 5000), timeout=30) as s:
        s.settimeout(timeout)
        s.sendall(len(payload).to_bytes(4, 'big') + payload)

        def exact(n):
            out = b''
            while len(out) < n:
                c = s.recv(n - len(out))
                if not c:
                    raise RuntimeError('Almond connection closed')
                out += c
            return out
        return json.loads(exact(int.from_bytes(exact(4), 'big')))


def view(guids=None, **kw):
    msg = {'type': 'structure_view', 'guids': guids or []}
    msg.update(kw)
    return request(msg)


if __name__ == '__main__':
    print(json.dumps(view(json.loads(sys.argv[1]), **json.loads(sys.argv[2] if len(sys.argv) > 2 else '{}')), indent=1)[:6000])
