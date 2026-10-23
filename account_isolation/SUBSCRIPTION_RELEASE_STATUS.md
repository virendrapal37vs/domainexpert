# Subscription release status

This implementation is a restricted staging preview. Razorpay accepts test keys only; test payments grant staging access, not a live trading entitlement.

## Verified behavior

- Subscription amount is server-controlled at INR 2,360 for one calendar month. Checkout is a one-time payment, not an automatic monthly debit.
- Unpaid accounts cannot use the guarded broker setup routes or paper write routes.
- The same logged-in session loses guarded access at the exact expiry boundary. Saved paper reports remain readable.
- A payment grants access only to its persisted account owner. Rechecking a processed payment does not extend its expiry.
- Free owner access requires the persisted exact owner identity and administrator role. Session email or role fields cannot transfer the exemption.
- Payment verification checks signatures and retrieves captured payment/order details from Razorpay before granting access.

`test_subscription_access_lifecycle.py` exercises the access transition through Flask HTTP requests and temporary SQLite databases. Gateway API responses are simulated; it does not test a live broker or a public webhook delivery.

## Before a public paid release

- Implement and verify subscription enforcement for every enabled API-key, WebSocket, background execution and broker trading entry point. The current staging route gate is not a universal production paywall.
- Verify webhook delivery on the intended HTTPS environment, including retries and duplicate events. A localhost SSH tunnel does not provide an inbound webhook URL.
- Implement and test the chosen refund/dispute access policy and payment reconciliation operations.
- Replace exposed test credentials before release; configure live credentials separately only after live-mode code and merchant approval are ready. The current code intentionally rejects live keys.
- Confirm the business's actual tax registration and invoice treatment before collecting real payments; current pricing does not separately charge GST.
- Publish accurate business contact, terms, privacy, cancellation and refund information; retain source/license notices and provide corresponding source to network users as required by the project license.
- Keep AI claims aligned with delivered features. Planned AI capabilities and disabled live trading must not be advertised as active functionality.

No production deployment, live payment collection, real broker orders, or AI execution is enabled by these tests.
