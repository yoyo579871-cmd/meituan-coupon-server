'use strict';

// The official SDK supplies the signature. No device state is copied to CI.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

function prepare(body, sdk) {
  const endpoint = 'https://media.meituan.com/fulishemini/couponActivity/sendCouponWork';
  const common = sdk.addCommonParams(endpoint);
  const url = common && common.url;
  if (!url) throw new Error('SDK did not supply public parameters');
  const hash = crypto.createHash('md5').update(body.subarray(0, 16200)).digest('hex');
  const headers = sdk.signRequest('POST', url, hash);
  if (!headers || typeof headers.mtgsig !== 'string' || !headers.mtgsig) {
    throw new Error('SDK did not supply mtgsig');
  }
  return {url, headers: {mtgsig: headers.mtgsig}};
}

if (require.main === module) {
  try {
    const modulePath = process.env.WORKBUDDY_CLIGUARD_MODULE;
    if (!modulePath || !path.isAbsolute(modulePath)) throw new Error('SDK path required');
    const body = fs.readFileSync(0);
    if (!body.length || body.length > 1024 * 1024) throw new Error('Invalid input size');
    const sdk = require(modulePath);
    const request = prepare(body, sdk);
    process.stdout.write(JSON.stringify(request));
  } catch (_) {
    // Do not echo SDK exceptions: they may contain request or device values.
    process.stderr.write('WorkBuddy signing failed\n');
    process.exitCode = 1;
  }
}

module.exports = {prepare};
