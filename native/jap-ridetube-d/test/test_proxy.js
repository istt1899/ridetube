// Host test for the service proxy support: proxy.js (HTTP CONNECT and SOCKS5 with credentials),
// ytRequest through both, and the daemon plumbing (state/proxy.json -> the fetch child's stdin,
// the uplink preflight skipped when a proxy is set).
const assert = require('assert');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const tls = require('tls');

process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0'; // the origin below wears a test-only self-signed cert

const proxyMod = require('../proxy.js');
const cp = require('child_process');
const { Daemon, ytRequest } = require('../ytd.js');

const CRED = { user: 'rt', pass: 's3cret' };
const EXPECTED_AUTH = 'Basic ' + Buffer.from(CRED.user + ':' + CRED.pass).toString('base64');

function tlsOrigin() {
    const cert = fs.readFileSync(path.join(__dirname, 'fixtures', 'cert.pem'));
    const key = fs.readFileSync(path.join(__dirname, 'fixtures', 'key.pem'));
    const seen = [];
    const server = tls.createServer({ cert, key }, (s) => {
        s.on('error', () => { /* RST from a gone client */ });
        let buf = '';
        s.on('data', (d) => {
            buf += d.toString('latin1');
            const end = buf.indexOf('\r\n\r\n');
            if (end < 0) return;
            const head = buf.slice(0, end).split('\r\n');
            seen.push(head[0]);
            s.end('HTTP/1.1 200 OK\r\nContent-Length: 9\r\nConnection: close\r\n\r\norigin-ok');
        });
    });
    return new Promise((r) => { server.listen(0, '127.0.0.1', () => r({ server, seen, port: server.address().port })); });
}

// One stub speaking both protocols on two ports; records handshakes, tunnels bytes to the target.
function stubProxy() {
    const events = [];
    const http = net.createServer((c) => {
        c.on('error', () => { /* EPIPE/RST when a failing client goes away */ });
        let buf = Buffer.alloc(0);
        c.on('data', function onData(d) {
            buf = Buffer.concat([buf, d]);
            const end = buf.indexOf('\r\n\r\n');
            if (end < 0) return;
            c.off('data', onData);
            const head = buf.slice(0, end).toString('latin1');
            const line = head.split('\r\n')[0];
            const m = /^CONNECT (\S+):(\d+) /.exec(line);
            const auth = /(?:^|\r\n)Proxy-Authorization: (.*)\r\n$/.exec(head + '\r\n');
            events.push(['connect', line, auth && auth[1]]);
            if (!auth || auth[1] !== EXPECTED_AUTH) {
                c.end('HTTP/1.1 407 Proxy Auth Required\r\nProxy-Authenticate: Basic\r\nContent-Length: 0\r\n\r\n');
                return;
            }
            const target = net.connect(Number(m[2]), m[1], () => {
                c.write('HTTP/1.1 200 OK\r\n\r\n');
                if (buf.length > end + 4) target.write(buf.slice(end + 4));
                c.pipe(target).pipe(c);
            });
            target.once('error', () => c.destroy());
        });
    });
    const socks = net.createServer((c) => {
        let phase = 0;
        c.on('error', () => { /* EPIPE when a failing client goes away */ });
        c.on('data', function onData(d) {
            if (phase === 0) {
                c.write(Buffer.from([0x05, 0x02])); // offer user/pass auth
                phase = 1;
                return undefined;
            }
            if (phase === 1) {
                const ulen = d[1]; // d[0] is the auth version byte
                const user = d.slice(2, 2 + ulen).toString();
                const plen = d[2 + ulen];
                const pass = d.slice(3 + ulen, 3 + ulen + plen).toString();
                events.push(['socks-auth', user + ':' + pass]);
                if (user + ':' + pass !== CRED.user + ':' + CRED.pass) {
                    c.off('data', onData);
                    c.write(Buffer.from([0x01, 0x01]));
                    c.end();
                    return;
                }
                c.write(Buffer.from([0x01, 0x00]));
                phase = 2;
                return undefined;
            }
            if (phase === 2) {
                const atyp = d[3];
                let host, off;
                if (atyp === 0x01) { host = Array.from(d.slice(4, 8)).join('.'); off = 8; }
                else if (atyp === 0x03) { const hlen = d[4]; host = d.slice(5, 5 + hlen).toString(); off = 5 + hlen; }
                else { c.end(Buffer.from([0x05, 0x08, 0x00, 0x01, 0, 0, 0, 0, 0, 0])); return; }
                const port = (d[off] << 8) | d[off + 1];
                events.push(['socks-connect', host + ':' + port]);
                const target = net.connect(port, host, () => {
                    c.write(Buffer.from([0x05, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0]));
                    if (d.length > off + 2) target.write(d.slice(off + 2));
                    c.pipe(target).pipe(c);
                });
                target.once('error', () => { try { c.end(Buffer.from([0x05, 0x05, 0x00, 0x01, 0, 0, 0, 0, 0, 0])); } catch (e) { /* gone */ } });
                phase = 3;
            }
            return undefined;
        });
    });
    return new Promise((r) => {
        http.listen(0, '127.0.0.1', () => socks.listen(0, '127.0.0.1', () => r({
            httpPort: http.address().port, socksPort: socks.address().port, events,
            close: () => { http.close(); socks.close(); }
        })));
    });
}

