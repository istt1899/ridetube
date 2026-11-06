'use strict';
// Minimal dependency-free HTTP CONNECT and SOCKS5 client tunnels, shared by ytd.js and thumb.js.
// Parsed once by the daemon and handed to the helpers over their stdin JSON, like the rest of a
// request's secrets: proxies carry credentials, and argv/env show in ps on the head unit.

const net = require('net');
const URL = require('url').URL; // Node 8 has no global URL: take it from the module

// 'http://user:pass@host:port' | 'http://host:port' | 'socks5://...' (defaults: http, port 8080/1080)
function parse(raw) {
    if (typeof raw !== 'string') return null;
    const s = raw.trim();
    if (!s) return null;
    let u;
    try { u = new URL(s); } catch (e) { return null; }
    const scheme = u.protocol.replace(/:$/, '').toLowerCase();
    if (scheme !== 'http' && scheme !== 'socks5' && scheme !== 'socks5h') return null;
    const host = u.hostname;
    const port = Number(u.port || (scheme === 'http' ? 8080 : 1080));
    if (!host || !Number.isInteger(port) || port < 1 || port > 65535) return null;
    const user = u.username ? decodeURIComponent(u.username) : '';
    const pass = u.password ? decodeURIComponent(u.password) : '';
    return { type: scheme === 'http' ? 'http' : 'socks5', host: host, port: port, user: user, pass: pass };
}

// cb(err, socket): socket is a plain net.Socket tunneled to targetHost:targetPort; TLS wraps it
function connect(proxy, targetHost, targetPort, options, cb) {
    if (typeof options === 'function') { cb = options; options = {}; }
    const timeoutMs = options.timeoutMs || 10000;
    let done = false;
    const finish = (err, sock) => {
        if (done) { if (err && sock) sock.destroy(); return; }
        done = true;
        clearTimeout(timer);
        if (err) socket.destroy();
        cb(err, sock);
    };
    const socket = net.connect({ host: proxy.host, port: proxy.port, lookup: options.lookup });
    const timer = setTimeout(() => finish(new Error('proxy connect timeout')), timeoutMs);
    if (timer.unref) timer.unref();
    socket.once('error', (e) => finish(new Error('proxy ' + proxy.host + ':' + proxy.port + ': ' + e.message)));
    socket.setTimeout(timeoutMs, () => finish(new Error('proxy connect timeout')));
    if (proxy.type === 'http') httpTunnel(socket, proxy, targetHost, targetPort, finish);
    else socks5Tunnel(socket, proxy, targetHost, targetPort, finish);
}

// Collect bytes until the predicate declares the reply complete (or invalid). onEarly may fail fast
// on bytes already buffered. done(err, reply, rest): reply = the bytes the predicate consumed.
function readReply(socket, predicate, cap, onEarly, done) {
    let buf = Buffer.alloc(0);
    let finished = false;
    const finish = (err, reply, rest) => {
        if (finished) return;
        finished = true;
        socket.off('data', onData);
        socket.off('error', onErr);
        socket.off('timeout', onTimeout);
        done(err, reply, rest);
    };
    const onData = (d) => {
        buf = Buffer.concat([buf, d]);
        if (buf.length > cap) return finish(new Error('proxy answer over ' + cap + ' B'));
        const r = predicate(buf);
        if (r.hit) return finish(null, buf.slice(0, r.len), buf.slice(r.len));
        if (r.bad) return finish(r.bad);
        return undefined;
    };
    const onErr = (e) => finish(new Error('proxy ' + e.message));
    const onTimeout = () => finish(new Error('proxy connect timeout'));
    socket.on('data', onData);
    socket.once('error', onErr);
    socket.once('timeout', onTimeout);
    onEarly(buf, finish);
}

function httpTunnel(socket, proxy, host, port, finish) {
    socket.once('connect', () => {
        const auth = (proxy.user || proxy.pass)
            ? 'Proxy-Authorization: Basic ' + Buffer.from(proxy.user + ':' + proxy.pass, 'utf8').toString('base64') + '\r\n'
            : '';
        socket.write('CONNECT ' + host + ':' + port + ' HTTP/1.1\r\nHost: ' + host + ':' + port + '\r\n' + auth + '\r\n');
        readReply(socket,
            (buf) => {
                const end = buf.indexOf('\r\n\r\n');
                if (end < 0) return buf.length > 65536 ? { hit: false, bad: new Error('proxy answer over 64 KiB') } : { hit: false };
                const line = (buf.slice(0, end).toString('latin1').split('\r\n')[0]) || '';
                const m = /^HTTP\/\d\.\d\s+(\d{3})\b/.exec(line);
                if (!m) return { hit: false, bad: new Error('proxy bad answer: ' + line.slice(0, 80)) };
                if (m[1] !== '200') return { hit: false, bad: new Error('proxy CONNECT ' + m[1]) };
                return { hit: true, len: end + 4 };
            },
            65536 + 1,
            () => {},
            (err, reply, rest) => {
                socket.setTimeout(0);
                if (err) return finish(err);
                if (rest && rest.length) socket.unshift(rest);
                return finish(null, socket);
            });
    });
}

