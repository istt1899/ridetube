#!/usr/bin/env python3
"""Host test for ytfetch's proxy support: parse_proxy/proxy_from_file, socks5_connect against a
stub, and ranged_get through both an HTTP CONNECT stub and the SOCKS5 stub."""

import base64
import json
import os
import socket
import ssl
import sys
import threading
import unittest
import unittest.mock as mock
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ytfetch  # noqa: E402

HERE = Path(__file__).resolve().parent
CERT = HERE / 'fixtures' / 'cert.pem'
KEY = HERE / 'fixtures' / 'key.pem'
CRED = ('rt', 's3cret')


class RangeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        rng = self.headers.get('Range', '')
        total = 1000
        body = bytes((i % 251 for i in range(total)))
        if rng.startswith('bytes='):
            s, e = (int(x) for x in rng[6:].split('-'))
            part = body[s:e + 1]
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {s}-{e}/{total}')
            self.send_header('Content-Length', str(len(part)))
        else:
            part = body
            self.send_response(200)
            self.send_header('Content-Length', str(len(part)))
        self.end_headers()
        self.wfile.write(part)

    def log_message(self, *a):
        pass


def tls_origin():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    server = ThreadingHTTPServer(('127.0.0.1', 0), RangeHandler)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


class HttpConnectStub:
    """HTTP CONNECT proxy requiring Basic auth; tunnels to the target."""

    def __init__(self):
        self.events = []
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(('127.0.0.1', 0))
        self.server.listen(16)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._conn, args=(c,), daemon=True).start()

    def _conn(self, c):
        try:
            data = b''
            while b'\r\n\r\n' not in data:
                chunk = c.recv(4096)
                if not chunk:
                    return
                data += chunk
            head = data.split(b'\r\n\r\n')[0].decode('latin1')
            line = head.split('\r\n')[0]
            auth = None
            for h in head.split('\r\n')[1:]:
                if h.lower().startswith('proxy-authorization:'):
                    auth = h.split(':', 1)[1].strip()
            self.events.append(('connect', line, auth))
            ok = 'Basic ' + base64.b64encode(f'{CRED[0]}:{CRED[1]}'.encode()).decode()
            if auth != ok:
                c.sendall(b'HTTP/1.1 407 Proxy Auth Required\r\nContent-Length: 0\r\n\r\n')
                return
            target_host, target_port = line.split(' ')[1].rsplit(':', 1)
            t = socket.create_connection((target_host, int(target_port)), timeout=10)
            c.sendall(b'HTTP/1.1 200 OK\r\n\r\n')
            rest = data.split(b'\r\n\r\n', 1)[1]
            if rest:
                t.sendall(rest)
            self._pipe(c, t)
        except OSError:
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass

    @staticmethod
    def _pipe(a, b):
        def pump(src, dst):
            try:
                while True:
                    d = src.recv(65536)
                    if not d:
                        break
                    dst.sendall(d)
            except OSError:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
        threading.Thread(target=pump, args=(a, b), daemon=True).start()
        pump(b, a)


