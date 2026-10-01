'use strict';
// Run with: node tests/test_pixel_thumbnails.js
const assert = require('assert');
const { blockSize, fit } = require('../deploy/mirklurk-pixel-thumbnails.js');

function upscale(native, width, height, scale) {
    const data = new Uint8ClampedArray(width * scale * height * scale * 4);
    for (let y = 0; y < height * scale; y++) {
        for (let x = 0; x < width * scale; x++) {
            const from = (Math.floor(y / scale) * width + Math.floor(x / scale)) * 4;
            data.set(native.slice(from, from + 4), (y * width * scale + x) * 4);
        }
    }
    return data;
}

function art(width, height, seed) {
    const data = new Uint8ClampedArray(width * height * 4);
    for (let i = 0; i < width * height; i++) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        data.set([seed % 7 * 40, seed % 5 * 50, seed % 3 * 90, seed % 4 ? 255 : 0], i * 4);
    }
    return data;
}

for (const [width, height, scale] of [[16, 16, 8], [16, 48, 5], [32, 16, 8], [85, 135, 4], [48, 48, 1], [56, 80, 3]]) {
    const native = art(width, height, width * 31 + height);
    assert.strictEqual(blockSize(upscale(native, width, height, scale), width * scale, height * scale), scale,
        `${width}x${height} at ${scale}x`);
}

// Encoders may store different colours under fully transparent pixels.
const noisy = upscale(art(16, 16, 7), 16, 16, 4);
for (let i = 0; i < noisy.length; i += 4) {
    if (noisy[i + 3] === 0) {
        noisy.set([i % 251, i % 241, i % 239], i);
    }
}
assert.strictEqual(blockSize(noisy, 64, 64), 4);
assert.strictEqual(blockSize(new Uint8ClampedArray(24 * 16 * 4).fill(255), 24, 16), 8);

assert.deepStrictEqual(fit(16, 16, 40, 40), { width: 32, height: 32 });
assert.deepStrictEqual(fit(32, 16, 80, 80), { width: 64, height: 32 });
assert.deepStrictEqual(fit(16, 48, 80, 80), { width: 16, height: 48 });
assert.deepStrictEqual(fit(32, 80, 80, 80), { width: 32, height: 80 });
assert.strictEqual(fit(16, 48, 40, 40), null);
assert.strictEqual(fit(16, 16, 0, 0), null);
console.log('Pixel thumbnail scaling tests passed.');
