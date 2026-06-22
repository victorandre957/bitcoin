#!/usr/bin/env python3
# Copyright (c) 2026-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test -dynamicrandomizep2pport."""

import socket

from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import (
    assert_equal,
    assert_raises,
    p2p_port,
)

RANDOMIZED_PORT_MIN = 49152
RANDOMIZED_PORT_MAX = 65534


class DynamicRandomizeP2PPortTest(BitcoinTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.num_nodes = 4
        self.bind_to_localhost_only = False

    def setup_network(self):
        self.add_nodes(self.num_nodes)
        for node in self.nodes:
            node.has_explicit_bind = True
            node.replace_in_config([(f"port={p2p_port(node.index)}\n", "")])

    def assert_valid_randomized_port(self, port):
        assert RANDOMIZED_PORT_MIN <= port <= RANDOMIZED_PORT_MAX
        assert port not in [8333, 18333, 38333, 48333, 18444]

    def get_dynamic_port(self, node):
        dynamic_port = node.getnetworkinfo()["dynamicrandomizedp2pport"]
        assert_equal(dynamic_port["enabled"], True)
        port = dynamic_port["port"]
        self.assert_valid_randomized_port(port)
        return port

    def assert_port_closed(self, port):
        assert_raises(OSError, lambda: socket.create_connection(("127.0.0.1", port), timeout=1).close())

    def connect_to_dynamic_port(self, from_node, to_node, port, expected_inbound):
        from_node.addnode(node=f"127.0.0.1:{port}", command="onetry", v2transport=False)
        self.wait_until(lambda: to_node.getnetworkinfo()["connections_in"] >= expected_inbound)
        self.wait_until(lambda: self.get_dynamic_port(to_node) != port)

    def run_test(self):
        node0, node1, node2, validation_node = self.nodes

        self.log.info("-dynamicrandomizep2pport cannot be used with -port")
        validation_node.assert_start_raises_init_error(
            extra_args=["-dynamicrandomizep2pport=1", f"-port={p2p_port(validation_node.index)}"],
            expected_msg="Error: -dynamicrandomizep2pport cannot be used with -port.",
        )

        self.log.info("-dynamicrandomizep2pport is limited to default clearnet binds")
        validation_node.assert_start_raises_init_error(
            extra_args=["-dynamicrandomizep2pport=1", "-bind=127.0.0.1"],
            expected_msg="Error: -dynamicrandomizep2pport cannot be used with -bind or -whitebind.",
        )
        validation_node.assert_start_raises_init_error(
            extra_args=["-dynamicrandomizep2pport=1", "-whitebind=127.0.0.1:50000"],
            expected_msg="Error: -dynamicrandomizep2pport cannot be used with -bind or -whitebind.",
        )

        self.log.info("A node exposes its current dynamic randomized port over RPC")
        self.start_node(0, extra_args=["-listen=1", "-dynamicrandomizep2pport=1"])
        port0 = self.get_dynamic_port(node0)

        self.log.info("The listening port rotates after the first accepted inbound connection")
        self.start_node(1)
        self.connect_to_dynamic_port(node1, node0, port0, expected_inbound=1)
        port1 = self.get_dynamic_port(node0)
        assert port1 != port0
        self.assert_port_closed(port0)
        assert_equal(node0.getnetworkinfo()["connections_in"], 1)

        self.log.info("The rotated port accepts the next inbound connection and rotates again")
        self.start_node(2)
        self.connect_to_dynamic_port(node2, node0, port1, expected_inbound=2)
        port2 = self.get_dynamic_port(node0)
        assert port2 != port1
        self.assert_port_closed(port1)
        assert_equal(node0.getnetworkinfo()["connections_in"], 2)


if __name__ == '__main__':
    DynamicRandomizeP2PPortTest(__file__).main()
