from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


POOL_CORE_DIR = Path(__file__).resolve().parents[1] / "apps" / "pool-core"
sys.path.insert(0, str(POOL_CORE_DIR))


def _load_module(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, POOL_CORE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


stratum_protocol = _load_module("pool_core_stratum_protocol", "stratum_protocol.py")


class StratumProtocolIdentityTests(unittest.TestCase):
    def _authorized_state(self, login: str):
        wallet, worker, normalized_login = stratum_protocol.authorize_identity(login)
        state = stratum_protocol.new_connection_state()
        state.authorized = True
        state.authorized_wallet = wallet
        state.authorized_worker = worker
        state.authorized_login = normalized_login
        return state

    def test_wallet_only_submit_keeps_authorized_phi_worker(self):
        wallet = "wallet-a"
        state = self._authorized_state(f"{wallet}.PHI")

        self.assertEqual(
            stratum_protocol.resolve_submit_identity([wallet], state),
            (wallet, "PHI", f"{wallet}.PHI"),
        )

    def test_wallet_only_submit_keeps_authorized_5950x_worker(self):
        wallet = "wallet-a"
        state = self._authorized_state(f"{wallet}.5950x")

        self.assertEqual(
            stratum_protocol.resolve_submit_identity([wallet], state),
            (wallet, "5950x", f"{wallet}.5950x"),
        )

    def test_explicit_submit_worker_wins(self):
        wallet = "wallet-a"
        state = self._authorized_state(f"{wallet}.PHI")

        self.assertEqual(
            stratum_protocol.resolve_submit_identity([f"{wallet}.GPU"], state),
            (wallet, "GPU", f"{wallet}.GPU"),
        )

    def test_unrelated_wallet_only_submit_keeps_default_behavior(self):
        state = self._authorized_state("wallet-a.PHI")

        self.assertEqual(
            stratum_protocol.resolve_submit_identity(["wallet-b"], state),
            ("wallet-b", "default", "wallet-b"),
        )

    def test_missing_submit_login_uses_authorized_state(self):
        state = self._authorized_state("wallet-a.PHI")

        self.assertEqual(
            stratum_protocol.resolve_submit_identity([], state),
            ("wallet-a", "PHI", "wallet-a.PHI"),
        )


if __name__ == "__main__":
    unittest.main()
