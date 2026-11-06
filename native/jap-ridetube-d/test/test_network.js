// Host test for the car uplink preflight and the first sign-in request retry.
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { Daemon } = require('../ytd.js');

if (process.argv[2] === '--helper') {
    const calls = process.argv[3];
    let input = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (s) => { input += s; });
    process.stdin.on('end', () => {
        const req = JSON.parse(input);
        fs.appendFileSync(calls, JSON.stringify(req) + '\n');
        const n = fs.readFileSync(calls, 'utf8').trim().split('\n').length;
        process.stdout.write(JSON.stringify(n === 1 ? { error: 'timeout' } : { status: 200, body: 'ok' }));
    });
} else {
    (async () => {
        const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ridetube-network-'));
        const lease = path.join(dir, 'lease.json'), calls = path.join(dir, 'calls.jsonl');
        const d = new Daemon({ leaseFile: lease, fetchCmd: [process.execPath, __filename, '--helper', calls],
            noSetuid: true, authTimeoutMs: 25, networkRetryMs: 10, log: () => {} });
        d.fetchUid = 12345;
        try {
            await assert.rejects(d.fetch({ method: 'GET', url: 'https://www.youtube.com/tv', timeoutMs: 5 }), /car internet is offline/);
            assert.ok(!fs.existsSync(calls), 'offline preflight must not spawn a request');
            fs.writeFileSync(lease, JSON.stringify({ dns: ['1.1.1.1'] }));
            const r = await d.fetch({ method: 'GET', url: 'https://www.youtube.com/tv', timeoutMs: 5 });
            assert.deepStrictEqual(r, { status: 200, body: 'ok' });
            const reqs = fs.readFileSync(calls, 'utf8').trim().split('\n').map(JSON.parse);
            assert.strictEqual(reqs.length, 2, 'sign-in request retried once after timeout');
            assert.ok(reqs.every((q) => q.timeoutMs === 25), 'sign-in receives the longer timeout');
            fs.writeFileSync(calls, '');
            await assert.rejects(d.fetch({ method: 'POST', url: 'https://www.youtube.com/youtubei/v1/search', timeoutMs: 5 }), /timeout/);
            assert.strictEqual(fs.readFileSync(calls, 'utf8').trim().split('\n').length, 1, 'other requests are not retried');
            fs.writeFileSync(calls, '');
            await assert.rejects(d.fetch({ method: 'POST', url: 'https://www.youtube.com/o/oauth2/token', timeoutMs: 5 }), /timeout/);
            const tokenCalls = fs.readFileSync(calls, 'utf8').trim().split('\n').map(JSON.parse);
            assert.strictEqual(tokenCalls.length, 1, 'a token request must not be replayed');
            assert.strictEqual(tokenCalls[0].timeoutMs, 25);
            console.log('ok: offline preflight, sign-in retry and timeout, no retry for other requests');
        } finally {
            fs.rmSync(dir, { recursive: true, force: true });
        }
    })().catch((e) => { console.error(e); process.exitCode = 1; });
}
