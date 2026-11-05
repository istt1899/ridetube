'use strict';

// Pure tests: no head unit, network, private credentials, or BMW SDK needed.
const assert = require('assert');
const { Model } = require('../../apps/jap_ridetube/yt');
const fonts = require('../runtime/fonts');

const sent = [];
let available = false;
const model = new Model((command) => { sent.push(command); return available; });
const rev = model.rev;
assert.strictEqual(model.play('dQw4w9WgXcQ', '800x400', false), false);
assert.strictEqual(model.state, 'error');
assert.match(model.error, /not connected/i);
assert.ok(model.rev > rev, 'failed request notifies the UI');
available = true;
assert.strictEqual(model.play('dQw4w9WgXcQ', '800x400', false), true);
assert.strictEqual(model.state, 'preparing');
assert.strictEqual(model.error, null);
assert.strictEqual(sent[sent.length - 1].cmd, 'play');

for (const text of ['Привет, мир!', 'BMW и YouTube 2026', 'Ёжик']) {
    const f = fonts.get('label', 28, text);
    assert.ok(f && f.family === 'cyrillic', 'Cyrillic atlas selected');
    for (const ch of text) {
        assert.ok(f.glyphs[ch.codePointAt(0)], 'missing glyph: ' + ch);
    }
    assert.ok(fonts.measure(f, text) > 0, 'text has a visible width');
}
const fullAlphabet = Array.from({ length: 64 }, (_, i) => String.fromCharCode(0x410 + i)).join('') + '\u0401\u0451';
const atlas = fonts.get('label', 28, fullAlphabet);
for (const ch of fullAlphabet) assert.ok(atlas.glyphs[ch.codePointAt(0)], 'missing Russian letter ' + ch);
console.log('ok: disconnected playback, retry, Cyrillic and mixed text');