if (process.argv[2] === '--helper') {
    // the fetch child the daemon test spawns: record the request JSON, answer ok
    const calls = process.argv[3];
    let input = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (s) => { input += s; });
    process.stdin.on('end', () => {
        fs.appendFileSync(calls, input + '\n');
        process.stdout.write(JSON.stringify({ status: 200, body: 'ok' }));
    });
} else {
    (async () => {
        const origin = await tlsOrigin();
        const stub = await stubProxy();

        // parse()
        assert.deepStrictEqual(proxyMod.parse('http://u:p@10.0.0.1:8080'), { type: 'http', host: '10.0.0.1', port: 8080, user: 'u', pass: 'p' });
        assert.deepStrictEqual(proxyMod.parse('socks5://u:p@h'), { type: 'socks5', host: 'h', port: 1080, user: 'u', pass: 'p' });
        assert.strictEqual(proxyMod.parse('http://'), null);
        assert.strictEqual(proxyMod.parse('ftp://h:1'), null);
        assert.strictEqual(proxyMod.parse(''), null);
        assert.strictEqual(proxyMod.parse(null), null);

        // ytRequest over HTTP CONNECT: the origin answers, the stub saw the CONNECT with credentials
        const viaHttp = proxyMod.parse(`http://${CRED.user}:${CRED.pass}@127.0.0.1:${stub.httpPort}`);
        const r1 = await ytRequest('GET', `https://127.0.0.1:${origin.port}/via-http`, null, null, 8000, undefined, viaHttp);
        assert.deepStrictEqual(r1, { status: 200, body: 'origin-ok' });
        const conn = stub.events.find((e) => e[0] === 'connect');
        assert.ok(conn, 'CONNECT seen');
        assert.strictEqual(/^CONNECT (\S+) /.exec(conn[1])[1], '127.0.0.1:' + origin.port, 'CONNECT target: ' + conn[1]);
        assert.strictEqual(Buffer.from(/^Basic (.*)$/.exec(conn[2])[1], 'base64').toString(), CRED.user + ':' + CRED.pass);
        assert.ok(origin.seen.some((l) => l.startsWith('GET /via-http ')), 'origin saw the tunneled request');

        // ytRequest over SOCKS5 with credentials
        const viaSocks = proxyMod.parse(`socks5://${CRED.user}:${CRED.pass}@127.0.0.1:${stub.socksPort}`);
        const r2 = await ytRequest('GET', `https://127.0.0.1:${origin.port}/via-socks`, null, null, 8000, undefined, viaSocks);
        assert.deepStrictEqual(r2, { status: 200, body: 'origin-ok' });
        assert.ok(stub.events.some((e) => e[0] === 'socks-auth' && e[1] === CRED.user + ':' + CRED.pass));
        assert.ok(stub.events.some((e) => e[0] === 'socks-connect' && e[1].endsWith(':' + origin.port)));

        // wrong credentials: HTTP 407 / SOCKS auth failure surface as errors
        await assert.rejects(ytRequest('GET', `https://127.0.0.1:${origin.port}/`, null, null, 8000, undefined,
            proxyMod.parse(`http://u:wrong@127.0.0.1:${stub.httpPort}`)), /proxy CONNECT 407/);
        await assert.rejects(ytRequest('GET', `https://127.0.0.1:${origin.port}/`, null, null, 8000, undefined,
            proxyMod.parse(`socks5://u:wrong@127.0.0.1:${stub.socksPort}`)), /auth failed/);

        // the daemon: proxy.json feeds the fetch child's stdin; no lease needed when a proxy is set
        const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ridetube-proxy-'));
        const proxyFile = path.join(dir, 'proxy.json'), calls = path.join(dir, 'calls.jsonl');
        fs.writeFileSync(proxyFile, JSON.stringify({ url: `http://${CRED.user}:${CRED.pass}@127.0.0.1:${stub.httpPort}` }));
        const d = new Daemon({ proxyFile: proxyFile, leaseFile: path.join(dir, 'lease.json'),
            fetchCmd: [process.execPath, __filename, '--helper', calls], noSetuid: true, log: () => {} });
        d.fetchUid = 12345;
        const rq = await d.fetch({ method: 'GET', url: 'https://www.youtube.com/tv', timeoutMs: 5 });
        assert.deepStrictEqual(rq, { status: 200, body: 'ok' });
        const got = JSON.parse(fs.readFileSync(calls, 'utf8').trim().split('\n').pop());
        assert.strictEqual(got.proxy, `http://${CRED.user}:${CRED.pass}@127.0.0.1:${stub.httpPort}`, 'the child receives the raw proxy URL');
        // the full daemon -> stdin -> ytd.js --fetch -> proxy -> origin chain, with the real child
        // (async spawn: the stubs live in this process, a spawnSync would starve them)
        const fetchChild = (payload) => new Promise((resolve, reject) => {
            const ch = cp.spawn(process.execPath, [path.join(__dirname, '..', 'ytd.js'), '--fetch'], { stdio: ['pipe', 'pipe', 'pipe'] });
            let out = '', err = '';
            ch.stdout.on('data', (d) => { out += d; });
            ch.stderr.on('data', (d) => { err += d; });
            ch.on('error', reject);
            ch.on('close', () => { try { resolve(JSON.parse(out || '{}')); } catch (e) { reject(new Error('child: ' + out + ' / ' + err)); } });
            ch.stdin.end(JSON.stringify(payload));
        });
        const childAns = await fetchChild({ method: 'GET', url: `https://127.0.0.1:${origin.port}/via-child`, headers: {}, timeoutMs: 8000,
            proxy: `http://${CRED.user}:${CRED.pass}@127.0.0.1:${stub.httpPort}` });
        assert.deepStrictEqual(childAns, { status: 200, body: 'origin-ok' }, 'child answer: ' + JSON.stringify(childAns));
        assert.ok(origin.seen.some((l) => l.startsWith('GET /via-child ')), 'origin saw the child-chain request');

        // the socks5 form of the same chain
        const childOut2 = await fetchChild({ method: 'GET', url: `https://127.0.0.1:${origin.port}/via-child-socks`, headers: {}, timeoutMs: 8000,
            proxy: `socks5://${CRED.user}:${CRED.pass}@127.0.0.1:${stub.socksPort}` });
        assert.deepStrictEqual(childOut2, { status: 200, body: 'origin-ok' }, 'socks child answer: ' + JSON.stringify(childOut2));

        // Node 8 compatibility: the process may lack a global URL entirely
        const legacyOut = cp.spawnSync(process.execPath, ['-e',
            'delete global.URL; const p = require(process.argv[1]); console.log(JSON.stringify(p.parse(process.argv[2])))',
            path.join(__dirname, '..', 'proxy.js'), 'socks5://u:p@127.0.0.1:1080'], { encoding: 'utf8', timeout: 10000 });
        assert.ok(JSON.parse(legacyOut.stdout || 'null'), 'proxy.parse must not depend on the global URL (Node 8)');

        // proxy removal restores the lease preflight
        fs.rmSync(proxyFile);
        await assert.rejects(d.fetch({ method: 'GET', url: 'https://www.youtube.com/tv', timeoutMs: 5 }), /car internet is offline/);

        // no proxy configured, no lease: the preflight still stops the request before any child runs
        const d2 = new Daemon({ proxyFile: path.join(dir, 'absent.json'), leaseFile: path.join(dir, 'lease.json'),
            fetchCmd: [process.execPath, __filename, '--helper', calls], noSetuid: true, log: () => {} });
        d2.fetchUid = 12345;
        await assert.rejects(d2.fetch({ method: 'GET', url: 'https://www.youtube.com/tv', timeoutMs: 5 }), /car internet is offline/);

        stub.close(); origin.server.close();
        fs.rmSync(dir, { recursive: true, force: true });
        console.log('ok: proxy parse, CONNECT and SOCKS5 tunnels, auth failures, daemon plumbing, preflight switch');
        process.exit(0); // deterministic end even if a stub socket lingers
    })().catch((e) => { console.error(e); process.exit(1); }); // exit: the stub servers would hold the loop open
}
