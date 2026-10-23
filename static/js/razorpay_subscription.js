(() => {
  function initialize() {
  const pay = document.getElementById('razorpay-pay');
  const message = document.getElementById('razorpay-message');
  if (!pay || !message) return;
  let busy = false;
  const csrf = document.querySelector('input[name="csrf_token"]').value;
  async function post(path, data) {
    const response = await fetch(path, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
      body: JSON.stringify(data),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Unable to confirm payment. Check the payment status.');
    return result;
  }
  function unlock() { busy = false; pay.disabled = false; }
  pay.addEventListener('click', async () => {
    if (busy) return;
    if (!window.Razorpay) { message.textContent = 'Checkout could not load. Please refresh or check your browser settings.'; return; }
    busy = true; pay.disabled = true;
    message.textContent = 'Creating a test payment order…';
    try {
      const order = await post('/subscription/razorpay/order', {});
      const options = {...order, theme: {color: '#087e68'},
        handler: async (result) => {
          try {
            message.textContent = 'Verifying captured payment…';
            const verified = await post('/subscription/razorpay/verify', result);
            if (verified.active) window.location.assign('/subscription');
            else message.textContent = 'Access is not active. Refresh and check payment status.';
          } catch (error) { message.textContent = error.message + ' Refresh this page to check the saved order.'; }
          finally { unlock(); }
        },
        modal: {ondismiss: () => {message.textContent = 'Checkout closed. Refresh to check your order before paying again.'; unlock();}},
      };
      const checkout = new window.Razorpay(options);
      checkout.on('payment.failed', () => {message.textContent = 'Payment was not completed. Refresh and check the saved order before retrying.'; unlock();});
      checkout.open();
    } catch (error) { message.textContent = error.message; unlock(); }
  });
  document.querySelectorAll('[data-check-order]').forEach(button => button.addEventListener('click', async () => {
    if (busy) return;
    busy = true; button.disabled = true;
    const label = button.textContent;
    button.textContent = 'Checking…';
    message.textContent = 'Checking saved payment status…';
    try {
      const result = await post('/subscription/razorpay/status', {order_id: button.dataset.checkOrder});
      if (result.active) {
        message.textContent = result.already_processed
          ? 'Payment already verified. Your subscription expiry is unchanged: ' + result.access_until + ' (UTC).'
          : 'Payment verified. Subscription active until ' + result.access_until + ' (UTC). Refresh to continue to broker setup.';
      } else if (result.already_processed) {
        message.textContent = 'This payment was already processed. Its access period has expired; checking it again does not extend access.';
      } else {
        message.textContent = 'No captured payment found for this order. Access has not been extended.';
      }
    } catch (error) { message.textContent = error.message; }
    finally { busy = false; button.disabled = false; button.textContent = label; }
  }));
  }
  // The client script appears above the order table in the server-rendered page.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize, {once: true});
  } else {
    initialize();
  }
})();
