// Regression: the server emits the client script BEFORE the saved order table.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname, '../../../static/js/razorpay_subscription.js'), 'utf8');
function harness(readyState) {
  const callbacks = {};
  const pay = {disabled:false, addEventListener(name, fn) {this[name] = fn;}};
  const check = {disabled:false, textContent:'Check payment', dataset:{checkOrder:'order_saved'}, addEventListener(name, fn) {this[name] = fn;}};
  const message = {textContent:''};
  let calls = 0;
  let pending;
  let tableReady = readyState !== 'loading';
  const context = {document:{readyState,
    getElementById:id => id === 'razorpay-pay' ? pay : message,
    querySelector:() => ({value:'test-csrf'}),
    querySelectorAll:() => tableReady ? [check] : [],
    addEventListener:(name,fn) => callbacks[name]=fn,
  }, window:{location:{assign() {throw Error('Do not silently reload on status check');}}},
  fetch:async (url, options) => {calls++; assert.equal(url,'/subscription/razorpay/status');
    assert.equal(JSON.parse(options.body).order_id,'order_saved');
    assert.equal(options.headers['X-CSRFToken'],'test-csrf');
    return new Promise(resolve => pending=resolve);
  }};
  vm.runInNewContext(source,context);
  return {pay,check,message, get calls(){return calls;},
    ready(){tableReady=true; callbacks.DOMContentLoaded();},
    resolve(result,ok=true){pending({ok,json:async()=>result});}};
}
(async () => {
  const page=harness('loading');
  assert.equal(page.check.click,undefined);
  page.ready();
  assert.equal(typeof page.check.click,'function');
  const first=page.check.click();
  assert.equal(page.check.textContent,'Checking…');
  assert.equal(page.check.disabled,true);
  await page.check.click();
  assert.equal(page.calls,1);
  page.resolve({active:true,already_processed:true,access_until:'2026-11-23T11:22:59+00:00'});
  await first;
  assert.match(page.message.textContent,/already verified.*unchanged/);
  assert.equal(page.check.disabled,false);
  assert.equal(page.check.textContent,'Check payment');
  const failure=page.check.click();
  page.resolve({error:'Payment service unavailable'},false);
  await failure;
  assert.equal(page.message.textContent,'Payment service unavailable');
  assert.equal(page.check.disabled,false);
  const loaded=harness('complete');
  assert.equal(typeof loaded.check.click,'function');
  console.log('PASS: delayed table binding, visible feedback, duplicate click guard and error recovery');
})().catch(error=>{console.error(error); process.exitCode=1;});
