"""A/B shadow-validation sandbox for coin-selection ranking strategies.

SAFETY CONTRACT (read before touching anything in this package):

* Nothing in this package may import, construct, or call any class from
  ``hummingbot.connector.exchange.kraken.*`` (the authenticated, nonce-locked
  live connector), ``multi_coin_grid_pro.controllers.multi_coin_grid_controller``
  (the live controller), ``hummingbot.strategy_v2.models.executor_actions``
  (``StopExecutorAction`` et al.), or ``hummingbot.strategy_v2.executors.executor_orchestrator``.
* Market data comes exclusively from a public, unauthenticated ccxt client
  (see ``public_market_data.py``) — no API key/secret is ever read or passed.
* All state (virtual portfolios, positions, results) lives in a dedicated
  SQLite file (``data/shadow_ab_results.db``), never the live
  ``multi_coin_grid_v2_usd.sqlite`` or ``realised_pnl_ledger_usd.db``.
* This package is designed to run as a **separate OS process**
  (``python -m multi_coin_grid_pro.shadow.ab_shadow_runner``). It is never
  imported by the live strategy scripts or controller.
* A structural regression test (``test_shadow_isolation.py``) enforces the
  import restrictions above automatically.
"""
