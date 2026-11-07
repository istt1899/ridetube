'use strict';
// node22 thumb.js <id> [--lease <path>] [--proxy-file <path>]: i.ytimg.com's mqdefault.jpg as
// 320x180 RGBA (230400 bytes) on stdout.
// Runs as the fetch uid (env {}, cwd /); the car has no image library, so the JPEG is decoded here.
// The proxy file (0600 our uid, written by the daemon) carries the proxy url with credentials.
const https = require('https');
const tls = require('tls');
const fs = require('fs');
const proxyMod = require('./proxy.js');
const decode = require('./vendor/jpeg-js/decoder.js');

const W = 320, H = 180, MAX = 2 * 1024 * 1024, TIMEOUT_MS = 8000;

// as ytd.js's uplinkLookup (Node 8 there); Node 22's autoSelectFamily asks with {all: true}
function uplinkLookup(leaseFile) {
    let servers = [];
    try { servers = (JSON.parse(fs.readFileSync(leaseFile || '/run/mgu-uplink/lease.json', 'utf8')).dns || []).filter((x) => typeof x === 'string'); } catch (e) { /* no lease: system resolver */ }
    if (!servers.length) return undefined;
    const r = new (require('dns').Resolver)();
    r.setServers(servers);
    return function (host, opts, cb) {
        if (typeof opts === 'function') { cb = opts; opts = {}; }
        r.resolve4(host, (e, a) => (e ? cb(e) : opts.all ? cb(null, a.map((address) => ({ address, family: 4 }))) : cb(null, a[0], 4)));
    };
}

function fetchJpeg(id, lookup, via) {
    return new Promise((resolve, reject) => {
        const ask = (cc) => {
            const req = https.request({
                host: 'i.ytimg.com', port: 443, defaultPort: 443,
                path: '/vi/' + id + '/mqdefault.jpg', lookup, headers: { 'user-agent': 'Mozilla/5.0' },
                createConnection: cc || undefined
            }, (res) => {
                // 404 is YouTube's placeholder for private/removed videos; redirects are not followed
                if (res.statusCode !== 200) { res.resume(); return reject(new Error('http ' + res.statusCode)); }
                const parts = [];
                let n = 0;
                res.on('data', (d) => { n += d.length; if (n > MAX) req.destroy(new Error('body over 2 MB')); else parts.push(d); });
                res.on('end', () => resolve(Buffer.concat(parts)));
                res.on('error', reject);
            });
            req.setTimeout(TIMEOUT_MS, () => req.destroy(new Error('timeout')));
            setTimeout(() => req.destroy(new Error('timeout')), TIMEOUT_MS).unref();
            req.on('error', reject);
            req.end();
        };
        if (!via) return ask(null);
        proxyMod.connect(via, 'i.ytimg.com', 443, { timeoutMs: TIMEOUT_MS, lookup }, (e, sock) => {
            if (e) return reject(e);
            ask(() => tls.connect({ socket: sock, servername: 'i.ytimg.com' }));
        });
    });
}

function thumbRgba(jpeg) {
    const img = decode(jpeg, { useTArray: true, formatAsRGBA: true, maxResolutionInMP: 4, maxMemoryUsageInMB: 64 });
    const out = Buffer.alloc(W * H * 4);
    for (let y = 0; y < H; y++) {
        const sy = Math.floor((y + 0.5) * img.height / H);
        for (let x = 0; x < W; x++) {
            const s = (sy * img.width + Math.floor((x + 0.5) * img.width / W)) * 4;
            const d = (y * W + x) * 4;
            out[d] = img.data[s]; out[d + 1] = img.data[s + 1]; out[d + 2] = img.data[s + 2]; out[d + 3] = 255;
        }
    }
    return out;
}

function proxyFrom(file) {
    if (!file) return null;
    let raw = null;
    try { raw = JSON.parse(fs.readFileSync(file, 'utf8')).url; } catch (e) { /* unreadable: direct */ }
    return proxyMod.parse(raw);
}

module.exports = { thumbRgba, uplinkLookup, fetchJpeg, proxyFrom };

if (require.main === module) {
    const fail = (m) => { process.stderr.write('thumb: ' + m + '\n'); process.exit(1); };
    const a = process.argv.slice(2);
    const id = a[0];
    const li = a.indexOf('--lease');
    const pi = a.indexOf('--proxy-file');
    if (!/^[A-Za-z0-9_-]{11}$/.test(id || '')) fail('bad id');
    if (li > 0 && !a[li + 1]) fail('--lease needs a path');
    if (pi > 0 && !a[pi + 1]) fail('--proxy-file needs a path');
    fetchJpeg(id, uplinkLookup(li > 0 ? a[li + 1] : undefined), proxyFrom(pi > 0 ? a[pi + 1] : undefined))
        .then((jpeg) => { const b = thumbRgba(jpeg); process.stdout.write(b, () => process.exit(0)); })
        .catch((e) => fail(e.message));
}