class SocksStub:
    """SOCKS5 stub requiring user/pass auth."""

    def __init__(self):
        self.events = []
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(('127.0.0.1', 0))
        self.server.listen(16)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._conn, args=(c,), daemon=True).start()

    @staticmethod
    def _exact(c, n):
        buf = b''
        while len(buf) < n:
            b = c.recv(n - len(buf))
            if not b:
                raise OSError('closed')
            buf += b
        return buf

    def _conn(self, c):
        try:
            n = self._exact(c, 2)[1]
            self._exact(c, n)
            c.sendall(b'\x05\x02')
            self._exact(c, 1)  # the auth sub-negotiation version byte
            ulen = self._exact(c, 1)[0]
            user = self._exact(c, ulen).decode()
            plen = self._exact(c, 1)[0]
            pwd = self._exact(c, plen).decode()
            self.events.append(('auth', f'{user}:{pwd}'))
            if (user, pwd) != CRED:
                c.sendall(b'\x01\x01')
                return
            c.sendall(b'\x01\x00')
            self._exact(c, 4)
            hlen = self._exact(c, 1)[0]
            host = self._exact(c, hlen).decode()
            port = int.from_bytes(self._exact(c, 2), 'big')
            self.events.append(('connect', f'{host}:{port}'))
            t = socket.create_connection((host, port), timeout=10)
            c.sendall(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')
            self._pipe(c, t)
        except OSError:
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass

    @staticmethod
    def _pipe(a, b):
        def pump(src, dst):
            try:
                while True:
                    d = src.recv(65536)
                    if not d:
                        break
                    dst.sendall(d)
            except OSError:
                pass
        threading.Thread(target=pump, args=(a, b), daemon=True).start()
        pump(b, a)


class ProxyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.origin, cls.origin_port = tls_origin()
        cls.http_stub = HttpConnectStub()
        cls.socks_stub = SocksStub()
        if os.name == 'nt':  # os.pwrite is POSIX-only; ranged_get targets the car's Linux
            def _pwrite(fd, data, offset):
                os.lseek(fd, offset, os.SEEK_SET)
                return os.write(fd, data)
            cls._pwrite = mock.patch('os.pwrite', _pwrite, create=True)
            cls._pwrite.start()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, '_pwrite', None):
            cls._pwrite.stop()
        cls.origin.shutdown()

    def test_parse_proxy(self):
        p = ytfetch.parse_proxy('http://u:p@10.0.0.1:8080')
        self.assertEqual(p['type'], 'http')
        self.assertEqual((p['user'], p['pass'], p['host'], p['port']), ('u', 'p', '10.0.0.1', 8080))
        s = ytfetch.parse_proxy('socks5://u:p@h')
        self.assertEqual((s['type'], s['port']), ('socks5', 1080))
        self.assertIsNone(ytfetch.parse_proxy('ftp://h:1'))
        self.assertIsNone(ytfetch.parse_proxy(''))
        self.assertIsNone(ytfetch.parse_proxy(None))

    def test_proxy_from_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, 'proxy.json')
            with open(f, 'w') as fh:
                json.dump({'url': f'http://{CRED[0]}:{CRED[1]}@127.0.0.1:9'}, fh)
            self.assertEqual(ytfetch.proxy_from_file(f)['port'], 9)
            self.assertIsNone(ytfetch.proxy_from_file(os.path.join(d, 'absent')))
            with open(f, 'w') as fh:
                fh.write('{bad json')
            self.assertIsNone(ytfetch.proxy_from_file(f))

    def test_socks5_connect_ok_and_fail(self):
        sock = ytfetch.socks5_connect({'type': 'socks5', 'host': '127.0.0.1', 'port': self.socks_stub.port,
                                       'user': CRED[0], 'pass': CRED[1]}, '127.0.0.1', self.origin_port, 10)
        sock.close()
        self.assertTrue(any(e[0] == 'connect' and e[1].endswith(':' + str(self.origin_port))
                            for e in self.socks_stub.events))
        with self.assertRaises(OSError):
            ytfetch.socks5_connect({'type': 'socks5', 'host': '127.0.0.1', 'port': self.socks_stub.port,
                                    'user': 'u', 'pass': 'wrong'}, '127.0.0.1', self.origin_port, 10)

    def test_ranged_get_via_http_proxy(self):
        proxy = ytfetch.parse_proxy(f'http://{CRED[0]}:{CRED[1]}@127.0.0.1:{self.http_stub.port}')
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, 'a.m4a')
            n = ytfetch.ranged_get(f'https://127.0.0.1:{self.origin_port}/a', {}, dst, 1000,
                                   conns=2, first=100, chunk=100, ctx=ctx, opener=ytfetch.url_opener(ctx, proxy))
            self.assertEqual(n, 1000)
            with open(dst, 'rb') as f:
                self.assertEqual(len(f.read()), 1000)
        self.assertTrue(any(e[0] == 'connect' for e in self.http_stub.events))

    def test_ranged_get_via_socks5(self):
        proxy = ytfetch.parse_proxy(f'socks5://{CRED[0]}:{CRED[1]}@127.0.0.1:{self.socks_stub.port}')
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, 'a.m4a')
            n = ytfetch.ranged_get(f'https://127.0.0.1:{self.origin_port}/a', {}, dst, 1000,
                                   conns=2, first=100, chunk=100, ctx=ctx, opener=ytfetch.url_opener(ctx, proxy))
            self.assertEqual(n, 1000)

    def test_check_proxy_line(self):
        """check()'s proxy line through the HTTP stub against the local origin."""
        import types
        proxy = ytfetch.parse_proxy(f'http://{CRED[0]}:{CRED[1]}@127.0.0.1:{self.http_stub.port}')
        lines = []
        unverified = ssl.create_default_context()
        unverified.check_hostname = False
        unverified.verify_mode = ssl.CERT_NONE
        a = types.SimpleNamespace(proxy=proxy)
        with mock.patch.object(ssl, 'create_default_context', lambda **kw: unverified):
            ytfetch.check_proxy(a, lambda *args, **kw: lines.append(args),
                                url=f'https://127.0.0.1:{self.origin_port}/robots.txt')
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][0], 'proxy')
        self.assertTrue(lines[0][1], lines[0])


class YtdlpParamsTest(unittest.TestCase):
    def _args(self, proxy):
        import types
        return types.SimpleNamespace(cache_dir='/tmp/rt-ydl-test', node='node', proxy=proxy)

    def test_ydl_params_gets_url_string(self):
        """yt-dlp must receive the URL string, never the parsed dict (the 0.3.11 regression)."""
        proxy = ytfetch.parse_proxy('socks5://audit:dummy@127.0.0.1:1080')
        params = ytfetch.ydl_params(self._args(proxy), None)
        self.assertIsInstance(params['proxy'], str)
        self.assertEqual(params['proxy'], 'socks5://audit:dummy@127.0.0.1:1080')
        params = ytfetch.ydl_params(self._args(None), None)
        self.assertIsNone(params['proxy'])

    def test_real_ytdlp_accepts_params(self):
        """Construct YoutubeDL with these params using the package's own yt-dlp, when available."""
        pyz = Path(__file__).resolve().parents[4] / 'RideTube-artifacts' / 'ytdlp.pyz'
        if not pyz.is_file():
            self.skipTest('session-only ytdlp.pyz not extracted next to the repo clone')
        sys.path.insert(0, str(pyz))
        try:
            import yt_dlp
            proxy = ytfetch.parse_proxy('socks5://audit:dummy@127.0.0.1:1080')
            yt_dlp.YoutubeDL(ytfetch.ydl_params(self._args(proxy), None))  # the 0.3.11 dict made this explode at use
        finally:
            sys.path.remove(str(pyz))


if __name__ == '__main__':
    unittest.main()
