#!/usr/bin/env python3
# Copyright (c) 2026-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test -port=0 randomized P2P port selection."""

from contextlib import contextmanager
import json
import socket

from test_framework.test_framework import BitcoinTestFramework
from test_framework.test_node import ErrorMatch
from test_framework.util import (
    assert_equal,
    p2p_port,
)

RANDOMIZED_PORT_MIN = 49152
RANDOMIZED_PORT_MAX = 65534
RANDOMIZED_PORT_SETTING = "randomizedp2pport"
EXTERNAL_IP = "42.42.42.42"


@contextmanager
def listening_socket(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("0.0.0.0", port))
    sock.listen()
    try:
        yield
    finally:
        sock.close()


def unused_randomized_port(exclude=()):
    for port in range(RANDOMIZED_PORT_MIN, RANDOMIZED_PORT_MAX + 1):
        if port in exclude:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise AssertionError("No unused randomized port found")


class RandomizeP2PPortTest(BitcoinTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.num_nodes = 3

    def setup_network(self):
        self.add_nodes(self.num_nodes)
        for node in self.nodes:
            node.has_explicit_bind = True
            node.replace_in_config([(f"port={p2p_port(node.index)}\n", "")])

    def get_persisted_port(self, node):
        settings = json.loads((node.chain_path / "settings.json").read_text())
        return int(settings[RANDOMIZED_PORT_SETTING])

    def has_persisted_port(self, node):
        settings_path = node.chain_path / "settings.json"
        return settings_path.exists() and RANDOMIZED_PORT_SETTING in json.loads(settings_path.read_text())

    def assert_valid_randomized_port(self, port):
        assert RANDOMIZED_PORT_MIN <= port <= RANDOMIZED_PORT_MAX
        assert port not in [8333, 18333, 38333, 48333, 18444]

    def assert_external_ip_port(self, node, port):
        local_address = next((addr for addr in node.getnetworkinfo()["localaddresses"] if addr["address"] == EXTERNAL_IP), None)
        assert local_address is not None
        assert_equal(local_address["port"], port)

    def run_test(self):
        node0, node1, node2 = self.nodes

        self.log.info("-port=0 generates and persists a randomized P2P port on first start")
        self.start_node(0, extra_args=["-port=0", f"-externalip={EXTERNAL_IP}"])
        port0 = self.get_persisted_port(node0)
        self.assert_valid_randomized_port(port0)
        self.assert_external_ip_port(node0, port0)

        self.log.info("Restart reuses the persisted randomized P2P port")
        self.restart_node(0, extra_args=["-port=0", f"-externalip={EXTERNAL_IP}"])
        assert_equal(self.get_persisted_port(node0), port0)
        self.assert_external_ip_port(node0, port0)

        self.log.info("Another randomized node can connect to the persisted random port")
        self.start_node(1, extra_args=["-port=0"])
        node1.addnode(node=f"127.0.0.1:{port0}", command="onetry", v2transport=False)
        self.wait_until(lambda: node0.getnetworkinfo()["connections_in"] >= 1)

        self.stop_node(1)
        self.stop_node(0)

        self.log.info("A blocked persisted randomized port fails without rerandomizing")
        with listening_socket(port0):
            node0.assert_start_raises_init_error(
                extra_args=["-port=0"],
                expected_msg=rf"Error: Unable to bind to .*:{port0} on this computer",
                match=ErrorMatch.PARTIAL_REGEX,
            )
        assert_equal(self.get_persisted_port(node0), port0)

        self.log.info("A blocked manual -port fails immediately")
        manual_port = port0
        with listening_socket(manual_port):
            node0.assert_start_raises_init_error(
                extra_args=[f"-port={manual_port}"],
                expected_msg=rf"Error: Unable to bind to .*:{manual_port} on this computer",
                match=ErrorMatch.PARTIAL_REGEX,
            )

        self.log.info("-port=0 with an explicit randomized bind port does not generate a persisted port")
        explicit_bind_port = unused_randomized_port(exclude={port0})
        node2.replace_in_config([("bind=127.0.0.1\n", "")])
        self.start_node(2, extra_args=["-port=0", f"-bind=127.0.0.1:{explicit_bind_port}", f"-externalip={EXTERNAL_IP}:{explicit_bind_port}"])
        self.assert_external_ip_port(node2, explicit_bind_port)
        assert not self.has_persisted_port(node2)
        self.stop_node(2)

        self.log.info("Invalid randomized bind ports are rejected while remote port 8333 remains allowed")
        node0.assert_start_raises_init_error(
            extra_args=["-port=0", "-bind=127.0.0.1:8333"],
            expected_msg="Error: -bind cannot be set to reserved P2P port 8333 when -port=0 is used.",
        )
        node0.assert_start_raises_init_error(
            extra_args=["-port=0", "-bind=127.0.0.1:49151"],
            expected_msg="Error: -bind must be in the randomized P2P port range 49152-65534 when -port=0 is used.",
        )

        self.start_node(2, extra_args=["-port=0", "-connect=127.0.0.1:8333"])
        self.stop_node(2)


if __name__ == '__main__':
    RandomizeP2PPortTest(__file__).main()
