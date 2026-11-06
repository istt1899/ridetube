// A silent network helper must not leave the app waiting for a sign-in code forever.
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { Account } = require('../ytd.js');

const tv = { status: 200, body: 'clientId:"123-abc.apps.googleusercontent.com",\nqz:"secret" clientVersion:"7.20261102.18.00"' };
const code = { status: 200, body: JSON.stringify({ device_code: 'device', user_code: 'ABC-DEF', interval: 60, expires_in: 60 }) };
const later = () => {
    let resolve;
    const promise = new Promise((r) => { resolve = r; });
    return { promise, resolve };
};

(async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ridetube-deadline-'));
    const accountFile = path.join(dir, 'account.json');
    const events = [];
    const page = later();
    let request = (_method, url) => url.endsWith('/tv') ? page.promise : Promise.resolve(code);
    const a = new Account({ accountFile, ytRequest: (...args) => request(...args),
        ytTimeoutMs: 1000, authDeadlineMs: 50, log: () => {} }, (ev) => events.push(ev));
    try {
        await a.start();
        assert.deepStrictEqual(events.map((ev) => ev.state), ['error']);
        assert.match(events[0].msg, /TV credentials: timeout/);
        assert.strictEqual(a.starting, false);
        page.resolve(tv);
        await new Promise((r) => setImmediate(r));
        assert.strictEqual(a.cred, null, 'a late TV page must not set the credentials');
        assert.strictEqual(events.length, 1, 'a late TV page must not issue a code');

        const device = later();
        request = (_method, url) => Promise.resolve(url.endsWith('/tv') ? tv : device.promise);
        await a.start();
        assert.deepStrictEqual(events.map((ev) => ev.state), ['error', 'error']);
        assert.match(events[1].msg, /device code: timeout/);
        device.resolve(code);
        await new Promise((r) => setImmediate(r));
        assert.strictEqual(a.pending, null, 'a late device response must not issue a code');
        assert.strictEqual(events.length, 2);

        request = (_method, url) => Promise.resolve(url.endsWith('/tv') ? tv : code);
        await a.start();
        assert.strictEqual(events[2].state, 'code', 'a later retry can still succeed');
        console.log('ok: TV and device-code deadlines return errors; late replies stay inert; retry works');
    } finally {
        a.close();
        fs.rmSync(dir, { recursive: true, force: true });
    }
})().catch((e) => { console.error(e); process.exitCode = 1; });
