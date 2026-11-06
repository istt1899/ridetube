// Cross-platform account test: the live TV client version survives sign-in and restart.
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { Account } = require('../ytd.js');

(async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ridetube-account-'));
    const accountFile = path.join(dir, 'account.json');
    const version = '7.20261103.19.00';
    const calls = [], events = [];
    const request = async (method, url, headers, body) => {
        calls.push({ method, url, headers, body });
        if (url.endsWith('/tv')) return { status: 200, body: 'clientId:"123-abc.apps.googleusercontent.com",\nqz:"secret" clientVersion:"' + version + '"' };
        if (url.endsWith('/device/code')) return { status: 200, body: JSON.stringify({ device_code: 'device', user_code: 'ABC-DEF', interval: 0.01, expires_in: 60 }) };
        if (url.endsWith('/oauth2/token')) return { status: 200, body: JSON.stringify({ access_token: 'access', refresh_token: 'refresh', expires_in: 3600 }) };
        if (url.endsWith('/youtubei/v1/browse')) return { status: 200, body: '{}' };
        throw new Error('unexpected request: ' + url);
    };
    const options = { accountFile, ytRequest: request, ytTimeoutMs: 1000, log: () => {} };
    const a = new Account(options, (ev) => events.push(ev));
    try {
        await a.start();
        assert.ok(events.some((ev) => ev.state === 'code'), 'device code issued');
        const until = Date.now() + 1000;
        while (!events.some((ev) => ev.state === 'signed_in')) {
            if (Date.now() >= until) throw new Error('account was not signed in');
            await new Promise((resolve) => setTimeout(resolve, 10));
        }
        assert.strictEqual(JSON.parse(fs.readFileSync(accountFile, 'utf8')).ver, version);
        const restarted = new Account(options, () => {});
        await restarted.browse('FEsubscriptions', await restarted.token(false));
        const browse = calls.filter((c) => c.url.endsWith('/youtubei/v1/browse')).pop();
        assert.strictEqual(browse.body.context.client.clientVersion, version);
        restarted.close();
        console.log('ok: TV client version parsed, saved and reused after restart');
    } finally {
        a.close();
        fs.rmSync(dir, { recursive: true, force: true });
    }
})().catch((e) => { console.error(e); process.exitCode = 1; });
