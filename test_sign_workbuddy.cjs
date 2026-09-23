'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {prepare} = require('./sign_workbuddy.cjs');

test('signs the exact body bytes and the URL after public parameters', () => {
  const body = Buffer.from(JSON.stringify({token:'offline-placeholder', aiScene:'测试', version:2}));
  const signedUrl = 'https://media.meituan.com/fulishemini/couponActivity/sendCouponWork?csecplatform=1&csecversion=test';
  const sdk = {
    addCommonParams(url) {
      assert.equal(new URL(url).pathname, '/fulishemini/couponActivity/sendCouponWork');
      return {url:signedUrl};
    },
    signRequest(method, url, hash) {
      assert.equal(method, 'POST');
      assert.equal(url, signedUrl);
      assert.equal(hash, crypto.createHash('md5').update(body).digest('hex'));
      return {mtgsig:'test-signature'};
    },
  };
  assert.deepEqual(prepare(body, sdk), {url:signedUrl, headers:{mtgsig:'test-signature'}});
});

test('matches the official 16200 byte digest limit', () => {
  const body = Buffer.from('a'.repeat(16199) + '你好');
  const sdk = {
    addCommonParams: () => ({url:'https://media.meituan.com/test'}),
    signRequest: (_, __, hash) => {
      assert.equal(hash, crypto.createHash('md5').update(body.subarray(0, 16200)).digest('hex'));
      return {mtgsig:'test'};
    },
  };
  prepare(body, sdk);
});

test('missing public parameters or signature cannot degrade to an unsigned request', () => {
  assert.throws(() => prepare(Buffer.from('{}'), {addCommonParams: () => null}));
  assert.throws(() => prepare(Buffer.from('{}'), {
    addCommonParams: () => ({url:'https://media.meituan.com/test'}),
    signRequest: () => ({}),
  }));
});