function socks5Tunnel(socket, proxy, host, port, finish) {
    socket.once('connect', () => {
        socket.write((proxy.user || proxy.pass) ? Buffer.from([0x05, 0x01, 0x02]) : Buffer.from([0x05, 0x01, 0x00]));
        readReply(socket,
            (buf) => (buf.length >= 2 ? { hit: true, len: 2 } : { hit: false }),
            3,
            (buf, fail) => {
                if (buf.length >= 2 && buf[1] !== 0x00 && buf[1] !== 0x02 && buf[1] !== 0xff)
                    return fail(new Error('socks: bad method reply'));
                return undefined;
            },
            (err, reply, rest) => {
                if (err) return finish(err);
                if (reply[0] !== 0x05) return finish(new Error('socks: bad version ' + reply[0]));
                if (reply[1] === 0xff) return finish(new Error('socks: no acceptable auth method'));
                if (reply[1] === 0x02) return socks5Auth(socket, proxy, rest, host, port, finish);
                return socks5Ask(socket, rest, host, port, finish);
            });
    });
}

function socks5Auth(socket, proxy, rest, host, port, finish) {
    const u = Buffer.from(proxy.user || '', 'utf8'), p = Buffer.from(proxy.pass || '', 'utf8');
    if (u.length > 255 || p.length > 255) return finish(new Error('socks: credentials over 255 B'));
    if (rest && rest.length) socket.unshift(rest);
    socket.write(Buffer.concat([Buffer.from([0x01, u.length]), u, Buffer.from([p.length]), p]));
    readReply(socket,
        (buf) => (buf.length >= 2 ? { hit: true, len: 2 } : { hit: false }),
        3,
        () => {},
        (err, reply, rest2) => {
            if (err) return finish(err);
            if (reply[1] !== 0x00) return finish(new Error('socks: auth failed'));
            return socks5Ask(socket, rest2, host, port, finish);
        });
}

function socks5Ask(socket, rest, host, port, finish) {
    let dst;
    if (net.isIP(host)) {
        if (net.isIPv6(host)) {
            const parts = [];
            for (let i = 0; i < 8; i++) parts.push(parseInt((host.split(':')[i] || '0'), 16));
            dst = Buffer.concat([Buffer.from([0x04]), Buffer.from(parts)]);
        } else {
            dst = Buffer.concat([Buffer.from([0x01]), Buffer.from(host.split('.').map(Number))]);
        }
    } else {
        const h = Buffer.from(host, 'utf8');
        if (h.length > 255) return finish(new Error('socks: host name over 255 B'));
        dst = Buffer.concat([Buffer.from([0x03, h.length]), h]);
    }
    if (rest && rest.length) socket.unshift(rest); // bytes that arrived with the previous reply
    socket.write(Buffer.concat([Buffer.from([0x05, 0x01, 0x00]), dst, Buffer.from([port >> 8 & 0xff, port & 0xff])]));
    readReply(socket,
        (buf) => {
            if (buf.length < 4) return { hit: false };
            if (buf[0] !== 0x05) return { hit: false, bad: new Error('socks: bad reply version ' + buf[0]) };
            if (buf[1] !== 0x00) return { hit: false, bad: new Error('socks: connect failed, code ' + buf[1]) };
            const atyp = buf[3];
            let need;
            if (atyp === 0x01) need = 10;
            else if (atyp === 0x04) need = 22;
            else if (atyp === 0x03) {
                if (buf.length < 5) return { hit: false };
                need = 7 + buf[4];
            } else {
                return { hit: false, bad: new Error('socks: bad address type ' + atyp) };
            }
            return buf.length >= need ? { hit: true, len: need } : { hit: false };
        },
        600,
        () => {},
        (err, reply, rest2) => {
            socket.setTimeout(0);
            if (err) return finish(err);
            if (rest2 && rest2.length) socket.unshift(rest2);
            return finish(null, socket);
        });
}

module.exports = { parse: parse, connect: connect };
